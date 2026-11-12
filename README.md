# Jawab · جواب

**A search engine that shows its work.**

Ask a question, get an answer where every single sentence is traceable to a
page that was actually downloaded and read. No confident guessing, no
paraphrased half-truths — just quotes with numbered citations you can click.

[![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-73%20passing-brightgreen)](tests/)
[![Lint](https://img.shields.io/badge/ruff-clean-brightgreen)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

---

## Why this exists

Every AI search tool has the same problem: it sounds certain whether or not
it's right. You get a fluent paragraph, and you have no idea which part came
from a real page and which part the model made up.

Jawab takes the opposite bet. It doesn't generate prose — it **selects
sentences** from pages it read, and attaches the source to each one. If a page
couldn't be downloaded, it's listed but never quoted. If only one source backs
the answer, the UI says so.

The result reads a little less smooth than an LLM. It's also checkable, which
is the whole point.

---

## Features

**Cited answers, not generated ones**
Every sentence carries a numbered chip linking to the exact page it came from.
Click it, read the original, decide for yourself.

**Honest confidence**
`0.35 + 0.45 × coverage + 0.20 × agreement`, capped at 97%. Coverage is how
much of your question the answer touches; agreement is how many distinct
sources back it. A single-source answer is flagged in the UI.

**Unread sources are marked**
The search engine might return eight results; we only download five. The other
three appear in the source list with a `not read` badge — visible, but never
quoted.

**No API keys, no LLM bill**
Search runs on DuckDuckGo's HTML endpoint with a Wikipedia fallback. Answer
composition is deterministic Python. The whole thing costs nothing to run and
gives the same answer twice.

**Threads with history**
Every question is saved with its answer and sources. Reopen a thread, read it
back, delete it.

**Real auth**
bcrypt (cost 12) + JWT. Another user's thread returns 404, not 403 — a request
can't even confirm the id exists.

**Mobile-first UI**
Dark, editorial, no framework, no build step. Three files: `index.html`,
`styles.css`, `app.js`.

---

## Screenshots

| | |
|---|---|
| **Ask** — the empty state, with suggested questions | **Answer** — cited sentences with numbered chips |
| ![Ask](screenshots/ask.png) | ![Answer](screenshots/answer.png) |
| **Sources** — cited vs unread, clearly distinguished | **Mobile** — sidebar collapsed, composer at thumb height |
| ![Sources](screenshots/sources.png) | ![Mobile](screenshots/mobile.png) |

---

## Live demo

**Not deployed.** There is no `VERCEL_TOKEN` in the build environment, and
Vercel is not a natural target for a Python/FastAPI app with a SQLite file
anyway. Rather than fake a URL, here is the honest state:

- The app runs locally and has been verified end to end — real DuckDuckGo
  results, real page fetches, real cited answers.
- `Dockerfile` and `docker-compose.yml` are committed and ready.
- To get a live URL in about two minutes, see **Deploy** below.

---

## Quick start

### Docker (recommended)

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-19-jawab.git
cd day-19-jawab

cp .env.example .env
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))" >> .env

docker compose up --build
```

Open <http://localhost:8000> → click **Use the demo account**.

### Local Python

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-19-jawab.git
cd day-19-jawab

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m app.seed          # creates demo@jawab.app / demo12345
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

Full instructions, including Postgres and troubleshooting, are in
[docs/setup.md](docs/setup.md).

---

## How it works

```
question
   │
   ├─► search      DuckDuckGo HTML → lite → Wikipedia fallback
   │
   ├─► fetch       up to 5 pages, concurrent, HTML stripped, bytes capped
   │
   ├─► rank        split sentences → IDF over corpus → score each one
   │               (coverage × rarity + damped term frequency + position)
   │
   ├─► compose     drop junk and title fragments → dedupe syndicated copy
   │               → pick with source diversity → attach citation indices
   │
   └─► persist     query + answer + one row per source, with cited positions
```

The ranking is lexical, not semantic — it matches words, not meaning. That's
a real limitation and it's documented in
[ARCHITECTURE.md](ARCHITECTURE.md#scaling-notes) along with the fix (an
embedding reranker drops in at `rank_sentences` without touching anything
else).

---

## Tech stack

| | |
|---|---|
| **Backend** | FastAPI 0.115, SQLAlchemy 2.0, Pydantic v2 |
| **Database** | SQLite (dev) → PostgreSQL (prod), one env var |
| **Auth** | PyJWT + bcrypt cost 12 |
| **HTTP** | httpx (async) |
| **Frontend** | Vanilla JS + CSS, no build step |
| **Tests** | pytest — 73 tests, no network needed |
| **Lint** | ruff check + ruff format, both clean |

---

## API

| Method | Path | What |
|---|---|---|
| `GET` | `/api/health` | Liveness |
| `POST` | `/api/auth/register` | Create account, returns token |
| `POST` | `/api/auth/login` | Sign in |
| `GET` | `/api/auth/me` | Current user |
| `POST` | `/api/ask` | **The main one** — search, read, answer with citations |
| `GET` | `/api/threads` | List your threads |
| `GET` | `/api/threads/{id}` | One thread with all its queries |
| `DELETE` | `/api/threads/{id}` | Delete a thread |

Full reference with request/response examples: [docs/api.md](docs/api.md).
Interactive Swagger at `/api/docs` when running.

---

## Tests

```bash
pytest                  # 73 passed
ruff check .            # All checks passed
ruff format --check .   # 24 files already formatted
```

The suite covers sentence splitting (including abbreviations), IDF ranking,
dedupe, citation mapping, confidence behaviour, junk filtering, follow-up
generation, password hashing, JWT round-trips, the rate limiter, and the full
HTTP surface — auth, ownership isolation, validation, and graceful degradation
when search fails.

No network calls in the tests. The pipeline is stubbed in `tests/test_api.py`.

---

## Deploy

### Docker anywhere

```bash
docker compose up -d --build
```

Works on any VPS, Fly.io, Railway, Render, or a home server. Set `JWT_SECRET`
and `CORS_ORIGINS` in `.env` first.

### With Postgres

```bash
docker compose --profile postgres up -d --build
```

Then set `DATABASE_URL=postgresql+psycopg://jawab:jawab@postgres:5432/jawab`
and add `psycopg[binary]` to `pyproject.toml`.

### Vercel

Not recommended for this app — Vercel's filesystem is read-only except `/tmp`,
and `/tmp` doesn't survive between invocations, so a SQLite database would
lose data. If you want Vercel specifically, swap `DATABASE_URL` to a hosted
Postgres (Neon, Supabase) and add `psycopg[binary]`. The app itself needs no
changes.

---

## Project structure

```
day-19-jawab/
├── app/
│   ├── main.py              FastAPI app, middleware, static mount
│   ├── config.py            Settings from env, all defaults documented
│   ├── db.py                Engine, session, init
│   ├── models.py            User, Thread, Query, Source
│   ├── schemas.py           Bounded request/response models
│   ├── security.py          bcrypt, JWT, rate limiter
│   ├── service.py           The pipeline: search → fetch → rank → persist
│   ├── seed.py              Demo account
│   ├── engine/
│   │   ├── text.py          Sentence split, tokenise, IDF rank, dedupe
│   │   └── answer.py        Compose, cite, confidence, follow-ups
│   ├── providers/
│   │   ├── search.py        DuckDuckGo HTML + lite + Wikipedia
│   │   └── fetch.py         Concurrent download, HTML → text
│   ├── routers/
│   │   ├── auth.py
│   │   └── search.py
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js
├── tests/                   73 tests
├── docs/                    setup · usage · api
├── ARCHITECTURE.md          Diagram, data flow, scaling notes
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## What it won't do

Being straight about the limits:

- **It won't reason across sources.** If the answer needs page A plus page B
  combined, you get both sentences and do the combining.
- **It won't paraphrase.** Awkward source, awkward answer. That's the price of
  every sentence being checkable.
- **It won't remember your last question.** Each question is answered on its
  own terms — include the noun, not "it".
- **It won't answer from training data.** No model is involved. If the web
  doesn't say it, Jawab doesn't know it.

---

## License

MIT — see [LICENSE](LICENSE).

Built by [ABraz Baloch](https://github.com/mohdabrarbaloch-arch) as Day 19 of
the Autonomous AI Software Engineer 30-Day Challenge.
