.PHONY: check-env db-shell db-reset db-stats shell-api classify-images airflow-list-dags airflow-dag-status docs help build up down logs test clean benchmark docs

help:
	@echo "Insect Lake Data Pipeline - Available Commands"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make build          Build Docker images"
	@echo "  make up             Start all services (docker-compose up -d)"
	@echo "  make down           Stop all services"
	@echo "  make logs           View service logs (Ctrl+C to exit)"
	@echo "  make logs-api       View API logs only"
	@echo "  make logs-airflow   View Airflow logs only"
	@echo "  make logs-db        View PostgreSQL logs only"
	@echo ""
	@echo "Data Loading:"
	@echo "  make load-test      Load small test dataset to staging"
	@echo "  make load-gbif      Load GBIF CSV (requires CSV_PATH=/path/to/file.txt)"
	@echo "  make transform      Run H3 transformation to curated zone"
	@echo "  make airflow-trigger Manually trigger iNaturalist DAG"
	@echo ""
	@echo "Testing & Validation:"
	@echo "  make test           Run integration test suite"
	@echo "  make benchmark      Run performance benchmarks"
	@echo "  make classify-images  Run CNN classification on new photos (batch of 20)"
	@echo ""
	@echo "Database:"
	@echo "  make db-shell       Open PostgreSQL shell"
	@echo "  make db-reset       Reset database (WARNING: deletes all data)"
	@echo "  make db-stats       Show database statistics"
	@echo ""
	@echo "Development:"
	@echo "  make shell-api      Open shell in API container"
	@echo "  make docs           Generate documentation"
	@echo "  make clean          Remove volumes and containers"

build:
	docker compose build --no-cache --pull

up: check-env
	docker-compose up -d
	@echo "Services starting... waiting for health checks..."
	@sleep 10
	docker-compose ps

down:
	docker-compose down

logs:
	docker-compose logs -f

logs-api:
	docker-compose logs -f api

logs-airflow:
	docker-compose logs -f airflow-scheduler airflow-webserver
logs-db:
	docker-compose logs -f postgres

# ── Data Loading ──────────────────────────────────────────────────────────────

load-test:
	@echo "Loading test data (10 observations)..."
	docker-compose exec api python /tests/load_test_data.py

load-gbif:
ifndef CSV_PATH
	@echo "Error: CSV_PATH not set. Usage: make load-gbif CSV_PATH=/path/to/occurrence.txt"
	@exit 1
endif
	docker-compose exec api python /scripts/load_gbif.py $(CSV_PATH)

transform:
	@echo "Running H3 transformation to curated zone..."
	docker-compose exec api python /scripts/transform_to_curated.py

airflow-trigger:
	docker-compose exec airflow-scheduler airflow dags trigger ingest_inaturalist
	@echo "✓ DAG trigger requested. View logs with: make logs-airflow"
airflow-list-dags:
	docker-compose exec airflow-scheduler airflow dags list

airflow-dag-status:
	docker-compose exec airflow-scheduler airflow dags list-runs -d ingest_inaturalist
# ── Testing ───────────────────────────────────────────────────────────────────

test:
	@echo "Running integration tests..."
	docker-compose exec api python /tests/test_integration.py

benchmark:
	@echo "Running performance benchmarks..."
	docker-compose exec api python /tests/fast_ingestor.py
classify-images:
	@echo "Running CNN image classification (batch de 20)..."
	docker-compose exec api python /scripts/classify_images.py 20

# ── Database ──────────────────────────────────────────────────────────────────

db-shell:
	docker-compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

db-reset:
	@echo "WARNING: This will delete all data!"
	@read -p "Are you sure? (yes/no): " confirm && \
	[ "$$confirm" = "yes" ] && \
	docker-compose down -v && \
	docker-compose up -d && \
	echo "✓ Database reset (fresh volume, init_db.sql re-executed)" || echo "Cancelled"
db-stats:
	docker-compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -c \
		"SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size FROM pg_tables WHERE schemaname IN ('staging', 'curated') ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;"

# ── Dev ───────────────────────────────────────────────────────────────────────

shell-api:
	docker-compose exec api bash

docs:
	@echo "Documentation files:"
	@echo "  • README.md - Full project documentation"
	@echo "  • BENCHMARKS.md - Performance analysis"
	@echo "  • docker-compose.yml - Container configuration"
	@echo "  • scripts/init_db.sql - Database schema"

clean:
	docker-compose down -v
	rm -rf postgres_data/ minio_data/ airflow_logs/
	@echo "✓ Cleaned up volumes and data directories"

.PHONY: check-env
check-env:
	@if [ ! -f .env ]; then \
		echo "Error: .env file not found. Creating from .env.example..."; \
		cp .env.example .env; \
		echo "✓ Created .env - please configure with your settings"; \
	else \
		echo "✓ .env already exists"; \
	fi