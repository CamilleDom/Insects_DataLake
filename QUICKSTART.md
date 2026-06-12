# Quick Start Guide

Complete setup of the Insect Lake data pipeline in 5 minutes.

## Prerequisites

- **Docker & Docker Compose** (version 3.9+)
- **Python 3.11+** (for local scripts)
- **Git** (for version control)

## Step 1: Configure Environment (1 min)

```bash
cd DataLake_Project
cp .env.example .env
# Edit .env if needed (defaults are fine for local development)
cat .env
```

## Step 2: Start Docker Stack (2 min)

```bash
# Build and start all services
docker-compose up -d

# Wait for services to be healthy
docker-compose ps

# Verify API is running
curl http://localhost:8000/health
```

You should see:
- ✓ `minio` (MinIO object storage on port 9000/9001)
- ✓ `postgres` (PostgreSQL on port 5432)
- ✓ `airflow` (Airflow on port 8080)
- ✓ `api` (FastAPI on port 8000)

## Step 3: Load Test Data (1 min)

```bash
# Option A: Load 10 test records
make load-test

# Option B: Load real GBIF data
# First download CSV from https://www.gbif.org/occurrence/download
# Then:
make load-gbif CSV_PATH=/path/to/occurrence.txt
```

## Step 4: Transform to Curated Zone (30 sec)

```bash
# Run H3 transformation pipeline
make transform

# This creates:
# - H3 hexagon cells at resolution 7 (~1 km² each)
# - Species richness rankings (0-100 percentile)
# - Invasive species hotspot detection
```

## Step 5: Query Results via API (30 sec)

```bash
# Check stats
curl http://localhost:8000/stats | python -m json.tool

# Get top 10 biodiversity hotspots
curl http://localhost:8000/curated/hotspots?limit=10 | python -m json.tool

# Get invasive species alerts
curl http://localhost:8000/curated/invasives | python -m json.tool
```

## Optional: Performance Benchmarking

```bash
# Run complete benchmark suite
make benchmark

# Or test /ingest_fast endpoint directly
curl -X POST http://localhost:8000/ingest_fast \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "observations": [
        {"species_name": "Vespa velutina", "latitude": 48.8, "longitude": 2.3, "observed_on": "2025-06-01"},
        {"species_name": "Harmonia axyridis", "latitude": 49.0, "longitude": 2.5, "observed_on": "2025-06-02"}
      ]
    }
  }' | python -m json.tool
```

## Useful Commands

| Command | Purpose |
|---------|---------|
| `make up` | Start all services |
| `make down` | Stop all services |
| `make logs` | View all service logs |
| `make test` | Run integration tests |
| `make db-shell` | Open PostgreSQL shell |
| `make clean` | Delete all volumes (destructive) |

## Data Flow

```
iNaturalist API / GBIF CSV
        ↓
   MinIO (raw zone)
        ↓
   PostgreSQL Staging
        ↓
   Transform to H3
        ↓
   PostgreSQL Curated
        ↓
   FastAPI REST
```

## Service URLs

| Service | URL | Purpose |
|---------|-----|---------|
| FastAPI | `http://localhost:8000` | REST API & endpoints |
| Airflow | `http://localhost:8080` | DAG scheduling & monitoring |
| MinIO Console | `http://localhost:9001` | Object storage browser |
| PostgreSQL | `localhost:5432` | Database (use DBeaver or psql) |

## Troubleshooting

### Services won't start
```bash
# Check logs
docker-compose logs postgres
docker-compose logs api

# Full reset
make clean
docker-compose up -d
```

### Database connection errors
```bash
# Verify PostgreSQL is ready
docker-compose exec postgres pg_isready

# Reset database
make db-reset
```

### API not responding
```bash
# Check if API container is running
docker-compose ps api

# View API logs
make logs-api

# Restart API
docker-compose restart api
```

## Next Steps

1. **Download real data**: Get GBIF dataset from https://www.gbif.org/occurrence/download
2. **Monitor Airflow**: Set up iNaturalist API key for hourly data fetch
3. **Analyze results**: Use curated zone endpoints for species richness analysis
4. **Deploy**: Follow deployment guide in README.md

## Performance Targets

| Metric | Target | Achieved |
|--------|--------|----------|
| Throughput | 40 obs/sec | **59.5 obs/sec** ✓ |
| Improvement | 30% | **33.3%** ✓ |
| H3 Cells Created | 1000+ | Depends on data |
| Invasive Hotspots | 50+ | Depends on data |

## Support

- 📖 See [README.md](README.md) for complete documentation
- 📊 See [BENCHMARKS.md](BENCHMARKS.md) for performance analysis
- 🐛 Check logs: `make logs`
- 💾 Database schema: [scripts/init_db.sql](scripts/init_db.sql)

---

**Time to full setup: ~5 minutes** ⚡

