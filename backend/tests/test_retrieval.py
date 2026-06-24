import uuid

from app.retrieval import (
    FusedCandidate,
    RetrievedPoint,
    local_security_context_stage,
    neighbor_indices_for_candidate_payloads,
    parse_retrieved_points,
    reciprocal_rank_fuse,
    response_cache_scope,
    response_cache_stage,
    score_to_text,
)


class CacheSettings:
    dense_embedding_model = "nomic-embed-text:latest"
    sparse_encoder_model = "qdrant-bm25-local-v1"
    reranker_model = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    context_max_chars = 4000
    context_max_chunks = 4


def test_parse_retrieved_points_supports_qdrant_query_response() -> None:
    payload = {
        "result": {
            "points": [
                {
                    "score": 0.91,
                    "payload": {
                        "chunk_id": "chunk-1",
                        "text": "Evidence text",
                    },
                },
                {"score": 0.4, "payload": {"missing_chunk_id": True}},
            ]
        }
    }

    points = parse_retrieved_points(payload)

    assert points == [
        RetrievedPoint(
            chunk_id="chunk-1",
            score=0.91,
            rank=1,
            payload={"chunk_id": "chunk-1", "text": "Evidence text"},
        )
    ]


def test_reciprocal_rank_fuse_combines_dense_and_sparse_matches() -> None:
    dense = [
        RetrievedPoint("shared", 0.8, 1, {"chunk_id": "shared"}),
        RetrievedPoint("dense-only", 0.7, 2, {"chunk_id": "dense-only"}),
    ]
    sparse = [
        RetrievedPoint("shared", 11.0, 1, {"chunk_id": "shared"}),
        RetrievedPoint("sparse-only", 9.0, 2, {"chunk_id": "sparse-only"}),
    ]

    fused = reciprocal_rank_fuse(dense, sparse, limit=3)

    assert [candidate.chunk_id for candidate in fused] == [
        "shared",
        "dense-only",
        "sparse-only",
    ]
    assert fused[0].dense_rank == 1
    assert fused[0].sparse_rank == 1
    assert fused[0].dense_score == 0.8
    assert fused[0].sparse_score == 11.0


def test_score_to_text_preserves_none_and_numeric_values() -> None:
    assert score_to_text(None) is None
    assert score_to_text(-3.4557268619537354) == "-3.4557268619537354"


def test_neighbor_indices_for_candidate_payloads_uses_same_version_window() -> None:
    candidates = [
        FusedCandidate(
            chunk_id="chunk-1",
            payload={
                "document_version_id": "00000000-0000-0000-0000-000000000001",
                "chunk_index": 10,
            },
        ),
        FusedCandidate(
            chunk_id="chunk-2",
            payload={
                "document_version_id": "00000000-0000-0000-0000-000000000001",
                "chunk_index": 0,
            },
        ),
    ]

    indices = neighbor_indices_for_candidate_payloads(candidates)

    assert indices == {
        uuid.UUID("00000000-0000-0000-0000-000000000001"): {9, 11, 1}
    }


def test_local_security_context_stage_uses_fixed_development_principal() -> None:
    stage = local_security_context_stage(sequence=2)

    assert stage.stage == "security context"
    assert stage.status == "completed"
    assert stage.details["tenant_id"] == "local-development"
    assert stage.details["user_id"] == "local-user"
    assert stage.details["principal_id"] == "local-development-principal"
    assert stage.details["acl_filter_applied"] is False


def test_response_cache_scope_uses_model_and_hashed_query() -> None:
    qwen_scope = response_cache_scope(
        query="How To Enroll",
        settings=CacheSettings(),  # type: ignore[arg-type]
        generation_model="qwen3.5:9b",
    )
    gemma_scope = response_cache_scope(
        query="How To Enroll",
        settings=CacheSettings(),  # type: ignore[arg-type]
        generation_model="gemma2:2b",
    )

    assert qwen_scope["query_hash"] == gemma_scope["query_hash"]
    assert qwen_scope["generation_model"] == "qwen3.5:9b"
    assert gemma_scope["generation_model"] == "gemma2:2b"
    assert qwen_scope["cache_key_preview"] != gemma_scope["cache_key_preview"]
    assert "How To Enroll" not in qwen_scope["cache_key_preview"]


def test_response_cache_stage_is_trace_only_for_now() -> None:
    stage = response_cache_stage(
        sequence=3,
        query="how to enroll",
        settings=CacheSettings(),  # type: ignore[arg-type]
        generation_model="gemma2:2b",
    )

    assert stage.stage == "response cache"
    assert stage.status == "skipped"
    assert stage.details["cache_enabled"] is False
    assert stage.details["cache_event"] == "miss"
    assert stage.details["generation_model"] == "gemma2:2b"
