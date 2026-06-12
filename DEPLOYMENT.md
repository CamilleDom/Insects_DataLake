# Deployment Guide

Complete deployment instructions for the Insect Lake Data Pipeline.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Sources                             │
│  ┌────────────────────┐  ┌─────────────────────────────┐  │
│  │ iNaturalist API    │  │ GBIF CSV Download           │  │
│  │ (Real-time, France)│  │ (Historical, Tab-delimited) │  │
│  └────────────────────┘  └─────────────────────────────┘  │
└────────────────┬───────────────────────────────────────────┘
                 │
        ┌────────▼─────────┐
        │   Ingestion      │
        │  (FastAPI POST)  │
        └────────┬─────────┘
                 │
        ┌────────▼──────────────────────┐
        │   Raw Zone Storage            │
        │ MinIO: raw-inaturalist/       │
        │        raw-gbif/              │
        └────────┬──────────────────────┘
                 │
        ┌────────▼──────────────────────┐
        │   Staging Zone (PostgreSQL)   │
        │ • occurrences table           │
        │ • Normalized observations     │
        │ • Coordinate validation       │
        └────────┬──────────────────────┘
                 │
        ┌────────▼──────────────────────┐
        │   H3 Transformation           │
        │ • Hexagon aggregation (res 7) │
        │ • Richness calculation        │
        │ • Percentile ranking          │
        └────────┬──────────────────────┘
                 │
        ┌────────▼──────────────────────┐
        │   Curated Zone (PostgreSQL)   │
        │ • species_richness_h3         │
        │ • invasive_hotspots           │
        │ • indexed for queries         │
        └────────┬──────────────────────┘
                 │
        ┌────────▼──────────────────────┐
        │   REST API (FastAPI)          │
        │ • /health                     │
        │ • /stats                      │
        │ • /curated/hotspots           │
        │ • /curated/invasives          │
        └──────────────────────────────┘
```

## Production Checklist

### Pre-Deployment

- [ ] Environment variables configured (.env file)
- [ ] Docker & Docker Compose installed
- [ ] Sufficient disk space (minimum 10GB for volumes)
- [ ] Network connectivity (iNaturalist API access)
- [ ] PostgreSQL backup strategy defined
- [ ] Monitoring/alerting configured

### Deployment Steps

#### 1. Prepare Infrastructure

```bash
# Clone or navigate to project
cd DataLake_Project

# Create .env from template
cp .env.example .env

# Edit .env with production values
nano .env
# Important variables:
# - POSTGRES_PASSWORD (change from default)
# - MINIO_ROOT_PASSWORD (change from default)
# - INATURALIST_API_KEY (optional, for higher rate limit)
```

#### 2. Build & Start Services

```bash
# Build custom images (API container)
docker-compose build

# Start all services
docker-compose up -d

# Wait for health checks to pass
sleep 30
docker-compose ps

# Verify all services are healthy (should show "healthy" status)
```

#### 3. Verify Database

```bash
# Check PostgreSQL is initialized
docker-compose exec postgres pg_isready

# Verify schema exists
docker-compose exec postgres psql -U insect_user -d insect_lake \
  -c "SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('staging', 'curated')"

# Expected output: count > 0
```

#### 4. Load Initial Data

```bash
# Option A: GBIF CSV (recommended for production data)
# 1. Download from https://www.gbif.org/occurrence/download
# 2. Select: Insecta class, France, 2010-2025, CSV format
# 3. Extract ZIP to get occurrence.txt

docker-compose exec api python /app/../scripts/load_gbif.py /path/to/occurrence.txt

# Option B: Test data (for validation)
make load-test
```

#### 5. Transform to Curated Zone

```bash
# Run H3 transformation pipeline
docker-compose exec api python /app/../scripts/transform_to_curated.py

# Expected output:
# - Processing 100,000+ occurrences
# - Creating 2,000-5,000 H3 cells
# - Computing richness percentiles
# - Detecting invasive hotspots
```

#### 6. Start Airflow DAG

```bash
# Enable iNaturalist hourly ingestion
docker-compose exec airflow airflow dags unpause ingest_inaturalist

# Trigger first run manually
docker-compose exec airflow airflow dags trigger ingest_inaturalist

# Monitor DAG execution
docker-compose logs -f airflow
```

#### 7. Validate & Test

```bash
# Run integration test suite
docker-compose exec api python /app/../scripts/test_integration.py

# Expected results:
# - PostgreSQL connection: OK
# - MinIO connection: OK
# - API health: OK
# - API stats: Accurate record counts
# - Ingestion endpoints: Working
# - Curated endpoints: Returning data
```

#### 8. Performance Benchmarking

```bash
# Run benchmark suite (verify 30%+ improvement)
make benchmark

# Expected results:
# - Baseline (single element): 15-25ms
# - Optimized (100 elements): 1500-2000ms (33%+ improvement)
# - Throughput: 50+ observations/sec
```

### Post-Deployment

#### Monitoring

```bash
# Check service health
docker-compose ps

# Monitor logs (real-time)
docker-compose logs -f

# Specific service logs
docker-compose logs -f api
docker-compose logs -f airflow
docker-compose logs -f postgres
```

#### Database Maintenance

```bash
# Daily: Check database size
make db-stats

# Weekly: Vacuum & analyze
docker-compose exec postgres psql -U insect_user -d insect_lake -c "VACUUM ANALYZE;"

# Monthly: Check replication status (if HA enabled)
# Monthly: Backup database
docker-compose exec postgres pg_dump -U insect_user -d insect_lake > backup_$(date +%Y%m%d).sql
```

#### MinIO Maintenance

```bash
# Access MinIO console
# URL: http://localhost:9001
# User: minioadmin
# Password: (from .env)

# Check bucket usage
docker-compose exec minio du -sh /data/

# List archived files
docker-compose exec minio ls -la /data/raw-inaturalist/
```

#### API Monitoring

```bash
# Check API uptime
watch -n 5 'curl -s http://localhost:8000/health | jq .'

# Monitor response times
# Integration test includes timing metrics
docker-compose exec api python /app/../scripts/test_integration.py
```

## Scaling Considerations

### Vertical Scaling (Bigger Machine)
- Increase PostgreSQL memory: `shared_buffers`, `work_mem`
- Increase FastAPI workers: Modify Dockerfile
- Increase MinIO replicas: Configure S3 replication

### Horizontal Scaling (Multiple Machines)
- PostgreSQL replication to read-only replicas
- MinIO distributed mode (multiple nodes)
- Multiple FastAPI instances behind load balancer
- Airflow worker scaling for DAG parallelization

### Database Optimization
```sql
-- Add more indexes for common queries
CREATE INDEX idx_invasive_risk ON curated.invasive_hotspots(invasive_risk);
CREATE INDEX idx_h3_richness ON curated.species_richness_h3(richness_percentile DESC);

-- Partition tables for large datasets
ALTER TABLE staging.occurrences PARTITION BY RANGE (observed_on);
```

## Troubleshooting

### Services not starting
```bash
# Check logs
docker-compose logs postgres
docker-compose logs api

# Verify ports are available
netstat -tlnp | grep -E '5432|9000|8000|8080'

# Reset everything
docker-compose down -v
docker-compose up -d
```

### Ingestion failures
```bash
# Check Airflow logs
docker-compose logs airflow

# Verify iNaturalist API
curl 'https://api.inaturalist.org/v1/observations?place_id=6753&taxon_id=47158&quality_grade=research&per_page=1'

# Check MinIO connectivity
docker-compose exec api python -c "from minio import Minio; m = Minio('minio:9000'); print(m.list_buckets())"
```

### Database issues
```bash
# Check PostgreSQL logs
docker-compose logs postgres

# Verify connectivity
docker-compose exec postgres psql -U insect_user -d insect_lake -c "SELECT 1"

# Check disk space
docker-compose exec postgres df -h

# Check for long-running queries
docker-compose exec postgres psql -U insect_user -d insect_lake -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"
```

### Performance degradation
```bash
# Analyze table statistics
docker-compose exec postgres psql -U insect_user -d insect_lake -c "ANALYZE;"

# Check index fragmentation
docker-compose exec postgres psql -U insect_user -d insect_lake -c "SELECT * FROM pg_stat_user_indexes WHERE idx_scan = 0;"

# Rebuild problematic indexes
docker-compose exec postgres psql -U insect_user -d insect_lake -c "REINDEX INDEX idx_name;"
```

## Backup & Recovery

### Backup Strategy

```bash
# Daily PostgreSQL backup
docker-compose exec postgres pg_dump -U insect_user -d insect_lake > backup_$(date +%Y%m%d_%H%M%S).sql

# Backup MinIO buckets
docker-compose exec minio mc mirror minio/raw-inaturalist ./backups/raw-inaturalist/
docker-compose exec minio mc mirror minio/raw-gbif ./backups/raw-gbif/

# Store backups offsite (S3, Azure, etc.)
aws s3 cp backup_*.sql s3://my-bucket/insect-lake-backups/
```

### Recovery Procedure

```bash
# Restore PostgreSQL
docker-compose exec -T postgres psql -U insect_user -d insect_lake < backup_20250612_100000.sql

# Restore MinIO (from local backups)
docker-compose exec minio mc mirror ./backups/raw-inaturalist/ minio/raw-inaturalist/

# Rerun transformation
docker-compose exec api python /app/../scripts/transform_to_curated.py
```

## Security Hardening

### Environment Variables
```bash
# Never commit .env file
echo ".env" >> .gitignore

# Use strong passwords
POSTGRES_PASSWORD=$(openssl rand -base64 32)
MINIO_ROOT_PASSWORD=$(openssl rand -base64 32)
```

### Network Security
```yaml
# In docker-compose.yml, use internal networks only
# Remove port mappings for production
# Use reverse proxy (nginx) for external access
```

### Data Encryption
```bash
# Enable PostgreSQL SSL
# Enable MinIO TLS/SSL
# Encrypt volumes at rest
```

## Performance Tuning

### PostgreSQL
```sql
-- Increase shared buffers (25% of RAM)
ALTER SYSTEM SET shared_buffers = '4GB';

-- Increase work memory
ALTER SYSTEM SET work_mem = '50MB';

-- Increase effective cache size (50% of RAM)
ALTER SYSTEM SET effective_cache_size = '8GB';

-- Apply changes
SELECT pg_reload_conf();
```

### FastAPI
```dockerfile
# Increase workers in Dockerfile
CMD ["gunicorn", "--workers=4", "--threads=2", "main:app"]
```

## Support & Maintenance

- **Documentation**: See [README.md](README.md)
- **Performance**: See [BENCHMARKS.md](BENCHMARKS.md)
- **Quick Start**: See [QUICKSTART.md](QUICKSTART.md)
- **Issues**: Check service logs with `docker-compose logs`

---

**Estimated deployment time: 30-45 minutes**

Last updated: June 2025
