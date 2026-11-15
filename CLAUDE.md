# GovFlow

AI agent platform for government case processing (Go AI Hackathon, Goa). One agent, many schemes.
Primary scheme: land acquisition compensation. Second scheme: disaster relief. Jury: Nov 30, 2026.
Solo developer, so keep everything simple, testable and demo-able. Read SPEC.md before building anything.

## Non-negotiable rules
1. The LLM never decides eligibility, compensation or approval. Deterministic tools decide. The LLM only extracts text, calls tools and explains results in plain language.
2. The agent never rejects a case. It recommends. Only the officer role can approve or reject.
3. Every result must cite its source: the rule id and clause for rule results, the document and field for extracted values.
4. Low-confidence extraction (below the threshold in config) must route to human review, never guess.
5. Every tool call, rule result and officer action is written to the append-only audit table, with the rule version used.
6. A new scheme must be addable by adding a YAML rules file. Do not hardcode scheme logic in Python.
7. Never commit real citizen data. Use synthetic data only. Mask identifiers (Aadhaar-like numbers) in logs and UI.

## Stack
- Backend: Python 3.11+, FastAPI, Pydantic, SQLite (SQLAlchemy), pytest
- Rules: YAML files in `rules/`, loaded and evaluated by `app/rules_engine.py`
- OCR/extraction: vision-capable LLM first, Tesseract as fallback (`app/extraction.py`)
- Agent: tool-calling loop in `app/agent.py`, with the LLM provider behind a thin interface so it can be swapped
- Frontend: React + Vite officer dashboard in `web/`

## Layout
```
app/            backend code (rules_engine, compensation, extraction, verification, agent, audit, api)
rules/          one YAML file per scheme
data/synthetic/ fixed test cases (about 15 per scheme) with expected outcomes
tests/          pytest, tools tested WITHOUT the LLM
web/            officer dashboard
docs/           architecture diagram, demo script
```

## Commands
- Run API: `uvicorn app.main:app --reload`
- Tests: `pytest -q`
- Frontend: `cd web && npm run dev`

## Working style
- Build and test tools first, then add the agent loop last.
- Every tool gets pytest cases against the fixed synthetic set before it is wired to the agent.
- Prefer small, working vertical slices over broad scaffolding. Keep one scheme fully working before adding another.
- Keep functions small and typed. No clever abstractions.
- Never change expected outcomes in `data/synthetic/` to make a test pass. Fix the code or ask.
- If a rule or legal formula is uncertain, mark it `# VERIFY: <what>` and tell the user instead of guessing.
