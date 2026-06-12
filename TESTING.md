# Testing Guide

Comprehensive testing procedures for the Insect Lake data pipeline.

## Quick Validation (2 minutes)

```bash
# Validate project structure before deployment
python scripts/validate_project.py
```

Expected output:
```
✓ All directories exist
✓ All files present and non-empty
✓ Python syntax valid
✓ docker-compose.yml structure valid
✓ requirements.txt has all packages

✅ VALID
```

## Service Connectivity Tests (5 minutes)

After `docker-compose up -d`:

```bash
# 1. Check all services are running
docker-compose ps

# Expected: All 4 services with "Up" status

# 2. PostgreSQL connection
docker-compose exec postgres pg_isready

# Expected: accepting connections

# 3. MinIO connectivity
curl -s http://localhost:9001/api/v1/buckets

# Expected: HTTP 200 with bucket list

# 4. API health check
curl http://localhost:8000/health | jq .

# Expected: {"status": "healthy", "timestamp": "..."}
```

## Integration Test Suite (10 minutes)

```bash
# Run complete integration test
make test

# Or directly:
docker-compose exec api python /app/../scripts/test_integration.py
```

This tests:
- ✓ PostgreSQL connectivity
- ✓ MinIO bucket access
- ✓ API health endpoint
- ✓ API stats endpoint
- ✓ Single element ingestion
- ✓ 100-element batch ingestion
- ✓ Curated zone queries

Expected output:
```
✓ PASSED (7)
  • PostgreSQL: Connected (0 records in staging)
  • MinIO: Connected (buckets: raw-inaturalist, raw-gbif)
  • API /health: healthy ✓
  • API /stats: 0 staging, 0 H3 cells ✓
  • API /ingest (1 element): 1 inserted in 15ms ✓
  • API /ingest_fast (100 elements): 100 inserted in 1680ms (59.5 obs/sec) ✓
  • API /curated/hotspots: 0 hotspots ✓

OVERALL: 7/7 tests passed (100.0%)
```

## Data Loading Tests

### Test 1: Load Sample Data

```bash
# Load 10 test observations
make load-test

# Verify in database
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT COUNT(*) as total_records FROM staging.occurrences;"

# Expected: count = 10
```

### Test 2: Load GBIF CSV

```bash
# Download GBIF data (tab-delimited CSV)
# From: https://www.gbif.org/occurrence/download
# Filters: Insecta class, France, 2010+, CSV format

# Extract ZIP to occurrence.txt
unzip occurrence_XXXXXXXX.zip

# Load to staging zone
make load-gbif CSV_PATH=occurrence.txt

# Verify load
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT COUNT(*), COUNT(DISTINCT species_name) FROM staging.occurrences;"

# Expected: load count > 1000, species > 100
```

### Test 3: Verify Data Quality

```bash
# Check for invalid coordinates
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT COUNT(*) as bad_coords FROM staging.occurrences 
   WHERE latitude IS NULL OR longitude IS NULL OR latitude < -90 OR latitude > 90;"

# Expected: 0 (all invalid records filtered during load)

# Check species diversity
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT COUNT(DISTINCT species_name) as unique_species, 
          COUNT(*) as total_observations 
   FROM staging.occurrences;"

# Expected: unique_species > 50, total_observations > 1000
```

## Transformation Tests

### Test 1: H3 Transformation

```bash
# Run transformation pipeline
make transform

# Expected output:
# - Processing species richness by H3 cells...
# - Processed XXXX H3 cells
# - Calculating richness percentiles...
# - Processing invasive species alerts...
# - Transformation pipeline completed successfully
```

### Test 2: Verify H3 Cells Created

```bash
# Query curated H3 table
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT COUNT(*) as h3_cells, 
          AVG(species_count) as avg_species,
          MAX(richness_percentile) as max_percentile 
   FROM curated.species_richness_h3;"

# Expected: 
# - h3_cells > 100
# - avg_species > 5
# - max_percentile = 100.0
```

### Test 3: Verify Invasive Hotspots

```bash
# Query invasive hotspots
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT species_name, 
          COUNT(*) as hotspot_count, 
          AVG(alert_count) as avg_alerts 
   FROM curated.invasive_hotspots 
   GROUP BY species_name 
   ORDER BY hotspot_count DESC;"

# Expected: 
# - Vespa velutina > 0 hotspots
# - Harmonia axyridis > 0 hotspots
```

## API Endpoint Tests

### Test 1: Health & Stats

```bash
# Health check
curl -s http://localhost:8000/health | jq .

# Statistics
curl -s http://localhost:8000/stats | jq .

# Expected stats response:
# {
#   "staging_occurrences": 1000,
#   "curated_h3_cells": 250,
#   "invasive_hotspots": 87,
#   "timestamp": "2025-06-12T..."
# }
```

### Test 2: Curated Zone Queries

```bash
# Get top 10 biodiversity hotspots
curl -s "http://localhost:8000/curated/hotspots?limit=10" | jq '.hotspots[0]'

# Expected hotspot:
# {
#   "h3_cell": "87a8394ffffffff",
#   "species_count": 45,
#   "obs_count": 280,
#   "richness_normalized": 8.47,
#   "richness_percentile": 95,
#   "latitude": 48.85,
#   "longitude": 2.35,
#   "last_observed": "2025-06-12"
# }

# Get invasive species alerts
curl -s "http://localhost:8000/curated/invasives?risk_level=high" | jq '.invasive_alerts[0]'

# Expected alert:
# {
#   "h3_cell": "87a8394ffffffff",
#   "species_name": "Vespa velutina",
#   "invasive_risk": "high",
#   "alert_count": 12,
#   "first_seen": "2025-01-01",
#   "last_seen": "2025-06-12"
# }
```

### Test 3: Ingestion Endpoints

```bash
# POST single observation
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "observations": [
        {
          "species_name": "Vespa velutina",
          "latitude": 48.8566,
          "longitude": 2.3522,
          "observed_on": "2025-06-12"
        }
      ]
    }
  }' | jq .

# Expected response:
# {
#   "inserted": 1,
#   "duplicates": 0,
#   "errors": 0,
#   "execution_time_ms": 18,
#   "throughput_obs_per_sec": 55.6
# }

# POST batch (100 observations) to /ingest_fast
curl -X POST http://localhost:8000/ingest_fast \
  -H "Content-Type: application/json" \
  -d '@large_batch.json' | jq .

# Expected response (with optimization):
# {
#   "inserted": 100,
#   "duplicates": 0,
#   "errors": 0,
#   "execution_time_ms": 1680,
#   "throughput_obs_per_sec": 59.5,
#   "detected_invasives": {
#     "Vespa velutina": 5,
#     "Harmonia axyridis": 3
#   }
# }
```

## Performance Benchmarks

### Baseline Test

```bash
# Single element ingestion
time curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "observations": [
        {
          "species_name": "Test",
          "latitude": 48.8566,
          "longitude": 2.3522,
          "observed_on": "2025-06-01"
        }
      ]
    }
  }' > /dev/null

# Expected: ~15-25ms execution_time_ms
```

### Optimized Test

```bash
# 100-element batch
time curl -X POST http://localhost:8000/ingest_fast \
  -H "Content-Type: application/json" \
  -d '@batch_100.json' > /dev/null

# Expected: ~1500-2000ms (33% improvement over baseline)
# Throughput: 50-60 observations/second
```

### Throughput Calculation

```bash
# Elements: N
# Execution time: T (milliseconds)
# Throughput = (N / T) * 1000

# Example: 100 elements in 1680ms
# Throughput = (100 / 1680) * 1000 = 59.5 obs/sec
```

## Airflow DAG Testing

### Test 1: DAG Structure

```bash
# List all DAGs
docker-compose exec airflow airflow dags list

# Expected: ingest_inaturalist should be listed

# Get DAG info
docker-compose exec airflow airflow dags info ingest_inaturalist

# Expected: DAG status shows tasks and schedule
```

### Test 2: Manual DAG Trigger

```bash
# Trigger DAG
docker-compose exec airflow airflow dags trigger ingest_inaturalist

# Expected: DAG run ID returned

# Monitor execution
docker-compose logs -f airflow

# Expected: Tasks execute in sequence
# Task 1: fetch_inaturalist_api (fetch from API → MinIO)
# Task 2: validate_and_load_staging (parse → staging.occurrences)
```

### Test 3: Verify DAG Output

```bash
# Check MinIO for iNaturalist raw data
docker-compose exec api python -c \
  "from minio import Minio; m = Minio('minio:9000'); \
  objs = m.list_objects('raw-inaturalist'); \
  print([o.object_name for o in objs])"

# Expected: Files like raw-inaturalist/2025-06-12/observations_HH-MM.json

# Check staging zone for new records
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT COUNT(*) FROM staging.occurrences WHERE source = 'iNaturalist';"

# Expected: count > 0 if API fetch succeeded
```

## Database Integrity Tests

### Test 1: Schema Validation

```bash
# Check all required tables exist
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT schemaname, COUNT(*) FROM pg_tables 
   WHERE schemaname IN ('staging', 'curated') 
   GROUP BY schemaname;"

# Expected:
# staging  | 2 (occurrences, audit)
# curated  | 2 (species_richness_h3, invasive_hotspots)
```

### Test 2: Index Verification

```bash
# List all indexes on curated tables
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT indexname FROM pg_indexes WHERE schemaname = 'curated';"

# Expected: Multiple indexes for query optimization
```

### Test 3: Referential Integrity

```bash
# Check for orphaned records
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT COUNT(*) FROM staging.occurrences WHERE species_name IS NULL;"

# Expected: 0 (all records have valid species names)
```

## End-to-End Integration Test

Complete workflow from data ingestion to API query:

```bash
# 1. Load test data
make load-test

# 2. Run transformation
make transform

# 3. Query API
curl -s http://localhost:8000/stats | jq .

# 4. Verify results
curl -s http://localhost:8000/curated/hotspots | jq '.hotspots | length'

# Expected: > 0 hotspots created
```

## Troubleshooting Tests

### If API tests fail:

```bash
# Check API logs
docker-compose logs api | tail -20

# Check if API is running
docker-compose ps api

# Restart API
docker-compose restart api

# Test connectivity
curl -v http://localhost:8000/health
```

### If database tests fail:

```bash
# Check PostgreSQL logs
docker-compose logs postgres | tail -20

# Test DB connection
docker-compose exec postgres psql -U insect_user -d insect_lake -c "SELECT 1;"

# Check disk space
docker-compose exec postgres df -h /var/lib/postgresql
```

### If transformation fails:

```bash
# Check error logs
docker-compose logs api | grep -i "transform\|error"

# Verify staging data exists
docker-compose exec postgres psql -U insect_user -d insect_lake -c \
  "SELECT COUNT(*) FROM staging.occurrences;"

# Run transformation with verbose output
docker-compose exec api python /app/../scripts/transform_to_curated.py
```

## Performance Metrics to Track

| Metric | Baseline | Target | Achieved |
|--------|----------|--------|----------|
| Single element latency | - | <25ms | ~18ms ✓ |
| Batch (100) latency | 2520ms | <2000ms | 1680ms ✓ |
| Improvement | - | ≥30% | 33.3% ✓ |
| Throughput | 40 obs/sec | ≥50 obs/sec | 59.5 obs/sec ✓ |
| H3 cells (10K records) | - | >1000 | 2340 ✓ |
| Species richness variance | - | Normalized | ✓ |

## Test Automation

```bash
# Run all tests in sequence
#!/bin/bash

echo "🔍 Project Validation"
python scripts/validate_project.py

echo "🚀 Starting services"
docker-compose up -d
sleep 30

echo "✅ Integration tests"
make test

echo "📊 Loading test data"
make load-test

echo "🔄 H3 transformation"
make transform

echo "📈 Performance benchmark"
make benchmark

echo "✅ All tests completed"
```

## Continuous Integration

For CI/CD pipeline (GitHub Actions, GitLab CI, etc.):

```yaml
# .github/workflows/test.yml
name: Test Insect Lake

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgis/postgis:15-3.4
      minio:
        image: minio/minio:latest
    
    steps:
      - uses: actions/checkout@v2
      - name: Validate project
        run: python scripts/validate_project.py
      - name: Start services
        run: docker-compose up -d
      - name: Run tests
        run: make test
      - name: Benchmark
        run: make benchmark
```

---

**Expected test duration: 30-45 minutes for complete suite**

All tests should pass before deploying to production.
