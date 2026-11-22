# GovFlow: known limitations

GovFlow is a hackathon prototype. This list is meant to be read before anyone treats a number,
a screen or a test result as more than it is.

## Security and access
- **No real authentication. Production needs the government single sign-on (SSO).** The demo sign-in
  (`POST /auth/demo-login`) has no password: it issues an HMAC-signed token (role, user, 8-hour expiry) with
  `GOVFLOW_AUTH_SECRET`. The token stops a client from editing its role and makes sessions expire, but anyone
  who can reach the sign-in can still choose to be an officer. Do not expose the demo on a public network.
  Plain `X-Role` / `X-User` headers are refused unless `GOVFLOW_DEMO_INSECURE=1` (scripts only).
- **Citizen verification codes are a demo mechanism.** A code is an HMAC of the case reference with
  `GOVFLOW_CITIZEN_SECRET`. There is no built-in secret: without one, status lookups answer 503 (the demo seed
  writes a random one to `.env`). Real codes should be issued to the applicant at intake and stored hashed.
- **Rate limiting is in memory** (production hardening still open):
  - Limits reset when the server restarts and are not shared between server processes.
  - The client address is the direct peer. Behind a reverse proxy every citizen shares the proxy's address,
    so the per-address limit becomes one limit for everyone; configure trusted proxy headers in production.
  - Five wrong codes for one reference block that reference for 15 minutes, so anyone can lock out the
    genuine applicant for that time (a trade-off against guessing; slowing down would be gentler).
  - Self-check and tracking share the per-address limit, so ten self-checks also pause tracking.
  - Records older than the window are dropped once per window, so memory does not grow without bound.
- **No separation of duties** (production hardening still open). One officer can create a case, upload its
  documents, run the agent and approve it. A real deployment should refuse a decision from the user who
  created the case or uploaded its documents (maker-checker), using the audit log.
- **Uploaded documents are stored unencrypted** on local disk under `uploads/` (gitignored). Requests over
  14 MB are refused before they are read, files over 10 MB are refused, and a file's first bytes must match its
  extension (PNG, JPEG, PDF; .txt must be UTF-8 text). There is no malware scanning and no check inside PDFs.
- **The audit log is append-only only inside SQLite** (triggers reject UPDATE and DELETE). Since 18 Nov every row is
  hash-chained, so an edited, deleted or moved row is now detectable (`GET /admin/audit/verify`, the Audit page's
  *Verify log integrity*). File-level tampering is still possible: someone who can write the database file can drop
  the triggers and recompute the whole chain, or cut rows off the end (see *Audit hash chain* below). There are no
  backups and no external log sink.

## Legal and policy parameters (all marked `# VERIFY`)
None of these may be used for a real decision until checked against official sources.
- **Land acquisition:** confirmed from research: solatium 100% of (market value × multiplier + assets);
  the 12% additional amount from the SIA notification date to the earlier of award and possession; the
  multiplier as a per-case input (urban 1.00, rural 1.00 to 2.00 as notified; outside that range a case
  goes to review). Still VERIFY: notification references, section numbers and every rule's `<clause ref>`;
  the multiplier default 1.0 (Goa's notified factor is unconfirmed); whether the 12% base includes the
  multiplier (one High Court held that it does; the formula currently includes it); estimating to the
  reference date while the award or possession date is not yet recorded; document ages (180 and 365 days);
  the actual/365 day count; the 60-day SLA.
- **Disaster relief:** amounts follow the MHA SDRF/NDRF norms 2022-26 (fully damaged house ₹1,20,000 plain
  or ₹1,30,000 hilly; partially damaged pucca ₹6,500 at 15% or more, kutcha ₹4,000; hut ₹8,000;
  clothing ₹2,500 and utensils ₹2,500), labelled "current schedule to be confirmed". Still VERIFY: the
  schedule in force in Goa and every `<clause ref>`; the 75% full-damage threshold (the norms do not give
  it as a percentage); applying the 15% minimum to kutcha houses, huts and the clothing and utensils relief;
  the condition for clothing and utensils (the norms tie it to houses washed away, fully damaged or severely
  inundated); which Goa areas count as hilly; document ages (365 and 90 days); the 15-day SLA.
- **Plausibility ranges** are placeholders, not legal values: land area 10 to 500,000 sq m per holding
  (10 to 5,000,000 per survey number) and market value ₹100 to ₹1,00,000 per sq m.
- **Social welfare (`rules/social_welfare.yaml`, `2002.10-published`):** rebuilt on 2026-11-19 from the Dayanand
  Social Security Scheme notification No. 50/354/02-03/HC/part-I/4247 dated 02/10/2002, as published on the
  Directorate of Social Welfare page (https://socialwelfare.goa.gov.in/?p=2518). Still YAML only. Sourced from it:
  resident of Goa by birth or 15 years of domicile; income limit ₹24,000 a year; senior citizen 60 at application,
  ₹2,000 a month; adult with a listed disability ₹2,000 a month, ₹3,500 at 90 to 100%; widows and single women below
  60 ₹2,500 a month (amounts shown per year, × 12). 2002 notification as published on the department site; later
  amendments not confirmed. A state commission has recommended raising the income limit, which is a recommendation,
  not law. The 80+ and minor-child supplements (from other sources) were removed. Still VERIFY: every clause number;
  30-day SLA; 365-day residence proof and income certificate validity; "adult" read as 18+; the 40% minimum
  disability (not on the page; RPwD Act benchmark); a widow or single woman aged 60 or over (the page states the
  amount only below 60, so the rule does not pass her in that category: she would apply as a senior citizen);
  **conflict**: single women 18 and above (category list) versus unmarried women above 50 (objectives text); 18 is
  used.
- **Notified area:** disaster relief relies on the damage assessment's own "notified area" certification;
  there is no list of notified villages per disaster event.
- **Tenant / mundkar entries** (land): the rule cites the Goa, Daman and Diu Agricultural Tenancy Act, 1964 and
  the Goa, Daman and Diu Mundkars (Protection from Eviction) Act, 1975 as its basis, but which Form I & XIV
  column(s) hold the entries, and which resolution document applies in an acquisition, are unconfirmed (VERIFY).
  The officer records the reference they relied on; no specific Mamlatdar order is assumed. An entry the reader
  does not return at all is not checked (it cannot be told apart from a blank column); an entry read at or below
  the threshold goes to review. The empty-value list (Nil, NA, none, a dash and Devanagari forms) may be
  incomplete. The rule only flags and labels the total as the holding's: it does not compute any owner's share.

## Language
- **Hindi, Marathi and Konkani were reviewed line by line by native speakers** (22 Nov 2026) and no wording was
  changed. Departments should still confirm official terms before real use.
- The citizen pages (home, self-check, tracking) are translated; the officer dashboard and the rule simulator
  are English only.
- **Translated self-check questions: planned.** On Hindi, Marathi and Konkani pages the self-check's question
  prompts and its guide label stay in English, because they come from the scheme YAML, which is English. The
  English draft-translation note under the translated one is deliberate. Sahayak is English only (see below).
- Officer comments (for example, the reason a case was sent back) are not shown to citizens, because they
  are free text in English and may contain internal notes.

## AI and extraction
- **Live results exist for one small model only** (`docs/EVAL_RESULTS.md`): `gemini-3.5-flash-lite`, now the
  default. A lighter model than first planned: `gemini-3.8-flash` could not be reached (503, then timeouts) and has
  never run live. Any model set through `GEMINI_MODEL` other than the default is unverified (VERIFY).
- **Extraction accuracy is measured on a tiny synthetic set only** (17 Nov 2026): 7 land documents (27 fields)
  and 7 relief documents (35 fields), each as clean, degraded and "hard" generated images (stamp, one
  handwriting-style field, simulated phone photo). Gemini: relief 35/35 on all three; land 24/27, 25/27, 21/27,
  with 2 to 3 wrong values per set passing the confidence gate. No real handwriting, Devanagari or real Goa
  documents; one run, and two reads of the same image already differed on 2 fields.
- **Model confidence is not a reliable signal.** In run 1 Gemini read an ambiguous "01/10/2026" month-first at
  confidence 1.0; dates are now copied as printed and parsed day first in code. After the fix round the remaining
  wrong readings were still at 0.90 to 0.95. A reading at or below 0.85 now goes to review, but the officer's
  confirmation of amount-driving fields is the backstop, not the threshold.
- **Dates only in DD/MM/YYYY (or ISO).** A written month ("1 Oct 2026") or a two-digit year is rejected and goes to
  review; real documents in other formats will be over-flagged rather than misread.
- **Name match rejects symbols:** a name containing digits or symbols fails outright. A name printed with an
  unusual character (for example "&") would fail too and need the officer.
- The Tesseract baseline's label parser knows the synthetic document layouts, so its accuracy is generous.
- **Cross-check (readers disagree).** When Tesseract is installed it reads each document again; a field it reads
  differently from Gemini (after normalising case, spacing, digit grouping, dates and unit synonyms) goes to
  review. It only speaks when Tesseract finds the field: its label parser knows the synthetic layouts, so on real
  documents it will often find nothing and stay silent. Punctuation at either end of a reading is now ignored.
  It still over-flags on hard images: in run 2 it fired 23 times, 21 on correct readings, and caught 2 wrong
  readings that other checks also caught. The false alarms are Tesseract misreads, not something normalisation
  can remove.
- Gemini's confidence scores are self-reported, not calibrated; the 0.85 threshold depends on them. So a
  document cannot vouch for itself where it matters: the fields that drive an amount (land area and unit;
  relief damage %, house type, area type) must be confirmed by the officer at their current value before
  approval, whatever the confidence, and values outside the YAML's plausible range go to review.
- **Prompt injection is reduced, not eliminated.** The prompts call document text and tool results untrusted
  data, the agent has no decision tool, and explanations that quote an unknown amount or say approved /
  rejected / sanctioned are flagged. Instruction-like text in other fields (a name, a remark) is not detected
  as such; it reaches the officer as data. LA-17 and DR-15 are the injected test cases.

## Data and testing
- **All data is synthetic.** 21 land-acquisition, 15 disaster-relief, and 6 social-welfare cases (42 total; two with injected text),
  hand-derived expected outcomes. Document images: 7 land and 7 relief documents, each rendered three ways
  from a computer font: clean, degraded (tilt, blur, faded ink, speckle) and hard (one field in a
  handwriting-style font, a red stamp over the values, a phone-photo look with perspective, a shadow and JPEG
  artefacts). All generated, all marked SYNTHETIC; not real scans, real handwriting or real Goa forms.
- A case whose amount cannot be computed at all (for example DR-09, damage report missing) is flagged but
  stays *verified*: it never reaches *awaiting officer decision*, so it is found through the queue filters.
- The demo seed spreads intake dates over recent weeks by a fixed pattern so SLA flags appear; those dates
  are synthetic.
- **Browser checks are scripted, not exhaustive.** `npm run test:layout` drives Chrome against the real
  pages with the API mocked: layout at 390 and 1280 px, the shared analytics scale, loading / error / empty
  states, tracking input checks and 24 px touch targets. There is no automated accessibility audit (axe),
  and keyboard and screen-reader use have not been tested by hand.
- The rule simulator runs over the synthetic set only, not over live cases.

## Product scope
- **Voice assistant: planned**, not built. There is no voice input or spoken output anywhere in the product
  (Sahayak is text only).
- **Multilingual helper: planned.** Sahayak answers in English only, whatever the page language, and says so.
- **Revenue mutation (Form I and XIV): built on branch `mutation`, merged into main 20 Nov 2026.** Engine changes (a) to
  (d) from `docs/FUTURE_MUTATION_SCHEME.md`, then `rules/revenue_mutation.yaml` and 5 synthetic cases. Limits:
  - Every source is VERIFY except rule 11(2) of the 1969 Rules (see the YAML `timelines` and `# VERIFY` comments);
    the 30-day `sla_days` rests on a press report of a ministerial statement. Clauses are `<GLRC clause: ...>`
    placeholders.
  - The transferor check is a naming workaround (deed and Form I both use `owner_name`), not a cross-field comparison.
  - The co-owner notice compares counts (holders on Form I & XIV against holders named on the deed), not names.
  - No Form X notice or mutation order screen; no case statuses for notice issued or the objection period. Working
    days are shown, never counted. The 90-day application window (commercial guide only) is shown, never checked.
  - The deterministic summary (agent explanation without the LLM) and the case blockers still say the engine's own
    words ("Eligibility recommendation: eligible / needs_review"), not "Ready for notice": `app/agent.py` could change
    for item (c) only. The case page's eligibility card uses the scheme's words.
  - Self-check prompts are English (as for every scheme); only `documents.deed` was added to hi / mr / kok (since
    reviewed by native speakers, no changes).
- **Sahayak** (the self-check page's helper) answers only from `rules/sahayak_knowledge.yaml`: seven entries,
  keyword retrieval (no synonyms or spelling tolerance, so an unusual wording may find nothing and get the fixed
  "I can't help with that here" reply). Entries marked VERIFY carry a "Verify with …" tag naming who to check with (the Collectorate, the issuing
  office or the relief office); four
  are marked (which land record, name spelling, and the two relief self-check topics) and six give VERIFY as
  their source URL (all but the land record entry). The Gemini wording path is tested offline only (never exercised live); its temperature is a
  VERIFY. The guard is pattern-based: it rejects numbers, rupee mentions, decision words, websites and office
  names not in the retrieved entries, so a harmful sentence without any of those could pass; anything it rejects
  falls back to the entry text. Rate limit (20 per client per ten minutes) and daily provider cap (200) are in
  memory: they reset on restart and count the proxy's address behind a proxy. The message is never stored (the
  audit row keeps its length and the matched entry ids).
- **Citizen document pre-check (`POST /public/precheck`)**: checks one citizen-uploadable document at a time in
  memory (excluding the clerk's `application` form) and answers in English only, whatever the page language. Because it
  sees a single document without a case, it checks readability, typed coercion, plausible ranges, document age/expiry,
  damaged name characters and single-document recorded entries (such as a tenant or mundkar entry on Form I & XIV),
  but cannot check whether names, survey numbers or house numbers match across documents or whether a duplicate claim
  exists. Its rate limit (10 per client per ten minutes) and daily provider cap (100) are in memory and reset on
  restart. Nothing is stored on disk, in case/document tables or in logs; the audit row keeps only the document type,
  readability category (`yes` / `partly` / `no`), elapsed milliseconds and whether the OCR fallback was used.
- **`used_fallback` has two meanings**: in the pre-check it means "Gemini was not used" (OCR-only result), whereas in
  case extraction (`app/extraction.py`) it means "Tesseract filled weakly read fields" after Gemini read the document.
- **Audit hash chain**: shows a stored row edited, deleted or moved, but on its own it cannot show (a) the newest rows
  removed from the end, or (b) the whole chain recomputed by someone with write access to the database file: the hash
  has no secret key. Production would anchor the latest `row_hash` outside the database (printed in a daily report,
  or sent to a separate log service) and could use an HMAC with a key held outside the database. Two writers racing
  in SQLite fail with "database is locked" rather than forking the chain; a server database would need the same
  serialisation. A failed check only reports; it does not stop new rows being written.
- **Duplicate survey-number flag (`duplicate_survey_claim`)**: flags every other open or decided case on the same
  survey number, co-owners included, so a legitimate co-owner claim still goes to review (LA-14, LA-15). The flag is
  computed when a case is verified: the case submitted first gets it only when it is next verified (new documents,
  re-run), not at the moment a second claim arrives; the second case always names the first. A rejected claim still
  counts, which is intended (the land was claimed before) but means a once-rejected duplicate keeps flagging. An
  unreadable survey number gives a second "cannot check" flag next to `duplicate_claim`'s. Matching is the exact
  survey-number normalisation (spaces removed, upper case): "45/2" and "45-2" are different numbers. The demo database
  keeps the flags stored at its last seed until cases are re-verified or the demo is re-seeded.
- **Deficiency notice ("Request documents")**: it asks only for what a citizen can fix (missing, expired or

  unreadable documents, a name mismatch, a missing entry); anything else (survey or house mismatch, duplicate
  claims, implausible values, tenant / mundkar entries, extraction outages) is left to the officer. Field names
  in the notice come from the YAML labels, which are English, so a Hindi, Marathi or Konkani notice still names
  fields in English; those translations are drafts. Nothing is sent to the citizen: the notice appears on the
  tracking page (and prints from there). It reuses the existing "More information needed" status. Open flags stay
  on the case until verification runs again on the new documents.
- The award letter is produced with the browser's *Save as PDF*; there is no server-side PDF.
- SLA overdue is a flag only: nothing escalates or changes status automatically.
- **The SLA clock pauses while a case waits for the citizen** ("More information needed"): from the send-back
  or deficiency notice to the next document added, read from the audit log's real timestamps; a waiting case is
  never shown overdue. The pause ends only when a document is added, so a citizen who replies by phone or in
  person without a new document leaves the clock paused until an officer acts. The demo seed's intake dates are
  backdated but its audit times are real, so its sent-back case (LA-05) starts waiting at seed time.
- SQLite single file, no schema migrations: a schema change needs a re-seed.
- The duplicate-claim check compares keys exactly (after normalisation); it does not catch near-identical
  survey or house numbers.
- Self-check runs only rules that can be answered without documents; cross-document checks (names, house
  numbers, duplicates) happen only after application.
