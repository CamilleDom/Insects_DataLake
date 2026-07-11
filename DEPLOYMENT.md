# 🚀 Déploiement en production (pistes)

Ce document liste les adaptations nécessaires pour un déploiement au-delà du
contexte local/pédagogique de ce projet.

## Secrets & configuration
- Ne jamais committer `.env` (déjà dans `.gitignore`)
- Utiliser un gestionnaire de secrets (Vault, AWS Secrets Manager, Docker Secrets)
- Générer une `AIRFLOW__CORE__FERNET_KEY` dédiée en production

## Base de données
- Remplacer le PostgreSQL conteneurisé par une instance managée
  (RDS, Cloud SQL) avec sauvegardes automatiques et réplication
- Ajouter un connection pooler externe (PgBouncer) devant l'API

## Stockage objet
- Remplacer MinIO par un vrai bucket S3 en production (ou garder MinIO en
  cluster distribué avec réplication)
- Politique de rétention/cycle de vie sur les fichiers raw anciens

## Orchestration
- Passer Airflow en `CeleryExecutor` ou `KubernetesExecutor` pour scaler
  horizontalement les workers
- Isoler webserver / scheduler / workers sur des nœuds distincts

## API
- Ajouter une couche d'authentification (API Key / OAuth2) devant `/ingest`
- Ajouter un rate-limiting (ex: `slowapi`)
- Servir derrière un reverse proxy TLS (Nginx / Traefik)
- Ajouter des healthchecks Docker sur le service `api`

## Observabilité
- Centraliser les logs (ELK / Loki)
- Exposer des métriques Prometheus (latence, taux d'erreur, throughput ingestion)
- Alerting sur échec de DAG Airflow

## CI/CD
- Pipeline GitHub Actions : lint, tests, build d'images, scan de vulnérabilités
- Déploiement via Docker Compose (petite échelle) ou Kubernetes/Helm (grande échelle)