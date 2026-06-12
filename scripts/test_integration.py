#!/usr/bin/env python3
"""
Integration tests for Insect Lake data pipeline

Tests:
1. Service connectivity (MinIO, PostgreSQL, API)
2. API endpoints (health, stats, ingestion)
3. Data loading and transformation
4. Performance benchmarks
"""

import requests
import psycopg2
import logging
import os
import json
import time
from minio import Minio
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Configuration
API_URL = os.getenv('API_URL', 'http://localhost:8000')
MINIO_URL = os.getenv('MINIO_URL', 'localhost:9000')
MINIO_USER = os.getenv('MINIO_USER', 'minioadmin')
MINIO_PASSWORD = os.getenv('MINIO_PASSWORD', 'minioadmin')
PG_HOST = os.getenv('POSTGRES_HOST', 'localhost')
PG_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
PG_USER = os.getenv('POSTGRES_USER', 'insect_user')
PG_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'insect_pass')
PG_DB = os.getenv('POSTGRES_DB', 'insect_lake')


class IntegrationTester:
    """Run integration tests"""
    
    def __init__(self):
        self.results = {
            'passed': [],
            'failed': [],
            'warnings': []
        }
    
    def test_postgresql_connection(self):
        """Test PostgreSQL connectivity"""
        try:
            conn = psycopg2.connect(
                host=PG_HOST,
                port=PG_PORT,
                user=PG_USER,
                password=PG_PASSWORD,
                database=PG_DB
            )
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM staging.occurrences")
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            
            self.results['passed'].append(f"PostgreSQL: Connected ✓ ({count} records in staging)")
        except Exception as e:
            self.results['failed'].append(f"PostgreSQL: Failed - {e}")
    
    def test_minio_connection(self):
        """Test MinIO connectivity"""
        try:
            client = Minio(
                MINIO_URL,
                access_key=MINIO_USER,
                secret_key=MINIO_PASSWORD,
                secure=False
            )
            buckets = [b.name for b in client.list_buckets()]
            
            if 'raw-inaturalist' in buckets and 'raw-gbif' in buckets:
                self.results['passed'].append(f"MinIO: Connected ✓ (buckets: {', '.join(buckets)})")
            else:
                self.results['warnings'].append(f"MinIO: Connected but missing buckets (found: {buckets})")
        except Exception as e:
            self.results['failed'].append(f"MinIO: Failed - {e}")
    
    def test_api_health(self):
        """Test API health endpoint"""
        try:
            response = requests.get(f"{API_URL}/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.results['passed'].append(f"API /health: {data.get('status', 'unknown')} ✓")
            else:
                self.results['failed'].append(f"API /health: HTTP {response.status_code}")
        except Exception as e:
            self.results['failed'].append(f"API /health: Failed - {e}")
    
    def test_api_stats(self):
        """Test API stats endpoint"""
        try:
            response = requests.get(f"{API_URL}/stats", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.results['passed'].append(
                    f"API /stats: {data['staging_occurrences']} staging, "
                    f"{data['curated_h3_cells']} H3 cells ✓"
                )
            else:
                self.results['failed'].append(f"API /stats: HTTP {response.status_code}")
        except Exception as e:
            self.results['failed'].append(f"API /stats: Failed - {e}")
    
    def test_single_element_ingestion(self):
        """Test /ingest with single element"""
        try:
            payload = {
                "data": {
                    "observations": [
                        {
                            "species_name": "Test Species",
                            "latitude": 48.8566,
                            "longitude": 2.3522,
                            "observed_on": datetime.now().strftime('%Y-%m-%d')
                        }
                    ]
                }
            }
            
            response = requests.post(
                f"{API_URL}/ingest",
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                exec_time = data.get('execution_time_ms', 'unknown')
                self.results['passed'].append(
                    f"API /ingest (1 element): {data['inserted']} inserted in {exec_time}ms ✓"
                )
            else:
                self.results['failed'].append(f"API /ingest: HTTP {response.status_code}")
        except Exception as e:
            self.results['failed'].append(f"API /ingest: Failed - {e}")
    
    def test_batch_ingestion_fast(self):
        """Test /ingest_fast with 100 elements"""
        try:
            observations = [
                {
                    "species_name": f"Test Species {i}",
                    "latitude": 48.8566 + (i * 0.01),
                    "longitude": 2.3522 + (i * 0.01),
                    "observed_on": (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                }
                for i in range(100)
            ]
            
            payload = {"data": {"observations": observations}}
            
            response = requests.post(
                f"{API_URL}/ingest_fast",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                exec_time = data.get('execution_time_ms', 'unknown')
                throughput = data.get('throughput_obs_per_sec', 0)
                self.results['passed'].append(
                    f"API /ingest_fast (100 elements): {data['inserted']} inserted in {exec_time}ms "
                    f"({throughput:.1f} obs/sec) ✓"
                )
            else:
                self.results['failed'].append(f"API /ingest_fast: HTTP {response.status_code}")
        except Exception as e:
            self.results['failed'].append(f"API /ingest_fast: Failed - {e}")
    
    def test_curated_endpoints(self):
        """Test curated zone endpoints"""
        try:
            # Test hotspots
            response = requests.get(f"{API_URL}/curated/hotspots?limit=10", timeout=5)
            if response.status_code == 200:
                data = response.json()
                hotspots_count = len(data.get('hotspots', []))
                self.results['passed'].append(f"API /curated/hotspots: {hotspots_count} hotspots ✓")
            else:
                self.results['warnings'].append(f"API /curated/hotspots: Empty or error")
            
            # Test invasives
            response = requests.get(f"{API_URL}/curated/invasives", timeout=5)
            if response.status_code == 200:
                data = response.json()
                invasives_count = len(data.get('invasive_alerts', []))
                self.results['passed'].append(f"API /curated/invasives: {invasives_count} alerts ✓")
            else:
                self.results['warnings'].append(f"API /curated/invasives: Empty or error")
        except Exception as e:
            self.results['failed'].append(f"API /curated endpoints: Failed - {e}")
    
    def print_results(self):
        """Print test results"""
        print("\n" + "="*60)
        print("INTEGRATION TEST RESULTS")
        print("="*60)
        
        if self.results['passed']:
            print(f"\n✓ PASSED ({len(self.results['passed'])})")
            for msg in self.results['passed']:
                print(f"  • {msg}")
        
        if self.results['warnings']:
            print(f"\n⚠ WARNINGS ({len(self.results['warnings'])})")
            for msg in self.results['warnings']:
                print(f"  • {msg}")
        
        if self.results['failed']:
            print(f"\n✗ FAILED ({len(self.results['failed'])})")
            for msg in self.results['failed']:
                print(f"  • {msg}")
        
        print("\n" + "="*60)
        total = len(self.results['passed']) + len(self.results['failed'])
        passed = len(self.results['passed'])
        if total > 0:
            percentage = (passed / total) * 100
            print(f"OVERALL: {passed}/{total} tests passed ({percentage:.1f}%)")
        print("="*60 + "\n")
    
    def run_all(self):
        """Run all tests"""
        print("Starting integration tests...")
        print(f"API URL: {API_URL}")
        print(f"PostgreSQL: {PG_HOST}:{PG_PORT}/{PG_DB}")
        print(f"MinIO: {MINIO_URL}\n")
        
        self.test_postgresql_connection()
        self.test_minio_connection()
        self.test_api_health()
        self.test_api_stats()
        self.test_single_element_ingestion()
        self.test_batch_ingestion_fast()
        self.test_curated_endpoints()
        
        self.print_results()
        
        # Return success if no critical failures
        return len(self.results['failed']) == 0


def main():
    tester = IntegrationTester()
    success = tester.run_all()
    exit(0 if success else 1)


if __name__ == '__main__':
    main()
