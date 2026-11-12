"""The one place that knows how a question becomes a stored, cited answer.

Routers stay thin; this module owns the pipeline:

    search -> fetch -> rank -> compose -> persist

Keeping it here means the whole flow can be tested without HTTP, and the
router can't accidentally skip a step.
"""

from __future__ import annotations

import json
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.answer import Answer, build_answer, extract_followups
from app.models import Query, Source, Thread, User
from app.providers import fetch, search


def _title_from(question: str) -> str:
    """A thread title that reads like a person named it."""
    q = " ".join(question.split())
    if len(q) <= 70:
        return q
    cut = q[:70]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def get_or_create_thread(
    db: Session, user: User, question: str, thread_id: str | None
) -> Thread:
    """Resume a thread the user owns, or start a new one.

    A thread id belonging to someone else is treated as absent — the caller
    gets a fresh thread rather than a 403 that confirms the id exists.
    """
    if thread_id:
        thread = db.get(Thread, thread_id)
        if thread is not None and thread.user_id == user.id:
            return thread

    thread = Thread(user_id=user.id, title=_title_from(question))
    db.add(thread)
    db.flush()
    return thread


async def run_pipeline(question: str) -> tuple[Answer, list[search.SearchResult], list]:
    """Search, read, and compose. Returns the answer plus what it was built from."""
    results = await search.search(question, limit=settings.search_results)
    if not results:
        empty = Answer(
            summary="I couldn't reach a search engine just now, so I have nothing to cite.",
            confidence=0.0,
            notes=["search_unavailable"],
        )
        return empty, [], []

    docs = await fetch.fetch_many(results, limit=settings.fetch_pages)

    # Only pages we actually read can be quoted. Unread results are still
    # listed as sources, flagged, so the reader can go look themselves.
    readable = [d for d in docs if d.fetched and d.text]
    answer = build_answer(
        question,
        readable,
        max_sentences=settings.max_answer_sentences,
        min_chars=settings.min_sentence_chars,
        max_chars=settings.max_sentence_chars,
    )
    return answer, results, docs


def persist(
    db: Session,
    thread: Thread,
    question: str,
    answer: Answer,
    results: list[search.SearchResult],
    docs: list,
    latency_ms: int,
) -> Query:
    """Store the query, its answer, and one row per source."""
    followups = extract_followups(question, answer, limit=settings.followup_count)

    query = Query(
        thread_id=thread.id,
        question=question,
        answer=answer.text,
        summary=answer.summary,
        followups_json=json.dumps(followups),
        confidence=answer.confidence,
        latency_ms=latency_ms,
    )
    db.add(query)
    db.flush()

    # Prefer the docs we read (they carry the citation indices the answer
    # used). Append any search results we never got to, marked unread.
    seen_urls: set[str] = set()
    rank = 0

    for idx, doc in enumerate(docs):
        if doc.url in seen_urls:
            continue
        seen_urls.add(doc.url)
        cited = answer.citations_for(idx)
        db.add(
            Source(
                query_id=query.id,
                rank=rank,
                title=doc.title[:400],
                url=doc.url,
                domain=doc.domain,
                snippet=doc.snippet[:2000],
                cited_sentences=",".join(str(c) for c in cited),
                fetched=doc.fetched,
            )
        )
        rank += 1

    for res in results:
        if res.url in seen_urls:
            continue
        seen_urls.add(res.url)
        db.add(
            Source(
                query_id=query.id,
                rank=rank,
                title=res.title[:400],
                url=res.url,
                domain=res.domain,
                snippet=res.snippet[:2000],
                cited_sentences="",
                fetched=False,
            )
        )
        rank += 1

    thread.updated_at = query.created_at
    db.commit()
    db.refresh(query)
    return query


async def ask(
    db: Session, user: User, question: str, thread_id: str | None
) -> tuple[Thread, Query]:
    """The full request path, timed end to end."""
    started = time.perf_counter()
    thread = get_or_create_thread(db, user, question, thread_id)

    answer, results, docs = await run_pipeline(question)
    latency_ms = int((time.perf_counter() - started) * 1000)

    query = persist(db, thread, question, answer, results, docs, latency_ms)
    return thread, query


def list_threads(db: Session, user: User, limit: int = 50) -> list[Thread]:
    stmt = (
        select(Thread)
        .where(Thread.user_id == user.id)
        .order_by(Thread.updated_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def get_thread(db: Session, user: User, thread_id: str) -> Thread | None:
    thread = db.get(Thread, thread_id)
    if thread is None or thread.user_id != user.id:
        return None
    return thread


def delete_thread(db: Session, user: User, thread_id: str) -> bool:
    thread = get_thread(db, user, thread_id)
    if thread is None:
        return False
    db.delete(thread)
    db.commit()
    return True


def query_to_dict(query: Query) -> dict:
    """Serialise a stored query back into the shape the API returns."""
    try:
        followups = json.loads(query.followups_json or "[]")
    except json.JSONDecodeError:
        followups = []

    sentences = []
    if query.answer:
        # Rebuild sentence/source pairs from the stored citation map so the
        # UI can render chips without re-running the pipeline.
        from app.engine.text import split_sentences

        parts = split_sentences(query.answer)
        cited_map: dict[int, int] = {}
        for src in query.sources:
            if not src.cited_sentences:
                continue
            for pos in src.cited_sentences.split(","):
                pos = pos.strip()
                if pos.isdigit():
                    cited_map[int(pos)] = src.rank

        for i, text in enumerate(parts):
            sentences.append({"text": text, "source_index": cited_map.get(i, 0)})

    return {
        "id": query.id,
        "question": query.question,
        "answer": query.answer,
        "summary": query.summary,
        "confidence": query.confidence,
        "latency_ms": query.latency_ms,
        "created_at": query.created_at,
        "sentences": sentences,
        "followups": followups,
        "sources": query.sources,
        "notes": [],
    }
