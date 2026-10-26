from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VM_", extra="ignore")
    database_url: SecretStr
    redis_url: SecretStr
    minio_endpoint: str = "minio:9000"
    minio_access_key: str
    minio_secret_key: SecretStr
    minio_bucket: str = "videomind"
    max_upload_bytes: int = Field(default=64 * 1024**2, gt=0, le=64 * 1024**2)
    workspace_storage_bytes: int = Field(default=5 * 1024**3, gt=0)
    workspace_storage_objects: int = Field(default=10000, gt=0)
    import_root: str = "/imports"
    signup_workspace_id: str = ""
    cookie_secure: bool = False  # Loopback HTTP only; TLS deployments set true.
    allowed_origins: tuple[str, ...] = (
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
