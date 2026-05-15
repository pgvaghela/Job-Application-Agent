import pytest

from app.rag.chunker import chunk_text


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []


def test_whitespace_only_returns_no_chunks():
    assert chunk_text("   \n\n   \n\n   ") == []


def test_short_text_becomes_single_chunk():
    text = "This is a short paragraph with just a few words."
    chunks = chunk_text(text, max_tokens=250, overlap_tokens=50)
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].chunk_index == 0
    assert chunks[0].token_count > 0


def test_chunk_indices_are_sequential():
    para = " ".join(["word"] * 80)
    text = "\n\n".join([para] * 10)
    chunks = chunk_text(text, max_tokens=250, overlap_tokens=50)
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_overlap_content_present_in_next_chunk():
    # Two paragraphs of ~200 tokens each — total exceeds 250, so two chunks.
    # The second chunk should contain text from the first (overlap).
    para1 = " ".join(["alpha"] * 200)
    para2 = " ".join(["beta"] * 200)
    text = f"{para1}\n\n{para2}"
    chunks = chunk_text(text, max_tokens=250, overlap_tokens=50)
    assert len(chunks) >= 2
    # The second chunk must contain the overlap word from para1
    assert "alpha" in chunks[1].content


def test_token_counts_within_bounds():
    para = " ".join(["hello"] * 80)
    text = "\n\n".join([para] * 8)
    chunks = chunk_text(text, max_tokens=250, overlap_tokens=50)
    for chunk in chunks:
        # Allow a small slack because paragraph separators add a few tokens
        assert 1 <= chunk.token_count <= 300


def test_very_long_single_paragraph_is_split():
    # A paragraph longer than max_tokens must produce multiple chunks.
    long_para = " ".join(["x"] * 500)
    chunks = chunk_text(long_para, max_tokens=250, overlap_tokens=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 250


def test_single_word_file():
    chunks = chunk_text("hello", max_tokens=250, overlap_tokens=50)
    assert len(chunks) == 1
    assert "hello" in chunks[0].content
