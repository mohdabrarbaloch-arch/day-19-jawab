"""Request and response models.

Every input is bounded. A question is 3–500 characters, a password is 8–72
bytes, an email is validated. Nothing here trusts the client.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# --- auth ---------------------------------------------------------------


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(default="", max_length=80)

    @field_validator("password")
    @classmethod
    def _password_bytes(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes")
        return v

    @field_validator("display_name")
    @classmethod
    def _trim_name(cls, v: str) -> str:
        return v.strip()


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --- search -------------------------------------------------------------


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    thread_id: str | None = Field(default=None, max_length=32)

    @field_validator("question")
    @classmethod
    def _clean_question(cls, v: str) -> str:
        cleaned = " ".join(v.split())
        if len(cleaned) < 3:
            raise ValueError("question is too short")
        return cleaned


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    title: str
    url: str
    domain: str
    snippet: str
    cited_sentences: str
    fetched: bool


class SentenceOut(BaseModel):
    text: str
    source_index: int


class QueryOut(BaseModel):
    id: str
    question: str
    answer: str
    summary: str
    confidence: float
    latency_ms: int
    created_at: datetime
    sentences: list[SentenceOut] = []
    followups: list[str] = []
    sources: list[SourceOut] = []
    notes: list[str] = []


class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ThreadDetailOut(ThreadOut):
    queries: list[QueryOut] = []


class AskOut(BaseModel):
    thread: ThreadOut
    query: QueryOut


class HealthOut(BaseModel):
    status: str
    version: str
    environment: str
    database: str
