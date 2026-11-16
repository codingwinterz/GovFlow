import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formatRupees, maskIdentifiers, formatConfidence, formatDuration, fieldSource, validateDecision, confirmedFields,
  unavailableDocuments, formatDate, formatDay, todayInIndia,
} from "./format.js";

test("rupees use Indian grouping and are only formatted, never computed", () => {
  assert.equal(formatRupees(17200000), "₹1,72,00,000.00");
  assert.equal(formatRupees(35704931.51), "₹3,57,04,931.51");
  assert.equal(formatRupees(0), "₹0.00");
  assert.equal(formatRupees(null), "—");
  assert.equal(formatRupees(undefined), "—");
});

test("identifiers are masked again in the UI (defence in depth)", () => {
  assert.equal(maskIdentifiers("ID 9876 5432 1098"), "ID XXXX XXXX 1098");
  assert.equal(maskIdentifiers("987654321098"), "XXXX XXXX 1098");
  assert.equal(maskIdentifiers("XXXX XXXX 1098"), "XXXX XXXX 1098");
  assert.equal(maskIdentifiers("survey 154/2, area 3000"), "survey 154/2, area 3000");
  assert.equal(maskIdentifiers(42), "42");
});

test("confidence and durations", () => {
  assert.equal(formatConfidence(0.6234), "0.62");
  assert.equal(formatConfidence(null), "—");
  assert.equal(formatDuration(null), "—");
  assert.equal(formatDuration(45), "45 s");
  assert.equal(formatDuration(3 * 3600 + 120), "3 h 2 min");
  assert.equal(formatDuration(2 * 86400 + 5 * 3600), "2 d 5 h");
});

test("every extracted value names its source", () => {
  const f = { document_id: 12, document_type: "identity_proof", field: "name", source_page: 1, method: "llm" };
  const terms = { identity_proof: "Identity proof", name: "Name" };
  assert.equal(fieldSource(f, terms), "Identity proof #12 · Name · page 1 · Read by the vision model");
  assert.equal(fieldSource({ ...f, source_page: null, method: "seed" }, terms), "Identity proof #12 · Name · Synthetic seed data");
  assert.equal(fieldSource({ ...f, method: "ocr_fallback" }, {}), "Identity proof #12 · Name · page 1 · Read by OCR (fallback)");
});

test("reject and send back need a comment; approve does not", () => {
  assert.equal(validateDecision("approve", ""), null);
  assert.match(validateDecision("reject", "  "), /comment/);
  assert.match(validateDecision("send_back", ""), /comment/);
  assert.equal(validateDecision("reject", "survey mismatch"), null);
  assert.match(validateDecision("", "x"), /Choose/);
});

test("approving needs every amount-driving value ticked; the ticked values are what is sent", () => {
  const fields = [{ ref: "ownership_record.area", value: 0.25 }, { ref: "ownership_record.area_unit", value: "hectare" }];
  assert.match(validateDecision("approve", "", fields, { "ownership_record.area": true }), /Tick each value/);
  assert.equal(validateDecision("approve", "", fields, { "ownership_record.area": true, "ownership_record.area_unit": true }), null);
  assert.equal(validateDecision("reject", "wrong area", fields, {}), null);            // only approval needs the ticks
  assert.deepEqual(confirmedFields(fields, { "ownership_record.area": true, "ownership_record.area_unit": true }),
    { "ownership_record.area": 0.25, "ownership_record.area_unit": "hectare" });
  assert.deepEqual(confirmedFields(fields, { "ownership_record.area": true }), { "ownership_record.area": 0.25 });
});

test("retry banner lists only current documents whose extraction is unavailable", () => {
  const detail = { documents: [
    { id: 1, doc_type: "identity_proof", current: false, extraction_status: "extraction_unavailable" },
    { id: 2, doc_type: "identity_proof", current: true, extraction_status: "extraction_unavailable" },
    { id: 3, doc_type: "survey_sheet", current: true, extraction_status: "ok" },
  ] };
  assert.deepEqual(unavailableDocuments(detail).map((d) => d.id), [2]);
  assert.deepEqual(unavailableDocuments({}), []);
});

test("dates are shown to the minute, never with seconds", () => {
  const text = formatDate("2026-09-07T07:07:35.808317+00:00");
  assert.match(text, /2026/);
  assert.doesNotMatch(text, /\d{1,2}:\d{2}:\d{2}/);
  assert.match(text, /\d{1,2}:\d{2}/);
  assert.equal(formatDate(null), "—");
});

test("a day is shown without a time", () => {
  assert.match(formatDay("2026-09-07T07:07:35+00:00"), /^\d{1,2} \w+ 2026$/);
  assert.equal(formatDay(undefined), "—");
});

test("timestamps without a zone are UTC (as the backend stores them), not browser-local", () => {
  assert.equal(formatDate("2026-09-07T07:07:35.808317"), formatDate("2026-09-07T07:07:35.808317Z"));
  assert.equal(formatDay("2026-09-07T23:30:00"), formatDay("2026-09-07T23:30:00+00:00"));
});

test("timestamps are shown in India time whatever the browser's zone: a decision at 00:30 IST", () => {
  const ts = "2026-11-19T19:00:00Z";                       // 00:30 IST on 20 Nov
  assert.match(formatDate(ts), /^20 Nov 2026, 12:30\s?am$/i);
  assert.equal(formatDay(ts), "20 Nov 2026");
  assert.equal(formatDay("2026-11-20"), "20 Nov 2026");    // a plain date stays that date
  assert.equal(todayInIndia(new Date(ts)), "2026-11-20");  // intake's default reference date
});
