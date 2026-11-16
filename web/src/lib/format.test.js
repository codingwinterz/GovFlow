import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formatRupees, maskIdentifiers, formatConfidence, formatDuration, fieldSource, validateDecision,
  unavailableDocuments,
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

test("retry banner lists only current documents whose extraction is unavailable", () => {
  const detail = { documents: [
    { id: 1, doc_type: "identity_proof", current: false, extraction_status: "extraction_unavailable" },
    { id: 2, doc_type: "identity_proof", current: true, extraction_status: "extraction_unavailable" },
    { id: 3, doc_type: "survey_sheet", current: true, extraction_status: "ok" },
  ] };
  assert.deepEqual(unavailableDocuments(detail).map((d) => d.id), [2]);
  assert.deepEqual(unavailableDocuments({}), []);
});
