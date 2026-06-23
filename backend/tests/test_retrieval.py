from app.retrieval import (
    RetrievedPoint,
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
