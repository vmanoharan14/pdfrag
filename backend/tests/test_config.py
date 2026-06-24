from app.config import Settings


def test_generation_default_is_fast_local_model() -> None:
    settings = Settings(
        postgres_password="test",
        redis_password="test",
        qdrant_api_key="test",
        minio_root_user="test",
        minio_root_password="test",
    )

    assert settings.generation_model == "gemma2:2b"
    assert "gemma2:2b" in settings.required_ollama_models
    assert "qwen3.5:9b" in settings.required_ollama_models
