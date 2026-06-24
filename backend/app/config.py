from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PDFRAG API"
    app_version: str = "0.1.0"

    postgres_db: str = "pdfrag"
    postgres_user: str = "pdfrag"
    postgres_password: str
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 15432

    redis_password: str
    redis_host: str = "127.0.0.1"
    redis_port: int = 16379

    qdrant_api_key: str
    qdrant_host: str = "127.0.0.1"
    qdrant_http_port: int = 16333

    minio_api_port: int = 9000
    minio_host: str = "127.0.0.1"
    minio_root_user: str
    minio_root_password: str
    minio_bucket: str = "documents"

    ollama_base_url: str = "http://127.0.0.1:11434"
    dense_embedding_model: str = "nomic-embed-text:latest"
    qdrant_dense_collection_prefix: str = "pdfrag_chunks_dense"
    sparse_encoder_model: str = "qdrant-bm25-local-v1"
    qdrant_sparse_collection_prefix: str = "pdfrag_chunks_sparse"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_cache_dir: str = ".runtime/hf/hub"
    reranker_local_files_only: bool = True
    context_max_chars: int = 4000
    context_max_chunks: int = 4
    router_enabled: bool = False
    router_model: str = "gemma2:2b"
    router_timeout_seconds: float = 1.5
    generation_model: str = "gemma2:2b"
    generation_timeout_seconds: float = 180.0
    generation_num_predict: int = 220
    required_ollama_models: list[str] = Field(
        default_factory=lambda: [
            "nomic-embed-text:latest",
            "gemma2:2b",
            "gemma4:e4b",
        ]
    )

    dependency_timeout_seconds: float = 2.0

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_http_port}"

    @property
    def minio_url(self) -> str:
        return f"http://{self.minio_host}:{self.minio_api_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
