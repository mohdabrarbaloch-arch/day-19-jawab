# Architecture — Jawab

A search engine that answers with citations. This document explains how a
question becomes an answer, and where the seams are when it needs to grow.

---

## The one idea

Every sentence in an answer is traceable to a page that was actually
downloaded and read. If a page couldn't be fetched, it is still listed as a
source but it is never quoted. That single rule is what separates this from a
chatbot that sounds confident.

---

## System diagram

```
                        ┌──────────────────────────┐
                        │   Browser (vanilla SPA)  │
                        │  index.html / app.js     │
                        │  styles.css              │
                        └────────────┬─────────────┘
                                     │  JSON over HTTPS
                                     │  Bearer JWT
                        ┌────────────▼─────────────┐
                        │      FastAPI app         │
                        │  ┌────────────────────┐  │
                        │  │ security headers   │  │
                        │  │ CORS               │  │
                        │  │ rate limiter       │  │
                        │  └────────────────────┘  │
                        │  ┌────────────────────┐  │
                        │  │ routers/           │  │
                        │  │  auth.py           │  │
                        │  │  search.py         │  │
                        │  └─────────┬──────────┘  │
                        │            │             │
                        │  ┌─────────▼──────────┐  │
                        │  │ service.py         │  │
                        │  │  the pipeline      │  │
                        │  └─────────┬──────────┘  │
                        └────────────┼─────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
┌───────▼────────┐        ┌──────────▼─────────┐       ┌──────────▼────────┐
│ providers/     │        │ engine/            │       │ SQLAlchemy        │
│  search.py     │        │  text.py           │       │  users            │
│   DDG HTML     │        │   sentence split   │       │  threads          │
│   DDG lite     │        │   tokenise         │       │  queries          │
│   Wikipedia    │        │   IDF ranking      │       │  sources          │
│                │        │   dedupe           │       │                   │
│  fetch.py      │        │  answer.py         │       │ SQLite (dev)      │
│   httpx GET    │        │   compose          │       │ Postgres (prod)   │
│   strip HTML   │        │   cite             │       │                   │
│   cap bytes    │        │   confidence       │       │                   │
└───────┬────────┘        │   follow-ups       │       └───────────────────┘
        │                 └────────────────────┘
        │
┌───────▼──────────────────────────────────────┐
│  The open web                                 │
│  DuckDuckGo · Wikipedia · news · docs · blogs │
└──────────────────────────────────────────────┘
```

---

## Data flow for one question

1. **`POST /api/ask`** arrives with `{question, thread_id?}` and a JWT.
2. **`service.get_or_create_thread`** resumes the thread if the caller owns
   it, otherwise starts a new one. A thread id belonging to someone else is
   treated as absent — the caller gets a fresh thread rather than a 403 that
   confirms the id exists.
3. **`providers.search.search`** queries DuckDuckGo's HTML endpoint over GET
   with a browser user agent. If that returns nothing, the lite endpoint is
   tried, then Wikipedia's search API. If all three fail, the pipeline stops
   and says so — it never invents results.
4. **`providers.fetch.fetch_many`** downloads up to `FETCH_PAGES` results
   concurrently, strips scripts/styles/markup, and caps each page at
   `MAX_PAGE_BYTES`. A page under 400 characters of prose is treated as a
   paywall or a JS shell and marked unread.
5. **`engine.text.rank_sentences`** splits every readable page into sentences,
   computes IDF over the whole sentence corpus, and scores each sentence on
   question-term coverage, damped term frequency, and position in its document.
6. **`engine.answer.build_answer`** filters junk (cookie banners, nav links)
   and title fragments (headings with no verb), dedupes near-identical
   sentences from syndicated copy, then picks sentences with a diversity pass
   so one long article can't supply the whole answer.
7. **Confidence** is `0.35 + 0.45 × coverage + 0.20 × agreement`, capped at
   0.97. Coverage is the fraction of the question's content words the answer
   touches; agreement is how many distinct sources back it. A single-source
   answer is flagged in `notes` and never reads as certain.
8. **`service.persist`** writes the query, its answer, and one row per source
   with the sentence positions each source backs.
9. The response carries `sentences[]` (each with a `source_index`) and
   `sources[]` (each with `cited_sentences`), so the UI can render numbered
   chips that link to the exact page.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | FastAPI 0.115 | Async, typed, OpenAPI for free |
| ORM | SQLAlchemy 2.0 | Typed `Mapped[]` models, real migrations later |
| Database | SQLite → PostgreSQL | Zero-setup dev, one env var to switch |
| Auth | PyJWT + bcrypt (cost 12) | No session store to run |
| HTTP client | httpx | Async, one client for search and fetch |
| Frontend | Vanilla JS + CSS | No build step; the whole app is three files |
| Tests | pytest | 73 tests, no network in the suite |
| Lint | ruff | Check and format, both clean |

No LLM API is called. The answer is composed from sentences that were
actually read, which is why it can be cited and why it costs nothing to run.

---

## Database schema

```
users
  id            TEXT PK
  email         TEXT UNIQUE
  password_hash TEXT
  display_name  TEXT
  is_active     BOOL
  created_at    TIMESTAMP

threads
  id         TEXT PK
  user_id    TEXT FK → users.id  (CASCADE)
  title      TEXT
  created_at TIMESTAMP
  updated_at TIMESTAMP

queries
  id            TEXT PK
  thread_id     TEXT FK → threads.id  (CASCADE)
  question      TEXT
  answer        TEXT
  summary       TEXT
  followups_json TEXT
  confidence    FLOAT
  latency_ms    INT
  created_at    TIMESTAMP

sources
  id              TEXT PK
  query_id        TEXT FK → queries.id  (CASCADE)
  rank            INT
  title           TEXT
  url             TEXT
  domain          TEXT
  snippet         TEXT
  cited_sentences TEXT   -- "0,2,5" — which answer sentences this backs
  fetched         BOOL   -- false means listed but never quoted
```

Sources are a table, not a JSON blob, because a citation is a first-class
thing: you can count it, audit it, and later re-check whether the page still
says what it said.

---

## Security

- **Passwords**: bcrypt, cost 12. Input over 72 bytes is refused rather than
  silently truncated (bcrypt's own limit), so two different passwords can
  never hash the same.
- **Tokens**: HS256 JWT, `sub` = user id, 7-day expiry. Secret from env only.
- **Login**: identical error message and identical work whether the email
  exists or not — no account enumeration.
- **Ownership**: another user's thread returns **404, not 403**, so a request
  can't even confirm the id exists.
- **Rate limiting**: sliding window, 30 requests/minute per client IP.
- **Headers**: `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Permissions-Policy`, HSTS outside debug.
- **Input**: every field bounded in `schemas.py` — question 3–500 chars,
  password 8–72 bytes, email validated.
- **Errors**: a global handler logs the trace and returns a generic 500. No
  stack traces reach the client.
- **Secrets**: nothing hardcoded. `.env.example` documents every variable.

---

## Scaling notes

Honest about what breaks first, in order:

1. **The rate limiter is per-process.** Behind more than one worker each
   worker keeps its own counter, so the effective limit multiplies. Move it
   to Redis (`INCR` + `EXPIRE`) before running more than one instance.
2. **Fetching is the slow part.** Five pages at 6 s timeout each, concurrent,
   is ~1–2 s typical. At volume, put a queue in front: the request returns a
   query id immediately and the client polls or subscribes over WebSocket.
3. **No caching.** The same question asked twice re-fetches everything. A
   short-TTL cache keyed on the normalised question would cut most of the
   cost; a `queries` lookup by question hash is the cheap version.
4. **SQLite writes serialise.** Fine for a demo, not for concurrent writers.
   `DATABASE_URL` to Postgres is the fix, and the models already work there.
5. **`create_all()` is not migrations.** One deploy is fine. The second
   environment needs Alembic.
6. **Ranking is lexical.** It matches words, not meaning. An embedding
   reranker over the top ~50 candidates would improve quality noticeably and
   is a drop-in at `rank_sentences` — the rest of the pipeline doesn't change.
7. **No robots.txt check.** We fetch what the search engine returned. At
   scale, respect `robots.txt` and add a per-domain delay.

---

## What this deliberately is not

- **Not an LLM.** It cannot paraphrase, reason across sources, or answer a
  question whose answer is spread across three pages in different words. It
  quotes. That is the trade: verifiability over fluency.
- **Not a crawler.** It reads what a search engine already indexed.
- **Not multi-tenant.** One user, one set of threads. Teams would need an
  organisation table and a scope on every query.
