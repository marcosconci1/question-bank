"""Qdrant vector store operations: collection setup, deterministic point IDs, upsert, delete, and filtered search."""
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    Range,
    VectorParams,
)

from . import config, errors

_client: QdrantClient | None = None


def get_client(url: str | None = None) -> QdrantClient:
    """Return a Qdrant client instance."""
    global _client
    target_url = url or config.QDRANT_URL
    if _client is None or url is not None:
        try:
            client = QdrantClient(url=target_url, timeout=30.0)
            if url is None:
                _client = client
            return client
        except Exception as exc:
            raise errors.QdrantUnreachableError(f"Could not connect to Qdrant at {target_url}: {exc}") from exc
    return _client


def make_point_id(question_id: str) -> int:
    """Generate a deterministic 63-bit integer point ID invariant to file path."""
    return int(uuid.uuid5(uuid.NAMESPACE_URL, f"{question_id}:0").int & 0x7FFFFFFFFFFFFFFF)


def ensure_collection(
    client: QdrantClient | None = None,
    collection_name: str | None = None,
    dim: int | None = None,
) -> None:
    """Ensure that the Qdrant collection exists with the required vector configuration and indexes."""
    c = client or get_client()
    coll = collection_name or config.COLLECTION
    dimension = dim or config.EMBEDDING_DIM

    try:
        if not c.collection_exists(coll):
            c.create_collection(
                collection_name=coll,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            # Create payload indexes to enable fast deterministic filtering
            try:
                c.create_payload_index(collection_name=coll, field_name="status", field_schema=PayloadSchemaType.KEYWORD)
                c.create_payload_index(collection_name=coll, field_name="exam", field_schema=PayloadSchemaType.KEYWORD)
                c.create_payload_index(collection_name=coll, field_name="year", field_schema=PayloadSchemaType.INTEGER)
                c.create_payload_index(collection_name=coll, field_name="tags", field_schema=PayloadSchemaType.KEYWORD)
            except Exception:
                pass
    except errors.QuestionSearchError:
        raise
    except Exception as exc:
        raise errors.QdrantUnreachableError(
            f"Could not reach or configure Qdrant at {config.QDRANT_URL}: {exc}"
        ) from exc


def upsert_points(
    points_data: list[tuple[int, list[float], dict[str, Any]]],
    client: QdrantClient | None = None,
    collection_name: str | None = None,
    batch_size: int = 100,
) -> None:
    """Upsert question points into Qdrant in batches."""
    if not points_data:
        return
    c = client or get_client()
    coll = collection_name or config.COLLECTION

    points = [
        PointStruct(id=pid, vector=vec, payload=payload)
        for pid, vec, payload in points_data
    ]

    try:
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            c.upsert(collection_name=coll, points=batch)
    except errors.QuestionSearchError:
        raise
    except Exception as exc:
        raise errors.QdrantUnreachableError(f"Failed to upsert points into Qdrant: {exc}") from exc


def delete_points(
    point_ids: list[int],
    client: QdrantClient | None = None,
    collection_name: str | None = None,
) -> None:
    """Delete points from Qdrant by point ID."""
    if not point_ids:
        return
    c = client or get_client()
    coll = collection_name or config.COLLECTION

    try:
        c.delete(
            collection_name=coll,
            points_selector=PointIdsList(points=point_ids),
        )
    except errors.QuestionSearchError:
        raise
    except Exception as exc:
        raise errors.QdrantUnreachableError(f"Failed to delete points from Qdrant: {exc}") from exc


def count_points(client: QdrantClient | None = None, collection_name: str | None = None) -> int:
    """Return the total number of points in the collection."""
    c = client or get_client()
    coll = collection_name or config.COLLECTION
    try:
        if not c.collection_exists(coll):
            return 0
        info = c.get_collection(coll)
        return info.points_count or 0
    except errors.QuestionSearchError:
        raise
    except Exception as exc:
        raise errors.QdrantUnreachableError(f"Failed to inspect Qdrant collection: {exc}") from exc


def search_questions(
    query_vector: list[float],
    limit: int = 10,
    status: str | None = "active",
    exam: str | None = None,
    year_range: tuple[int, int] | None = None,
    tags: list[str] | None = None,
    client: QdrantClient | None = None,
    collection_name: str | None = None,
) -> list[dict[str, Any]]:
    """Query Qdrant for questions using cosine similarity and payload filters."""
    c = client or get_client()
    coll = collection_name or config.COLLECTION

    conditions = []
    if status and status.lower() != "all":
        conditions.append(FieldCondition(key="status", match=MatchValue(value=status)))

    if exam:
        conditions.append(FieldCondition(key="exam", match=MatchValue(value=exam.lower())))

    if year_range:
        min_year, max_year = year_range
        conditions.append(FieldCondition(key="year", range=Range(gte=min_year, lte=max_year)))

    if tags:
        # Match any tag
        clean_tags = [t.strip() for t in tags if t.strip()]
        if clean_tags:
            conditions.append(FieldCondition(key="tags", match=MatchAny(any=clean_tags)))

    query_filter = Filter(must=conditions) if conditions else None

    try:
        resp = c.query_points(
            collection_name=coll,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
    except errors.QuestionSearchError:
        raise
    except Exception as exc:
        raise errors.QdrantUnreachableError(f"Vector search failed: {exc}") from exc

    results: list[dict[str, Any]] = []
    for pt in resp.points:
        payload = pt.payload or {}
        text = payload.get("text") or ""
        preview = text[:160].replace("\n", " ").strip()
        results.append({
            "id": payload.get("question_id") or str(pt.id),
            "exam": payload.get("exam", ""),
            "year": payload.get("year"),
            "number": payload.get("number"),
            "type": payload.get("type", "mc"),
            "status": payload.get("status", "active"),
            "score": round(float(pt.score), 4),
            "preview": preview,
            "tags": payload.get("tags", []),
        })

    return results
