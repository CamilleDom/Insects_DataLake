from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'insect-lake',
    'start_date': datetime(2024, 1, 1),
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'ingest_inaturalist',
    default_args=default_args,
    description='Ingest insect observations from iNaturalist API',
    schedule_interval='@hourly',
    catchup=False,
)

def fetch_inaturalist_api(**context):
    """
    Récupère les nouvelles observations iNaturalist depuis le dernier run réussi.

    Deux protections mises en place suite à un incident de production :
    1. Ingestion incrémentale (paramètre `d1`) : on ne récupère que les
       observations créées depuis la dernière exécution réussie, stockée
       dans une Airflow Variable. Sans ça, chaque run horaire retéléchargeait
       l'intégralité de l'historique (~10 000+ observations), ce qui est
       à la fois inefficace et heurte la limite de pagination de l'API.
    2. Garde-fou sur le nombre de pages (MAX_PAGES) : l'API iNaturalist
       refuse tout accès au-delà de page*per_page=10000 (HTTP 403). Même
       en incrémental, on plafonne par sécurité plutôt que de laisser le
       DAG planter si un run raté fait s'accumuler beaucoup de nouvelles
       observations d'un coup.
    """
    import requests
    import json
    import io
    import time
    from minio import Minio
    from minio.error import S3Error
    from datetime import datetime, timedelta
    import os
    from airflow.models import Variable

    logger.info("Fetching iNaturalist API...")

    place_id = os.getenv('INATURALIST_PLACE_ID', '6753')
    taxon_id = os.getenv('INATURALIST_TAXON_ID', '47158')

    # --- Ingestion incrémentale ---
    # Récupère la date du dernier fetch réussi (Airflow Variable persistée
    # en base de métadonnées). Par défaut (premier run), on limite aux
    # dernières 24h pour éviter de plonger dans tout l'historique.
    last_fetch_str = Variable.get("inaturalist_last_fetch", default_var=None)
    if last_fetch_str:
        since_date = last_fetch_str
    else:
        since_date = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    logger.info(f"Fetching observations created since {since_date}")

    url = "https://api.inaturalist.org/v1/observations"
    params = {
        'place_id': place_id,
        'taxon_id': taxon_id,
        'quality_grade': 'research,needs_id',
        'per_page': 200,
        'created_d1': since_date,   # bound inférieure de date de création
        'order_by': 'created_at',
        'order': 'asc',
    }

    MAX_PAGES = 40  # garde-fou : 40*200 = 8000, reste sous la limite de 10000
    all_observations = []
    page = 1
    fetch_started_at = datetime.utcnow()

    try:
        while page <= MAX_PAGES:
            params['page'] = page
            response = requests.get(url, params=params, timeout=15)

            if response.status_code == 403:
                # Limite de pagination profonde atteinte : on arrête proprement
                # plutôt que de faire planter la tâche. Les observations déjà
                # récupérées sont tout de même traitées.
                logger.warning(
                    f"iNaturalist a renvoyé 403 à la page {page} "
                    f"(limite de pagination probable). Arrêt de la collecte "
                    f"avec {len(all_observations)} observations déjà récupérées."
                )
                break

            response.raise_for_status()

            data = response.json()
            observations = data.get('results', [])

            if not observations:
                break

            all_observations.extend(observations)

            if len(observations) < params['per_page']:
                break

            page += 1
            logger.info(f"Fetched page {page} with {len(observations)} observations")

            # Respect des recommandations de rate-limiting iNaturalist
            # (max ~1 requête/seconde en usage soutenu)
            time.sleep(1)

        logger.info(f"Total observations fetched: {len(all_observations)}")

        client = Minio(
            os.getenv('MINIO_URL', 'minio:9000'),
            access_key=os.getenv('MINIO_USER', 'minioadmin'),
            secret_key=os.getenv('MINIO_PASSWORD', 'minioadmin'),
            secure=False
        )

        bucket_name = 'raw-inaturalist'
        try:
            if not client.bucket_exists(bucket_name):
                client.make_bucket(bucket_name)
                logger.info(f"Bucket '{bucket_name}' créé par le DAG")
        except S3Error as e:
            logger.error(f"Erreur lors de la vérification/création du bucket: {e}")
            raise

        now = datetime.utcnow()
        filename = f"{now.strftime('%Y-%m-%d')}/observations_{now.strftime('%H-%M-%S')}.json"

        json_data = json.dumps(all_observations)
        json_bytes = json_data.encode('utf-8')

        client.put_object(
            bucket_name,
            filename,
            io.BytesIO(json_bytes),
            length=len(json_bytes),
            content_type='application/json'
        )

        logger.info(f"Uploaded {filename} to MinIO")
        context['task_instance'].xcom_push(key='raw_file', value=filename)

        # On ne met à jour le curseur incrémental QUE si la collecte s'est
        # terminée normalement (pas de 403), pour ne jamais perdre de données
        # entre deux runs en cas de coupure prématurée.
        if page <= MAX_PAGES:
            Variable.set("inaturalist_last_fetch", fetch_started_at.strftime('%Y-%m-%d'))
            logger.info(f"Curseur incrémental mis à jour : {fetch_started_at.strftime('%Y-%m-%d')}")

        return len(all_observations)

    except Exception as e:
        logger.error(f"Failed to fetch iNaturalist API: {e}")
        raise

def validate_and_load_staging(**context):
    """Validate data and load to staging zone"""
    import json
    import psycopg2
    from minio import Minio
    import os

    logger.info("Validating and loading to staging zone...")

    client = Minio(
        os.getenv('MINIO_URL', 'minio:9000'),
        access_key=os.getenv('MINIO_USER', 'minioadmin'),
        secret_key=os.getenv('MINIO_PASSWORD', 'minioadmin'),
        secure=False
    )

    # Récupère le nom du fichier depuis XCom (cas normal : run complet du DAG)
    filename = context['task_instance'].xcom_pull(task_ids='fetch_api', key='raw_file')

    # Fallback de robustesse : si XCom est vide (ex: tâches testées isolément
    # avec `airflow tasks test`, ou XCom perdu suite à un incident), on
    # récupère automatiquement le fichier le plus récent du bucket plutôt
    # que de planter avec un TypeError peu explicite.
    if not filename:
        logger.warning(
            "Aucun fichier trouvé via XCom (probablement un test isolé de la "
            "tâche, ou incident XCom). Fallback : recherche du fichier le "
            "plus récent dans le bucket raw-inaturalist."
        )
        objects = list(client.list_objects('raw-inaturalist', recursive=True))
        if not objects:
            raise ValueError(
                "Aucun fichier disponible dans le bucket raw-inaturalist. "
                "La tâche fetch_api doit être exécutée au préalable."
            )
        latest = max(objects, key=lambda o: o.last_modified)
        filename = latest.object_name
        logger.info(f"Fichier de fallback sélectionné : {filename}")

    try:
        response = client.get_object('raw-inaturalist', filename)
        data = json.loads(response.read().decode('utf-8'))

        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'postgres'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            user=os.getenv('POSTGRES_USER', 'insect_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'insect_pass'),
            database=os.getenv('POSTGRES_DB', 'insect_lake')
        )

        cursor = conn.cursor()
        loaded_count = 0
        skipped_count = 0

        for obs in data:
            obs_id = str(obs.get('id', 'unknown'))
            try:
                species_name = obs.get('species_guess') or 'Unknown'

                # ✅ FIX 1 : latitude/longitude sont dans 'location' = "lat,lng"
                # Le champ 'latitude' de l'API est None pour les obs non-obscurcies
                latitude = obs.get('latitude')
                longitude = obs.get('longitude')

                if latitude is None or longitude is None:
                    location = obs.get('location')
                    if location and ',' in str(location):
                        try:
                            parts = str(location).split(',')
                            latitude = float(parts[0])
                            longitude = float(parts[1])
                        except (ValueError, IndexError):
                            pass

                if latitude is None or longitude is None:
                    skipped_count += 1
                    continue

                observed_on = obs.get('observed_on')
                quality_grade = obs.get('quality_grade', 'needs_id')

                # ✅ FIX 2 : extraction photo (url square -> medium)
                photo_url = None
                photos = obs.get('photos', [])
                if photos and photos[0].get('url'):
                    photo_url = photos[0]['url'].replace('square', 'medium')

                # ✅ FIX 3 : raw_payload sérialisé proprement
                try:
                    raw_payload_json = json.dumps(obs, default=str)
                except Exception:
                    raw_payload_json = None

                cursor.execute("""
                    INSERT INTO staging.occurrences 
                    (id, species_name, latitude, longitude, observed_on,
                    quality_grade, source, raw_payload, photo_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        photo_url = EXCLUDED.photo_url,
                        raw_payload = EXCLUDED.raw_payload,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude
                """, (
                    obs_id, species_name, latitude, longitude, observed_on,
                    quality_grade, 'inaturalist', raw_payload_json, photo_url
                ))
                loaded_count += 1

            except Exception as e:
                logger.warning(f"Failed to load observation {obs_id}: {e}")

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"Loaded {loaded_count} records to staging ({skipped_count} skipped)")
        return loaded_count

    except Exception as e:
        logger.error(f"Failed to validate and load: {e}")
        raise

def run_image_classification(**context):
    """Classifie par CNN les nouvelles observations avec photo (batch limité)"""
    import sys
    sys.path.insert(0, '/opt/airflow/scripts')
    import os
    from classify_images import ImageClassificationPipeline

    logger.info("Starting CNN image classification batch...")

    pipeline = ImageClassificationPipeline(
        pg_host=os.getenv('POSTGRES_HOST', 'postgres'),
        pg_port=int(os.getenv('POSTGRES_PORT', '5432')),
        pg_user=os.getenv('POSTGRES_USER', 'insect_user'),
        pg_password=os.getenv('POSTGRES_PASSWORD', 'insect_pass'),
        pg_db=os.getenv('POSTGRES_DB', 'insect_lake')
    )

    try:
        # Batch limité à 20 par run horaire : l'inférence CPU est plus lente
        # qu'une requête SQL, le pipeline rattrape le retard au fil des runs.
        result = pipeline.run(limit=20)
        logger.info(f"Image classification result: {result}")
    finally:
        pipeline.close()

def run_transformation(**context):
    """Transforme staging -> curated (H3 richness + invasive hotspots)"""
    import sys
    sys.path.insert(0, '/opt/airflow/scripts')
    import os
    from transform_to_curated import CuratedTransformer

    logger.info("Starting staging -> curated transformation...")

    transformer = CuratedTransformer(
        pg_host=os.getenv('POSTGRES_HOST', 'postgres'),
        pg_port=int(os.getenv('POSTGRES_PORT', '5432')),
        pg_user=os.getenv('POSTGRES_USER', 'insect_user'),
        pg_password=os.getenv('POSTGRES_PASSWORD', 'insect_pass'),
        pg_db=os.getenv('POSTGRES_DB', 'insect_lake')
    )

    try:
        success = transformer.run_full_transformation()
        if not success:
            raise Exception("Transformation to curated failed")
        logger.info("Transformation completed successfully")
    finally:
        transformer.close()


fetch_task = PythonOperator(
    task_id='fetch_api',
    python_callable=fetch_inaturalist_api,
    dag=dag,
)

validate_task = PythonOperator(
    task_id='validate_and_load_staging',
    python_callable=validate_and_load_staging,
    dag=dag,
)

transform_task = PythonOperator(
    task_id='transform_to_curated',
    python_callable=run_transformation,
    dag=dag,
)

classify_task = PythonOperator(
    task_id='classify_images',
    python_callable=run_image_classification,
    dag=dag,
)

# Pipeline complète : raw -> staging -> curated -> classification CNN
fetch_task >> validate_task >> transform_task >> classify_task