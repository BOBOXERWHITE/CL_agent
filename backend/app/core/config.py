import os
from dataclasses import dataclass
from functools import lru_cache


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_csv_tuple(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default

    items = tuple(part.strip() for part in value.split(",") if part.strip())
    return items or default


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    log_level: str
    cors_allow_origins: tuple[str, ...]
    database_url: str
    object_storage_provider: str
    object_storage_root: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket_name: str
    minio_secure: bool
    vector_store_provider: str
    milvus_host: str
    milvus_port: int
    milvus_collection_name: str
    embedding_dimension: int
    chunk_size: int
    chunk_overlap: int
    chat_top_k: int
    chat_confidence_threshold: float
    celery_broker_url: str
    celery_result_backend: str
    celery_task_always_eager: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Travel Ops Copilot API"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        cors_allow_origins=_as_csv_tuple(
            os.getenv("CORS_ALLOW_ORIGINS"),
            default=(
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:4173",
                "http://127.0.0.1:4173",
            ),
        ),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://travel_ops:travel_ops@localhost:5432/travel_ops",
        ),
        object_storage_provider=os.getenv("OBJECT_STORAGE_PROVIDER", "minio").lower(),
        object_storage_root=os.getenv("OBJECT_STORAGE_ROOT", "./data/object-store"),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
        minio_access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        minio_secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        minio_bucket_name=os.getenv("MINIO_BUCKET_NAME", "knowledge"),
        minio_secure=_as_bool(os.getenv("MINIO_SECURE"), default=False),
        vector_store_provider=os.getenv("VECTOR_STORE_PROVIDER", "milvus").lower(),
        milvus_host=os.getenv("MILVUS_HOST", "localhost"),
        milvus_port=int(os.getenv("MILVUS_PORT", "19530")),
        milvus_collection_name=os.getenv("MILVUS_COLLECTION_NAME", "knowledge_chunks"),
        embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "16")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "450")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "1")),
        chat_top_k=int(os.getenv("CHAT_TOP_K", "3")),
        chat_confidence_threshold=float(os.getenv("CHAT_CONFIDENCE_THRESHOLD", "0.2")),
        celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        celery_task_always_eager=_as_bool(os.getenv("CELERY_TASK_ALWAYS_EAGER"), default=True),
    )
