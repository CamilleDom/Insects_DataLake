# ⚡ Quickstart — 5 minutes

```bash
git clone <repo>
cd insect-lake
cp .env.example .env
make build
make up
```

Attendre ~30s que les services soient healthy, puis :

```bash
curl http://localhost:8000/health
make load-test
make transform
curl http://localhost:8000/curated/hotspots | jq .
```

Déclencher l'ingestion iNaturalist manuellement :

```bash
make airflow-trigger
make logs-airflow
```

Lancer les tests :

```bash
make test
make benchmark
```

Tout arrêter :

```bash
make down
```