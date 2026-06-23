import uuid

from app.retrieval import (
    FusedCandidate,
    RetrievedPoint,
    local_security_context_stage,
    neighbor_indices_for_candidate_payloads,
    parse_retrieved_points,
    reciprocal_rank_fuse,
    score_to_text,
)


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
