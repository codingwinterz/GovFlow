// Timelines on the case page: each period with its source and whether it is still to be verified. Data only;
// only the timeline marked drives_sla is what the SLA clock counts (as sla_days).
import { test } from "node:test";
import assert from "node:assert/strict";
import { timelineNote, timelineRows } from "./timelines.js";

const T = [
  { id: "scrutiny", label: "Scrutiny of the application", period: "7 working days", days: 7, working_days: true,
    source_type: "ministerial_statement", source: "Revenue Minister, as reported", verify: true,
    verify_note: "against a notification or circular", drives_sla: false },
  { id: "objections", label: "Objections decided", period: "Within three months", days: null, working_days: false,
    source_type: "official_document", source: "Rules 1969, rule 11(2)", verify: false, verify_note: null, drives_sla: false },
  { id: "disposal", label: "Disposal, no objections", period: "30 days", days: 30, working_days: false,
    source_type: "ministerial_statement", source: "Revenue Minister, as reported", verify: true,
    verify_note: "against a notification or circular", drives_sla: true },
];

test("each row names the step, the period as written, the source with its kind, and the verify state", () => {
  assert.deepEqual(timelineRows(T)[0], { id: "scrutiny", step: "Scrutiny of the application", period: "7 working days",
    source: "Ministerial statement: Revenue Minister, as reported", verifyText: "To verify: against a notification or circular",
    verify: true, clock: false });
  assert.equal(timelineRows(T)[1].verifyText, "Sourced");
  assert.equal(timelineRows(T)[1].source, "Official document: Rules 1969, rule 11(2)");
  assert.equal(timelineRows(T)[2].clock, true);
});

test("the note says which step the clock counts, or that none does", () => {
  assert.equal(timelineNote(T), "For reference. The SLA clock counts only “Disposal, no objections” (30 calendar days); working days are not counted.");
  assert.equal(timelineNote(T.slice(0, 2)), "For reference. None of these drives the SLA clock; it counts the scheme's target in calendar days.");
});

test("no timelines, no rows", () => {
  assert.deepEqual(timelineRows(undefined), []);
});
