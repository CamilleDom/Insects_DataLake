from fastapi import FastAPI, HTTPException
import logging
import time
from datetime import datetime
import sys
import os

from config import get_settings
from db import get_db_connection, close_db_connection, get_minio_client
from schemas import HealthResponse, IngestPayload

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

try:
    from fast_ingestor import FastIngestor
except ImportError:
    FastIngestor = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Insect Lake API",
    description="Data Lake API for insect biodiversity in France",
    version="0.1.0"
)

settings = get_settings()

_fast_ingestor_instance = None

def get_fast_ingestor():
    """Instancie FastIngestor une seule fois (réutilise le pool de connexions)"""
    global _fast_ingestor_instance
    if _fast_ingestor_instance is None and FastIngestor:
        _fast_ingestor_instance = FastIngestor(
            pg_host=settings.postgres_host,
            pg_port=settings.postgres_port,
            pg_user=settings.postgres_user,
            pg_password=settings.postgres_password,
            pg_db=settings.postgres_db
        )
    return _fast_ingestor_instance


def _safe_release(conn):
    """Libère une connexion vers le pool en la nettoyant si besoin"""
    if conn is None:
        return
    try:
        conn.rollback()
    except Exception:
        pass
    close_db_connection(conn)


# ============================================
# HEALTH & DIAGNOSTICS
# ============================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    status = {"minio": "healthy", "postgres": "healthy", "api": "healthy"}

    try:
        client = get_minio_client()
        client.list_buckets()
    except Exception as e:
        logger.error(f"MinIO health check failed: {e}")
        status["minio"] = "unhealthy"

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
    except Exception as e:
        logger.error(f"PostgreSQL health check failed: {e}")
        status["postgres"] = "unhealthy"
    finally:
        _safe_release(conn)

    overall_status = "healthy" if all(v == "healthy" for v in status.values()) else "degraded"

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat(),
        services=status
    )


@app.get("/stats")
async def get_stats():
    """Métriques de remplissage : buckets MinIO (raw) + tables Postgres (staging/curated)"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM staging.occurrences")
        staging_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM curated.species_richness_h3")
        curated_h3_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM curated.invasive_hotspots")
        invasive_count = cursor.fetchone()[0]

        cursor.execute("SELECT MAX(ingested_at) FROM staging.occurrences")
        last_ingestion = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT source) FROM staging.occurrences")
        cursor.close()

        # Raw zone (MinIO)
        client = get_minio_client()
        raw_inat_count = sum(1 for _ in client.list_objects("raw-inaturalist", recursive=True))
        raw_gbif_count = sum(1 for _ in client.list_objects("raw-gbif", recursive=True))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "raw": {
                "inaturalist_files": raw_inat_count,
                "gbif_files": raw_gbif_count,
            },
            "staging": {
                "occurrences": staging_count,
                "last_ingestion": last_ingestion.isoformat() if last_ingestion else None
            },
            "curated": {
                "h3_cells": curated_h3_count,
                "invasive_hotspots": invasive_count
            }
        }
    except Exception as e:
        logger.error(f"Stats query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _safe_release(conn)


# ============================================
# RAW ZONE
# ============================================

@app.get("/raw")
async def list_raw_files():
    try:
        client = get_minio_client()
        files = {"inaturalist": [], "gbif": []}

        for obj in client.list_objects("raw-inaturalist", recursive=True):
            files["inaturalist"].append({
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None
            })

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
    conn = None
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

        cursor.execute("SELECT COUNT(*) FROM staging.occurrences")
        total = cursor.fetchone()[0]
        cursor.close()

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

        return {"total": total, "limit": limit, "offset": offset, "data": data}
    except Exception as e:
        logger.error(f"Failed to retrieve staging data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _safe_release(conn)


# ============================================
# CURATED ZONE
# ============================================

@app.get("/curated")
async def get_curated_overview():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM curated.species_richness_h3")
        h3_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM curated.invasive_hotspots")
        invasive_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM curated.image_classifications")
        classification_count = cursor.fetchone()[0]
        cursor.close()

        return {
            "description": "Curated zone - biodiversity insights (H3 richness, invasive alerts, CNN classifications)",
            "h3_cells": h3_count,
            "invasive_hotspots": invasive_count,
            "image_classifications": classification_count,
            "sub_endpoints": {
                "hotspots": "/curated/hotspots",
                "invasives": "/curated/invasives",
                "classifications": "/curated/classifications"
            }
        }
    except Exception as e:
        logger.error(f"Failed to retrieve curated overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _safe_release(conn)


@app.get("/curated/hotspots")
async def get_biodiversity_hotspots(limit: int = 50, min_percentile: float = 0):
    conn = None
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
    finally:
        _safe_release(conn)


@app.get("/curated/invasives")
async def get_invasive_alerts(risk_level: str = None):
    conn = None
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
    finally:
        _safe_release(conn)

@app.get("/curated/classifications")
async def get_image_classifications(limit: int = 50, insect_only: bool = False):
    """Résultats de classification d'images par CNN (MobileNetV2 / ImageNet-1k)"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT occurrence_id, species_name, image_url, predicted_class,
                   confidence, is_likely_insect, classified_at
            FROM curated.image_classifications
        """
        params = []
        if insect_only:
            query += " WHERE is_likely_insect = TRUE"
        query += " ORDER BY classified_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()

        data = [
            {
                "occurrence_id": row[0],
                "species_name": row[1],
                "image_url": row[2],
                "predicted_class": row[3],
                "confidence": row[4],
                "is_likely_insect": row[5],
                "classified_at": row[6].isoformat() if row[6] else None
            }
            for row in rows
        ]
        return {"classifications": data}
    except Exception as e:
        logger.error(f"Failed to retrieve classifications: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _safe_release(conn)

# ============================================
# INGESTION (STANDARD & ADVANCED)
# ============================================

@app.get("/benchmark")
async def get_benchmark_info():
    return {
        "title": "Insect Lake Ingestion Benchmark",
        "description": "Compare /ingest (standard) vs /ingest_fast (optimized)",
        "optimizations": [
            "NumPy vectorized H3 encoding (~3x faster)",
            "Batch inserts (1000 records per transaction)",
            "In-memory invasive species cache",
            "Early invasive detection while writing"
        ],
        "target_improvement": "30% performance gain",
        "endpoints": {
            "/ingest": "Standard ingestion (row-by-row)",
            "/ingest_fast": "Optimized ingestion (vectorized)"
        }
    }


@app.post("/ingest")
async def ingest_observations(payload: IngestPayload):
    """Standard ingestion endpoint for manual observation data"""
    start_time = time.time()
    conn = None
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
                    f"manual_{obs.species_name}_{obs.latitude}_{obs.longitude}_{obs.observed_on}",
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

        execution_time_ms = (time.time() - start_time) * 1000

        return {
            "status": "success",
            "inserted": success_count,
            "total": len(payload.data.observations),
            "execution_time_ms": execution_time_ms,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _safe_release(conn)

@app.post("/ingest_fast")
async def ingest_observations_fast(payload: IngestPayload):
    ingestor = get_fast_ingestor()
    if not ingestor:
        raise HTTPException(status_code=503, detail="FastIngestor module not available")

    try:
        observations_dicts = [
            {
                'species_name': obs.species_name,
                'latitude': obs.latitude,
                'longitude': obs.longitude,
                'observed_on': obs.observed_on
            }
            for obs in payload.data.observations
        ]

        result = ingestor.ingest_with_early_detection(observations_dicts)

        return {
            "status": "success",
            "inserted": result['inserted'],
            "duplicates": result['duplicates'],
            "errors": result['errors'],
            "total": len(payload.data.observations),
            "execution_time_ms": result['execution_time_ms'],
            "throughput_obs_per_sec": (len(payload.data.observations) / (result['execution_time_ms'] / 1000)) if result['execution_time_ms'] > 0 else 0,
            "detected_invasives": result.get('detected_invasives', {}),
            "timestamp": datetime.utcnow().isoformat(),
            "optimization": "Persistent connection pool + batch insert (execute_values)"
        }
    except Exception as e:
        logger.error(f"Fast ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def startup_event():
    """
    Pré-chauffe les pools de connexions au démarrage du serveur, plutôt
    que de laisser la première requête HTTP payer le coût de création
    du pool (connexions TCP + authentification PostgreSQL).
    """
    logger.info("Warming up connection pools...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        close_db_connection(conn)
        logger.info("Standard DB pool warmed up")
    except Exception as e:
        logger.warning(f"Failed to warm up standard pool: {e}")

    try:
        ingestor = get_fast_ingestor()
        if ingestor:
            conn = ingestor._get_connection()
            ingestor._release_connection(conn)
            logger.info("FastIngestor connection pool warmed up")
    except Exception as e:
        logger.warning(f"Failed to warm up fast ingestor pool: {e}")

@app.get("/")
async def root():
    return {
        "name": "Insect Lake API",
        "version": "0.1.0",
        "description": "Data Lake for insect biodiversity in France",
        "docs": "/docs"
    }