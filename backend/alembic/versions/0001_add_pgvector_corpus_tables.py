"""Add pgvector extension and corpus tables

Revision ID: 0001
Revises:
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "corpus_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_path", sa.String(500), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_corpus_documents_source_path", "corpus_documents", ["source_path"]
    )

    op.create_table(
        "corpus_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("corpus_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(3072), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_corpus_chunks_doc_chunk", "corpus_chunks", ["document_id", "chunk_index"]
    )

    # HNSW index for cosine similarity.
    # m=16: edges per node. Higher → better recall, more memory. Default 16.
    # ef_construction=64: beam width at build time. Higher → better recall, slower ingest. Default 64.
    # ef_search (query-time): SET hnsw.ef_search = 100 for higher recall on sparse corpora. Default 40.
    # vector_cosine_ops must match the <=> operator used at query time.
    op.execute(
        """
        CREATE INDEX ix_corpus_chunks_embedding_hnsw
        ON corpus_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_corpus_chunks_embedding_hnsw", table_name="corpus_chunks")
    op.drop_table("corpus_chunks")
    op.drop_table("corpus_documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
