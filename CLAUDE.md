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

## Current state (2026-11-17)
Keep this section current: update it in the same commit as any change to what is built, the test counts or a VERIFY item.
Fuller detail is in `docs/KNOWN_LIMITATIONS.md`.

### Built
- Two schemes from YAML only: land acquisition (21 synthetic cases) and disaster relief (15), with hand-derived
  expected outcomes. LA-17 and DR-15 carry prompt-injection text at confidence 1.0 and must end in review.
- Tools: rules engine, compensation, extraction (Gemini vision, Tesseract fallback), verification, SLA, analytics,
  self-check, rule simulator (read-only what-if over the synthetic set). Agent loop with a deterministic fallback.
- SLA pause: the clock stops while a case is in `needs_info` (from the send-back or deficiency notice to the next
  document added, read from audit-log timestamps; `app/sla.py` `waiting_times`). Days open excludes the wait and a
  waiting case is never overdue. Nothing is written and no status moves.
- Cross-check: when Tesseract is installed it reads each document again; a field the two readers read differently
  after normalisation goes to review as "readers disagree", whatever the confidence (skipped if Tesseract finds
  nothing for the field). Punctuation at either end of a reading is ignored when comparing.
- Review rule: a reading at or below `confidence_threshold` (0.85) goes to review (`app/confidence.py`, used at
  every accept/withhold point).
- Dates are day first: the prompt says DD/MM/YYYY and asks for the date as printed; `field_types` parses
  DD/MM/YYYY (and ISO) day first and rejects anything only valid month first.
- Name match: a name containing digits or symbols ("L?ta Sh1rodkar") fails outright.
- Tenant / mundkar entry (land): the record of rights' tenant and mundkar / other-rights entries are copied as
  printed; the YAML `recorded_entry` check flags any non-empty entry (`tenant_or_mundkar_claim`, high severity;
  blank, dash, Nil, NA, none and Devanagari forms are empty). While open: `valid_ownership` needs review, the
  total is labelled "Total for the holding, not the owner's share", approval needs the officer's resolution
  (reference + date, audit row `flag_resolution`), and the citizen page shows "additional verification of rights
  is in progress". LA-18 (tenant), LA-19 (mundkar), LA-20 (Nil / dash), LA-21 (whitespace only).
- Deficiency notice: officer-only "Request documents" on cases in review. Built from the open problems a citizen
  can fix (missing, expired or unreadable document, name mismatch where the YAML says `citizen_remedy`, missing
  field) with fixed templates (`deficiency.*` in the en/hi/mr/kok files) and YAML labels; no LLM. Preview, then
  send: stored (`deficiency_notices`), audit row `deficiency_notice_sent`, case to the existing `needs_info`. The
  tracking page shows "Documents needed" and prints it. Never approves, rejects or computes.
- Default model `gemini-3.5-flash-lite` (`GEMINI_MODEL` overrides).
- Synthetic document images for both schemes (land 7, relief 7), each clean, degraded and hard (stamp, one
  handwriting-style field, phone-photo look), all labelled SYNTHETIC. LA-11's image prints its damaged scan text.
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
- Python: 1002 passed (`pytest -q`, about 5 minutes; with little free memory, run in two batches).
- Frontend: 68 logic (`npm test`) + 25 browser (`npm run test:layout`); `npm run test:all` runs both. Build clean.

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
- `app/providers/gemini_agent.py` and `gemini.py`: wire format and default temperature verified live on the default
  `gemini-3.5-flash-lite` only; VERIFY on any other model set through `GEMINI_MODEL`.
- Every rule's `<clause ref>` in both YAML files.
- Tenant / mundkar rule (`rules/land_acquisition.yaml`): which Form I & XIV column(s) hold the tenant and the
  mundkar / other-rights entries; which resolution document applies in an acquisition; that the empty-value list
  covers how Goa's records write an empty column. Basis cited: the Goa, Daman and Diu Agricultural Tenancy Act,
  1964 and the Goa, Daman and Diu Mundkars (Protection from Eviction) Act, 1975.
- Plausibility ranges (placeholders, not legal values): land `area_sqm` 10 to 500,000 (holding) and 10 to 5,000,000
  (survey number); `market_value_per_sqm` Rs 100 to 1,00,000.

### Open items
- **Feature freeze from 2026-11-17.** No new features; only fixes, docs and demo preparation. One exception
  granted 2026-11-17: the tenant / mundkar rule and the deficiency notice.
- Voice assistant: planned, not built.
- Deficiency notices name fields in English (YAML labels) even in the hi/mr/kok drafts.
- Live evaluation (`docs/EVAL_RESULTS.md`, two runs on 17 Nov 2026, synthetic only) on `gemini-3.5-flash-lite`
  only (other models were unreachable on 16 Nov). After the fix round, Gemini: relief 35/35 on clean, degraded and
  hard; land 25/27, 25/27, 21/27 with 1, 0, 2 wrong values passing the confidence gate, every one caught later by
  a deterministic check. Dates 36/36. 0 provider errors.
- Model confidence still does not separate right from wrong: the remaining wrong values were read at 0.90 to 0.95.
- Cross-check still over-flags on hard images: 21 of its 23 firings were on correct readings (2 catches, both also
  caught by other checks). Decide whether to keep it on for hard documents.
- Cost of the at-or-below rule: Tesseract gives exactly 0.85 to four correct land dates on degraded images, now
  withheld (affects the Tesseract-only baseline, not Gemini + Tesseract).
- Hindi, Marathi and Konkani text needs native-speaker review.
- Goa rural multiplier: notified value unknown (default 1.0 above).
- Current relief schedule for Goa: amounts follow the 2022-26 norms, labelled "to be confirmed".
- 75% full-damage threshold: placeholder until an official definition is found.
- Production hardening (see KNOWN_LIMITATIONS): government SSO instead of the passwordless demo sign-in; rate
  limits behind a proxy, gentler lockout and separate self-check / tracking limits; separation of duties
  (maker-checker) on decisions.
- A case with no computable amount (DR-09, DR-15) stays *verified* and flagged; it never reaches the officer's
  decision state, so it is found through the queue filters. Decide whether it should go to the officer to send back.
