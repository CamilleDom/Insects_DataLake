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
    """Fetch observations from iNaturalist API"""
    import requests
    import json
    from minio import Minio
    from datetime import datetime
    import os
    
    logger.info("Fetching iNaturalist API...")
    
    # Parameters
    place_id = os.getenv('INATURALIST_PLACE_ID', '6753')  # France
    taxon_id = os.getenv('INATURALIST_TAXON_ID', '47158')  # Insecta
    
    url = "https://api.inaturalist.org/v1/observations"
    params = {
        'place_id': place_id,
        'taxon_id': taxon_id,
        'quality_grade': 'research,needs_id',
        'per_page': 200
    }
    
    all_observations = []
    page = 1
    
    try:
        while True:
            params['page'] = page
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            observations = data.get('results', [])
            
            if not observations:
                break
            
            all_observations.extend(observations)
            
            # Check if we've reached the end
            if len(observations) < params['per_page']:
                break
            
            page += 1
            logger.info(f"Fetched page {page} with {len(observations)} observations")
        
        logger.info(f"Total observations fetched: {len(all_observations)}")
        
        # Save to MinIO
        client = Minio(
            os.getenv('MINIO_URL', 'minio:9000'),
            access_key=os.getenv('MINIO_USER', 'minioadmin'),
            secret_key=os.getenv('MINIO_PASSWORD', 'minioadmin'),
            secure=False
        )
        
        # Create filename with timestamp
        now = datetime.utcnow()
        filename = f"{now.strftime('%Y-%m-%d')}/observations_{now.strftime('%H-%M')}.json"
        
        # Upload to MinIO
        json_data = json.dumps(all_observations)
        json_bytes = json_data.encode('utf-8')
        
        client.put_object(
            'raw-inaturalist',
            filename,
            json_bytes,
            length=len(json_bytes),
            content_type='application/json'
        )
        
        logger.info(f"Uploaded {filename} to MinIO")
        
        # Push filename to XCom for next task
        context['task_instance'].xcom_push(key='raw_file', value=filename)
        
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
    from datetime import datetime
    
    logger.info("Validating and loading to staging zone...")
    
    # Get filename from previous task
    filename = context['task_instance'].xcom_pull(task_ids='fetch_api', key='raw_file')
    
    try:
        # Download from MinIO
        client = Minio(
            os.getenv('MINIO_URL', 'minio:9000'),
            access_key=os.getenv('MINIO_USER', 'minioadmin'),
            secret_key=os.getenv('MINIO_PASSWORD', 'minioadmin'),
            secure=False
        )
        
        response = client.get_object('raw-inaturalist', filename)
        data = json.loads(response.read().decode('utf-8'))
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'postgres'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            user=os.getenv('POSTGRES_USER', 'insect_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'insect_pass'),
            database=os.getenv('POSTGRES_DB', 'insect_lake')
        )
        
        cursor = conn.cursor()
        loaded_count = 0
        
        for obs in data:
            try:
                # Extract relevant fields
                obs_id = str(obs.get('id'))
                species_name = obs.get('species_guess', 'Unknown')
                latitude = obs.get('latitude')
                longitude = obs.get('longitude')
                observed_on = obs.get('observed_on')
                quality_grade = obs.get('quality_grade', 'needs_id')
                
                # Validate coordinates
                if latitude is None or longitude is None:
                    continue
                
                # Insert into staging
                cursor.execute("""
                    INSERT INTO staging.occurrences 
                    (id, species_name, latitude, longitude, observed_on, quality_grade, source, raw_payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (
                    obs_id,
                    species_name,
                    latitude,
                    longitude,
                    observed_on,
                    quality_grade,
                    'inaturalist',
                    json.dumps(obs)
                ))
                loaded_count += 1
            except Exception as e:
                logger.warning(f"Failed to load observation {obs_id}: {e}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Loaded {loaded_count} records to staging")
        return loaded_count
    
    except Exception as e:
        logger.error(f"Failed to validate and load: {e}")
        raise

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

# Pipeline complète : raw -> staging -> curated
fetch_task >> validate_task >> transform_task