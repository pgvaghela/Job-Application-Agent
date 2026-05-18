"""
Retriever tests use mocks — no live DB or Gemini key required.

For a real integration test that seeds known chunks and verifies recall,
spin up the full stack and run ingest_corpus.py first, then adapt
test_retrieve_returns_chunks to use a real AsyncSession.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.retriever import RetrievedChunk, retrieve

FAKE_EMBEDDING = [0.0] * 3072


def _make_mock_db(rows: list[dict]) -> AsyncMock:
    mock_db = AsyncMock()
    mapping_rows = [MagicMock(**{"__getitem__": lambda self, k, _r=r: _r[k]}) for _r in rows]
    for row, raw in zip(mapping_rows, rows):
        # Make row["key"] work via MagicMock side_effect
        row.__getitem__ = lambda self, k, _r=raw: _r[k]

    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


@pytest.mark.asyncio
async def test_retrieve_empty_corpus_returns_empty_list():
    mock_db = _make_mock_db([])
    with patch("app.rag.retriever._embed_query", return_value=FAKE_EMBEDDING):
        result = await retrieve("Python experience", mock_db, k=5)
    assert result == []


@pytest.mark.asyncio
async def test_retrieve_maps_rows_to_dataclass():
    row = {
        "chunk_id": 7,
        "document_id": 2,
        "chunk_index": 1,
        "content": "Built a Python microservice handling 10k RPS.",
        "source_type": "resume",
        "source_path": "/corpus/resume.md",
        "token_count": 12,
        "distance": 0.18,
    }
    mock_db = _make_mock_db([row])
    with patch("app.rag.retriever._embed_query", return_value=FAKE_EMBEDDING):
        chunks = await retrieve("Python backend", mock_db, k=5)

    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, RetrievedChunk)
    assert c.chunk_id == 7
    assert c.content == row["content"]
    assert c.source_type == "resume"
    assert c.distance == pytest.approx(0.18)


@pytest.mark.asyncio
async def test_retrieve_calls_embed_query_once():
    mock_db = _make_mock_db([])
    with patch("app.rag.retriever._embed_query", return_value=FAKE_EMBEDDING) as mock_embed:
        await retrieve("test query", mock_db, k=3)
    mock_embed.assert_called_once_with("test query")


@pytest.mark.asyncio
async def test_retrieve_with_source_type_filter_includes_filter_in_sql():
    mock_db = _make_mock_db([])
    with patch("app.rag.retriever._embed_query", return_value=FAKE_EMBEDDING):
        await retrieve("leadership", mock_db, k=3, source_types=["resume"])

    call_args = mock_db.execute.call_args
    sql_text = str(call_args[0][0])
    bound_params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
    assert "source_type" in sql_text
    assert "st0" in bound_params
    assert bound_params["st0"] == "resume"


@pytest.mark.asyncio
async def test_k_is_clamped_to_50():
    mock_db = _make_mock_db([])
    with patch("app.rag.retriever._embed_query", return_value=FAKE_EMBEDDING):
        # k=999 should be silently clamped to 50
        await retrieve("query", mock_db, k=999)

    sql_text = str(mock_db.execute.call_args[0][0])
    assert "LIMIT 50" in sql_text
