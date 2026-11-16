# GovFlow

An AI agent platform for government case processing: one agent, many schemes. Built for the Go AI Hackathon
(Goa). Schemes: land acquisition compensation and disaster relief (housing damage).

Deterministic tools decide eligibility and amounts from a YAML rules file per scheme. The LLM only reads
documents, calls tools and explains. Only an officer approves or rejects. All data is synthetic.

## Set up

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt       # Windows; on macOS/Linux use .venv/bin/
cd web && npm install && cd ..
```

Optional: put `GEMINI_API_KEY=...` in `.env` (gitignored) for live extraction and the agent. Without it every
LLM step falls back to the deterministic tools and says so.

## Run the demo

```
.venv/Scripts/python -m scripts.seed_demo --reset     # builds govflow.db and prints citizen codes
.venv/Scripts/python -m uvicorn app.main:app          # API on port 8000
cd web && npm run dev                                 # dashboard on http://127.0.0.1:5173
```

### Settings in `.env`

| Setting | What it does |
|---|---|
| `GOVFLOW_CITIZEN_SECRET` | Secret for citizen tracking codes. **The seed writes a random one on its first run** and reuses it after that. Without it, `POST /public/status` answers 503: there is no built-in secret, because one in the source would make every code predictable. |
| `GEMINI_API_KEY` | Optional. Live extraction and agent. |

A real environment variable always wins over `.env`. Start the API after the first seed so it picks up the
secret.

See `docs/DEMO_SCRIPT.md` for the jury walkthrough and `docs/KNOWN_LIMITATIONS.md` before trusting any number.

## Tests

```
.venv/Scripts/python -m pytest -q        # backend, no network
cd web && npm test                       # frontend logic
cd web && npm run test:layout            # browser checks (needs Google Chrome)
```

## Not for production as is

Sign-in is a demo mechanism and documents are stored unencrypted. Read `docs/KNOWN_LIMITATIONS.md`.
