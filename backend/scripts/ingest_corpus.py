#!/usr/bin/env python3
"""
Ingest corpus documents into pgvector.

Usage (run from backend/):
    python -m scripts.ingest_corpus /path/to/corpus --source-type resume
    python -m scripts.ingest_corpus /path/to/readmes --source-type readme
    python -m scripts.ingest_corpus /path/to/writing --source-type writing_sample

Supported file types: .md, .txt, .pdf

Idempotent: re-running on the same file path replaces its chunks in-place.
A document is keyed by its absolute path.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python -m scripts.ingest_corpus` from the backend/ directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

import google.generativeai as genai
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import CorpusChunk, CorpusDocument
from app.rag.chunker import chunk_text

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}
# gemini-embedding-001 supports up to 100 texts per request.
EMBED_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def _embed_batch(texts: list[str], task_type: str) -> list[list[float]]:
    """Call gemini-embedding-001 for a batch of texts."""
    result = genai.embed_content(
        model="models/gemini-embedding-001",
        content=texts,
        task_type=task_type,
    )
    raw = result["embedding"]
    # embed_content returns a flat list[float] when content is a single string,
    # and list[list[float]] when content is a list. Normalise to list-of-lists.
    if texts and not isinstance(raw[0], list):
        return [raw]
    return raw  # type: ignore[return-value]


def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        all_embeddings.extend(_embed_batch(batch, task_type))
    return all_embeddings


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------


def read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    raise ValueError(f"Unsupported extension: {suffix}")


# ---------------------------------------------------------------------------
# Per-file ingest
# ---------------------------------------------------------------------------


async def ingest_file(
    path: Path,
    source_type: str,
    session: AsyncSession,
) -> int:
    abs_path = str(path.resolve())
    raw_text = read_file(path)

    stmt = select(CorpusDocument).where(CorpusDocument.source_path == abs_path)
    result = await session.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        doc = CorpusDocument(
            source_type=source_type,
            source_path=abs_path,
            raw_text=raw_text,
            metadata_={"filename": path.name},
        )
        session.add(doc)
        await session.flush()  # get doc.id
    else:
        doc.raw_text = raw_text
        await session.execute(
            delete(CorpusChunk).where(CorpusChunk.document_id == doc.id)
        )
        await session.flush()

    chunks = chunk_text(raw_text)
    if not chunks:
        print(f"  [skip] {path.name} — no content after chunking")
        return 0

    texts = [c.content for c in chunks]
    embeddings = embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")

    for chunk, embedding in zip(chunks, embeddings):
        session.add(
            CorpusChunk(
                document_id=doc.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=embedding,
                token_count=chunk.token_count,
            )
        )

    await session.flush()
    return len(chunks)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(directory: Path, source_type: str) -> None:
    if not settings.gemini_api_key:
        sys.exit("GEMINI_API_KEY is not set. Export it before running this script.")

    genai.configure(api_key=settings.gemini_api_key)

    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    files = [
        p
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not files:
        print(f"No supported files found in {directory}")
        return

    print(f"Found {len(files)} file(s) to ingest as source_type={source_type!r}")

    total_chunks = 0
    async with SessionLocal() as session:
        async with session.begin():
            for path in files:
                print(f"  Ingesting {path.name} ...", end=" ", flush=True)
                try:
                    n = await ingest_file(path, source_type, session)
                    print(f"{n} chunks")
                    total_chunks += n
                except Exception as exc:
                    print(f"ERROR: {exc}")

    await engine.dispose()
    print(f"\nDone. {total_chunks} total chunks ingested.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest corpus into pgvector.")
    parser.add_argument("directory", type=Path, help="Directory to walk for documents.")
    parser.add_argument(
        "--source-type",
        default="resume",
        choices=["resume", "readme", "writing_sample"],
        help="Label applied to all documents in this run.",
    )
    args = parser.parse_args()

    if not args.directory.is_dir():
        sys.exit(f"Not a directory: {args.directory}")

    asyncio.run(main(args.directory, args.source_type))
