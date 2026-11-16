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
- **The audit log is append-only only inside SQLite** (triggers reject UPDATE and DELETE). Someone with
  direct access to the database file can drop the triggers. There are no backups and no external log sink.

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
- **Notified area:** disaster relief relies on the damage assessment's own "notified area" certification;
  there is no list of notified villages per disaster event.

## Language
- **Hindi, Marathi and Konkani translations were written without native-speaker review** and are marked
  "needs native-speaker review" in each file and on the page. They are not verified.
- Only the citizen status page is translated. The officer dashboard, the self-check and the rule simulator
  are English only.
- Officer comments (for example, the reason a case was sent back) are not shown to citizens, because they
  are free text in English and may contain internal notes.

## AI and extraction
- **Live results exist for one small model only** (`docs/EVAL_RESULTS.md`, 16 Nov 2026, `gemini-3.5-flash-lite`).
  The default model `gemini-3.8-flash` could not be reached (503, then timeouts), so it has never run live; its
  function-calling wire format stays marked VERIFY. The agent's wire format worked live on `gemini-3.5-flash-lite`.
- **Extraction accuracy is measured on a tiny synthetic set only:** 7 land-acquisition documents (27 fields),
  27/27 correct on clean and mildly degraded images, 0 wrong values accepted. No stamps, handwriting or phone
  photos, no disaster-relief images, no real Goa documents. 0 errors in 27 still allows up to about 11% on this
  kind of data, and real documents are harder.
- **The model's confidence was 0.99 on every field**, clean or degraded, so the 0.85 threshold never sent a field
  to review. Treat model confidence as uninformative until it is shown to drop on hard documents.
- The Tesseract baseline's label parser knows the synthetic document layouts, so its accuracy is generous.
- Gemini's confidence scores are self-reported, not calibrated; the 0.85 threshold depends on them. So a
  document cannot vouch for itself where it matters: the fields that drive an amount (land area and unit;
  relief damage %, house type, area type) must be confirmed by the officer at their current value before
  approval, whatever the confidence, and values outside the YAML's plausible range go to review.
- **Prompt injection is reduced, not eliminated.** The prompts call document text and tool results untrusted
  data, the agent has no decision tool, and explanations that quote an unknown amount or say approved /
  rejected / sanctioned are flagged. Instruction-like text in other fields (a name, a remark) is not detected
  as such; it reaches the officer as data. LA-17 and DR-15 are the injected test cases.

## Data and testing
- **All data is synthetic.** 17 land-acquisition and 15 disaster-relief cases (two with injected text),
  hand-derived expected outcomes, and 7 messy documents rendered as clean and degraded images from a computer
  font, not real scans.
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
- The award letter is produced with the browser's *Save as PDF*; there is no server-side PDF.
- SLA overdue is a flag only: nothing escalates or changes status automatically.
- SQLite single file, no schema migrations: a schema change needs a re-seed.
- The duplicate-claim check compares keys exactly (after normalisation); it does not catch near-identical
  survey or house numbers.
- Self-check runs only rules that can be answered without documents; cross-document checks (names, house
  numbers, duplicates) happen only after application.
