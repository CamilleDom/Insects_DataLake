# 📈 Dashboard Streamlit — Documentation technique

## Objectif

Offrir une interface de visualisation du data lake sans écrire de SQL,
destinée à un profil non-technique (écologue, gestionnaire de biodiversité).

## Stack

- **Streamlit** : framework web Python, rendu réactif
- **Folium** : cartes Leaflet interactives (marqueurs cliquables)
- **pydeck** : rendu WebGL pour la visualisation H3 en 3D
- **Plotly** : graphiques (distribution, timeline)
- **h3-py** : conversion des index H3 en polygones géographiques

## Pages

### 🗺️ Carte des observations
Affiche jusqu'à 500 marqueurs (limite de performance Folium) avec popup
contenant photo, date d'observation et qualité. Filtrable par espèce.

### ⬡ Richesse spécifique (H3)
Visualisation 3D des cellules H3 (résolution 7, `curated.species_richness_h3`)
colorées selon un dégradé rouge (pauvre) → vert (riche). Utilise `PolygonLayer`
de pydeck avec conversion `h3.cell_to_boundary()`.

### 🚨 Espèces invasives
Cartographie des alertes de `curated.invasive_hotspots` avec marqueurs rouges.

### 🧠 Classifications CNN
Galerie photo des observations classifiées + histogramme de distribution
des classes prédites par MobileNetV2 (voir `ML.md`).

### 📊 Statistiques
Vue d'ensemble : top espèces observées, timeline temporelle des observations.

## Cache

Toutes les requêtes utilisent `@st.cache_data(ttl=60)` : les données sont
mises en cache 60 secondes pour éviter de spammer PostgreSQL à chaque
interaction utilisateur. Un bouton "🔄 Rafraîchir" force l'invalidation.

## Limites connues

- Carte Folium plafonnée à 500 marqueurs (au-delà, le rendu devient lent
  côté navigateur) — à terme, prévoir un clustering (`MarkerCluster`)
- Pas d'authentification (dashboard interne/démo uniquement)
- Rendu pydeck nécessite WebGL (non testé sur navigateurs très anciens)

## Lancement

```bash
make streamlit
```

Accessible sur http://localhost:8501