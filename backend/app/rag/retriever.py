from __future__ import annotations

import asyncio
from dataclasses import dataclass

import google.generativeai as genai
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


def _embed_query(query: str) -> list[float]:
    genai.configure(api_key=settings.gemini_api_key)
    result = genai.embed_content(
        model="models/gemini-embedding-001",
        content=query,
        task_type="RETRIEVAL_QUERY",
    )
    return result["embedding"]


async def retrieve(
    query: str,
    db: AsyncSession,
    k: int = 5,
    source_types: list[str] | None = None,
) -> list[RetrievedChunk]:
    """
    Embed query with RETRIEVAL_QUERY task type, then run cosine similarity
    search against corpus_chunks using the pgvector <=> operator.
    """
    k = max(1, min(k, 50))

    embedding: list[float] = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _embed_query(query)
    )

    # Safe interpolation: embedding is list[float] from Gemini, k is a bounded int.
    # Using a string literal avoids asyncpg vector-type registration complexity.
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
        )
        for row in rows
    ]
