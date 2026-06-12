import psycopg2
from psycopg2 import pool
from minio import Minio
import logging
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# PostgreSQL Connection Pool
_db_pool = None

def get_db_pool():
    """Get or create database connection pool"""
    global _db_pool
    if _db_pool is None:
        try:
            _db_pool = psycopg2.pool.SimpleConnectionPool(
                1, 20,
                host=settings.postgres_host,
                port=settings.postgres_port,
                user=settings.postgres_user,
                password=settings.postgres_password,
                database=settings.postgres_db
            )
            logger.info("Database pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise
    return _db_pool

def get_db_connection():
    """Get a connection from the pool"""
    pool = get_db_pool()
    return pool.getconn()

def close_db_connection(conn):
    """Return connection to the pool"""
    pool = get_db_pool()
    pool.putconn(conn)

# MinIO Client
_minio_client = None

def get_minio_client() -> Minio:
    """Get or create MinIO client"""
    global _minio_client
    if _minio_client is None:
        try:
            _minio_client = Minio(
                settings.minio_url,
                access_key=settings.minio_user,
                secret_key=settings.minio_password,
                secure=settings.minio_secure
            )
            logger.info("MinIO client initialized")
            
            # Ensure buckets exist
            ensure_buckets()
        except Exception as e:
            logger.error(f"Failed to initialize MinIO client: {e}")
            raise
    return _minio_client

def ensure_buckets():
    """Ensure required buckets exist"""
    client = _minio_client
    buckets = ["raw-inaturalist", "raw-gbif"]
    
    try:
        existing_buckets = [b.name for b in client.list_buckets()]
        
        for bucket in buckets:
            if bucket not in existing_buckets:
                client.make_bucket(bucket)
                logger.info(f"Created bucket: {bucket}")
            else:
                logger.info(f"Bucket already exists: {bucket}")
    except Exception as e:
        logger.error(f"Failed to ensure buckets: {e}")
        raise
