#!/usr/bin/env python3
"""
GBIF Dataset upload handler

Processes GBIF occurrence CSV files and loads them into the staging zone.
GBIF CSV format is tab-separated with many columns; we extract the relevant ones.

Usage:
    python load_gbif.py <path_to_occurrence.txt>
"""

import csv
import logging
import psycopg2
from datetime import datetime
from pathlib import Path
import sys
import os

logger = logging.getLogger(__name__)

# GBIF CSV column mapping (tab-separated)
GBIF_REQUIRED_COLUMNS = {
    'gbifID': 'id',
    'scientificName': 'species_name',
    'decimalLatitude': 'latitude',
    'decimalLongitude': 'longitude',
    'eventDate': 'observed_on',
}


class GBIFLoader:
    """Load GBIF occurrence data to staging zone"""
    
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
        if self.conn:
            self.conn.close()
    
    def parse_gbif_date(self, date_str: str) -> str:
        """Parse GBIF date format (ISO 8601) to YYYY-MM-DD"""
        if not date_str or date_str == '':
            return None
        
        try:
            # GBIF uses ISO 8601 format, might have time component
            dt = datetime.fromisoformat(date_str.split('T')[0])
            return dt.strftime('%Y-%m-%d')
        except:
            return None
    
    def load_csv(self, csv_path: str, batch_size: int = 1000) -> dict:
        """
        Load GBIF CSV file to staging zone
        
        Returns:
            {
                'loaded': int,
                'skipped': int,
                'errors': int,
                'total': int
            }
        """
        csv_path = Path(csv_path)
        
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        logger.info(f"Loading GBIF data from {csv_path}")
        
        loaded = 0
        skipped = 0
        errors = 0
        total = 0
        
        cursor = self.conn.cursor()
        
        try:
            # GBIF files are tab-separated with specific encoding
            with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
                # Detect if header exists
                reader = csv.DictReader(f, delimiter='\t')
                
                batch = []
                
                for row in reader:
                    total += 1
                    
                    try:
                        # Extract relevant fields
                        obs_id = row.get('gbifID', '').strip()
                        species_name = row.get('scientificName', 'Unknown').strip()
                        latitude_str = row.get('decimalLatitude', '').strip()
                        longitude_str = row.get('decimalLongitude', '').strip()
                        observed_on_str = row.get('eventDate', '').strip()
                        
                        # Validate coordinates
                        if not latitude_str or not longitude_str:
                            skipped += 1
                            continue
                        
                        try:
                            latitude = float(latitude_str)
                            longitude = float(longitude_str)
                        except ValueError:
                            skipped += 1
                            continue
                        
                        # Validate species name
                        if not species_name or species_name == 'Unknown':
                            skipped += 1
                            continue
                        
                        # Parse date
                        observed_on = self.parse_gbif_date(observed_on_str)
                        
                        # Add to batch
                        batch.append((
                            f"gbif_{obs_id}",
                            species_name,
                            latitude,
                            longitude,
                            observed_on,
                            'gbif'
                        ))
                        
                        # Insert when batch is full
                        if len(batch) >= batch_size:
                            try:
                                cursor.executemany("""
                                    INSERT INTO staging.occurrences 
                                    (id, species_name, latitude, longitude, observed_on, source)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (id) DO NOTHING
                                """, batch)
                                loaded += cursor.rowcount
                                batch = []
                            except Exception as e:
                                logger.error(f"Batch insert failed: {e}")
                                errors += 1
                                batch = []
                    
                    except Exception as e:
                        logger.warning(f"Failed to process row {total}: {e}")
                        errors += 1
                
                # Insert remaining batch
                if batch:
                    try:
                        cursor.executemany("""
                            INSERT INTO staging.occurrences 
                            (id, species_name, latitude, longitude, observed_on, source)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO NOTHING
                        """, batch)
                        loaded += cursor.rowcount
                    except Exception as e:
                        logger.error(f"Final batch insert failed: {e}")
                        errors += 1
                
                self.conn.commit()
        
        except Exception as e:
            logger.error(f"Failed to load CSV: {e}")
            self.conn.rollback()
            raise
        finally:
            cursor.close()
        
        logger.info(f"Load complete: {loaded} loaded, {skipped} skipped, {errors} errors out of {total} total")
        
        return {
            'loaded': loaded,
            'skipped': skipped,
            'errors': errors,
            'total': total
        }


def main():
    """CLI entry point"""
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("Usage: python load_gbif.py <path_to_occurrence.txt>")
        print("\nExample:")
        print("  python load_gbif.py /data/gbif/occurrence.txt")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    
    loader = GBIFLoader(
        pg_host=os.getenv('POSTGRES_HOST', 'localhost'),
        pg_port=int(os.getenv('POSTGRES_PORT', '5432')),
        pg_user=os.getenv('POSTGRES_USER', 'insect_user'),
        pg_password=os.getenv('POSTGRES_PASSWORD', 'insect_pass'),
        pg_db=os.getenv('POSTGRES_DB', 'insect_lake')
    )
    
    try:
        result = loader.load_csv(csv_path)
        print(f"\n✓ Successfully loaded {result['loaded']} records from GBIF")
        print(f"  Skipped: {result['skipped']}, Errors: {result['errors']}, Total processed: {result['total']}")
    except Exception as e:
        print(f"✗ Failed to load GBIF data: {e}")
        sys.exit(1)
    finally:
        loader.close()


if __name__ == '__main__':
    main()
