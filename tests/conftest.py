"""Test fixtures.

Each test module gets a fresh SQLite file in a temp dir, so tests never
touch the dev database and never leak state into each other.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Must be set before app.config is imported anywhere.
_TMP = Path(tempfile.mkdtemp(prefix="jawab-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["JWT_SECRET"] = "test-secret-not-for-production-0123456789"
os.environ["ENVIRONMENT"] = "test"
os.environ["RATE_LIMIT_REQUESTS"] = "10000"

# Imports below are deliberately after the env setup above — app.config reads
# the environment at import time, so these must not move to the top.
# ruff: noqa: E402

from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import User
from app.security import hash_password


@pytest.fixture(scope="function")
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user(db) -> User:
    u = User(
        email="reader@example.com",
        password_hash=hash_password("correct-horse-battery"),
        display_name="Test Reader",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_headers(client, user) -> dict[str, str]:
    resp = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "correct-horse-battery"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
