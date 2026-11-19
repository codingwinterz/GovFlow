# Future scheme: revenue mutation (designed, not built)

Status: **deferred, 2026-11-19.** Feasibility checked, no code or YAML written. This note records what was found so
the scheme can be built after the jury without repeating the analysis.

The scheme: mutation of Form I and XIV after a sale deed, succession, partition or court order. The officer decides;
the system recommends **"ready for notice"** or **"needs review"** and calculates **no amount**.

## 1. Sourced process and timelines

Nothing here is legal advice, and none of it is in the code. **Type** says what kind of source each item rests on.

Sources:
- **Ministerial statement:** the Revenue Minister's statement as reported in the press (goemkarponn.com, "113 online
  mutation applications filed in Goa in two years"). Not a notification or circular.
- **Citizen charter:** the Collectorate citizen charter, a 2016 document that may be out of date.
- **Rules 1969:** the Goa Land Revenue (Record of Rights and Register of Cultivators) Rules, 1969, rule 11(2), as
  amended in 2010.
- **Commercial guide:** a commercial (non-government) guide.

| Step | Period / rule | Type | Source | Status |
|---|---|---|---|---|
| Application to the Talathi | Under section 96 (Goa Land Revenue Code) | Official document | Collectorate citizen charter (2016) | VERIFY: the charter is current |
| Form X notice | 15 days | Official document | Collectorate citizen charter (2016) | VERIFY: the charter is current |
| Scrutiny of the application | 7 working days | Ministerial statement | Revenue Minister, as reported (goemkarponn.com) | VERIFY against a notification or circular |
| Public notice | 15 days | Ministerial statement | Revenue Minister, as reported (goemkarponn.com) | VERIFY against a notification or circular |
| Disposal, no objections | 30 days | Ministerial statement | Revenue Minister, as reported (goemkarponn.com) | VERIFY against a notification or circular |
| Disposal, with objections | 90 days from the end of the notice period | Ministerial statement | Revenue Minister, as reported (goemkarponn.com) | VERIFY against a notification or circular |
| Objections decided by the Mamlatdar | Within three months, after hearing all parties; notice in Form XII to those who objected | Official document | Rules 1969, rule 11(2), as amended in 2010 | Sourced |
| Notice to all co-owners | Required before mutation | Not yet sourced | none confirmed | VERIFY: which provision |
| Civil title disputes | Not decided by the revenue authority; referred to the civil court | Not yet sourced | none confirmed | VERIFY: which provision |
| Application window (90 days after the transfer) | 90 days | Commercial guide only | commercial guide | **VERIFY** |
| Fees | as stated there | Commercial guide only | commercial guide | **VERIFY** |

The 15-day notice appears twice: as Form X in the 2016 citizen charter and as the public notice period in the
minister's statement. Both say 15 days. Only one period could drive the queue clock (`sla_days`); see (d) below.

## 2. What works with YAML alone

Checked against the engine on 2026-11-19 (`app/rules_loader.py`, `app/tools.py`, `app/verification.py`,
`app/citizen.py`, `app/analytics.py`).

- **Loading the scheme:** `compensation` is optional. With no compensation section a case is marked assessed on its
  rule results alone (`tools._mark_assessed_if_complete`) and reaches the officer queue.
- **Tenant or mundkar entry:** reuse the `recorded_entry` built-in (as `tenant_or_mundkar_claim` in land
  acquisition): a high flag, approval needs the officer's resolution, and the citizen sees a notice key only.
- **Recorded dispute:** a second `recorded_entry` check on the dispute indicator, with its own message:
  "Dispute recorded: refer; this system does not decide title."
- **Second open mutation on the same survey number:** the `duplicate_claim` built-in keyed on the survey number, with
  `ignore_statuses: [approved, rejected, withdrawn]` so only open mutations compete. It compares within the scheme.
- **Survey number across documents:** the existing field comparison check.
- **Transferor matches the Form I owner:** a field comparison works only if the deed's transferor field has the
  same field name as Form I's owner field (the comparison matches field names), labelled "Transferor name" in
  `terms`. That is a naming workaround, not a real cross-field comparison.
- **Officer queue and dashboard:** no change. The scheme appears in the scheme-by-stage table and contributes no
  liability.
- **Citizen self-check, plain-language terms, hi / mr / kok drafts:** data files only (`self_check` in the YAML,
  `web/src/i18n/*.json`).

## 3. What needs code (five items)

1. **Recommendation labels.** The rules engine has three fixed outcomes (`eligible`, `not_eligible`, `needs_review`,
   `app/rules_engine.py` `overall_from`), shown with app-wide labels ("Eligible", "Not eligible", "Needs review",
   `web/src/i18n/labels.en.json`). A scheme cannot say "Ready for notice".
2. **The co-owner rule.** It can be written with counts (co-owners listed on Form I against parties named, unless
   the holding is partitioned), but a rule whose condition is false always gives `fail`, so the case would be
   recommended **"Not eligible"** instead of "notice to all co-owners required". No built-in compares two lists
   of names. Needs an `on_false: needs_review` option.
3. **Approval and award screens, and the citizen "Why this amount" page.** An approved case opens the award letter
   (a compensation document); there is no Form X notice or mutation order screen. The citizen tracking page builds
   amounts for every approved case (`app/citizen.py` `_amounts`), so it would show "Why this amount ... Total:
   ₹0.00". The case page and summary strip would show the total as "Not computed yet" permanently.
4. **Timelines and working days.** The engine reads one `sla_days`. Unknown YAML keys are silently ignored, so a
   `timelines:` block would load but nothing would read or show it. Working days are not supported, and there are no
   case statuses for notice issued or the objection period.
5. **The pipeline compensation step.** `app/agent.py` `run_pipeline` always calls `compute_compensation`, which
   raises "no compensation section" for such a scheme. The error is caught and the case still moves on, but every
   run records a failed tool step in the step list and audit. Fixing it is agent code.

## 4. Smallest proposed change

No extraction, compensation or agent code. Each item with its own tests and commit.

- **(a) Per-scheme recommendation labels:** optional `recommendation_labels` in the YAML, for example
  `{eligible: "Ready for notice", needs_review: "Needs review"}`, sent with the case and used by the case page,
  queue and citizen page in place of the app-wide label.
- **(b) `on_false: needs_review` on a rule:** a false condition routes to review instead of `fail`, so a notice
  requirement never reads as "Not eligible". Default stays `fail`; existing schemes are unchanged.
- **(c) Schemes with no compensation:** hide the amounts card, summary-strip total and award-letter link on the
  officer side; skip "Why this amount" on the citizen page (`_amounts` returns nothing when the scheme has no
  compensation section). A mutation notice or order screen is a separate, later piece of work.
- **(d) Timelines as data:** a validated `timelines` list in the YAML (id, days, `working_days: true|false`,
  source, `verify: true|false`), shown on the case page with its source. Only `sla_days` drives the queue clock;
  working-day counting is not added.

Left as a documented gap: item 5 (the pipeline's compensation step), until agent code may change.

## 5. Planned data (when built)

- **Fields:** applicant name, survey and sub-division number, area, trigger type (sale deed, succession, partition,
  court order), transferor name, deed registration date, current owner as read from Form I, co-owners listed, tenant
  or mundkar entry present, pending dispute indicator.
- **Documents:** application, deed or order, current Form I and XIV, identity proof; any others marked VERIFY.
- **Synthetic cases (5):** a clean sale; co-owners not all named; a tenant entry; a name mismatch with Form I; a
  duplicate pending mutation. Invented names and IDs only, added to `seed_demo`.
- **Tests:** hand-derived outcomes per case, boundary cases for the notice requirement, no scheme name hardcoded in
  `app/*.py`, the scheme in the dashboard; sabotage of the co-owner rule must fail a test.
