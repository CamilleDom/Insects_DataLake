# Insect Lake - Data Lake for Biodiversity

🐛 A comprehensive data lake for mapping insect biodiversity in France, detecting invasive species, and identifying biodiversity hotspots.

## Project Overview

This project implements a complete data lake architecture (Raw → Staging → Curated) for processing insect observation data from two sources:
- **iNaturalist API** (real-time observations)
- **GBIF Dataset** (historical data)

### Key Features

- 🏗️ **Multi-zone architecture**: Raw (MinIO) → Staging (PostgreSQL) → Curated (H3 indexing + invasive detection)
- 🔄 **Automated orchestration**: Apache Airflow DAGs for scheduled ingestion
- 🌍 **Geospatial indexing**: Uber H3 hexagon cells (~1 km²) for biodiversity hotspots
- 🚨 **Invasive species alerts**: Automatic detection of invasive insect species
- 📊 **FastAPI gateway**: RESTful endpoints for data access
- 🤖 **AI enrichment**: Claude Haiku 4.5 integration for species descriptions
- 🐳 **Docker Compose**: Complete containerized stack

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DATA SOURCES                               │
│         iNaturalist API          GBIF Dataset (CSV)             │
└────────────┬──────────────────────────┬──────────────────────────┘
             │                          │
             └──────────┬───────────────┘
                        ▼
        ┌─────────────────────────────────┐
        │      AIRFLOW ORCHESTRATION      │
        │  (DAGs: fetch, validate, load)  │
        └────────────┬────────────────────┘
                     ▼
        ┌─────────────────────────────────┐
        │   RAW ZONE (MinIO S3)           │
        │ raw-inaturalist/ | raw-gbif/    │
        └────────────┬────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────┐
        │  STAGING ZONE (PostgreSQL)      │
        │ staging.occurrences (normalized)│
        └────────────┬────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────┐
        │   CURATED ZONE (PostgreSQL)     │
        │ ├─ species_richness_h3          │
        │ └─ invasive_hotspots            │
        └────────────┬────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────┐
        │    FastAPI GATEWAY (Port 8000)  │
        │ /raw | /staging | /curated      │
        │ /ingest | /ingest_fast          │
        └─────────────────────────────────┘
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Raw Storage** | MinIO (S3-compatible) | Store raw JSON/CSV files |
| **Staging/Curated DB** | PostgreSQL + PostGIS | Normalized & enriched data |
| **Geospatial Indexing** | Uber H3 | Hexagon-based hotspot mapping |
| **Orchestration** | Apache Airflow 2.9.1 | DAG scheduling & monitoring |
| **API Gateway** | FastAPI | RESTful endpoints |
| **ML/Processing** | NumPy, scikit-learn, pandas | Data transformation |
| **LLM Integration** | Anthropic Claude Haiku 4.5 | Species enrichment |
| **Containerization** | Docker + Docker Compose | Local dev & deployment |

## Quick Start

### Prerequisites

- Docker & Docker Compose (latest)
- Python 3.11+ (for local development)
- Git

### 1. Clone Repository

```bash
cd c:\Users\camil\Desktop\DataLake_Project
git init
git add .
git commit -m "Initial commit: Insect Lake data lake structure"
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
# Required: Add your ANTHROPIC_API_KEY
```

### 3. Start Services

```bash
# Build and start all services
docker-compose up -d

# Verify services are running
docker-compose ps
```

### 4. Initialize Database

```bash
# Wait for PostgreSQL to be ready, then initialize
docker-compose exec postgres psql -U insect_user -d insect_lake -f /docker-entrypoint-initdb.d/01_init.sql
```

### 5. Access Services

| Service | URL | Credentials |
|---------|-----|-------------|
| **MinIO Console** | http://localhost:9001 | minioadmin / minioadmin |
| **Airflow UI** | http://localhost:8080 | admin / airflow |
| **API Docs** | http://localhost:8000/docs | N/A |
| **PostgreSQL** | localhost:5432 | insect_user / insect_pass |

## API Endpoints

### Health & Diagnostics

```bash
# Check service health
GET /health

# Get statistics
GET /stats
```

### Raw Zone

```bash
# List raw files in MinIO
GET /raw
```

### Staging Zone

```bash
# Get paginated staging data
GET /staging?limit=100&offset=0
```

### Curated Zone

```bash
# Get biodiversity hotspots (richness percentile)
GET /curated/hotspots?limit=50&min_percentile=75

# Get invasive species alerts
GET /curated/invasives?risk_level=high
```

### Data Ingestion

```bash
# Standard ingestion (1 element benchmark)
POST /ingest
{
  "data": {
    "observations": [
      {
        "species_name": "Vespa velutina",
        "latitude": 48.85,
        "longitude": 2.35,
        "observed_on": "2025-06-01"
      }
    ]
  }
}

# Fast ingestion (100+ elements, vectorized)
POST /ingest_fast
# Same payload as /ingest
```

## Data Sources

### iNaturalist API

- **Endpoint**: https://api.inaturalist.org/v1/observations
- **Parameters**:
  - `place_id=6753` (France)
  - `taxon_id=47158` (Insecta class)
  - `quality_grade=research,needs_id`
  - Rate limit: 100 req/min

### GBIF Dataset

- **Download**: https://www.gbif.org/occurrence/download
- **Filters**:
  - Taxon: Insecta (class)
  - Country: France
  - Year: 2010+
  - Format: CSV

## Database Schema

### Staging Zone

```sql
staging.occurrences
├─ id (VARCHAR, PK)
├─ species_name
├─ latitude / longitude
├─ observed_on
├─ quality_grade
├─ source (inaturalist | gbif)
└─ raw_payload (JSONB)
```

### Curated Zone

```sql
curated.species_richness_h3
├─ h3_cell (PK) - Uber H3 index resolution 7
├─ species_count
├─ richness_normalized = species_count / log(1 + obs_count)
└─ richness_percentile

curated.invasive_hotspots
├─ id (UUID)
├─ species_name
├─ invasive_risk (high | medium | low)
├─ alert_count
├─ first_seen / last_seen
└─ h3_cell
```

## Airflow DAG

**DAG Name**: `ingest_inaturalist`

```
fetch_api → validate_and_load_staging
```

- **Schedule**: @hourly
- **Retry**: 3 attempts, 5-minute delay
- **Tasks**:
  1. `fetch_api`: Call iNaturalist, save to MinIO
  2. `validate_and_load_staging`: Parse JSON, insert to PostgreSQL

### Trigger Manually

```bash
docker-compose exec airflow airflow dags trigger ingest_inaturalist
```

## Advanced Features (Optional)

### Optimization Benchmarks

Two-tier ingestion endpoints for performance testing:

#### `/ingest` (Standard)
- Single-row inserts
- Baseline performance

#### `/ingest_fast` (Optimized +30%)
- Vectorized H3 encoding with NumPy
- Async batch writes with asyncpg
- Invasive species list cached in memory

**Benchmark Test** (1 element):
```bash
time curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"data": {"observations": [{"species_name": "Test", "latitude": 48.85, "longitude": 2.35, "observed_on": "2025-01-01"}]}}'
```

**Benchmark Test** (100 elements):
```bash
# Generate 100 observations and POST to /ingest_fast
```

### Claude Haiku Integration

Enrich invasive species with auto-generated descriptions:

```python
from anthropic import Anthropic

client = Anthropic()
message = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=256,
    messages=[{
        "role": "user",
        "content": "Describe Vespa velutina (Asian hornet) briefly."
    }]
)
```

**Use Cases**:
- Generate species descriptions for `/curated/invasives`
- Classify unknown species risk levels
- Summarize alert trends

## Project Structure

```
DataLake_Project/
├── api/                          # FastAPI application
│   ├── main.py                   # Main app, endpoints
│   ├── config.py                 # Settings management
│   ├── db.py                     # DB & MinIO connections
│   ├── schemas.py                # Pydantic models
│   ├── requirements.txt           # Python dependencies
│   └── Dockerfile                # API container
├── airflow/
│   ├── dags/
│   │   └── ingest_inaturalist_dag.py  # Main orchestration DAG
│   └── plugins/                  # Custom operators (future)
├── scripts/
│   └── init_db.sql              # Database initialization
├── config/                       # Configuration files
├── docker-compose.yml            # Container orchestration
├── .env.example                  # Environment template
├── .gitignore                    # Git ignore rules
└── README.md                     # This file
```

## Development

### Run Locally (Without Docker)

```bash
# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r api/requirements.txt

# Set environment variables
$env:POSTGRES_HOST = "localhost"
$env:MINIO_URL = "localhost:9000"

# Run API
cd api
uvicorn main:app --reload
```

### Code Quality

```bash
# Format with Black
black api/

# Lint with Flake8
flake8 api/ --max-line-length=120

# Type check with Mypy
mypy api/
```

## Monitoring & Troubleshooting

### Check Service Logs

```bash
# API logs
docker-compose logs -f api

# Airflow logs
docker-compose logs -f airflow

# PostgreSQL logs
docker-compose logs -f postgres

# MinIO logs
docker-compose logs -f minio
```

### Common Issues

**MinIO bucket not found**:
```bash
docker-compose exec api python -c "from db import get_minio_client; get_minio_client()"
```

**PostgreSQL connection refused**:
```bash
# Wait for PostgreSQL startup
docker-compose exec postgres pg_isready
```

**Airflow DAG not visible**:
```bash
docker-compose exec airflow airflow dags list
```

## Evaluation Criteria (EFREI Project)

### Standard Level (16-20/20)

- ✅ Three-zone architecture (Raw/Staging/Curated)
- ✅ Robust transformation scripts with error handling
- ✅ Reliable integration pipeline (Airflow DAG)
- ✅ Complete API Gateway with all endpoints
- ✅ Well-documented code and README

### Advanced Level (Bonus)

- 🔧 `/ingest` endpoint (manual data ingestion)
- ⚡ `/ingest_fast` endpoint (+30% performance)
- 📊 Documented benchmarks (1 & 100 elements)
- 🎯 Creative optimizations (NumPy vectorization, async writes, caching)

## Deliverables

- [x] GitHub repository with full source code
- [x] Technical documentation (README, architecture)
- [x] Installation & build procedures
- [ ] Performance benchmarks (to be completed)
- [ ] Code comments (in progress)

## License

EFREI 2025-2026 - Data Lakes & Data Integration Project

## Author

Built for EFREI Data Engineering Specialization

---

**Questions or issues?** Refer to the [official project brief](Documentation/insect_lake_reference.pdf) or consult [project guidelines](Documentation/Data_Lakes__Projet.pdf).