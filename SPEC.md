# GovFlow: Specification

## 1. What it is
A single AI agent that helps officers process government cases end to end: read documents (OCR), verify them against each other, check eligibility with deterministic rules, compute itemised compensation, route to an officer, and track progress. Schemes are plug-in YAML files.

Schemes: (1) Land acquisition compensation (primary, build fully). (2) Disaster relief (second, config only). Optional later: one welfare scheme.

## 2. Architecture
```
Citizen / clerk / field team
        |  upload docs, ask status (text/voice)
        v
   Agent (LLM tool-calling loop)  ---->  Audit log (append-only)
        |
        +-- extract_facts        (OCR + LLM extraction -> fields + confidence)
        +-- verify_documents     (cross-document checks, flags)
        +-- check_eligibility    (rules engine -> per-rule pass/fail + clause)
        +-- compute_compensation (deterministic calculator -> itemised breakdown)
        +-- submit_to_officer    (creates pre-triaged queue item)
        +-- get_case_status      (for citizen/officer)
        +-- log_action           (every step)
        v
 Officer dashboard (approve / reject / send back) + analytics
```
The agent orchestrates and explains. Tools decide.

## 3. Data model (SQLite)
- `cases(id, scheme, applicant_ref, status, created_at, updated_at, officer_id, confidence_flag)`
- `documents(id, case_id, doc_type, file_path, uploaded_at)`
- `extracted_fields(id, document_id, field, value, confidence, source_page)`
- `verification_flags(id, case_id, kind, detail, severity)`
- `rule_results(id, case_id, rule_id, passed, reason, clause, rules_version)`
- `compensation_items(id, case_id, component, amount, formula_note)`
- `audit_log(id, ts, case_id, actor, action, payload_json, rules_version)` (append-only, never updated or deleted)

Case status flow: `received -> extracted -> verified -> assessed -> in_officer_review -> approved | rejected | needs_info`

## 4. Rules schema (every scheme plugs into this)
```yaml
scheme: land_acquisition
version: "0.1.0"
source: "<Act / notification reference>"   # VERIFY with official documents
required_documents:
  - id: ownership_record
  - id: identity_proof
  - id: survey_sheet
  - id: mutation_record
verification_checks:
  - id: name_match
    fields: [applicant_name]
    across: [ownership_record, identity_proof]
    tolerance: fuzzy_0.9
  - id: survey_no_match
    fields: [survey_number]
    across: [ownership_record, survey_sheet]
    tolerance: exact
eligibility_rules:
  - id: valid_ownership
    clause: "<clause ref>"
    when: "ownership_record.present and ownership_record.owner_name == applicant_name"
    fail_reason: "Ownership record missing or owner name differs from applicant."
  - id: documents_not_expired
    clause: "<clause ref>"
    when: "all_documents_valid"
    fail_reason: "One or more documents are expired."
compensation:
  components:
    - id: land_value
      formula: "area_sqm * market_value_per_sqm * multiplier"
    - id: assets_value
      formula: "assets_total"
    - id: solatium
      formula: "(land_value + assets_value) * solatium_rate"
    - id: interest
      formula: "land_value * interest_rate * years_since_notification"
  parameters:                  # VERIFY every value against the notified Goa rules
    multiplier: 1.0
    solatium_rate: 1.0
    interest_rate: 0.12
confidence_threshold: 0.85
```
Notes: formulas follow the structure of RFCTLARR Act 2013 compensation (market value, multiplier, assets, solatium, interest). Parameters are placeholders and MUST be verified with official Goa notifications before any public claim. Use a safe expression evaluator (no `eval` on raw strings).

## 5. Tools (contracts)
All tools are plain Python functions with typed inputs and outputs, testable without the LLM.
- `extract_facts(document) -> {fields: [{name, value, confidence, source}]}`
- `verify_documents(case_id) -> {flags: [{kind, detail, severity}]}`
- `check_eligibility(case_id) -> {results: [{rule_id, passed, reason, clause}], overall: "eligible|not_eligible|needs_review"}`
- `compute_compensation(case_id) -> {items: [{component, amount, formula_note}], total}`
- `submit_to_officer(case_id) -> {queue_position}`
- `get_case_status(case_id) -> {status, next_step, blockers}`
- `log_action(case_id, actor, action, payload)`

`overall: not_eligible` is a recommendation only. Only an officer can reject.

## 6. Test set (build first)
About 15 synthetic cases per scheme in `data/synthetic/<scheme>/case_XX.json`, each with documents (as text or images) and an `expected.json`. Include messy edge cases:
- name spelled differently across two documents
- expired document
- missing attachment
- survey number mismatch
- area given in different units
- low-quality scan (low OCR confidence)
- duplicate claim
- compensation edge: zero assets, interest over multiple years
Report: extraction accuracy on key fields, rule-result match rate, compensation match rate, correct human-review routing.

## 7. Officer dashboard (web/)
- Queue sorted by priority and confidence flag
- Case page: documents, extracted fields with confidence, verification flags, per-rule results with clauses, itemised compensation, agent explanation
- Actions: approve, reject, send back with comment
- Analytics: cases by status, average processing time, stuck-case list, per-scheme counts
- Audit trail view per case

## 8. Build order (15 days from Nov 15)
1. Day 1: repo, schema, rules engine, compensation calculator, synthetic cases, pytest green (no LLM).
2. Days 2 to 3: extraction and cross-document verification.
3. Days 4 to 5: agent loop, audit log, API.
4. Days 6 to 8: officer dashboard and analytics.
5. Day 9: disaster relief as a second YAML file (no new Python).
6. Days 10 to 12: voice/language support, polish, measured results from the test set.
7. Days 13 to 15: demo video, deck, buffer.

## 9. Day 1 checklist
- [ ] Create repo structure from CLAUDE.md
- [ ] SQLAlchemy models for section 3
- [ ] YAML loader and safe expression evaluator
- [ ] `check_eligibility` and `compute_compensation` with tests
- [ ] 15 synthetic land-acquisition cases with expected outcomes
- [ ] `pytest -q` passes with zero LLM calls

## 10. Demo script (target 3 minutes)
1. Upload a case bundle for a landowner.
2. Show extracted fields and the flagged name mismatch.
3. Fix the document, re-run, show eligibility with per-rule clauses.
4. Show the itemised compensation breakdown.
5. Switch to the officer view, approve, show the audit trail.
6. Show the dashboard, then add disaster relief by dropping in a YAML file.
