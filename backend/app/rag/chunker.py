from dataclasses import dataclass

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    content: str
    chunk_index: int
    token_count: int


def chunk_text(
    text: str,
    max_tokens: int = 250,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """
    Split text into overlapping chunks aligned to paragraph boundaries.

    Strategy:
    - Split on double newlines to get paragraphs.
    - Greedily pack paragraphs into chunks until max_tokens is reached.
    - On overflow, emit the current chunk then start the next one with the
      last N whole paragraphs that fit within overlap_tokens.
    - A single paragraph larger than max_tokens is split on raw token
      boundaries (with overlap) since no paragraph boundary exists to use.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    current_paras: list[str] = []
    current_count: int = 0

    def _flush() -> None:
        if not current_paras:
            return
        content = "\n\n".join(current_paras)
        chunks.append(
            Chunk(
                content=content,
                chunk_index=len(chunks),
                token_count=current_count,
            )
        )

    def _overlap_seed(paras: list[str]) -> tuple[list[str], int]:
        """Return the trailing paragraphs that fit within overlap_tokens."""
        seed: list[str] = []
        seed_count = 0
        for p in reversed(paras):
            pt = len(_ENC.encode(p))
            if seed_count + pt <= overlap_tokens:
                seed.insert(0, p)
                seed_count += pt
            else:
                break
        return seed, seed_count

    for para in paragraphs:
        para_tokens = len(_ENC.encode(para))

        if para_tokens > max_tokens:
            # Flush current buffer before splitting this oversized paragraph.
            _flush()
            current_paras = []
            current_count = 0

            tokens = _ENC.encode(para)
            step = max(1, max_tokens - overlap_tokens)
            for start in range(0, len(tokens), step):
                piece = tokens[start : start + max_tokens]
                if piece:
                    chunks.append(
                        Chunk(
                            content=_ENC.decode(piece),
                            chunk_index=len(chunks),
                            token_count=len(piece),
                        )
                    )
            continue

        if current_count + para_tokens > max_tokens and current_paras:
            _flush()
            current_paras, current_count = _overlap_seed(current_paras)

        current_paras.append(para)
        current_count += para_tokens

    _flush()
    return chunks
