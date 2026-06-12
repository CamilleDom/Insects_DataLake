"""
Transformation pipeline: Staging → Curated

Processes occurrences from staging zone:
1. Converts lat/lon to H3 hexagon cells (resolution 7)
2. Calculates species richness per H3 cell
3. Detects invasive species alerts
4. Updates curated zone tables
"""

import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import h3
import numpy as np
from collections import defaultdict
from datetime import datetime
import math

logger = logging.getLogger(__name__)

# Invasive species reference list (curated list)
INVASIVE_SPECIES = {
    'Vespa velutina': 'high',           # Asian hornet
    'Harmonia axyridis': 'high',        # Asian ladybird
    'Sciurus carolinensis': 'medium',   # Eastern gray squirrel
    'Procyon lotor': 'medium',          # Raccoon
    'Oxyura jamaicensis': 'high',       # Ruddy duck
}

H3_RESOLUTION = 7


class CuratedTransformer:
    """Transforms staging data to curated zone"""
    
    def __init__(self, pg_host, pg_port, pg_user, pg_password, pg_db):
        self.conn = psycopg2.connect(
            host=pg_host,
            port=pg_port,
            user=pg_user,
            password=pg_password,
            database=pg_db
        )
        logger.info("Connected to PostgreSQL")
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def get_unprocessed_occurrences(self):
        """Fetch occurrences not yet in curated zone"""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id, species_name, latitude, longitude, observed_on
            FROM staging.occurrences
            WHERE id NOT IN (
                SELECT DISTINCT h3_cell FROM curated.species_richness_h3
            )
            ORDER BY observed_on DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        return rows
    
    def process_h3_richness(self):
        """Calculate and update species richness by H3 cells"""
        logger.info("Processing species richness by H3 cells...")
        
        cursor = self.conn.cursor()
        
        # Get all occurrences grouped by H3 cell
        cursor.execute("""
            SELECT 
                species_name,
                latitude,
                longitude,
                observed_on
            FROM staging.occurrences
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """)
        
        all_occurrences = cursor.fetchall()
        
        # Group by H3 cell
        h3_cells = defaultdict(lambda: {'species': set(), 'count': 0, 'lats': [], 'lons': [], 'dates': []})
        
        for species_name, lat, lon, observed_on in all_occurrences:
            try:
                h3_cell = h3.geo_to_h3(lat, lon, H3_RESOLUTION)
                h3_cells[h3_cell]['species'].add(species_name)
                h3_cells[h3_cell]['count'] += 1
                h3_cells[h3_cell]['lats'].append(lat)
                h3_cells[h3_cell]['lons'].append(lon)
                h3_cells[h3_cell]['dates'].append(observed_on)
            except Exception as e:
                logger.warning(f"Failed to convert {lat},{lon} to H3: {e}")
        
        # Upsert H3 richness data
        for h3_cell, data in h3_cells.items():
            species_count = len(data['species'])
            obs_count = data['count']
            
            # Calculate normalized richness: count / log(1 + observations)
            richness_normalized = species_count / math.log(1 + obs_count) if obs_count > 0 else 0
            
            # Calculate centroid
            lat_centroid = np.mean(data['lats']) if data['lats'] else None
            lon_centroid = np.mean(data['lons']) if data['lons'] else None
            
            # Find last observed date
            last_observed = max(data['dates']) if data['dates'] else None
            
            try:
                cursor.execute("""
                    INSERT INTO curated.species_richness_h3 
                    (h3_cell, species_count, obs_count, richness_normalized, 
                     richness_percentile, lat_centroid, lon_centroid, last_observed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (h3_cell) DO UPDATE SET
                        species_count = EXCLUDED.species_count,
                        obs_count = EXCLUDED.obs_count,
                        richness_normalized = EXCLUDED.richness_normalized,
                        last_observed = EXCLUDED.last_observed,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    h3_cell,
                    species_count,
                    obs_count,
                    richness_normalized,
                    None,  # percentile calculated in next step
                    lat_centroid,
                    lon_centroid,
                    last_observed
                ))
            except Exception as e:
                logger.error(f"Failed to insert H3 cell {h3_cell}: {e}")
        
        self.conn.commit()
        logger.info(f"Processed {len(h3_cells)} H3 cells")
        cursor.close()
    
    def calculate_richness_percentiles(self):
        """Calculate percentile rankings for richness"""
        logger.info("Calculating richness percentiles...")
        
        cursor = self.conn.cursor()
        
        try:
            # Update percentiles using window function
            cursor.execute("""
                UPDATE curated.species_richness_h3 SET
                    richness_percentile = (
                        SELECT PERCENT_RANK() OVER (ORDER BY richness_normalized) * 100
                        FROM curated.species_richness_h3 r2
                        WHERE r2.h3_cell = curated.species_richness_h3.h3_cell
                    )
            """)
            
            self.conn.commit()
            logger.info("Percentiles updated")
        except Exception as e:
            logger.error(f"Failed to calculate percentiles: {e}")
        finally:
            cursor.close()
    
    def process_invasive_alerts(self):
        """Detect and update invasive species hotspots"""
        logger.info("Processing invasive species alerts...")
        
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        
        for species_name, risk_level in INVASIVE_SPECIES.items():
            # Get all occurrences for this invasive species
            cursor.execute("""
                SELECT 
                    species_name,
                    latitude,
                    longitude,
                    observed_on
                FROM staging.occurrences
                WHERE LOWER(species_name) LIKE LOWER(%s)
                    AND observed_on IS NOT NULL
                ORDER BY observed_on DESC
            """, (f"%{species_name}%",))
            
            occurrences = cursor.fetchall()
            
            if not occurrences:
                continue
            
            # Group by H3 cell
            h3_invasive = defaultdict(lambda: {'dates': [], 'count': 0, 'lats': [], 'lons': []})
            
            for occ in occurrences:
                try:
                    h3_cell = h3.geo_to_h3(occ['latitude'], occ['longitude'], H3_RESOLUTION)
                    h3_invasive[h3_cell]['count'] += 1
                    h3_invasive[h3_cell]['dates'].append(occ['observed_on'])
                    h3_invasive[h3_cell]['lats'].append(occ['latitude'])
                    h3_invasive[h3_cell]['lons'].append(occ['longitude'])
                except Exception as e:
                    logger.warning(f"Failed to convert invasive occurrence: {e}")
            
            # Upsert invasive hotspots
            update_cursor = self.conn.cursor()
            
            for h3_cell, data in h3_invasive.items():
                lat_centroid = np.mean(data['lats']) if data['lats'] else None
                lon_centroid = np.mean(data['lons']) if data['lons'] else None
                first_seen = min(data['dates']) if data['dates'] else None
                last_seen = max(data['dates']) if data['dates'] else None
                
                try:
                    update_cursor.execute("""
                        INSERT INTO curated.invasive_hotspots 
                        (h3_cell, species_name, invasive_risk, alert_count, 
                         first_seen, last_seen, lat_centroid, lon_centroid)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (h3_cell, species_name) DO UPDATE SET
                            alert_count = EXCLUDED.alert_count,
                            last_seen = EXCLUDED.last_seen,
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        h3_cell,
                        species_name,
                        risk_level,
                        data['count'],
                        first_seen,
                        last_seen,
                        lat_centroid,
                        lon_centroid
                    ))
                except Exception as e:
                    logger.error(f"Failed to insert invasive hotspot: {e}")
            
            self.conn.commit()
            update_cursor.close()
            
            logger.info(f"Processed invasive species: {species_name} ({len(h3_invasive)} hotspots)")
        
        cursor.close()
    
    def run_full_transformation(self):
        """Execute complete transformation pipeline"""
        try:
            logger.info("Starting full transformation pipeline...")
            
            self.process_h3_richness()
            self.calculate_richness_percentiles()
            self.process_invasive_alerts()
            
            logger.info("Transformation pipeline completed successfully")
            return True
        except Exception as e:
            logger.error(f"Transformation pipeline failed: {e}")
            return False


def main():
    """CLI entry point"""
    import os
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    transformer = CuratedTransformer(
        pg_host=os.getenv('POSTGRES_HOST', 'localhost'),
        pg_port=int(os.getenv('POSTGRES_PORT', '5432')),
        pg_user=os.getenv('POSTGRES_USER', 'insect_user'),
        pg_password=os.getenv('POSTGRES_PASSWORD', 'insect_pass'),
        pg_db=os.getenv('POSTGRES_DB', 'insect_lake')
    )
    
    try:
        transformer.run_full_transformation()
    finally:
        transformer.close()


if __name__ == '__main__':
    main()
