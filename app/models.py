"""ORM models.

Four tables, and the shape is deliberate:

  users      -> who is asking
  threads    -> one conversation, owned by a user
  queries    -> one question inside a thread, with its answer and sources
  sources    -> the citations for a query, ordered

Sources are a separate table rather than a JSON blob because the whole point
of this app is that a citation is a first-class thing you can click, count,
and later audit. Storing them as text would throw that away.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    threads: Mapped[list[Thread]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New search")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship(back_populates="threads")
    queries: Mapped[list[Query]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Query.created_at",
    )


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("threads.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The one-line "here's the short version" that sits above the answer.
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    followups_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    thread: Mapped[Thread] = relationship(back_populates="queries")
    sources: Mapped[list[Source]] = relationship(
        back_populates="query",
        cascade="all, delete-orphan",
        order_by="Source.rank",
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    query_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("queries.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Which sentences of the answer this source backs, e.g. "0,2,5".
    cited_sentences: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    fetched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    query: Mapped[Query] = relationship(back_populates="sources")


Index("ix_queries_thread_created", Query.thread_id, Query.created_at)
Index("ix_threads_user_updated", Thread.user_id, Thread.updated_at)
