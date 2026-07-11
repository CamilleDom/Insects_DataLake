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
Voir les résultats dans le dashboard

```bash
make streamlit
```

Ouvrir : **http://localhost:8501**

Déclencher l'ingestion iNaturalist manuellement :

```bash
make airflow-trigger
make logs-airflow
```
Classifier des images par CNN

```bash
make classify-images
curl "http://localhost:8000/curated/classifications?insect_only=true" | jq .
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