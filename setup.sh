#!/bin/bash
# PROJECT INITIALIZATION AND EXECUTION SCRIPT
# Insect Lake Data Pipeline - Complete Setup & Testing

set -e

echo "═══════════════════════════════════════════════════════════"
echo "  INSECT LAKE DATA PIPELINE - Setup & Testing Script"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_DIR"

# Step 1: Validate project structure
echo -e "${YELLOW}[1/6]${NC} Validating project structure..."
if python scripts/validate_project.py > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Project validation passed"
else
    echo -e "${RED}✗${NC} Project validation failed"
    exit 1
fi
echo ""

# Step 2: Create .env if not exists
echo -e "${YELLOW}[2/6]${NC} Checking environment configuration..."
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo -e "${YELLOW}⚠${NC} .env created with defaults. Edit if needed before starting."
else
    echo -e "${GREEN}✓${NC} .env file exists"
fi
echo ""

# Step 3: Build Docker images
echo -e "${YELLOW}[3/6]${NC} Building Docker images..."
if docker-compose build > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Docker images built successfully"
else
    echo -e "${RED}✗${NC} Docker build failed"
    exit 1
fi
echo ""

# Step 4: Start services
echo -e "${YELLOW}[4/6]${NC} Starting Docker services..."
docker-compose up -d > /dev/null 2>&1
echo "Waiting for services to be healthy (30 seconds)..."
sleep 30

# Check if services are running
if docker-compose ps | grep -q "healthy\|Up"; then
    echo -e "${GREEN}✓${NC} All services started"
    docker-compose ps | grep -E "NAME|Up"
else
    echo -e "${RED}✗${NC} Some services failed to start"
    docker-compose logs
    exit 1
fi
echo ""

# Step 5: Run integration tests
echo -e "${YELLOW}[5/6]${NC} Running integration tests..."
if docker-compose exec api python /app/../scripts/test_integration.py 2>&1 | tail -20; then
    echo -e "${GREEN}✓${NC} Integration tests completed"
else
    echo -e "${RED}✗${NC} Integration tests failed"
fi
echo ""

# Step 6: Load test data and transform
echo -e "${YELLOW}[6/6]${NC} Loading test data and running transformation..."

# Load test data
echo "Loading 10 test observations..."
docker-compose exec api python -c "
import sys; sys.path.insert(0, '/app')
from api.db import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
for i in range(10):
    cursor.execute(
        'INSERT INTO staging.occurrences (species_name, latitude, longitude, observed_on, source) VALUES (%s, %s, %s, NOW(), %s) ON CONFLICT DO NOTHING',
        (f'Vespa velutina test {i}', 48.8 + i*0.01, 2.3 + i*0.01, 'test')
    )
conn.commit()
cursor.close()
conn.close()
print('✓ Loaded 10 test records')
" > /dev/null 2>&1

# Run transformation
echo "Running H3 transformation..."
docker-compose exec api python /app/../scripts/transform_to_curated.py > /dev/null 2>&1

# Check results
STATS=$(docker-compose exec postgres psql -U insect_user -d insect_lake -t -c \
    "SELECT COUNT(*) as occurrences, 
            (SELECT COUNT(*) FROM curated.species_richness_h3) as h3_cells FROM staging.occurrences;" 2>/dev/null)

echo -e "${GREEN}✓${NC} Transformation completed"
echo "  Data in system: $STATS"
echo ""

# Final summary
echo "═══════════════════════════════════════════════════════════"
echo -e "${GREEN}✅ SETUP COMPLETE!${NC}"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Service URLs:"
echo "  API:              http://localhost:8000"
echo "  Airflow:          http://localhost:8080"
echo "  MinIO Console:    http://localhost:9001"
echo "  PostgreSQL:       localhost:5432"
echo ""
echo "Quick Commands:"
echo "  docker-compose ps           # Check service status"
echo "  make logs                   # View all logs"
echo "  make test                   # Run integration tests"
echo "  make load-test              # Load more test data"
echo "  make benchmark              # Run performance tests"
echo "  curl http://localhost:8000/stats | jq ."
echo ""
echo "Documentation:"
echo "  README.md       - Complete documentation"
echo "  QUICKSTART.md   - 5-minute setup guide"
echo "  TESTING.md      - Comprehensive testing procedures"
echo "  DEPLOYMENT.md   - Production deployment guide"
echo "  BENCHMARKS.md   - Performance analysis"
echo ""
echo "Next steps:"
echo "  1. Verify API: curl http://localhost:8000/health"
echo "  2. Load GBIF data: make load-gbif CSV_PATH=/path/to/file.txt"
echo "  3. Run transformation: make transform"
echo "  4. Query results: curl http://localhost:8000/curated/hotspots"
echo ""
