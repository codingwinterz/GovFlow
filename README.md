# GovFlow

An AI agent platform for government case processing: one agent, many schemes. Built for the Go AI Hackathon
(Goa). Four schemes, each one YAML file in `rules/`: land acquisition compensation, disaster relief (housing
damage), social welfare pension and revenue mutation.

Deterministic tools decide eligibility and amounts from a YAML rules file per scheme. The LLM only reads
documents, calls tools and explains. Only an officer approves or rejects. All data is synthetic (47 invented cases
in `data/synthetic/`, images labelled SYNTHETIC); never put real citizen data in it.

## Set up

Needs Python 3.11+ and Node 20.19+ (Vite 8). Tesseract OCR is optional (second reader and offline fallback).

```
git clone <this repo> && cd GovFlow
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt       # Windows; on macOS/Linux use .venv/bin/
cd web && npm install && cd ..
```

Optional: put `GEMINI_API_KEY=...` (a key from Google AI Studio) in `.env` (gitignored) for live extraction and the
agent. Without it every
LLM step falls back to the deterministic tools and says so.

## Run the demo

```
.venv/Scripts/python -m scripts.seed_demo --reset     # builds govflow.db and prints citizen codes
.venv/Scripts/python -m uvicorn app.main:app          # API on port 8000
cd web && npm run dev                                 # dashboard on http://localhost:5173
```

Open http://localhost:5173 and pick *Citizen services* or *Staff*. Staff sign-in is demo only, no password: choose
a role and any user id, for example officer `O-1` (decides cases), clerk `C-1` (intake) or admin `A-1`
(analytics, simulator). Citizen tracking uses a reference and the 6-digit code the seed printed. `--reset` deletes
and rebuilds `govflow.db`.

### Settings in `.env`

| Setting | What it does |
|---|---|
| `GOVFLOW_CITIZEN_SECRET` | Secret for citizen tracking codes. **The seed writes a random one on its first run** and reuses it after that. Without it, `POST /public/status` answers 503: there is no built-in secret, because one in the source would make every code predictable. |
| `GOVFLOW_AUTH_SECRET` | Signs the staff sign-in tokens (8 hours). **Also written by the seed on its first run.** Without it, sign-in answers 503. |
| `GOVFLOW_DEMO_INSECURE` | `1` also accepts plain `X-Role` / `X-User` headers (old scripts). Off by default; never in a shared deployment. |
| `GEMINI_API_KEY` | Optional. Live extraction and agent. |
| `GEMINI_MODEL` | Optional. Defaults to `gemini-3.5-flash-lite`, the only model evaluated live (`docs/EVAL_RESULTS.md`). Any other model is unverified. |

A real environment variable always wins over `.env`. Start the API after the first seed so it picks up the
secret.

See `docs/DEMO_SCRIPT.md` for the jury walkthrough and `docs/KNOWN_LIMITATIONS.md` before trusting any number.

## Tests

```
.venv/Scripts/python -m pytest -q        # backend, no network
cd web && npm test                       # frontend logic
cd web && npm run test:layout            # browser checks (needs Google Chrome)
cd web && npm run test:all               # both
```

On a low-memory machine run the Python tests in three batches: `tests/test_[a-f]*.py`, `tests/test_[g-r]*.py`,
`tests/test_[s-z]*.py`.

## Not for production as is

**Production needs the government single sign-on (SSO).** The staff sign-in here has no password: it issues a
signed, expiring role token, so a client cannot edit its role, but anyone who can reach the sign-in can choose
one. Do not expose the demo on a public network. Documents are stored unencrypted. Read
`docs/KNOWN_LIMITATIONS.md`.
