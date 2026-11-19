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
- Three schemes from YAML only: land acquisition (21 synthetic cases), disaster relief (15), and social welfare
  (6; `rules/social_welfare.yaml`, modeled on Goa's DSSS with zero scheme-specific Python code), totaling 42
  synthetic cases with hand-derived expected outcomes. LA-17 and DR-15 carry prompt-injection text at confidence
  1.0 and must end in review.
- Tools: rules engine, compensation, extraction (Gemini vision, Tesseract fallback), verification, SLA, analytics,
  self-check, rule simulator (read-only what-if over the synthetic set). Agent loop with a deterministic fallback.
- SLA pause: the clock stops while a case is in `needs_info` (from the send-back or deficiency notice to the next
  document added, read from audit-log timestamps; `app/sla.py` `waiting_times`). Days open excludes the wait and a
  waiting case is never overdue. Nothing is written and no status moves. The queue marks those cases "clock
  paused" and always shows how many there are, with a link to that filter.
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
- Citizen dates (decision date, notice date) read "17 Nov 2026" in every language (web `formatDay`; the notice
  text from `models.india_day`, same month spellings).
- Sahayak (self-check page): text-only, English-only helper, `POST /public/sahayak` (no sign-in). Keyword
  retrieval (top 3) over `rules/sahayak_knowledge.yaml` (7 sourced entries, not a scheme); Gemini may phrase an
  answer from those entries only (no tools, low temperature); a guard (numbers, rupees, decision words, websites,
  offices not in the entries) or any provider failure falls back to the entry text verbatim. Own rate limit, daily
  provider cap, message never stored (audit row: length and entry ids), and a 422 (any route) never echoes the
  submitted value. No voice anywhere. Each verify entry names
  who to check with (`verify_with`: the Collectorate, the issuing office, the relief office); source names are
  plain words; a reply cites only the top entry.
- Citizen document pre-check (`GET /public/precheck`, `POST /public/precheck`, self-check page): stateless, no
  sign-in, in-memory only. Validates scheme and citizen-uploadable document type (excluding `application`), enforces
  the 14 MB body cap, 10 MB file cap and file-signature check, and runs extraction (Gemini when available, OCR
  fallback), typed coercion, plausible ranges, document age/validity, cross-check and single-document checks in
  memory. Zero storage on disk, DB or logs; writes one minimal `audit_log` row (`document_precheck`: document type,
  result category, timing, fallback flag) only after YAML validation. Plain-language feedback with zero `snake_case`,
  `what_we_read` shown only for name and area fields (never ID numbers), output guard on both primary and OCR
  fallback paths rejecting decision words and rupee mentions, plus its own per-client rate limiter and daily cap.
- Default model `gemini-3.5-flash-lite` (`GEMINI_MODEL` overrides).
- Hash-chained audit log: every `audit_log` row stores `prev_hash` and `row_hash` = SHA-256(prev_hash + "|" + canonical
  row: id, ts as stored, case_id, actor, action, payload_json, rules_version); the first row chains on 64 zeros. Set in
  a `before_flush` hook for every new row (`app/audit_chain.py`); existing rows were chained in id order by the
  start-up migration, which never fills in a hash-less row once a chain exists. `GET /admin/audit/verify` (officer and
  admin; 403 clerk) returns ok, rows and the first broken row id, and logs `audit_chain_verified`. Audit page button
  "Verify log integrity" (checks the whole log, not only that case).
- Duplicate survey-number flag (land): `duplicate_survey_claim`, YAML only, on the `duplicate_claim` built-in with
  `ignore_statuses: [withdrawn]` and no area fields: any other open or decided (approved or rejected) case naming the
  same survey number (existing `_normalise_exact`), whatever the areas. High severity, needs_review, never fail; feeds
  `no_competing_claim`. The officer sees the other case's reference in the flag; the citizen sees only
  `notice.claim_verification` ("Additional verification is in progress."). Co-owners are flagged too (decided
  2026-11-18): LA-14 and LA-15 (both 77/1) now end in review; LA-12 and LA-13 (45/2) carry it as well.
- Extended Officer/Admin Analytics (`GET /analytics`, `#/officer/analytics`): accessible to `officer` and `admin`
  roles only (`clerk` and `citizen` get 403, unauthenticated gets 401; no Analytics nav link for `clerk`); read-only
  queries over existing tables returning `by_scheme_and_status` across all loaded YAML schemes and
  lifecycle stages, `overdue_count` / `overdue_by_scheme` respecting `sla_days` and `needs_info` pauses, `average_days_open`
  / `average_days_open_by_scheme` excluding `needs_info` waiting intervals, `liability` (`committed_total`, `pending_total`,
  `combined_total` and per-scheme breakdowns, excluding `rejected` and `withdrawn`), and `flags` (`total_count`,
  `open_count`, `resolved_count`, `by_kind`, `by_severity`, `by_scheme`). Zero personal data, zero frontend arithmetic.

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
  empty states with Retry; 24 px touch targets; no sideways scroll at 390 px. Case, audit and award pages mount
  fresh per case id (never the previous case while loading); the case page opens with a summary strip (status, stored
  total, flags by severity, SLA clock); placeholder clauses show as a dash; the queue opens on all cases; an approval
  must name the case it was confirmed for
  (`confirmed_case`, else 409); visible keyboard focus on every control, including radios, checkboxes, text areas.
- Demo database re-seeded 2026-11-19 (`--reset`, 42 cases) for the UI polish screenshots.

### Tests (all green at commit time)
- Python: 1,158 passed (`pytest -q`, run in 3 low-memory batches: `[a-f]` 566 + `[g-r]` 245 + `[s-z]` 347).
- Frontend: 87 logic (`npm test`) + 56 browser (`npm run test:layout`); `npm run test:all` runs both. Build clean.




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
- Sahayak (`rules/sahayak_knowledge.yaml`): entries with verify: true (land_record_to_bring, name_spelling_mismatch,
  relief_damage_share, relief_notified_area) and every source given as VERIFY (name_spelling_mismatch,
  tenant_or_mundkar_entry, document_missing_expired_unreadable, what_this_tool_does, relief_damage_share,
  relief_notified_area); `app/providers/gemini_sahayak.py` temperature 0.1 (never run live).
- Duplicate survey-number flag (`rules/land_acquisition.yaml`, `duplicate_survey_claim`): the source for how a second
  claim on a survey number already under, or past, an award must be handled (e.g. a reference for apportionment).
- Plausibility ranges (placeholders, not legal values): land `area_sqm` 10 to 500,000 (holding) and 10 to 5,000,000
  (survey number); `market_value_per_sqm` Rs 100 to 1,00,000.
- Social welfare (`rules/social_welfare.yaml`, `2026.1-draft`): Goa Dayanand Social Security Scheme (DSSS)
  notification, slab rates, and clause references (`<DSSS clause: ...>`); 30-day SLA; 365-day residence proof and
  income certificate validity; eligible categories (`senior_citizen`, `widow`, `person_with_disability`,
  `single_woman`) and minor-child supplement; 15-year continuous Goa residence; Rs 1,50,000 annual family income
  ceiling; age thresholds (60 senior citizen, 40 single woman, 80+ bonus); 40% minimum disability; annualized base
  pension Rs 24,000/yr (Rs 2,000/month) and Rs 6,000/yr age 80+ / minor-child supplements.
  SOURCE CONFLICT (noted 2026-11-19): the Social Welfare Department page shows a 15-year residence rule and a
  Rs 24,000 per annum income limit from a 2002 notification; other public sources show Rs 1.5 lakh and Rs 3 lakh;
  monthly amounts are reported as Rs 2,000 and Rs 2,500. All values stay placeholders until the Directorate
  confirms them; no value was changed.

### Open items
- **Feature freeze from 2026-11-17.** No new features; only fixes, docs and demo preparation. One exception
  granted 2026-11-17: the tenant / mundkar rule and the deficiency notice.
- Voice assistant: planned, not built. Multilingual helper: planned (Sahayak is English only).
- A second freeze exception, 2026-11-17: Sahayak (text only, English only).
- A third freeze exception, 2026-11-17: citizen document pre-check (`POST /public/precheck`, in memory, zero storage).
- Fourth freeze exception, 2026-11-18: hash-chained audit log and the duplicate survey-number flag. Frozen again after.
- Final freeze exception, 2026-11-19: item 1 done (social welfare source-conflict note, no value changed). Item 2,
  the revenue mutation scheme, was **deferred**: it cannot be added with YAML alone (no per-scheme recommendation
  labels, no `on_false: needs_review`, award and citizen amount screens assume an amount, one `sla_days` only, and
  the pipeline always calls compute_compensation). Design and sourced timelines: `docs/FUTURE_MUTATION_SCHEME.md`.

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
