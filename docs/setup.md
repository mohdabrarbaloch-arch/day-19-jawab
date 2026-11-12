# Setup

Three ways to run Jawab. Pick the one that matches how much you care about
isolation.

---

## Option 1 — Docker (fastest, recommended)

You need Docker and Docker Compose. Nothing else.

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-19-jawab.git
cd day-19-jawab

# compose refuses to start without a JWT secret — that's deliberate.
cp .env.example .env
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))" >> .env

docker compose up --build
```

Open <http://localhost:8000>. The demo account is created on first boot:

```
demo@jawab.app / demo12345
```

To use Postgres instead of SQLite:

```bash
docker compose --profile postgres up --build
```

Then set `DATABASE_URL=postgresql+psycopg://jawab:jawab@postgres:5432/jawab`
in your `.env` and restart. You'll also need `psycopg[binary]` in the image —
add it to `pyproject.toml` dependencies.

---

## Option 2 — Local Python

Python 3.11 or newer.

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-19-jawab.git
cd day-19-jawab

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

Create the database and the demo user:

```bash
python -m app.seed
```

That prints:

```
Created demo account: demo@jawab.app / demo12345
```

Start the server:

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

---

## Option 3 — Bare minimum, no venv

If you just want to see it work and don't care about polluting your global
Python:

```bash
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic pydantic-settings \
            email-validator pyjwt bcrypt httpx
python -m app.seed
uvicorn app.main:app --reload
```

---

## Configuration

Every setting has a working default, so you can run without a `.env` at all.
Copy `.env.example` to `.env` when you want to change something.

The only one you **must** change for production:

| Variable | Why |
|---|---|
| `JWT_SECRET` | The default is a known string. Anyone who reads this repo could forge tokens. |

Generate a real one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The rest are documented inline in `.env.example`. The ones you're most likely
to touch:

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/jawab.db` | Point at Postgres for production |
| `FETCH_PAGES` | `5` | More pages = better answers, slower requests |
| `RATE_LIMIT_REQUESTS` | `30` | Per IP per minute |
| `CORS_ORIGINS` | `*` | Lock this down in production |
| `ENVIRONMENT` | `development` | `production` enables HSTS |

---

## Verifying the install

```bash
curl http://127.0.0.1:8000/api/health
```

Should return:

```json
{"status":"ok","version":"1.0.0","environment":"development","database":"sqlite"}
```

Then sign in and ask something:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@jawab.app","password":"demo12345"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://127.0.0.1:8000/api/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"what is retrieval augmented generation"}' \
  | python -m json.tool | head -40
```

You should get back an answer with `sentences` and `sources`, and at least one
source with a non-empty `cited_sentences`.

---

## Running the tests

```bash
pytest
```

73 tests, no network required — the pipeline is stubbed in the API tests.

```bash
ruff check .          # lint
ruff format --check . # formatting
```

Both should pass cleanly.

---

## Troubleshooting

**`JWT_SECRET must be set`** — compose is refusing to start with the default
secret. Add one to `.env`. This is intentional.

**Answers come back with `confidence: 0` and "couldn't reach a search engine"**
— outbound HTTPS is blocked, or DuckDuckGo and Wikipedia are both rate-limiting
you. Check with:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://html.duckduckgo.com/html/?q=test
```

**`sqlite3.OperationalError: unable to open database file`** — the `data/`
directory doesn't exist. `mkdir -p data` and retry.

**Answers are thin or irrelevant** — raise `FETCH_PAGES` to 8 and
`SEARCH_RESULTS` to 12. More pages read means more sentences to rank.

**Port 8000 already in use** — `uvicorn app.main:app --port 8001`.
