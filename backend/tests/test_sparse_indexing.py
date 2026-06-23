import uuid

from app.config import Settings
from app.models import DocumentChunk
from app.sparse_indexing import (
    encode_sparse_text,
    sparse_collection_name,
    sparse_point_id_for,
    tokenize,
)


def test_tokenize_keeps_exact_term_fragments() -> None:
    assert tokenize("Plan PPO-100 has $40 copay.") == [
        "plan",
        "ppo-100",
        "has",
        "40",
        "copay",
    ]


def test_encode_sparse_text_is_deterministic_and_weighted() -> None:
    first = encode_sparse_text("copay copay deductible")
    second = encode_sparse_text("copay copay deductible")

    assert first == second
    assert len(first.indices) == 2
    assert max(first.values) > min(first.values)


def test_sparse_collection_and_point_ids_are_stable() -> None:
    settings = Settings(
        postgres_password="postgres",
        redis_password="redis",
        qdrant_api_key="qdrant",
        minio_root_user="minio",
        minio_root_password="minio",
    )
    chunk = DocumentChunk(
        id=uuid.UUID("00000000-0000-0000-0000-000000000321"),
        document_version_id=uuid.uuid4(),
        chunk_index=0,
        content="Example",
        token_estimate=2,
        element_type="prose",
    )

    assert sparse_collection_name(settings) == "pdfrag_chunks_sparse_qdrant_bm25_local_v1"
    assert sparse_point_id_for(chunk, settings.sparse_encoder_model) == sparse_point_id_for(
        chunk,
        settings.sparse_encoder_model,
    )
