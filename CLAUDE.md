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
- Frontend tests: `cd web && npm run test:all` = `npm test` (logic) + `npm run test:layout` (browser checks; needs Google Chrome)

## Working style
- Build and test tools first, then add the agent loop last.
- Every tool gets pytest cases against the fixed synthetic set before it is wired to the agent.
- Prefer small, working vertical slices over broad scaffolding. Keep one scheme fully working before adding another.
- Keep functions small and typed. No clever abstractions.
- Never change expected outcomes in `data/synthetic/` to make a test pass. Fix the code or ask.
- If a rule or legal formula is uncertain, mark it `# VERIFY: <what>` and tell the user instead of guessing.

## Current state (2026-11-16)
Keep this section current: update it in the same commit as any change to what is built, the test counts or a VERIFY item.
Fuller detail is in `docs/KNOWN_LIMITATIONS.md`.

### Built
- Two schemes from YAML only: land acquisition (17 synthetic cases) and disaster relief (15), with hand-derived
  expected outcomes. LA-17 and DR-15 carry prompt-injection text at confidence 1.0 and must end in review.
- Tools: rules engine, compensation, extraction (Gemini vision, Tesseract fallback), verification, SLA, analytics,
  self-check, rule simulator (read-only what-if over the synthetic set). Agent loop with a deterministic fallback.
- Injection defences: prompts call document text and tool results untrusted data; per-field `plausible` ranges in
  the YAML; approval needs the officer's confirmation of every amount-driving field (derived from the YAML) at its
  current value, whatever the confidence; explanations saying approved / rejected / sanctioned are flagged.
- API (FastAPI): demo sign-in issues HMAC-signed, 8-hour role tokens (`GOVFLOW_AUTH_SECRET`); plain `X-Role`
  only with `GOVFLOW_DEMO_INSECURE=1`; roles checked on the server per route; officer-only decisions; append-only
  audit with masked identifiers; UTC timestamps with `Z`; dates in India time; 14 MB body cap; uploads must match
  their file signature.
- Citizen tracking (`POST /public/status`): reference plus a 6-digit HMAC code (`GOVFLOW_CITIZEN_SECRET`, no
  built-in secret: 503 without it), the same 404 for any wrong pair, rate-limited per client and per reference.
  The demo seed writes both secrets to `.env` on first run.
- Web: landing page, citizen shell (home, self-check, track; en/hi/mr/kok; light theme by default) and officer shell
  (queue, case, intake, analytics with one shared scale, simulator, audit, award letter); plain loading / error /
  empty states with Retry; 24 px touch targets; no sideways scroll at 390 px.
- Demo database re-seeded 2026-11-16 after the backdating fix: Submitted and Days open agree for all 23 open cases.

### Tests (all green at commit time)
- Python: 798 passed (`pytest -q`, about 4 minutes).
- Frontend: 65 logic (`npm test`) + 25 browser (`npm run test:layout`); `npm run test:all` runs both. Build clean.

### Still marked VERIFY
- Land acquisition (`rules/land_acquisition.yaml`): notification references (source); 60-day SLA; record-of-rights
  age 180 days; mutation extract age 365 days; rural multiplier default 1.0 (Goa's notified factor unconfirmed);
  estimating to the reference date while the award or possession date is unrecorded; solatium and 12% section
  numbers; whether the 12% base includes the multiplier (formula currently includes it).
- `app/compensation.py`: actual/365 day count for the 12% additional amount.
- Disaster relief (`rules/disaster_relief.yaml`): the SDRF/NDRF 2022-26 schedule in force in Goa; 15-day SLA;
  residence proof age 365 days; claim window 90 days; which Goa areas count as hilly; relying on the assessment's
  own "notified area" certification; 75% full-damage threshold (a placeholder: the norms give no percentage);
  applying the 15% minimum to kutcha houses, huts, clothing and utensils; the condition for clothing and utensils.
- `app/providers/gemini_agent.py`: Gemini function-calling wire format and default temperature (never run live).
- Every rule's `<clause ref>` in both YAML files.
- Plausibility ranges (placeholders, not legal values): land `area_sqm` 10 to 500,000 (holding) and 10 to 5,000,000
  (survey number); `market_value_per_sqm` Rs 100 to 1,00,000.

### Open items
- Gemini: free-tier quota exhausted during testing; the agent has never run against the live API.
- Real-extraction accuracy is unmeasured (last real-image run: 1 of 28 requests answered before rate limits).
- Hindi, Marathi and Konkani text needs native-speaker review.
- Goa rural multiplier: notified value unknown (default 1.0 above).
- Current relief schedule for Goa: amounts follow the 2022-26 norms, labelled "to be confirmed".
- 75% full-damage threshold: placeholder until an official definition is found.
- Production hardening (see KNOWN_LIMITATIONS): government SSO instead of the passwordless demo sign-in; rate
  limits behind a proxy, gentler lockout and separate self-check / tracking limits; separation of duties
  (maker-checker) on decisions.
- A case with no computable amount (DR-09, DR-15) stays *verified* and flagged; it never reaches the officer's
  decision state, so it is found through the queue filters. Decide whether it should go to the officer to send back.
