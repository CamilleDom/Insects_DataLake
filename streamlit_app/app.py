import streamlit as st
import pandas as pd
import psycopg2
import folium
from streamlit_folium import st_folium
import plotly.express as px
import os
import pydeck as pdk
import h3

# --- Config ---
st.set_page_config(page_title="🐝 Insect Lake Dashboard", layout="wide")

PG_CONFIG = dict(
    host=os.getenv('POSTGRES_HOST', 'postgres'),
    port=int(os.getenv('POSTGRES_PORT', '5432')),
    user=os.getenv('POSTGRES_USER', 'insect_user'),
    password=os.getenv('POSTGRES_PASSWORD', 'insect_pass'),
    database=os.getenv('POSTGRES_DB', 'insect_lake'),
)


@st.cache_resource
def get_connection():
    return psycopg2.connect(**PG_CONFIG)


@st.cache_data(ttl=60)
def load_occurrences():
    conn = get_connection()
    return pd.read_sql("""
        SELECT id, species_name, latitude, longitude, observed_on,
               quality_grade, photo_url
        FROM staging.occurrences
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """, conn)


@st.cache_data(ttl=60)
def load_classifications():
    conn = get_connection()
    return pd.read_sql("""
        SELECT c.occurrence_id, c.species_name, c.predicted_class,
               c.confidence, c.is_likely_insect, c.image_url,
               o.latitude, o.longitude
        FROM curated.image_classifications c
        JOIN staging.occurrences o ON o.id = c.occurrence_id
    """, conn)


@st.cache_data(ttl=60)
def load_hotspots():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM curated.species_richness_h3", conn)


@st.cache_data(ttl=60)
def load_invasives():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM curated.invasive_hotspots", conn)



@st.cache_data(ttl=60)
def load_h3_richness():
    conn = get_connection()
    return pd.read_sql("""
        SELECT h3_cell, species_count, obs_count, 
               richness_normalized, richness_percentile,
               lat_centroid, lon_centroid, last_observed
        FROM curated.species_richness_h3
    """, conn)


def h3_to_polygon(h3_index):
    """Convertit un index H3 en polygone [[lon, lat], ...] pour pydeck"""
    boundary = h3.cell_to_boundary(h3_index)
    return [[lng, lat] for lat, lng in boundary]

# --- Sidebar ---
st.sidebar.title("🐝 Insect Lake")
page = st.sidebar.radio("Navigation", [
    "🗺️ Carte des observations",
    "⬡ Richesse spécifique (H3)",
    "🚨 Espèces invasives",
    "🧠 Classifications CNN",
    "📊 Statistiques"
])
if st.sidebar.button("🔄 Rafraîchir les données"):
    st.cache_data.clear()

# --- Page 1 : Carte des observations ---
if page == "🗺️ Carte des observations":
    st.title("Carte des observations d'insectes")

    df = load_occurrences()
    st.metric("Total observations géolocalisées", len(df))

    species_filter = st.multiselect(
        "Filtrer par espèce",
        options=sorted(df['species_name'].dropna().unique()),
    )
    if species_filter:
        df = df[df['species_name'].isin(species_filter)]

    if len(df) > 0:
        center = [df['latitude'].mean(), df['longitude'].mean()]
        m = folium.Map(location=center, zoom_start=6)

        for _, row in df.head(500).iterrows():  # cap pour la perf
            popup_html = f"""
                <b>{row['species_name']}</b><br>
                Observé le : {row['observed_on']}<br>
                Qualité : {row['quality_grade']}<br>
            """
            if row['photo_url']:
                popup_html += f'<img src="{row["photo_url"]}" width="150">'

            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=5,
                popup=folium.Popup(popup_html, max_width=200),
                color='green',
                fill=True,
            ).add_to(m)

        st_folium(m, width=1200, height=600)
    else:
        st.warning("Aucune observation à afficher")

elif page == "⬡ Richesse spécifique (H3)":
    st.title("Richesse spécifique par cellule H3")
    st.caption("Chaque hexagone représente une cellule H3 (résolution 7, ~5km²). "
               "La couleur indique la richesse en espèces distinctes observées.")

    df = load_h3_richness()

    if len(df) == 0:
        st.warning("Aucune donnée H3. Lance `make transform`.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Cellules H3 actives", len(df))
        col2.metric("Richesse max (espèces)", int(df['species_count'].max()))
        col3.metric("Total observations", int(df['obs_count'].sum()))

        metric_choice = st.radio(
            "Métrique à visualiser",
            ["species_count", "obs_count", "richness_percentile"],
            format_func=lambda x: {
                "species_count": "Richesse en espèces",
                "obs_count": "Nombre d'observations",
                "richness_percentile": "Percentile de richesse"
            }[x],
            horizontal=True
        )

        center_lat = float(df['lat_centroid'].mean())
        center_lon = float(df['lon_centroid'].mean())

        # Couleur rouge -> vert selon la métrique
        max_val = df[metric_choice].max()
        min_val = df[metric_choice].min()

        def get_color(value):
            if max_val == min_val:
                ratio = 0.5
            else:
                ratio = (value - min_val) / (max_val - min_val)
            return [int(255 * (1 - ratio)), int(255 * ratio), 50, 180]

        # ✅ DataFrame épuré avec types Python natifs pour pydeck
        pydeck_data = pd.DataFrame({
            'polygon': [
                [[float(lng), float(lat)] for lat, lng in h3.cell_to_boundary(h)]
                for h in df['h3_cell']
            ],
            'color': df[metric_choice].apply(get_color).tolist(),
            'species_count': df['species_count'].tolist(),
            'obs_count': df['obs_count'].tolist(),
            'richness_percentile': df['richness_percentile'].fillna(0).round(2).tolist(),
            'last_observed': df['last_observed'].astype(str).tolist(),
        })

        layer = pdk.Layer(
            "PolygonLayer",
            data=pydeck_data,
            get_polygon="polygon",
            get_fill_color="color",
            get_line_color=[80, 80, 80],
            line_width_min_pixels=1,
            pickable=True,
            auto_highlight=True,
        )

        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(
                latitude=center_lat,
                longitude=center_lon,
                zoom=6,
                pitch=30,
            ),
            tooltip={
                "html": "<b>Espèces :</b> {species_count}<br/>"
                        "<b>Observations :</b> {obs_count}<br/>"
                        "<b>Percentile :</b> {richness_percentile}<br/>"
                        "<b>Dernière obs :</b> {last_observed}",
                "style": {"backgroundColor": "steelblue", "color": "white"}
            },
            map_style="mapbox://styles/mapbox/light-v10",
        )

        st.pydeck_chart(deck)

        st.subheader("Top 10 cellules les plus riches")
        st.dataframe(
            df.nlargest(10, metric_choice)[
                ['h3_cell', 'species_count', 'obs_count',
                 'richness_percentile', 'last_observed']
            ],
            use_container_width=True
        )
# --- Page 2 : Espèces invasives ---
elif page == "🚨 Espèces invasives":
    st.title("Alertes espèces invasives")

    df = load_invasives()
    st.metric("Zones à risque détectées", len(df))

    if len(df) > 0:
        st.dataframe(df, use_container_width=True)

        if 'latitude' in df.columns and 'longitude' in df.columns:
            m = folium.Map(
                location=[df['latitude'].mean(), df['longitude'].mean()],
                zoom_start=6
            )
            for _, row in df.iterrows():
                folium.CircleMarker(
                    location=[row['latitude'], row['longitude']],
                    radius=8,
                    popup=row.get('species_name', 'Invasive'),
                    color='red',
                    fill=True,
                    fill_color='red',
                ).add_to(m)
            st_folium(m, width=1200, height=500)
    else:
        st.info("Aucune alerte invasive pour le moment")

# --- Page 3 : Classifications CNN ---
elif page == "🧠 Classifications CNN":
    st.title("Résultats de classification par CNN")

    df = load_classifications()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total classifié", len(df))
    col2.metric("Détectés comme insectes", int(df['is_likely_insect'].sum()))
    col3.metric("Confiance moyenne", f"{df['confidence'].mean():.1%}")

    insect_only = st.checkbox("Afficher uniquement les insectes détectés", value=True)
    if insect_only:
        df = df[df['is_likely_insect'] == True]

    # Distribution des classes prédites
    fig = px.bar(
        df['predicted_class'].value_counts().reset_index(),
        x='predicted_class', y='count',
        title="Distribution des classes prédites"
    )
    st.plotly_chart(fig, use_container_width=True)

    # Galerie d'images
    st.subheader("Galerie")
    cols = st.columns(4)
    for i, (_, row) in enumerate(df.head(20).iterrows()):
        with cols[i % 4]:
            st.image(row['image_url'], caption=f"{row['predicted_class']} ({row['confidence']:.1%})")
            st.caption(row['species_name'])

# --- Page 4 : Statistiques ---
elif page == "📊 Statistiques":
    st.title("Statistiques globales")

    occ = load_occurrences()
    classif = load_classifications()

    col1, col2, col3 = st.columns(3)
    col1.metric("Observations totales", len(occ))
    col2.metric("Espèces distinctes", occ['species_name'].nunique())
    col3.metric("Images classifiées", len(classif))

    # Top espèces
    st.subheader("Top 10 espèces observées")
    top_species = occ['species_name'].value_counts().head(10)
    fig = px.bar(top_species, orientation='h')
    st.plotly_chart(fig, use_container_width=True)

    # Timeline
    if 'observed_on' in occ.columns:
        st.subheader("Observations dans le temps")
        occ['observed_on'] = pd.to_datetime(occ['observed_on'])
        timeline = occ.groupby(occ['observed_on'].dt.date).size().reset_index(name='count')
        fig2 = px.line(timeline, x='observed_on', y='count')
        st.plotly_chart(fig2, use_container_width=True)