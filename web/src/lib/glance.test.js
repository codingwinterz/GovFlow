// At-a-glance helpers for the simplified pages. Hand-derived expected values; none of these adds money or dates.
import { test } from "node:test";
import assert from "node:assert/strict";
import { attentionCases, caseHeadline, headlineTiles, queueRows, topSeverity } from "./glance.js";

const detail = (over) => ({ status: "in_officer_review", recommendation: "eligible", recommendation_labels: null, flags: [], ...over });

test("caseHeadline: a case ready for decision says what the checks recommend and how many items need attention", () => {
  assert.equal(caseHeadline(detail({})), "Ready for your decision. The checks recommend: Eligible. Nothing needs your attention.");
  assert.equal(caseHeadline(detail({ flags: [{ severity: "high" }] })),
    "Ready for your decision. The checks recommend: Eligible. 1 item needs your attention.");
  assert.equal(caseHeadline(detail({ recommendation: "needs_review", flags: [{ severity: "high" }, { severity: "low" }] })),
    "Ready for your decision. The checks recommend: Needs review. 2 items need your attention.");
});

test("caseHeadline: the scheme's own recommendation label is used when the YAML gives one", () => {
  assert.equal(caseHeadline(detail({ recommendation_labels: { eligible: "Ready for notice" } })),
    "Ready for your decision. The checks recommend: Ready for notice. Nothing needs your attention.");
});

test("caseHeadline: waiting, decided, withdrawn and still in processing read plainly, never as the agent deciding", () => {
  assert.equal(caseHeadline(detail({ status: "needs_info" })), "Waiting for the citizen to send documents. The clock is paused.");
  assert.equal(caseHeadline(detail({ status: "approved" })), "Decided by an officer: Approved.");
  assert.equal(caseHeadline(detail({ status: "rejected" })), "Decided by an officer: Rejected.");
  assert.equal(caseHeadline(detail({ status: "withdrawn" })), "Closed: the application was withdrawn.");
  assert.equal(caseHeadline(detail({ status: "verified", flags: [{ severity: "high" }] })),
    "Still being processed, not ready for a decision. 1 item needs attention.");
  assert.equal(caseHeadline(detail({ status: "received" })), "Still being processed, not ready for a decision.");
});

test("topSeverity: the most severe flag, or null", () => {
  assert.equal(topSeverity([{ severity: "low" }, { severity: "high" }, { severity: "medium" }]), "high");
  assert.equal(topSeverity([{ severity: "medium" }]), "medium");
  assert.equal(topSeverity([]), null);
  assert.equal(topSeverity(undefined), null);
});

const row = (id, over) => ({ case_id: id, status: "in_officer_review", flags: [], overdue: false, ...over });
const ROWS = [row("A"), row("B", { flags: [{ kind: "x", severity: "medium" }] }), row("C", { overdue: true }),
  row("D", { flags: [{ kind: "y", severity: "high" }], overdue: true }), row("E", { status: "approved", flags: [{ kind: "z", severity: "high" }] })];

test("queueRows: all, needs attention (any flag) and overdue (the API's flag), order kept", () => {
  assert.deepEqual(queueRows(ROWS, "all").map((r) => r.case_id), ["A", "B", "C", "D", "E"]);
  assert.deepEqual(queueRows(ROWS, "attention").map((r) => r.case_id), ["B", "D", "E"]);
  assert.deepEqual(queueRows(ROWS, "overdue").map((r) => r.case_id), ["C", "D"]);
  assert.deepEqual(queueRows(null, "all"), []);
});

test("attentionCases: overdue or high-severity open cases, each with its reasons; decided cases left out", () => {
  assert.deepEqual(attentionCases(ROWS), [
    { case_id: "C", scheme: undefined, overdue: true, high: false },
    { case_id: "D", scheme: undefined, overdue: true, high: true },
  ]);
  const open = [row("F", { flags: [{ severity: "high" }] }), row("G", { status: "needs_info", flags: [{ severity: "high" }] })];
  assert.deepEqual(attentionCases(open).map((c) => c.case_id), ["F", "G"]);
  assert.deepEqual(attentionCases(undefined), []);
});

test("headlineTiles: exactly four numbers, each read straight from the API field it names (no arithmetic)", () => {
  const a = { by_status: { in_officer_review: 7 }, overdue_count: 3, average_days_open: 12.5,
    liability: { pending_total: 4250000, committed_total: 1 } };
  const tiles = headlineTiles(a);
  assert.deepEqual(tiles.map((t) => t.key), ["awaiting", "overdue", "days_open", "pending"]);
  assert.deepEqual(tiles.map((t) => t.value), [7, 3, 12.5, 4250000]);
  assert.deepEqual(tiles.map((t) => t.source), ["by_status.in_officer_review", "overdue_count", "average_days_open",
    "liability.pending_total"]);
  assert.deepEqual(headlineTiles({ by_status: {}, overdue_count: 0, average_days_open: null }).map((t) => t.value),
    [0, 0, null, null]);
});
