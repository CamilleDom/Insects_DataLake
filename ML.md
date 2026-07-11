# 🧠 Classification d'images par CNN (bonus)

## Approche

Chaque observation iNaturalist possédant une photo est classifiée par
**MobileNetV2** (transfer learning, poids pré-entraînés ImageNet-1k, via
`torchvision`). Le résultat est stocké dans `curated.image_classifications`.

## Pourquoi ImageNet et pas un modèle "espèces d'insectes" ?

Aucun dataset annoté d'espèces d'insectes françaises n'était disponible
dans le cadre du projet. Plutôt que d'entraîner un modèle peu fiable sur
un petit dataset non labellisé, on utilise un CNN robuste et bien établi,
en interprétant intelligemment ses prédictions : ImageNet-1k contient ~17
classes directement liées aux insectes (papillon monarque, criquet, mante
religieuse, libellule, coléoptères...). On détecte dynamiquement ces
classes dans les 1000 catégories du modèle (par mots-clés), plutôt que de
hardcoder des indices numériques fragiles.

## Pipeline

```
staging.occurrences.photo_url
        │  (batch de 20, non classifiées)
        ▼
image_classifier.classify_image()
   - téléchargement de l'image
   - transformation (resize/normalize ImageNet)
   - inférence MobileNetV2 (CPU)
   - top-5 + détection is_likely_insect
        ▼
curated.image_classifications
```

Intégré comme 4ᵉ tâche du DAG Airflow `ingest_inaturalist` (après
`transform_to_curated`), traité par lots de 20 pour rester compatible avec
un scheduling horaire (l'inférence CPU est plus lente qu'une requête SQL).

## Limites assumées

- Classification **indicative**, pas une identification taxonomique fiable
- Pas de fine-tuning sur des images d'insectes spécifiquement
- Dépend de la qualité/résolution de la photo iNaturalist
- Latence : ~100-300ms/image en CPU, d'où le traitement par petits lots

## Endpoint

```
GET /curated/classifications?limit=50&insect_only=true
```