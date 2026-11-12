"""HTTP surface: auth, ownership, validation, status codes.

The pipeline is stubbed here — these tests are about the API contract, not
about whether DuckDuckGo is up.
"""

from __future__ import annotations

import pytest

from app.engine.answer import SourceDoc
from app.providers.search import SearchResult


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Replace the network with a fixed, realistic result."""

    async def fake_search(query, limit=None):
        return [
            SearchResult(
                title="Retrieval-augmented generation — overview",
                url="https://example.com/rag",
                snippet="RAG combines retrieval with generation.",
            ),
            SearchResult(
                title="Why citations matter",
                url="https://example.org/citations",
                snippet="Citations let readers verify claims.",
            ),
        ]

    async def fake_fetch(results, limit=None):
        return [
            SourceDoc(
                title="Retrieval-augmented generation — overview",
                url="https://example.com/rag",
                domain="example.com",
                text=(
                    "Retrieval augmented generation combines a retriever with a "
                    "language model. The retriever fetches relevant documents "
                    "before the model writes an answer. This reduces hallucination "
                    "because the model works from retrieved text."
                ),
                snippet="RAG combines retrieval with generation.",
                fetched=True,
            ),
            SourceDoc(
                title="Why citations matter",
                url="https://example.org/citations",
                domain="example.org",
                text=(
                    "Citations let a reader verify each claim in an answer. "
                    "A cited answer is auditable in a way a fluent paragraph is not."
                ),
                snippet="Citations let readers verify claims.",
                fetched=True,
            ),
        ]

    monkeypatch.setattr("app.providers.search.search", fake_search)
    monkeypatch.setattr("app.providers.fetch.fetch_many", fake_fetch)
    return True


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["database"] == "sqlite"

    def test_security_headers_present(self, client):
        r = client.get("/api/health")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"


class TestAuth:
    def test_register_returns_token(self, client):
        r = client.post(
            "/api/auth/register",
            json={
                "email": "new@example.com",
                "password": "a-good-password",
                "display_name": "New Person",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["access_token"]
        assert body["user"]["email"] == "new@example.com"

    def test_duplicate_email_conflicts(self, client):
        payload = {"email": "dup@example.com", "password": "a-good-password"}
        assert client.post("/api/auth/register", json=payload).status_code == 201
        assert client.post("/api/auth/register", json=payload).status_code == 409

    def test_short_password_rejected(self, client):
        r = client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "abc"},
        )
        assert r.status_code == 422

    def test_invalid_email_rejected(self, client):
        r = client.post(
            "/api/auth/register",
            json={"email": "not-an-email", "password": "a-good-password"},
        )
        assert r.status_code == 422

    def test_login_wrong_password(self, client, user):
        r = client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "wrong-password"},
        )
        assert r.status_code == 401

    def test_login_unknown_email_same_message(self, client, user):
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever123"},
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "Email or password is incorrect."

    def test_me_requires_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_returns_user(self, client, auth_headers, user):
        r = client.get("/api/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["email"] == user.email

    def test_bad_token_rejected(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"})
        assert r.status_code == 401


class TestAsk:
    def test_ask_requires_auth(self, client):
        r = client.post("/api/ask", json={"question": "what is rag"})
        assert r.status_code == 401

    def test_ask_returns_cited_answer(self, client, auth_headers, stub_pipeline):
        r = client.post(
            "/api/ask",
            json={"question": "what is retrieval augmented generation"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["query"]["answer"]
        assert body["query"]["sources"]
        assert body["thread"]["id"]

        cited = [s for s in body["query"]["sources"] if s["cited_sentences"]]
        assert cited, "at least one source should be cited"

    def test_ask_rejects_short_question(self, client, auth_headers):
        r = client.post("/api/ask", json={"question": "hi"}, headers=auth_headers)
        assert r.status_code == 422

    def test_ask_rejects_overlong_question(self, client, auth_headers):
        r = client.post("/api/ask", json={"question": "x" * 600}, headers=auth_headers)
        assert r.status_code == 422

    def test_followup_continues_same_thread(self, client, auth_headers, stub_pipeline):
        first = client.post(
            "/api/ask",
            json={"question": "what is retrieval augmented generation"},
            headers=auth_headers,
        ).json()
        thread_id = first["thread"]["id"]

        second = client.post(
            "/api/ask",
            json={
                "question": "why does it reduce hallucination",
                "thread_id": thread_id,
            },
            headers=auth_headers,
        ).json()

        assert second["thread"]["id"] == thread_id

        detail = client.get(f"/api/threads/{thread_id}", headers=auth_headers).json()
        assert len(detail["queries"]) == 2


class TestThreads:
    def test_list_threads_empty(self, client, auth_headers):
        r = client.get("/api/threads", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_thread_not_found(self, client, auth_headers):
        r = client.get("/api/threads/doesnotexist", headers=auth_headers)
        assert r.status_code == 404

    def test_other_users_thread_is_404(self, client, auth_headers, stub_pipeline):
        created = client.post(
            "/api/ask",
            json={"question": "what is retrieval augmented generation"},
            headers=auth_headers,
        ).json()
        thread_id = created["thread"]["id"]

        # A second, unrelated account must not see it — and must not learn
        # that it exists.
        other = client.post(
            "/api/auth/register",
            json={"email": "other@example.com", "password": "another-password"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}

        r = client.get(f"/api/threads/{thread_id}", headers=other_headers)
        assert r.status_code == 404

    def test_delete_thread(self, client, auth_headers, stub_pipeline):
        created = client.post(
            "/api/ask",
            json={"question": "what is retrieval augmented generation"},
            headers=auth_headers,
        ).json()
        thread_id = created["thread"]["id"]

        assert (
            client.delete(f"/api/threads/{thread_id}", headers=auth_headers).status_code
            == 204
        )
        assert (
            client.get(f"/api/threads/{thread_id}", headers=auth_headers).status_code == 404
        )

    def test_delete_missing_thread_404(self, client, auth_headers):
        assert client.delete("/api/threads/nope", headers=auth_headers).status_code == 404


class TestSearchUnavailable:
    def test_graceful_when_search_fails(self, client, auth_headers, monkeypatch):
        async def no_results(query, limit=None):
            return []

        monkeypatch.setattr("app.providers.search.search", no_results)

        r = client.post(
            "/api/ask",
            json={"question": "what is retrieval augmented generation"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["query"]["confidence"] == 0.0
        assert "couldn't reach" in body["query"]["summary"].lower()
