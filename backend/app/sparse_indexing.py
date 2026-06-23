import hashlib
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.indexing import chunk_payload
from app.models import DocumentChunk, DocumentVersion

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)?")
SPARSE_VECTOR_NAME = "text"
UPSERT_BATCH_SIZE = 64


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class SparseIndexResult:
    collection_name: str
    encoder_model: str
    point_count: int


def sparse_collection_name(settings: Settings) -> str:
    normalized_model = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        settings.sparse_encoder_model,
    ).strip("_").lower()
    return f"{settings.qdrant_sparse_collection_prefix}_{normalized_model}"


def sparse_point_id_for(chunk: DocumentChunk, encoder_model: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"pdfrag:chunk:{chunk.id}:sparse:{encoder_model}")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def token_id(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def encode_sparse_text(text: str) -> SparseVector:
    counts = Counter(tokenize(text))
    if not counts:
        return SparseVector(indices=[], values=[])

    weighted = {
        token_id(token): 1.0 + math.log(count)
        for token, count in counts.items()
    }
    ordered = sorted(weighted.items())
    return SparseVector(
        indices=[index for index, _ in ordered],
        values=[value for _, value in ordered],
    )


async def ensure_sparse_collection(
    client: httpx.AsyncClient,
    collection_name: str,
    settings: Settings,
) -> None:
    headers = {"api-key": settings.qdrant_api_key}
    response = await client.get(
        f"{settings.qdrant_url}/collections/{collection_name}",
        headers=headers,
    )
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()

    create_response = await client.put(
        f"{settings.qdrant_url}/collections/{collection_name}",
        headers=headers,
        json={
            "sparse_vectors": {
                SPARSE_VECTOR_NAME: {
                    "modifier": "idf",
                },
            },
        },
    )
    create_response.raise_for_status()


async def upsert_sparse_points(
    version: DocumentVersion,
    chunks: list[DocumentChunk],
    vectors: list[SparseVector],
    collection_name: str,
    settings: Settings,
) -> None:
    headers = {"api-key": settings.qdrant_api_key}
    points = [
        {
            "id": str(sparse_point_id_for(chunk, settings.sparse_encoder_model)),
            "vector": {
                SPARSE_VECTOR_NAME: {
                    "indices": vector.indices,
                    "values": vector.values,
                },
            },
            "payload": chunk_payload(version, chunk),
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
        if vector.indices
    ]
    if not points:
        return

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.put(
            f"{settings.qdrant_url}/collections/{collection_name}/points",
            params={"wait": "true"},
            headers=headers,
            json={"points": points},
        )
        response.raise_for_status()


async def index_chunks_sparse(
    session: AsyncSession,
    version: DocumentVersion,
    chunks: list[DocumentChunk],
) -> SparseIndexResult:
    if not chunks:
        raise ValueError("Cannot sparse-index a document version with no chunks.")

    settings = get_settings()
    collection_name = sparse_collection_name(settings)

    async with httpx.AsyncClient(timeout=120) as client:
        await ensure_sparse_collection(client, collection_name, settings)

    indexed_at = datetime.now(UTC)
    indexed_count = 0
    for start in range(0, len(chunks), UPSERT_BATCH_SIZE):
        batch = chunks[start : start + UPSERT_BATCH_SIZE]
        vectors = [encode_sparse_text(chunk.content) for chunk in batch]
        await upsert_sparse_points(version, batch, vectors, collection_name, settings)
        for chunk, vector in zip(batch, vectors, strict=True):
            if not vector.indices:
                chunk.sparse_index_status = "empty"
                continue
            chunk.sparse_index_status = "indexed"
            chunk.sparse_vector_point_id = sparse_point_id_for(
                chunk,
                settings.sparse_encoder_model,
            )
            chunk.sparse_vector_collection = collection_name
            chunk.sparse_encoder_model = settings.sparse_encoder_model
            chunk.sparse_indexed_at = indexed_at
            indexed_count += 1
        await session.commit()

    return SparseIndexResult(
        collection_name=collection_name,
        encoder_model=settings.sparse_encoder_model,
        point_count=indexed_count,
    )
