import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import DocumentChunk, DocumentVersion

EMBED_BATCH_SIZE = 4
MIN_EMBED_TEXT_CHARS = 400


@dataclass(frozen=True)
class DenseIndexResult:
    collection_name: str
    embedding_model: str
    embedding_dimension: int
    point_count: int


class EmbeddingBatchTooLargeError(ValueError):
    pass


class EmbeddingTextTooLargeError(ValueError):
    pass


def collection_name_for(model: str, dimension: int, settings: Settings) -> str:
    normalized_model = re.sub(r"[^a-zA-Z0-9]+", "_", model).strip("_").lower()
    return f"{settings.qdrant_dense_collection_prefix}_{normalized_model}_{dimension}"


def point_id_for(chunk: DocumentChunk, model: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"pdfrag:chunk:{chunk.id}:dense:{model}")


def chunk_payload(version: DocumentVersion, chunk: DocumentChunk) -> dict:
    return {
        "tenant_id": version.document.tenant_id,
        "document_id": str(version.document_id),
        "document_version_id": str(version.id),
        "chunk_id": str(chunk.id),
        "chunk_index": chunk.chunk_index,
        "section_title": chunk.section_title,
        "element_type": chunk.element_type,
        "page_number": chunk.page_number,
        "source_filename": version.source_filename,
        "sha256": version.sha256,
        "parser_used": version.parser_used,
        "text": chunk.content,
    }


async def embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.dense_embedding_model, "input": texts},
        )
        if response.status_code == 404:
            return await embed_texts_legacy(texts, settings)
        if response.status_code == 400 and len(texts) > 1:
            raise EmbeddingBatchTooLargeError(
                f"Ollama rejected embedding batch of {len(texts)} texts."
            )
        if response.status_code == 400:
            raise EmbeddingTextTooLargeError("Ollama rejected a single embedding input.")
        response.raise_for_status()

    payload = response.json()
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise ValueError("Ollama returned an invalid embedding response.")
    return embeddings


async def embed_texts_adaptive(texts: list[str], settings: Settings) -> list[list[float]]:
    try:
        return await embed_texts(texts, settings)
    except EmbeddingBatchTooLargeError:
        midpoint = len(texts) // 2
        left = await embed_texts_adaptive(texts[:midpoint], settings)
        right = await embed_texts_adaptive(texts[midpoint:], settings)
        return [*left, *right]
    except EmbeddingTextTooLargeError:
        if len(texts) != 1 or len(texts[0]) <= MIN_EMBED_TEXT_CHARS:
            raise
        shortened = texts[0][: max(MIN_EMBED_TEXT_CHARS, len(texts[0]) // 2)]
        return await embed_texts_adaptive([shortened], settings)


async def embed_texts_legacy(texts: list[str], settings: Settings) -> list[list[float]]:
    embeddings: list[list[float]] = []
    async with httpx.AsyncClient(timeout=120) as client:
        for text in texts:
            response = await client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={"model": settings.dense_embedding_model, "prompt": text},
            )
            response.raise_for_status()
            embedding = response.json().get("embedding")
            if not isinstance(embedding, list):
                raise ValueError("Ollama returned an invalid legacy embedding response.")
            embeddings.append(embedding)
    return embeddings


async def ensure_dense_collection(
    client: httpx.AsyncClient,
    collection_name: str,
    dimension: int,
    settings: Settings,
) -> None:
    headers = {"api-key": settings.qdrant_api_key}
    response = await client.get(
        f"{settings.qdrant_url}/collections/{collection_name}",
        headers=headers,
    )
    if response.status_code == 200:
        vector_size = (
            response.json()
            .get("result", {})
            .get("config", {})
            .get("params", {})
            .get("vectors", {})
            .get("size")
        )
        if vector_size != dimension:
            raise ValueError(
                f"Qdrant collection {collection_name} has dimension "
                f"{vector_size}, expected {dimension}."
            )
        return
    if response.status_code != 404:
        response.raise_for_status()

    create_response = await client.put(
        f"{settings.qdrant_url}/collections/{collection_name}",
        headers=headers,
        json={
            "vectors": {
                "size": dimension,
                "distance": "Cosine",
            },
        },
    )
    create_response.raise_for_status()


async def upsert_dense_points(
    version: DocumentVersion,
    chunks: list[DocumentChunk],
    embeddings: list[list[float]],
    collection_name: str,
    settings: Settings,
) -> None:
    headers = {"api-key": settings.qdrant_api_key}
    points = [
        {
            "id": str(point_id_for(chunk, settings.dense_embedding_model)),
            "vector": embedding,
            "payload": chunk_payload(version, chunk),
        }
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.put(
            f"{settings.qdrant_url}/collections/{collection_name}/points",
            params={"wait": "true"},
            headers=headers,
            json={"points": points},
        )
        response.raise_for_status()


async def index_chunks_dense(
    session: AsyncSession,
    version: DocumentVersion,
    chunks: list[DocumentChunk],
) -> DenseIndexResult:
    if not chunks:
        raise ValueError("Cannot index a document version with no chunks.")

    settings = get_settings()
    first_embedding = (await embed_texts_adaptive([chunks[0].content], settings))[0]
    dimension = len(first_embedding)
    collection_name = collection_name_for(settings.dense_embedding_model, dimension, settings)

    async with httpx.AsyncClient(timeout=120) as client:
        await ensure_dense_collection(client, collection_name, dimension, settings)

    indexed_at = datetime.now(UTC)
    first_chunk = chunks[0]
    await upsert_dense_points(
        version,
        [first_chunk],
        [first_embedding],
        collection_name,
        settings,
    )
    first_chunk.index_status = "indexed"
    first_chunk.vector_point_id = point_id_for(first_chunk, settings.dense_embedding_model)
    first_chunk.vector_collection = collection_name
    first_chunk.embedding_model = settings.dense_embedding_model
    first_chunk.embedding_dimension = dimension
    first_chunk.indexed_at = indexed_at
    await session.commit()

    pending_chunks = chunks[1:]
    for start in range(0, len(pending_chunks), EMBED_BATCH_SIZE):
        batch = pending_chunks[start : start + EMBED_BATCH_SIZE]
        embeddings = await embed_texts_adaptive([chunk.content for chunk in batch], settings)
        await upsert_dense_points(version, batch, embeddings, collection_name, settings)
        for chunk in batch:
            chunk.index_status = "indexed"
            chunk.vector_point_id = point_id_for(chunk, settings.dense_embedding_model)
            chunk.vector_collection = collection_name
            chunk.embedding_model = settings.dense_embedding_model
            chunk.embedding_dimension = dimension
            chunk.indexed_at = indexed_at
        await session.commit()

    return DenseIndexResult(
        collection_name=collection_name,
        embedding_model=settings.dense_embedding_model,
        embedding_dimension=dimension,
        point_count=len(chunks),
    )
