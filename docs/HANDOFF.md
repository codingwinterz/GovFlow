# GovFlow: handoff for a new session

Written 17 Nov 2026 at commit `d73da8c` (the last code commit before this file); synced on 18 Nov 2026 with the code at
`9b648a6` (see "What changed since the first handoff", section 5). For anything that changes later, `CLAUDE.md`
"Current state" is the live source of truth.

## First 5 minutes (checklist)

1. Read `CLAUDE.md` (rules, current state, VERIFY list), then this file, then `docs/KNOWN_LIMITATIONS.md`.
2. `git log --oneline -15` and `git status`: the tree should be clean and in step with `origin/main`
   (https://github.com/codingwinterz/GovFlow).
3. Check `.env` exists in the repo root (it is gitignored, so a fresh clone has none). If not, ask the user to recreate
   it (section 7). **Never print it, and never print a key, a secret or a tracking code.**
4. Free memory is often under 1 GB on this machine: run test suites in batches (section 7), one thing at a time.
5. Before any live Gemini call, run the one-call preflight (section 7). If it fails, stop and report; don't retry in a loop.

---

## 1. Project and context

- **What:** GovFlow, an entry to the **Go AI Hackathon** (Goa government). Brief: "AI-powered Governance Platform for
  Automated Public Service Delivery".
- **Who:** solo developer WINTERZ (Avaneesh S).
- **Dates:** idea already submitted. Final package due **22 Nov 2026** (idea submission closes 23 Nov). **Jury: 30 Nov 2026.**
- **Pitch in one line:** one AI agent, many government schemes; schemes are YAML files; the AI reads and explains, and
  deterministic code and the officer decide.
- **Feature freeze since 17 Nov 2026.** Approved exceptions, all built: the tenant / mundkar rule, the deficiency notice,
  the SLA pause, Sahayak (text-only, English-only), the citizen document pre-check (`POST /public/precheck`,
  section 8), the hash-chained audit log and duplicate survey-number flag (18 Nov), and the final pre-freeze
  closure (18–19 Nov): extended officer/admin analytics (`by_scheme_and_status`, active `average_days_open`,
  `liability`, `flags`) and the 3rd pure-YAML scheme (`rules/social_welfare.yaml`). Frozen again after.

- All case data is **synthetic**. No real citizen data is ever committed (CLAUDE.md rule 7).

## 2. Architecture and how it works

### End-to-end flow (one case)

1. **Intake:** a clerk creates a case (`POST /cases`) and uploads documents (`POST /cases/{id}/documents`; a 14 MB request
   cap, about a 10 MB file sent as base64, and the bytes must match the file type: `app/body_limit.py`, `app/upload_check.py`).
2. **Extraction:** Gemini vision reads the declared fields of each document (`app/extraction.py`,
   `app/providers/gemini.py`). Fields at or below the confidence threshold get an OCR pass (Tesseract,
   `app/providers/tesseract.py`). When Tesseract is installed it also **cross-checks** every field: two readers that
   disagree send the field to review ("readers disagree", `app/cross_check.py`).
3. **Validation:** extracted strings are coerced once to their YAML type (`app/field_types.py`; dates are day-first);
   values outside the YAML's plausible range, low-confidence values and disagreeing values are withheld
   (`app/facts.py`, `app/confidence.py`).
4. **Flags:** cross-document checks from the YAML (name match, survey / house match, duplicate claims, the duplicate
   survey number, tenant / mundkar entries) plus missing, expired and unreadable documents (`app/verification.py`).
5. **Rules and calculator:** eligibility rules (`app/rules_engine.py`, expressions run by `app/safe_eval.py`) and the
   itemised amount from the YAML formulas (`app/compensation.py`). Each rule result carries its rule id, clause and rules
   version.
6. **Agent explanation:** a tool-calling loop (`app/agent.py`, Gemini via `app/providers/gemini_agent.py`) runs the tools
   above and writes a plain-language summary. Without an LLM it runs the same tools deterministically and says so.
   Numbers in the explanation that no tool produced, and decision words, are flagged.
7. **Officer confirmation and decision:** only the officer role decides (`tools.record_officer_decision`). Approving
   needs a tick on every amount-driving field at its current value, the resolution (reference plus date) for any open
   tenant / mundkar flag, and `confirmed_case` equal to the case in the URL.
8. **Audit:** every tool call, rule result and officer action goes to the append-only `audit_log` (SQLite triggers refuse
   UPDATE and DELETE), with identifiers masked and the rules version (`app/audit.py`, `app/privacy.py`, `app/models.py`).
   Every row is hash-chained (`prev_hash`, `row_hash`, `app/audit_chain.py`); `GET /admin/audit/verify` (officer and
   admin) walks the chain and returns ok, the row count and the first broken row id; the Audit page's *Verify log
   integrity* button shows the result.
9. **Citizen tracking:** `POST /public/status` with the case reference plus a 6-digit HMAC code; status, next step,
   what is missing, the decision and the approved amounts with their basis, in four languages (`app/citizen.py`).

### Design rules (non-negotiable; also in CLAUDE.md)

- **The model copies, code decides.** The LLM extracts text, calls tools and explains. Eligibility, amounts and
  decisions come only from deterministic code and the officer.
- **The agent has no decision tool.** Its six tools: `get_case_status`, `extract_document`, `verify_documents`,
  `check_eligibility`, `compute_compensation`, `submit_to_officer` (`app/agent.py`, `AGENT_TOOL_NAMES`).
- **The officer confirms money-affecting fields** before approval, whatever the extraction confidence.
- **Append-only, masked audit**; every result cites its source (rule id and clause, or document and field).
- **Low confidence goes to review**, never a guess. **No scheme logic in Python:** a new scheme is a YAML file.

### File and module map

| Path | What it does |
|---|---|
| `app/main.py` | FastAPI app and every route; roles checked per route; 422 handler that never echoes input |
| `app/auth.py` | Demo sign-in: HMAC-signed 8-hour role tokens (clerk, officer, admin) |
| `app/models.py` | SQLAlchemy tables, append-only audit triggers, the hash-chain hook and start-up migration, India-time dates (`india_date`, `india_day`) |
| `app/audit_chain.py` | Audit hash chain: canonical row, `row_hash`, `verify_chain`, the one-time backfill of rows written before the chain |
| `app/case_model.py`, `app/case_store.py` | Case input model; load and seed cases; status moves |
| `app/rules_loader.py` | Loads and validates scheme YAML; `scheme_names()` (leaves out the Sahayak knowledge file) |
| `app/field_types.py`, `app/units.py` | Typed coercion (text, number, percent, date, unit, one_of); area units to sq m |
| `app/facts.py`, `app/confidence.py` | Facts for the rules: withholds low-confidence, invalid, implausible, disagreeing values |
| `app/extraction.py`, `app/cross_check.py` | Extraction with OCR fallback; second-reader comparison |
| `app/verification.py` | Cross-document checks and flags (built-ins: `duplicate_claim` with optional `ignore_statuses`, `recorded_entry`) |
| `app/rules_engine.py`, `app/safe_eval.py` | Eligibility rules; a restricted expression evaluator |
| `app/compensation.py`, `app/assessment.py` | Itemised amounts from YAML formulas; one case assessment |
| `app/tools.py` | Database-backed tools the agent and API call; officer decision; deficiency notice |
| `app/agent.py` | Agent loop, explanation checks (`unverified_numbers`, `decision_words`), deterministic fallback |
| `app/resolutions.py` | Open flags that need an officer resolution before approval; the citizen notice keys (`citizen_notices`) |
| `app/deficiency.py` | "Documents needed" notice from the problems a citizen can fix; fixed templates |
| `app/citizen.py` | Public tracking view, HMAC codes, rate limiter |
| `app/self_check.py` | Dry-run self-check (nothing stored) |
| `app/sahayak.py`, `app/providers/gemini_sahayak.py` | Sahayak helper: knowledge base, retrieval, guard, fallback, limits |
| `app/sla.py`, `app/analytics.py` | Days open, overdue, the needs_info pause; analytics counts |
| `app/simulator.py` | Read-only policy what-if over the synthetic set |
| `app/evaluation.py` | Evaluation harness (offline replay and live image runs) |
| `app/providers/` | `gemini.py` (shared client: retries, pacing, key scrubbing), `gemini_agent.py`, `gemini_sahayak.py`, `tesseract.py`, `fake.py` (offline fakes) |
| `rules/land_acquisition.yaml`, `rules/disaster_relief.yaml` | The two schemes |
| `rules/sahayak_knowledge.yaml` | Sahayak's knowledge base (not a scheme) |
| `data/synthetic/` | 21 land and 15 relief cases with hand-derived `expected.json`; builders; rendered document images |
| `scripts/` | `seed_demo.py`, `eval_images.py` (live), `eval_day2.py` (offline replay), `render_images.py` |
| `web/src/` | React + Vite: `shells/` (landing, citizen, officer), `pages/`, `lib/` (logic + node tests), `i18n/` |
| `web/src/lib/auditChain.js` | Wording for the *Verify log integrity* result (the server does the check) |
| `web/e2e/layout.test.mjs` | Browser checks (playwright-core + the installed Chrome) |
| `tests/` | pytest, no network (a conftest guard blocks sockets); `test_repo_hygiene.py` blocks keys and `.env` |
| `docs/` | `DEMO_SCRIPT.md`, `EVAL_RESULTS.md`, `KNOWN_LIMITATIONS.md`, this file; `screenshots/` (synthetic demo screenshots) |

### Scheme YAML format (see the comments at the top of each file)

- `scheme`, `version`, `source` (law or notification), `confidence_threshold` (0.85), `sla_days`, `labels`
  (title, amounts, total).
- `required_documents`: each `id` with typed `fields` (`text | number | percent | date | unit | one_of`), optional
  `derived` (e.g. `area_sqm`), `plausible` ranges, `validity` (expiry, or maximum age), `may_be_blank`.
- `verification_checks`: field comparisons (`exact`, `fuzzy_0.9`) or built-ins (`duplicate_claim`, `recorded_entry`),
  `ignore_statuses` (duplicate checks: case statuses that do not count; default rejected and withdrawn), with severity, `basis`, `messages`, `approval_needs_resolution`, `total_label`, `citizen_notice`, `citizen_remedy`.
- `eligibility_rules`: `id`, `clause`, `when` (safe expression; can read `params.<name>`), `depends_on`, `fail_reason`.
- `compensation`: `inputs` (from documents or officer-entered case inputs, ranges, defaults), `parameters`, `components`
  (formulas).
- `self_check` (optional): questions and the rules they answer. `terms`: a human label for every identifier on screen.
- Branch `mutation` adds: `on_false: needs_review` on a rule (a false `when` routes to review; default `fail`);
  `recommendation_labels` (scheme words for eligible / not_eligible / needs_review; never decision words);
  `timelines` (period as written, optional days, working_days, source_type, source, verify + verify_note, at most one
  `drives_sla` equal to `sla_days`). With no `compensation`, `labels` needs only `title`, the pipeline has no
  compensation step, and the case page, award letter, citizen amounts and analytics liability leave the scheme out.
- Uncertain legal values are marked `# VERIFY: <what>` in the YAML.

### The two schemes

- **Land acquisition (primary):** compensation under the RFCTLARR Act 2013 with Goa specifics: land value (area ×
  market rate × rural multiplier), assets, solatium (100%), 12% a year additional amount from SIA notification to the
  earlier of award and possession. Documents: application, ownership record (Form I & XIV, including the tenant and
  mundkar / other-rights entries), identity proof, survey sheet, mutation record. SLA 60 days (VERIFY). No self-check.
- **Disaster relief (second, YAML only):** housing-damage relief from the MHA SDRF/NDRF norms 2022-26 (labelled "to be
  confirmed" for Goa): full / partial damage by house type, hut, clothing and utensils, plain or hilly area. Documents:
  application, identity proof, residence proof, damage assessment. SLA 15 days (VERIFY). Has a self-check.
- **Revenue mutation (branch `mutation`, merged into main 20 Nov, YAML only):** recommends "Ready for notice" / "Needs review" /
  "Not ready for notice" and calculates no amount. Checks: applicant name, transferor against the Form I owner, survey
  number across application / deed / Form I, co-owner notice (`on_false: needs_review`), tenant or mundkar entry,
  recorded dispute ("refer; this system does not decide title"), another open mutation on the survey number.
  Documents: application, deed or order, Form I & XIV, identity proof. SLA 30 days (VERIFY, the one timeline that
  drives the clock). Source-cited timelines on the case page. Has a self-check (co-owner question). 5 cases RM-01..05.

## 3. Features built

- **Shells:** a landing page; a citizen shell (home, check before you apply, track; en / hi / mr / kok; light theme
  default); an officer shell (queue, case, intake, analytics, simulator, audit, award letter).
- **Roles and sign-in:** demo sign-in issues HMAC-signed, 8-hour tokens for clerk, officer and admin; roles are checked on
  the server per route; plain `X-Role` headers only with `GOVFLOW_DEMO_INSECURE=1`. Production would use SSO.
- **Tracking:** reference plus a 6-digit HMAC code; the same 404 for any wrong pair; rate-limited per client (10 tries
  per 15 minutes) and per reference; 503 until a citizen secret is set.
- **Self-check:** dry run of the scheme's own rules on the citizen's answers; nothing stored; "a guide, not a decision".
- **Sahayak:** text-only, English-only helper on the self-check page. Keyword retrieval (top 3) over
  `rules/sahayak_knowledge.yaml` (7 sourced entries); Gemini may phrase the answer from those entries only (no tools,
  temperature 0.1); a guard rejects numbers, rupee mentions, decision words, websites and office names not in the
  entries and then returns the entry's own text (`used_fallback`); its own rate limit (20 per client per 10 minutes)
  and a daily cap of 200 provider calls; the message is never stored (the audit row keeps its length and entry ids).
  **No voice anywhere.**
- **Tenant / mundkar rule (land):** any non-empty tenant or mundkar / other-rights entry raises a high-severity flag;
  the total is labelled "Total for the holding, not the owner's share"; approval needs the officer's resolution;
  the citizen sees only "additional verification of rights is in progress".
- **Duplicate survey number (land):** `duplicate_survey_claim`, YAML only, on the `duplicate_claim` built-in with
  `ignore_statuses: [withdrawn]`: any other open or decided case naming the same survey number, whatever the areas
  (co-owners too). High severity, needs review, never rejects; feeds `no_competing_claim`. The officer sees the other
  case's reference; the citizen sees only "Additional verification is in progress."
- **Hash-chained audit log:** see step 8 of the flow; what it cannot detect is in KNOWN_LIMITATIONS.
- **Deficiency notice:** officer "Request documents" (cases in review): built from the problems a citizen can fix, fixed
  templates in four languages, preview then send; stored, audited, case to "More information needed"; shown and
  printable on the tracking page.
- **SLA:** days open and overdue flags per scheme; the clock **pauses** while a case waits for the citizen
  (needs_info), from the audit log's own timestamps; the queue marks those cases "clock paused" and counts them.
- **Award letter:** print-friendly summary for approved cases (browser "Save as PDF").
- **Analytics:** counts by status and scheme, overdue, stuck cases, average processing time, one shared chart scale.
- **Simulator:** officer / admin what-if of one parameter over the synthetic set; read-only, never edits YAML.
- **Languages:** citizen pages in English, Hindi, Marathi and Konkani. **Hindi, Marathi and Konkani are unreviewed
  drafts** (each file and the page say so).
- **Cross-check signal** (Tesseract as a second reader), **injection defences** (untrusted-data prompts, plausible
  ranges, officer confirmation of amount fields, decision-word and invented-number warnings), **upload limits**
  (14 MB request cap, file signature must match the extension).
- **Accessibility:** loading / error / empty states with Retry, `role=status` and `aria-live`, 24 px touch targets,
  visible keyboard focus, no sideways scroll at 390 px.

## 4. How it was built

### Working style

- **Tools first, agent last;** small vertical slices; one scheme fully working before the next.
- **Test-first** where possible; every tool tested against the fixed synthetic set without the LLM.
- **Hand-derived expected values** in `data/synthetic/*/expected.json` (worked calculations in the builders and tests).
  **Never change an expected outcome to make a test pass:** fix the code or ask. Extensions so far, each reported to
  the user: `tenant_or_mundkar_claim: pass` added to LA-01..17; `duplicate_survey_claim` added to all 21 land cases
  (needs_review for LA-12, LA-13, LA-14, LA-15) and to LA-12 / LA-13 in `messy_labels.json`. The only changed outcome:
  co-owners LA-14 and LA-15 moved from eligible to needs_review, the user's decision on 18 Nov.
- **Sabotage checks:** after each defence, break it on purpose (one exact substitution, always restored) and confirm a
  test fails; report the counts.
- **One commit per item**, with tests, sabotage results and choices in the message; CLAUDE.md "Current state" updated
  in the same commit.
- **Batched test runs** because memory is low.
- **Uncertain law is marked `# VERIFY`**, never guessed; the user is told.

### Major decisions and why

- **Deterministic tools decide, the LLM explains:** auditability and the hackathon brief's governance focus.
- **YAML schemes:** a second scheme (disaster relief) was added as config only, which proves the platform claim.
- **Officer confirmation of amount-driving fields:** a document must not vouch for itself (injection defence).
- **No built-in secrets:** a secret in the source would make every tracking code predictable; the seed writes random
  secrets to `.env` on first run.
- **Model pinned to `gemini-3.5-flash-lite`:** on 16 Nov the other models were unreachable (503, timeouts, 404); it is
  the only model evaluated live.
- **Dates are day-first and parsed in code:** in run 1 the model swapped an ambiguous date at confidence 1.0.
- **At or below 0.85 goes to review**, and **names with digits or symbols fail the match:** both fixed real misses from
  the live evaluation.
- **Cross-check kept, but known to over-flag** on hard images (see section 5).
- **Status `needs_info` reused** for the deficiency notice; the SLA clock pauses there.
- **Sahayak answers only from a sourced knowledge base** with a guard and a verbatim fallback, English only, no voice.

## 5. Current state (at `9b648a6`, 18 Nov 2026)

- **Tests, all green (20 Nov, branch `simplify`):** Python **1,304** passed (three batches: `[a-f]` 602 +
  `[g-r]` 314 + `[s-z]` 388); frontend **106** logic + **92** browser (1280 px and 390 px); build clean. On main
  (before `simplify`): 99 logic + 81 browser. Demo seed (`--reset`): 47 cases (21 land, 15 relief, 6 welfare, 5 mutation).
- **Branch `simplify` (20 Nov, not merged), UI only:** a juror or officer should get each page in five seconds.
  Measured in `docs/USABILITY_BASELINE.md`: scroll over the five tasks 5,669 → 1,962 px (approving a clean case
  4,740 → 1,398), clicks 16 → 17 (the document check is one click away); default case page 74–81% shorter.
  Secondary sections are collapsed native `<details>` holding the original content; the decision panel is a sticky
  bottom bar; analytics opens on four API numbers, one chart and an attention list; the queue has five columns and
  one-click views; citizen pages have progress lines and *Why?* for each amount's basis.
- **Fallback explanation masks ID numbers (20 Nov):** the no-LLM summary now shows "XXXX XXXX 1234" like the
  document view; a test runs the fallback for every synthetic case of every scheme. The SW-01 snapshot was retaken
  at the merge (it pinned the replaced draft welfare scheme) and then updated for this masking only.
- **UI polish (19 Nov):** branch `ui-polish` (tokens, case summary strip, analytics tiles, sticky queue header,
  44 px phone targets; before/after screenshots in `docs/screenshots/before|after/`) merged into main locally.
- **Branch `weak-spots` (19 Nov, merged into main 20 Nov):** `73e7e51` social welfare rebuilt from the published 2002 DSSS
  notification No. 4247 (income limit Rs 24,000; Rs 2,000 senior and disability, Rs 3,500 at 90 to 100%, Rs 2,500
  widows and single women below 60; 80+ and minor-child supplements removed; six cases re-derived by hand; single
  women 18+ vs unmarried above 50 left as a VERIFY conflict) · `1d4995e` `scripts/benchmark_processing.py` and
  `docs/BENCHMARK.md` (this run: fallback provider, the Gemini preflight timed out) · `0934e79`
  `scripts/export_translations.py` and `docs/translation_review.csv` for native-speaker review.
- **Final freeze exception (19 Nov):** item 1 `7d49203` social welfare source-conflict note (Social Welfare Department
  page: 15-year residence, Rs 24,000 p.a. income limit, 2002 notification; other sources Rs 1.5 lakh and Rs 3 lakh;
  Rs 2,000 or Rs 2,500 a month); no value changed, and a test pins every value. Item 2, the revenue mutation scheme,
  was **deferred** after a feasibility check found it needs engine code, not just YAML: `ed8e071`
  `docs/FUTURE_MUTATION_SCHEME.md` holds the findings, the proposed change (a) to (d) and the sourced timelines.
  Nothing of it is built.
- **UI polish round (19 Nov), UI only, no logic, rule, API or data change:**
  `387ed44` placeholder clauses (`<clause ref>`, `<DSSS clause: ...>`, every clause in the YAML is still VERIFY) show
  as a dash in the rule table and award letter and are stripped from the explanation on display; the stored explanation
  (audit log) is unchanged · `244319f` case summary strip: status, stored total, flags by severity, SLA clock (read from
  the case's row in the existing `GET /cases`) · `1fdaa9e` every rupee amount on the case page in Indian grouping,
  including the stored explanation's `Rs 3,816,000.00` (regrouped on display, never recomputed) · `7a31263` analytics
  bar labels wrap only between words, 340 px minimum card · `49b4908` scheme-by-stage table fits at 1280 px, Withdrawn
  included · `a782402` flags as three small tables · `313140e` short overdue tile, *How this is counted* note ·
  `c08783a` landing one-line description · `7e7a9b7` *Demo with synthetic data* note · `79619c8` staff card lists each
  role's pages as `nav.js` grants them · `eed2764` queue opens on all cases · `c6190b5` screenshots 01, 05, 06, 10
  retaken on a fresh `--reset` seed.
- **Not fixed on screen, by design:** the formula notes (`with land_value=1800000`) keep their raw inputs: they are the
  cited formula, and a bare number there may be an area or a rate, not rupees.
- **Commits:** 86 on `main` at `9b648a6`, then this docs sync; pushed to `origin/main`.
- **What changed since the first handoff** (after `d73da8c`):
  `2981b68` citizen document pre-check · `8d0b587` its docs · `7daaaf5` multi-field injection tests for it ·
  `12ca125` `used_fallback` is false when Gemini's reading passes the guard · `b99bcf7` synthetic screenshots in
  `docs/screenshots/` · `5443f5c` 390 px status pill wraps, sticky queue Case column, single-line analytics ticks ·
  `5803dd0` the sticky column scoped to the queue table (the audit Time column scrolls) · `c309048` hash-chained audit
  log, `GET /admin/audit/verify`, *Verify log integrity* · `9b648a6` the `duplicate_survey_claim` flag
  (LA-14 / LA-15 now end in review).
- **Last checks:** a full verification click-through on a throwaway database (17 Nov) found no critical or high
  issues; its medium and low findings were fixed in the bug-fix round below. A live Sahayak run (8 questions) stayed
  within its entries, gave no amount for "how much will I get", and refused the injection prompt.
- **Bug-fix round A to H (17 Nov): all committed and pushed.**
  A `2285cfc` case page never shows the previous case; approval bound to its case ·
  B `b403816` visible focus on radios, checkboxes, text areas ·
  C `0c41cd2` Sahayak per-entry "verify with", plain source names, one cited source ·
  D `64e3bda` queue "clock paused" badge and count ·
  E `74d5356` citizen dates "17 Nov 2026" ·
  F `888efed` a 422 never echoes input ·
  G `5b0da20` status pill sizes to its text ·
  H `d73da8c` docs.
- **Earlier audit:** a 20-item UX and security review (16 Nov) was fixed in the commits marked "(audit N)" in
  `git log` (signed tokens, no built-in citizen secret, injection hardening, loading / error states, touch targets,
  request cap and file signatures, and so on).
- **Evaluation summary** (`docs/EVAL_RESULTS.md`, two live runs on 17 Nov, `gemini-3.5-flash-lite` only, **synthetic
  documents only**): after the fix round, Gemini read disaster relief 35/35 fields correctly on clean, degraded and hard
  images, and land 25/27, 25/27, 21/27, with 1, 0, 2 wrong values passing the confidence gate, each caught later by a
  deterministic check; 36/36 dates. Caveats: tiny n (7 documents per scheme), generated images (no real handwriting
  or real Goa forms), one model, results vary between runs, model confidence does not separate right from wrong, and
  the cross-check over-flags on hard images (21 of 23 firings were on correct readings).

## 6. VERIFY items and open items

### Still marked VERIFY (details in CLAUDE.md and the YAML)

- **Land:** notification references; 60-day SLA; record-of-rights age 180 days; mutation extract age 365 days; **Goa's
  rural multiplier (default 1.0 is a placeholder)**; estimating to the reference date before the award; solatium and
  12% section numbers; whether the 12% base includes the multiplier.
- **`app/compensation.py`:** actual/365 day count for the 12% amount.
- **Relief:** the **SDRF/NDRF 2022-26 schedule in force in Goa**; 15-day SLA; residence proof age; claim window; which
  areas are hilly; relying on the assessment's "notified area"; the **75% full-damage threshold (placeholder)**; the 15%
  minimum for kutcha houses, huts, clothing and utensils.
- **Tenant / mundkar:** which Form I & XIV columns hold the entries; which resolution document applies; the empty-value
  list. Basis cited: the Goa, Daman and Diu Agricultural Tenancy Act, 1964 and the Goa, Daman and Diu Mundkars
  (Protection from Eviction) Act, 1975.
- **Gemini:** model pinned to `gemini-3.5-flash-lite`; the agent's wire format and default temperature were verified
  live **on that model only**; any other `GEMINI_MODEL` is VERIFY; Sahayak's temperature (0.1) was never run live.
- **Duplicate survey number:** the source for how a second claim on a survey number already under, or past, an
  award must be handled.
- **Every rule's `<clause ref>`** in both YAML files.
- **Plausibility ranges are placeholders**, not legal values.
- **Sahayak entries:** four marked `verify: true` (land record, name spelling, two relief self-check topics); six give
  `VERIFY` as their source URL.

### Open items

- Hindi, Marathi and Konkani need **native-speaker review**; self-check question prompts stay English on those pages
  (translated prompts planned). Voice assistant: planned. Multilingual helper: planned.
- Cross-check over-flags on hard images: decide whether to keep it on for hard documents.
- Deficiency notices name fields in English (YAML labels) even in the other languages.
- A case with no computable amount (DR-09, DR-15) stays "verified" and flagged; decide whether it should reach the officer.
- Production hardening: SSO, rate limits behind a proxy, maker-checker on decisions (KNOWN_LIMITATIONS).

## 7. How to run and test (Windows cmd)

Run from the repo root. Paths use backslashes in cmd.

### Set up (once)

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd web && npm install && cd ..
```

### Environment (names only; values never in the repo)

`.env` in the repo root is **gitignored**: a new clone has none, and the user must recreate it. A real environment
variable always wins over `.env`.

| Variable | Needed for |
|---|---|
| `GEMINI_API_KEY` | Live extraction, agent and Sahayak (optional: without it every LLM step falls back and says so) |
| `GEMINI_MODEL` | Optional; default `gemini-3.5-flash-lite` (the only model verified) |
| `GOVFLOW_CITIZEN_SECRET` | Citizen tracking codes (the seed writes a random one on first run) |
| `GOVFLOW_AUTH_SECRET` | Signs the staff sign-in tokens (the seed writes a random one on first run) |
| `GOVFLOW_DEMO_INSECURE` | Optional, `1` accepts plain `X-Role` headers; never in a shared deployment |
| `GEMINI_PACE_SECONDS`, `TESSERACT_CMD` | Optional: pause between Gemini calls; Tesseract path if not on PATH |

A line in `.env` looks like `GEMINI_API_KEY=<your key>`. Ask the user to paste the key themselves.

### Run the demo

```
.venv\Scripts\python -m scripts.seed_demo --reset
.venv\Scripts\python -m uvicorn app.main:app
cd web && npm run dev
```

The seed prints the demo tracking codes: don't copy them into files or messages. The API is on port 8000; the
dashboard on http://127.0.0.1:5173. The API uses `govflow.db` in the folder it is started from. Always seed with
`--reset` before a demo: flags are stored when a case is verified, so an older database lacks `duplicate_survey_claim`.
Starting the API on an older database adds the hash columns and chains its existing audit rows once.

### Test

```
.venv\Scripts\python -m pytest -q
cd web && npm test
cd web && npm run test:layout
cd web && npm run test:all
```

With little memory, run Python in batches. cmd does not expand wildcards for Python, so let `for` expand them, one file
at a time (slower, but small):

```
for %f in (tests\test_a*.py tests\test_b*.py tests\test_c*.py tests\test_d*.py tests\test_e*.py tests\test_f*.py) do @.venv\Scripts\python -m pytest -q %f
```

Repeat with `g` to `r`, then `s` to `z`. (In Git Bash the batches were `tests/test_[a-f]*.py`, `[g-r]`, `[s-z]`.)
Count everything collected: `.venv\Scripts\python -m pytest --co -q -o addopts=""`.
Browser tests need Google Chrome; they start their own Vite server and mock the API.

### Evaluation and preflight

- Offline replay (no network): `.venv\Scripts\python -m scripts.eval_day2`.
- Live image evaluation (Gemini + Tesseract; writes `eval_results\`, gitignored, never committed):
  `.venv\Scripts\python -m scripts.eval_images`. **Run the preflight first.**
- **Preflight** (there is no script in the repo; it was run as a one-off): one `generateContent` call, no retries,
  with a 1x1 red PNG, through `GeminiClient(pace_seconds=0)._call_once(...)` from `app/providers/gemini.py`, after
  `load_env_file` on `.env`. Print only the model, pass or fail, the time and the reply ("Red"), never the key.

## 8. Third approved exception (built in `2981b68`): citizen document pre-check


- **Endpoint:** `POST /public/precheck`, no sign-in, stateless. Scheme id and document type validated against the
  YAML; one file, with the same 14 MB cap and signature check as the officer upload.
- **Processing in memory only:** OCR, Gemini extraction when available, the existing validation, plausibility, document
  age and cross-check.
- **Store nothing:** no file, text, values or file name on disk, in the database or in logs. One audit row only:
  document type, result category, timing.
- **Response in plain words, no snake_case:** readable yes / no / partly; per field "found" or "could not read"; values
  shown only for name and area, labelled "what we read", never identifier values; issues in plain words; next steps
  from fixed templates; "A quick check, not an application. An officer reviews every document."
- **Must NOT:** compute amounts; say eligible, ineligible, approved or accepted; compare with other documents or cases;
  look up records.
- **Guard:** reject decision words and rupee amounts; on guard failure or provider error, fall back to OCR-only feedback
  (`used_fallback: true`). A prompt-injection document must still get normal feedback.
- **Limits:** its own strict rate limiter and a daily cap on provider calls.
- **Frontend:** on the self-check page; loading, error and empty states; `aria-live`; 24 px tap targets; 390 px layout;
  an English-UI note; a clear "nothing is saved" line.
- **Tests:** no storage (disk, database, logs), injection, caps, guard, role and abuse limits. **Sabotage-check** the
  guard, the no-store rule and the rate limit.
- **Cut-off:** if it is not green and committed by **end of 19 Nov 2026**, mark it "planned" in KNOWN_LIMITATIONS and
  drop it.

### Then

Freeze: bug fixes only; a final click-through on a throwaway database; screenshots; the deck.

## 9. Submission package status

Being written by the user's Claude chat advisor (not in this repo):

- **Deck (PDF, required).** Architecture diagram. Up to **5 prototype screenshots**. Optional demo video and URL.
- **Updated form answers:** prototype "Yes"; features built; measured numbers; honest limits.

Expected from the repo:

- `docs/EVAL_RESULTS.md` (measured numbers with caveats), `docs/DEMO_SCRIPT.md` (the 3-minute walkthrough),
  `docs/KNOWN_LIMITATIONS.md` (honest limits).
- Screenshots: 18 synthetic screenshots are in the repo under `docs/screenshots/` (13 views at 1280 px and 5 at 390 px),
  including the refreshed `10-analytics.png` and new `11-case-social-welfare-SW-01.png`, `12-audit-chain-verified.png`,
  and `13-case-duplicate-claim-LA-12.png` captured on a fresh 42-case `--reset` seed. `01`, `05`, `06` and `10` were
  retaken on 19 Nov after the UI polish round (fresh `--reset` seed). Re-take them after any UI change.

## 10. Guidance for the new session

### Reporting results

For each item: the commit hash; tests (counts, per batch); sabotage results (what was broken and how many tests
failed); anything chosen differently from the request and why; every VERIFY item touched.

### Never

- Give the agent a decision tool (approve, reject, send back).
- Do arithmetic in the frontend: amounts come from the API.
- Invent legal claims, section numbers, offices, fees or deadlines: mark `# VERIFY` and say so.
- Weaken, skip or delete a test, or change an expected outcome, to make something pass.
- Print or commit keys, secrets, `.env` contents or tracking codes.
- Commit real citizen data, or `eval_results/`, `uploads/` or `.env`.

### Stop and report

- If a provider fails (preflight or live run): stop, report the error, don't loop.
- If an expected outcome seems wrong, or a change needs more than the request allows: ask first.
- If memory runs out mid-run, report what finished and what did not.
