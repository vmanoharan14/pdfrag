import uuid
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.indexing import (
    EmbeddingTextTooLargeError,
    collection_name_for,
    embed_texts_adaptive,
    point_id_for,
)
from app.models import DocumentChunk


def test_collection_name_includes_model_and_dimension() -> None:
    settings = Settings(
        postgres_password="postgres",
        redis_password="redis",
        qdrant_api_key="qdrant",
        minio_root_user="minio",
        minio_root_password="minio",
    )

    collection_name = collection_name_for("nomic-embed-text:latest", 768, settings)

    assert collection_name == "pdfrag_chunks_dense_nomic_embed_text_latest_768"


def test_point_id_for_chunk_is_stable() -> None:
    chunk = DocumentChunk(
        id=uuid.UUID("00000000-0000-0000-0000-000000000123"),
        document_version_id=uuid.uuid4(),
        chunk_index=0,
        content="Example",
        token_estimate=2,
        element_type="prose",
    )

    assert point_id_for(chunk, "nomic-embed-text:latest") == point_id_for(
        chunk, "nomic-embed-text:latest"
    )
    assert point_id_for(chunk, "nomic-embed-text:latest") != point_id_for(
        chunk, "other-model"
    )


async def test_embed_texts_adaptive_shortens_rejected_single_input() -> None:
    settings = Settings(
        postgres_password="postgres",
        redis_password="redis",
        qdrant_api_key="qdrant",
        minio_root_user="minio",
        minio_root_password="minio",
    )
    rejected = "x" * 1000

    with patch("app.indexing.embed_texts", new_callable=AsyncMock) as embed_texts:
        embed_texts.side_effect = [
            EmbeddingTextTooLargeError(),
            [[0.1, 0.2]],
        ]

        embeddings = await embed_texts_adaptive([rejected], settings)

    assert embeddings == [[0.1, 0.2]]
    assert len(embed_texts.await_args_list[1].args[0][0]) == 500
