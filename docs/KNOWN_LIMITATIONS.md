# GovFlow: known limitations

GovFlow is a hackathon prototype. This list is meant to be read before anyone treats a number,
a screen or a test result as more than it is.

## Security and access
- **No real authentication.** Identity is the `X-Role` / `X-User` request headers, trusted as sent
  (*DEMO MODE*). Anyone who can reach the API can claim to be an officer. Replace with real
  authentication and authorisation before any deployment.
- **Citizen verification codes are a demo mechanism.** A code is an HMAC of the case reference with a
  server secret. Without `GOVFLOW_CITIZEN_SECRET` a built-in demo secret is used, so codes are predictable
  to anyone who has the source. Real codes should be issued to the applicant at intake.
- **Rate limiting is in memory.** Limits reset when the server restarts and are not shared between server
  processes. Five wrong codes for one reference block lookups for that reference for 15 minutes, which also
  locks out the genuine applicant for that time (a deliberate trade-off against guessing).
- **Uploaded documents are stored unencrypted** on local disk under `uploads/` (gitignored).
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
- **The Gemini agent has never been run against the live API.** The function-calling wire format follows
  Google's documentation and is marked VERIFY; the free-tier quota was exhausted during testing.
- **Live extraction accuracy is unmeasured.** The real-image evaluation was cut short by Gemini rate limits
  (1 of 28 requests answered in the last run). The only full numbers come from Tesseract and from recorded
  fake responses, which describe the recordings, not a model.
- The Tesseract baseline's label parser knows the synthetic document layouts, so its accuracy is generous.
- Gemini's confidence scores are self-reported, not calibrated; the 0.85 threshold depends on them.
- The agent can be asked to explain only; it cannot decide. If its explanation quotes an amount no tool
  produced, the amount is flagged, but other kinds of wrong wording are not detected.

## Data and testing
- **All data is synthetic.** 16 land-acquisition and 14 disaster-relief cases, hand-derived expected
  outcomes, and 7 messy documents rendered as clean and degraded images from a computer font, not real scans.
- The demo seed spreads intake dates over recent weeks by a fixed pattern so SLA flags appear; those dates
  are synthetic.
- **No screen has been tested in a browser.** Frontend tests cover logic, translation files and source
  guards (for example, that no page computes money); React components are not rendered in tests.
- The rule simulator runs over the synthetic set only, not over live cases.

## Product scope
- The award letter is produced with the browser's *Save as PDF*; there is no server-side PDF.
- SLA overdue is a flag only: nothing escalates or changes status automatically.
- SQLite single file, no schema migrations: a schema change needs a re-seed.
- The duplicate-claim check compares keys exactly (after normalisation); it does not catch near-identical
  survey or house numbers.
- Self-check runs only rules that can be answered without documents; cross-document checks (names, house
  numbers, duplicates) happen only after application.
