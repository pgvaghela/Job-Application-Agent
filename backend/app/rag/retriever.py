from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from google import genai
from google.genai import types
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    chunk_index: int
    content: str
    source_type: str
    source_path: str
    token_count: int
    distance: float  # cosine distance via <=>; lower = more similar
    metadata: dict = field(default_factory=dict)


def _embed_query(query: str) -> list[float]:
    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
    )
    result = client.models.embed_content(
        model="text-embedding-004",
        contents=[query],
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return list(result.embeddings[0].values)


async def retrieve(
    query: str,
    db: AsyncSession,
    k: int = 5,
    source_types: list[str] | None = None,
) -> list[RetrievedChunk]:
    """
    Embed query then run cosine similarity search via pgvector <=> operator.
    """
    k = max(1, min(k, 50))

    embedding: list[float] = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _embed_query(query)
    )

    vec_literal = "[" + ",".join(map(str, embedding)) + "]"

    type_clause = ""
    params: dict = {}
    if source_types:
        placeholders = ", ".join(f":st{i}" for i in range(len(source_types)))
        type_clause = f"AND d.source_type IN ({placeholders})"
        params = {f"st{i}": st for i, st in enumerate(source_types)}

    sql = text(
        f"""
        SELECT
            c.id           AS chunk_id,
            c.document_id,
            c.chunk_index,
            c.content,
            d.source_type,
            d.source_path,
            c.token_count,
            d.metadata,
            (c.embedding <=> '{vec_literal}'::vector) AS distance
        FROM corpus_chunks c
        JOIN corpus_documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL
        {type_clause}
        ORDER BY c.embedding <=> '{vec_literal}'::vector
        LIMIT {k}
        """
    )

    result = await db.execute(sql, params)
    rows = result.mappings().all()

    return [
        RetrievedChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            source_type=row["source_type"],
            source_path=row["source_path"],
            token_count=row["token_count"],
            distance=float(row["distance"]),
            metadata=dict(row["metadata"]) if row["metadata"] else {},
        )
        for row in rows
    ]
