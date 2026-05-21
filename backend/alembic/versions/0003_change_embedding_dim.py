"""Change embedding vector dim from 3072 to 768

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-20
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop HNSW index before altering column type (required by pgvector)
    op.execute("DROP INDEX IF EXISTS ix_corpus_chunks_embedding_hnsw")
    # NULL out existing embeddings — dimension mismatch prevents in-place conversion
    op.execute("UPDATE corpus_chunks SET embedding = NULL")
    # Change from vector(3072) to vector(768) for text-embedding-004
    op.execute("ALTER TABLE corpus_chunks ALTER COLUMN embedding TYPE vector(768)")
    # Recreate HNSW index
    op.execute(
        """
        CREATE INDEX ix_corpus_chunks_embedding_hnsw
        ON corpus_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_corpus_chunks_embedding_hnsw")
    op.execute("UPDATE corpus_chunks SET embedding = NULL")
    op.execute("ALTER TABLE corpus_chunks ALTER COLUMN embedding TYPE vector(3072)")
    op.execute(
        """
        CREATE INDEX ix_corpus_chunks_embedding_hnsw
        ON corpus_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
