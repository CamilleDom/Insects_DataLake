from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import logging
from datetime import datetime

from config import get_settings
from db import get_db_connection, get_minio_client
from schemas import HealthResponse, StatsResponse, IngestPayload

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Insect Lake API",
    description="Data Lake API for insect biodiversity in France",
    version="0.1.0"
)

settings = get_settings()

# ============================================
# HEALTH & DIAGNOSTICS
# ============================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check health status of all services"""
    status = {
        "minio": "healthy",
        "postgres": "healthy",
        "api": "healthy"
    }
    
    try:
        # Test MinIO connection
        client = get_minio_client()
        client.list_buckets()
    except Exception as e:
        logger.error(f"MinIO health check failed: {e}")
        status["minio"] = "unhealthy"
    
    try:
        # Test PostgreSQL connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"PostgreSQL health check failed: {e}")
        status["postgres"] = "unhealthy"
    
    overall_status = "healthy" if all(v == "healthy" for v in status.values()) else "degraded"
    
    return HealthResponse(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat(),
        services=status
    )

@app.get("/stats")
async def get_stats():
    """Get statistics about data lake content"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Count records by zone
        cursor.execute("SELECT COUNT(*) FROM staging.occurrences")
        staging_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM curated.species_richness_h3")
        curated_h3_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM curated.invasive_hotspots")
        invasive_count = cursor.fetchone()[0]
        
        # Last ingestion
        cursor.execute("""
            SELECT MAX(ingested_at) FROM staging.occurrences
        """)
        last_ingestion = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        return StatsResponse(
            timestamp=datetime.utcnow().isoformat(),
            staging_occurrences=staging_count,
            curated_h3_cells=curated_h3_count,
            invasive_hotspots=invasive_count,
            last_ingestion=last_ingestion.isoformat() if last_ingestion else None
        )
    except Exception as e:
        logger.error(f"Stats query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# RAW ZONE
# ============================================

@app.get("/raw")
async def list_raw_files():
    """List files in raw zone (MinIO)"""
    try:
        client = get_minio_client()
        
        files = {
            "inaturalist": [],
            "gbif": []
        }
        
        # List iNaturalist files
        for obj in client.list_objects("raw-inaturalist", recursive=True):
            files["inaturalist"].append({
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None
            })
        
        # List GBIF files
        for obj in client.list_objects("raw-gbif", recursive=True):
            files["gbif"].append({
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None
            })
        
        return {"raw_files": files}
    except Exception as e:
        logger.error(f"Failed to list raw files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# STAGING ZONE
# ============================================

@app.get("/staging")
async def get_staging_data(limit: int = 100, offset: int = 0):
    """Get paginated staging data"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, species_name, latitude, longitude, observed_on, 
                   quality_grade, source, ingested_at
            FROM staging.occurrences
            ORDER BY ingested_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        
        rows = cursor.fetchall()
        
        # Get total count
        cursor.execute("SELECT COUNT(*) FROM staging.occurrences")
        total = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        data = [
            {
                "id": row[0],
                "species_name": row[1],
                "latitude": row[2],
                "longitude": row[3],
                "observed_on": row[4].isoformat() if row[4] else None,
                "quality_grade": row[5],
                "source": row[6],
                "ingested_at": row[7].isoformat()
            }
            for row in rows
        ]
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "data": data
        }
    except Exception as e:
        logger.error(f"Failed to retrieve staging data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# CURATED ZONE
# ============================================

@app.get("/curated/hotspots")
async def get_biodiversity_hotspots(limit: int = 50, min_percentile: float = 0):
    """Get species richness hotspots sorted by richness percentile"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT h3_cell, species_count, obs_count, richness_normalized,
                   richness_percentile, lat_centroid, lon_centroid, last_observed
            FROM curated.species_richness_h3
            WHERE richness_percentile >= %s
            ORDER BY richness_percentile DESC
            LIMIT %s
        """, (min_percentile, limit))
        
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        data = [
            {
                "h3_cell": row[0],
                "species_count": row[1],
                "observation_count": row[2],
                "richness_normalized": row[3],
                "richness_percentile": row[4],
                "latitude": row[5],
                "longitude": row[6],
                "last_observed": row[7].isoformat() if row[7] else None
            }
            for row in rows
        ]
        
        return {"hotspots": data}
    except Exception as e:
        logger.error(f"Failed to retrieve hotspots: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/curated/invasives")
async def get_invasive_alerts(risk_level: str = None):
    """Get invasive species alerts, optionally filtered by risk level"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if risk_level:
            cursor.execute("""
                SELECT h3_cell, species_name, invasive_risk, alert_count,
                       first_seen, last_seen, lat_centroid, lon_centroid
                FROM curated.invasive_hotspots
                WHERE invasive_risk = %s
                ORDER BY last_seen DESC
            """, (risk_level,))
        else:
            cursor.execute("""
                SELECT h3_cell, species_name, invasive_risk, alert_count,
                       first_seen, last_seen, lat_centroid, lon_centroid
                FROM curated.invasive_hotspots
                ORDER BY last_seen DESC
            """)
        
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        data = [
            {
                "h3_cell": row[0],
                "species_name": row[1],
                "invasive_risk": row[2],
                "alert_count": row[3],
                "first_seen": row[4].isoformat() if row[4] else None,
                "last_seen": row[5].isoformat() if row[5] else None,
                "latitude": row[6],
                "longitude": row[7]
            }
            for row in rows
        ]
        
        return {"invasive_alerts": data}
    except Exception as e:
        logger.error(f"Failed to retrieve invasive alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# INGESTION (STANDARD & ADVANCED)
# ============================================

@app.post("/ingest")
async def ingest_observations(payload: IngestPayload):
    """Standard ingestion endpoint for manual observation data"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        success_count = 0
        
        for obs in payload.data.observations:
            try:
                cursor.execute("""
                    INSERT INTO staging.occurrences 
                    (id, species_name, latitude, longitude, observed_on, source)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (
                    f"manual_{obs.species_name}_{obs.latitude}_{obs.longitude}",
                    obs.species_name,
                    obs.latitude,
                    obs.longitude,
                    obs.observed_on,
                    "manual"
                ))
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to insert observation: {e}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return {
            "status": "success",
            "inserted": success_count,
            "total": len(payload.data.observations),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ingest_fast")
async def ingest_observations_fast(payload: IngestPayload):
    """Optimized ingestion endpoint (vectorized, async writes)"""
    try:
        # TODO: Implement vectorized H3 encoding and batch async writes
        # For now, same as /ingest but with optimization placeholder
        conn = get_db_connection()
        cursor = conn.cursor()
        
        success_count = 0
        
        for obs in payload.data.observations:
            try:
                cursor.execute("""
                    INSERT INTO staging.occurrences 
                    (id, species_name, latitude, longitude, observed_on, source)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (
                    f"manual_{obs.species_name}_{obs.latitude}_{obs.longitude}",
                    obs.species_name,
                    obs.latitude,
                    obs.longitude,
                    obs.observed_on,
                    "manual"
                ))
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to insert observation: {e}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return {
            "status": "success",
            "inserted": success_count,
            "total": len(payload.data.observations),
            "timestamp": datetime.utcnow().isoformat(),
            "note": "Fast ingestion variant"
        }
    except Exception as e:
        logger.error(f"Fast ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    """API information"""
    return {
        "name": "Insect Lake API",
        "version": "0.1.0",
        "description": "Data Lake for insect biodiversity in France",
        "docs": "/docs"
    }
