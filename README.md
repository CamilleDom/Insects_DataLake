# 🐝 Insect Lake — Data Lake pour la biodiversité entomologique en France

Projet final — Data Lakes & Data Integration (EFREI 2025-2026)

## 🎯 Objectif

Data lake complet ingérant des observations d'insectes en France depuis deux
sources hétérogènes (API temps réel + dataset fichier), les nettoyant, les
enrichissant (indexation spatiale H3, détection d'espèces invasives) et les
exposant via une API REST.

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  iNaturalist│────▶│              │     │                  │
│     API     │     │  RAW ZONE    │────▶│  STAGING ZONE    │
└─────────────┘     │  (MinIO S3)  │     │  (PostgreSQL)    │
┌─────────────┐     │              │     │                  │
│  GBIF CSV   │────▶│              │     └────────┬─────────┘
│  (fichier)  │     └──────────────┘              │
└─────────────┘                                   ▼
                                          ┌──────────────────┐
                     Orchestration        │   CURATED ZONE   │
                     Apache Airflow       │  (PostgreSQL +   │
                     (@hourly)            │   H3 indexing)   │
                                          └────────┬─────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │   FastAPI Gateway│
                                          │  /raw /staging   │
                                          │  /curated /health│
                                          │  /stats /ingest  │
                                          └──────────────────┘
```

- **Raw** : MinIO (S3-compatible) — fichiers JSON bruts iNaturalist + GBIF
- **Staging** : PostgreSQL/PostGIS — occurrences validées et normalisées
- **Curated** : PostgreSQL — agrégats métier :
  - `species_richness_h3` : richesse spécifique par cellule H3 (résolution 7)
  - `invasive_hotspots` : alertes d'espèces invasives géolocalisées

## 📊 Sources de données

| Source | Type | Fréquence |
|--------|------|-----------|
| [iNaturalist API](https://api.inaturalist.org) | API REST | Ingestion horaire via Airflow |
| [GBIF](https://www.gbif.org) | Dataset fichier (CSV/TSV) | Chargement manuel (`make load-gbif`) |

## 🚀 Installation & lancement

### Prérequis
- Docker & Docker Compose
- 4 Go RAM disponibles minimum

### Démarrage rapide

```bash
git clone <repo>
cd insect-lake
cp .env.example .env
make build
make up
```

Vérifier que tout tourne :

```bash
docker-compose ps
curl http://localhost:8000/health
```

### Services exposés

| Service | URL |
|---------|-----|
| API | http://localhost:8000 (docs : `/docs`) |
| Airflow UI | http://localhost:8080 (admin/admin) |
| MinIO Console | http://localhost:9001 (minioadmin/minioadmin) |
| PostgreSQL | localhost:5432 |

## 🔌 Endpoints API

| Endpoint | Méthode | Description |
|----------|---------|--------------|
| `/health` | GET | État des services (MinIO, Postgres, API) |
| `/stats` | GET | Métriques de remplissage (buckets + tables) |
| `/raw` | GET | Liste des fichiers bruts (MinIO) |
| `/staging` | GET | Données intermédiaires paginées |
| `/curated` | GET | Vue d'ensemble zone curated |
| `/curated/hotspots` | GET | Richesse spécifique par cellule H3 |
| `/curated/invasives` | GET | Alertes espèces invasives |
| `/ingest` | POST | Ingestion standard (niveau avancé) |
| `/ingest_fast` | POST | Ingestion optimisée (niveau avancé) |
| `/benchmark` | GET | Informations sur le benchmark |

## 🧪 Tests & données de test

```bash
make load-test         # Charge 10 observations de test
make transform         # Lance la transformation staging -> curated
make test               # Suite de tests d'intégration
make benchmark          # Benchmark /ingest vs /ingest_fast
```

## 📁 Chargement du dataset GBIF

```bash
# Télécharger un export GBIF (occurrence.txt, format Darwin Core)
make load-gbif CSV_PATH=/path/to/occurrence.txt
```

## ⚙️ Pipeline Airflow

Le DAG `ingest_inaturalist` (déclenché toutes les heures) exécute :
1. `fetch_api` : récupère les observations depuis l'API iNaturalist → MinIO
2. `validate_and_load_staging` : valide et charge dans `staging.occurrences`
3. `transform_to_curated` : recalcule les agrégats H3 et les alertes invasives

Déclenchement manuel : `make airflow-trigger`

## 🏎️ Niveau avancé : `/ingest` vs `/ingest_fast`

Voir [`BENCHMARKS.md`](BENCHMARKS.md) pour le détail des optimisations et les
résultats mesurés (objectif : +30% de performance).

## 📂 Structure du projet

```
├── airflow/
│   ├── dags/ingest_inaturalist_dag.py
│   ├── plugins/
│   ├── Dockerfile
│   └── requirements.txt
├── api/
│   ├── main.py            # FastAPI app + endpoints
│   ├── config.py          # Configuration (pydantic-settings)
│   ├── db.py               # Pool Postgres + client MinIO
│   ├── schemas.py          # Modèles Pydantic
│   ├── requirements.txt
│   └── Dockerfile
├── scripts/
│   ├── init_db.sql              # Schéma PostgreSQL (staging/curated/audit)
│   ├── fast_ingestor.py         # Module d'ingestion optimisée
│   ├── load_gbif.py             # Chargeur du dataset GBIF
│   ├── transform_to_curated.py  # Pipeline staging -> curated
│   └── validate_project.py      # Script de validation de la structure
├── tests/
│   ├── test_integration.py
│   ├── load_test_data.py
│   └── fast_ingestor.py         # Benchmark /ingest vs /ingest_fast
├── docker-compose.yml
├── Makefile
└── .env.example
```

## 🛠️ Choix techniques

- **MinIO** pour la zone raw : compatible S3, léger, facile à opérer en local
- **PostgreSQL + PostGIS** pour staging/curated : requêtes géospatiales natives
- **H3 (Uber)** pour l'indexation spatiale (résolution 7 ≈ cellules de 5 km²)
- **Airflow** pour l'orchestration (scheduling + XCom entre tâches)
- **FastAPI** pour l'API Gateway (validation Pydantic, docs auto `/docs`)

## 🐛 Gestion des erreurs

- Toutes les routes retournent des codes HTTP appropriés (`4xx`/`5xx`) avec
  message d'erreur explicite
- Le pool de connexions PostgreSQL est correctement libéré (`close_db_connection`)
  même en cas d'exception
- Les scripts d'ingestion valident les coordonnées et gèrent les doublons
  (`ON CONFLICT DO NOTHING`)

## 👤 Auteur

Camille Dommergue — EFREI 2025-2026