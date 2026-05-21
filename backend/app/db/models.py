import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Job info
    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)

    # Research output
    company_info: Mapped[str | None] = mapped_column(Text)

    # Analysis
    skill_gaps: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    keyword_matches: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    match_score: Mapped[int | None] = mapped_column(Integer)

    # Generated content
    original_resume: Mapped[str | None] = mapped_column(Text)
    rewritten_bullets: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    cover_letter: Mapped[str | None] = mapped_column(Text)

    # Modified LaTeX resume (populated after agent run if original was .tex)
    modified_resume_tex: Mapped[str | None] = mapped_column(Text)

    # Corpus items not on the resume that are relevant to this role
    suggested_additions: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    # Agent execution trace
    agent_steps: Mapped[list[Any]] = mapped_column(JSONB, default=list)


class Resume(Base):
    __tablename__ = "resumes"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CorpusDocument(Base):
    __tablename__ = "corpus_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "resume" | "readme" | "writing_sample"
    source_path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    chunks: Mapped[list["CorpusChunk"]] = relationship(
        "CorpusChunk", back_populates="document", cascade="all, delete-orphan"
    )


class CorpusChunk(Base):
    __tablename__ = "corpus_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("corpus_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped["CorpusDocument"] = relationship(
        "CorpusDocument", back_populates="chunks"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_corpus_chunks_doc_chunk"),
    )
