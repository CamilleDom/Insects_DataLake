from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # MinIO
    minio_url: str = "minio:9000"
    minio_user: str = "minioadmin"
    minio_password: str = "minioadmin"
    minio_secure: bool = False
    
    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "insect_user"
    postgres_password: str = "insect_pass"
    postgres_db: str = "insect_lake"
    
    # Data sources
    inaturalist_place_id: str = "6753"
    inaturalist_taxon_id: str = "47158"
    inaturalist_api_key: str = ""
    
    # Anthropic
    anthropic_api_key: str = ""
    
    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    return Settings()
