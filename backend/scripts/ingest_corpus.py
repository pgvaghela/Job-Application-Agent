#!/usr/bin/env python3
"""
Ingest career corpus documents into pgvector.

Source types and what to put in each:
  experience     — past job descriptions, role summaries, performance reviews
  project        — project case studies, GitHub READMEs, technical write-ups
  achievement    — awards, publications, certifications, notable outcomes
  writing_sample — cover letter examples, essays (for tone matching)

Markdown files can include YAML frontmatter to attach structured metadata:

    ---
    title: "Distributed Billing System Migration"
    company: "Acme Corp"
    date_range: "2021–2023"
    tags: [distributed-systems, kubernetes, python, team-leadership]
    ---

    Led the migration of Acme's monolithic billing system to a microservices
    architecture, handling 2M transactions per day...

Usage (run from backend/):
    python -m scripts.ingest_corpus /path/to/experiences --source-type experience
    python -m scripts.ingest_corpus /path/to/projects   --source-type project
    python -m scripts.ingest_corpus /path/to/awards     --source-type achievement
    python -m scripts.ingest_corpus /path/to/writing    --source-type writing_sample

Supported file types: .md, .txt, .pdf

Idempotent: re-running on the same file path replaces its chunks in-place.
A document is keyed by its absolute path.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

# Allow `python -m scripts.ingest_corpus` from the backend/ directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from google import genai
from google.genai import types as genai_types
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import CorpusChunk, CorpusDocument
from app.rag.chunker import chunk_text

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}
SOURCE_TYPES = ["experience", "project", "achievement", "writing_sample"]
EMBED_BATCH_SIZE = 250  # text-embedding-004 supports up to 250 texts per request


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Extract YAML frontmatter from a markdown document.
    Returns (metadata_dict, body_text). If no frontmatter, returns ({}, text).
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    body = text[match.end():]
    return meta, body


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def _embed_batch(texts: list[str], task_type: str) -> list[list[float]]:
    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
    )
    result = client.models.embed_content(
        model="text-embedding-004",
        contents=texts,
        config=genai_types.EmbedContentConfig(task_type=task_type),
    )
    return [list(e.values) for e in result.embeddings]


def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        all_embeddings.extend(_embed_batch(batch, task_type))
    return all_embeddings


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------


def read_file(path: Path) -> tuple[str, dict]:
    """
    Read a file and return (text, metadata).
    For .md files, YAML frontmatter is extracted into metadata.
    """
    suffix = path.suffix.lower()
    base_meta = {"filename": path.name}

    if suffix == ".md":
        raw = path.read_text(encoding="utf-8", errors="replace")
        frontmatter, body = parse_frontmatter(raw)
        meta = {**base_meta, **frontmatter}
        return body, meta

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace"), base_meta

    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages), base_meta

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
    text, metadata = read_file(path)

    if not text.strip():
        print(f"  [skip] {path.name} — empty content")
        return 0

    stmt = select(CorpusDocument).where(CorpusDocument.source_path == abs_path)
    result = await session.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        doc = CorpusDocument(
            source_type=source_type,
            source_path=abs_path,
            raw_text=text,
            metadata_=metadata,
        )
        session.add(doc)
        await session.flush()
    else:
        doc.raw_text = text
        doc.metadata_ = metadata
        doc.source_type = source_type
        await session.execute(
            delete(CorpusChunk).where(CorpusChunk.document_id == doc.id)
        )
        await session.flush()

    chunks = chunk_text(text)
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

    title = metadata.get("title") or path.name
    company = metadata.get("company", "")
    tags = metadata.get("tags") or []
    detail = title
    if company:
        detail += f" @ {company}"
    if tags:
        detail += f" [{', '.join(str(t) for t in tags)}]"
    print(f"  {detail} — {len(chunks)} chunk(s)")

    return len(chunks)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(directory: Path, source_type: str) -> None:
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

    print(f"Found {len(files)} file(s) to ingest as source_type={source_type!r}\n")

    total_chunks = 0
    async with SessionLocal() as session:
        async with session.begin():
            for path in files:
                try:
                    n = await ingest_file(path, source_type, session)
                    total_chunks += n
                except Exception as exc:
                    print(f"  ERROR {path.name}: {exc}")

    await engine.dispose()
    print(f"\nDone. {total_chunks} total chunks ingested.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest career corpus documents into pgvector.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
source-type values:
  experience     past jobs, role summaries, performance reviews
  project        project case studies, GitHub READMEs
  achievement    awards, certifications, publications
  writing_sample cover letter examples, essays
        """,
    )
    parser.add_argument("directory", type=Path, help="Directory to walk for documents.")
    parser.add_argument(
        "--source-type",
        default="project",
        choices=SOURCE_TYPES,
        help="Label applied to all documents in this run. Default: project",
    )
    args = parser.parse_args()

    if not args.directory.is_dir():
        sys.exit(f"Not a directory: {args.directory}")

    asyncio.run(main(args.directory, args.source_type))
