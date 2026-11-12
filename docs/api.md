# API reference

Base URL: `http://localhost:8000`

Interactive docs: `/api/docs` (Swagger) · OpenAPI JSON: `/api/openapi.json`

All request and response bodies are JSON. Authenticated endpoints expect:

```
Authorization: Bearer <access_token>
```

---

## Errors

Every error returns the same shape:

```json
{ "detail": "Human-readable message." }
```

| Status | When |
|---|---|
| `400` | Malformed request |
| `401` | Missing, invalid, or expired token |
| `403` | Account disabled |
| `404` | Resource not found — **or belongs to someone else** |
| `409` | Email already registered |
| `422` | Validation failed (field-level detail in `detail`) |
| `429` | Rate limit exceeded — see `Retry-After` header |
| `500` | Unhandled error (logged server-side, never leaked) |

---

## `GET /api/health`

No auth. Liveness check.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "environment": "development",
  "database": "sqlite"
}
```

---

## `POST /api/auth/register`

Creates an account and returns a token immediately — no email verification
step.

**Body**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `email` | string | yes | valid email, unique |
| `password` | string | yes | 8–72 bytes |
| `display_name` | string | no | ≤ 80 chars |

```json
{
  "email": "you@example.com",
  "password": "a-good-password",
  "display_name": "Your Name"
}
```

**201 Created**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": "3f2a...",
    "email": "you@example.com",
    "display_name": "Your Name",
    "created_at": "2026-11-13T00:12:00Z"
  }
}
```

**409** if the email is taken. **422** if the password is under 8 bytes or the
email is malformed.

---

## `POST /api/auth/login`

**Body**

```json
{ "email": "you@example.com", "password": "a-good-password" }
```

**200 OK** — same shape as register.

**401** with `"Email or password is incorrect."` — the same message whether
the email exists or not, so the endpoint can't be used to enumerate accounts.

---

## `GET /api/auth/me`

Requires auth. Returns the current user.

```json
{
  "id": "3f2a...",
  "email": "you@example.com",
  "display_name": "Your Name",
  "created_at": "2026-11-13T00:12:00Z"
}
```

---

## `POST /api/ask`

The main endpoint. Searches the web, reads pages, composes a cited answer.

Requires auth. Rate limited to 30 requests/minute per IP.

**Body**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `question` | string | yes | 3–500 chars, whitespace collapsed |
| `thread_id` | string | no | resume an existing thread you own |

```json
{
  "question": "what is retrieval augmented generation",
  "thread_id": null
}
```

**201 Created**

```json
{
  "thread": {
    "id": "a1b2...",
    "title": "what is retrieval augmented generation",
    "created_at": "2026-11-13T00:12:00Z",
    "updated_at": "2026-11-13T00:12:01Z"
  },
  "query": {
    "id": "c3d4...",
    "question": "what is retrieval augmented generation",
    "answer": "Retrieval-augmented generation (RAG) is an approach that integrates LLMs with document retrieval systems. ...",
    "summary": "Retrieval-augmented generation (RAG) is an approach that integrates LLMs with document retrieval systems. (5 sources)",
    "confidence": 0.91,
    "latency_ms": 787,
    "created_at": "2026-11-13T00:12:01Z",
    "sentences": [
      { "text": "Retrieval-augmented generation (RAG) is an approach...", "source_index": 2 },
      { "text": "The term retrieval-augmented generation (RAG) was introduced...", "source_index": 0 }
    ],
    "followups": [
      "How does retrieval augmented generation work in practice?",
      "What are the main criticisms of retrieval augmented generation?"
    ],
    "sources": [
      {
        "rank": 0,
        "title": "Retrieval-augmented generation - Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
        "domain": "en.wikipedia.org",
        "snippet": "Retrieval-augmented generation (RAG)...",
        "cited_sentences": "1",
        "fetched": true
      }
    ],
    "notes": []
  }
}
```

**Field notes**

- `sentences[].source_index` — index into `sources[]`. This is what the UI
  renders as a numbered chip.
- `sources[].cited_sentences` — comma-separated sentence positions this source
  backs, e.g. `"0,2,5"`. Empty means the source was listed but never quoted.
- `sources[].fetched` — `false` means the page couldn't be downloaded. It is
  shown to the reader but never quoted.
- `notes` — flags like `single_source`, `partial_coverage`, `snippets_only`,
  `search_unavailable`, `no_documents`, `no_relevant_sentences`.
- `confidence` — `0.35 + 0.45 × coverage + 0.20 × agreement`, capped at 0.97.
  `0.0` means nothing was found or nothing could be read.

**A `201` with `confidence: 0` is a valid, honest response** — it means the
search failed or the pages had nothing relevant. It is not an error.

---

## `GET /api/threads`

Requires auth. Lists your threads, newest first.

**Query params**

| Param | Default | Range |
|---|---|---|
| `limit` | 50 | 1–200 |

**200 OK**

```json
[
  {
    "id": "a1b2...",
    "title": "what is retrieval augmented generation",
    "created_at": "2026-11-13T00:12:00Z",
    "updated_at": "2026-11-13T00:12:01Z"
  }
]
```

---

## `GET /api/threads/{thread_id}`

Requires auth. Returns the thread with every query in it, oldest first.

**200 OK** — thread fields plus `queries[]`, each shaped like the `query`
object from `/api/ask`.

**404** if the thread doesn't exist **or belongs to another user**. The two
cases are deliberately indistinguishable.

---

## `DELETE /api/threads/{thread_id}`

Requires auth. Deletes the thread and cascades to its queries and sources.

**204 No Content** on success. **404** if not found or not yours.

---

## Rate limiting

30 requests per minute per client IP, sliding window. The key is the first
hop of `X-Forwarded-For` when present, otherwise the socket address.

When exceeded:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 42
```

```json
{ "detail": "Too many requests — slow down a little." }
```

Only `/api/ask` is limited — auth and read endpoints are not, so a client
that hits the limit can still read its own history.

---

## Security headers

Every response carries:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Strict-Transport-Security: max-age=31536000; includeSubDomains   (non-debug only)
```

---

## A full curl session

```bash
BASE=http://localhost:8000

# 1. sign in
TOKEN=$(curl -s -X POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@jawab.app","password":"demo12345"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. ask
curl -s -X POST $BASE/api/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"what is retrieval augmented generation"}' \
  | python -m json.tool

# 3. list threads
curl -s $BASE/api/threads -H "Authorization: Bearer $TOKEN" | python -m json.tool

# 4. read one back
curl -s $BASE/api/threads/<thread_id> -H "Authorization: Bearer $TOKEN" | python -m json.tool

# 5. delete it
curl -s -X DELETE $BASE/api/threads/<thread_id> -H "Authorization: Bearer $TOKEN" -w "%{http_code}\n"
```
