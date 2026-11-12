"""Asking questions, and reading back what was asked."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app import service
from app.db import get_db
from app.models import User
from app.schemas import (
    AskIn,
    AskOut,
    QueryOut,
    ThreadDetailOut,
    ThreadOut,
)
from app.security import current_user, rate_limit

router = APIRouter(prefix="/api", tags=["search"])


def _query_out(query) -> QueryOut:
    return QueryOut.model_validate(service.query_to_dict(query))


@router.post(
    "/ask",
    response_model=AskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit)],
)
async def ask(
    payload: AskIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AskOut:
    """Search the web, read the pages, and answer with citations."""
    thread, query = await service.ask(db, user, payload.question, payload.thread_id)
    return AskOut(thread=ThreadOut.model_validate(thread), query=_query_out(query))


@router.get("/threads", response_model=list[ThreadOut])
def list_threads(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ThreadOut]:
    threads = service.list_threads(db, user, limit=limit)
    return [ThreadOut.model_validate(t) for t in threads]


@router.get("/threads/{thread_id}", response_model=ThreadDetailOut)
def get_thread(
    thread_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ThreadDetailOut:
    thread = service.get_thread(db, user, thread_id)
    if thread is None:
        # 404 rather than 403: don't confirm that someone else's id exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found."
        )

    return ThreadDetailOut(
        id=thread.id,
        title=thread.title,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        queries=[_query_out(q) for q in thread.queries],
    )


@router.delete(
    "/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_thread(
    thread_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not service.delete_thread(db, user, thread_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found."
        )
