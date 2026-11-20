// The case page's summary strip: the SLA clock in words and the flag count by severity.
// Hand-derived expected values; the API's queue row (days_open, sla_days, overdue) is the only input for the clock.
import { test } from "node:test";
import assert from "node:assert/strict";
import { flagCounts, showsAmounts, slaClock, summaryTotal } from "./summary.js";

const row = (over) => ({ status: "in_officer_review", days_open: 20, sla_days: 60, overdue: false, ...over });

test("slaClock: days left while inside the target", () => {
  assert.deepEqual(slaClock(row({})), { kind: "left", text: "40 days left", title: "Day 20 of a 60-day target" });
  assert.equal(slaClock(row({ days_open: 59 })).text, "1 day left");
  assert.equal(slaClock(row({ days_open: 60 })).text, "Due today");        // overdue only once past the target
});

test("slaClock: overdue uses the API's flag and says by how much", () => {
  assert.deepEqual(slaClock(row({ days_open: 70, overdue: true })),
    { kind: "overdue", text: "Overdue by 10 days", title: "Day 70 of a 60-day target" });
  assert.equal(slaClock(row({ days_open: 61, overdue: true })).text, "Overdue by 1 day");
});

test("slaClock: paused while waiting for the citizen, closed once decided, unknown without a row", () => {
  assert.equal(slaClock(row({ status: "needs_info", days_open: 27 })).kind, "paused");
  assert.equal(slaClock(row({ status: "needs_info", days_open: 27 })).text, "Clock paused (waiting for the citizen)");
  assert.deepEqual(slaClock(row({ status: "approved", days_open: 45 })),
    { kind: "closed", text: "Decided after 45 days", title: "Target was 60 days" });
  assert.equal(slaClock(row({ status: "withdrawn", days_open: 1 })).text, "Closed after 1 day");
  assert.equal(slaClock(null), null);
  assert.equal(slaClock(row({ days_open: undefined })), null);
});

test("flagCounts: count per severity, most severe first, zero groups left out", () => {
  assert.deepEqual(flagCounts([{ severity: "low" }, { severity: "high" }, { severity: "high" }, { severity: "medium" }]),
    [{ severity: "high", count: 2 }, { severity: "medium", count: 1 }, { severity: "low", count: 1 }]);
  assert.deepEqual(flagCounts([{ severity: "medium" }]), [{ severity: "medium", count: 1 }]);
  assert.deepEqual(flagCounts([]), []);
  assert.deepEqual(flagCounts(undefined), []);
});

test("summaryTotal: the stored total exactly as the API sent it, or null when none was computed", () => {
  assert.equal(summaryTotal({ compensation: { items: [{ amount: 1 }], total: 7612345.67 } }), 7612345.67);
  assert.equal(summaryTotal({ compensation: { items: [], total: null } }), null);
  assert.equal(summaryTotal({}), null);
});

test("a scheme with no compensation shows no amounts, total or award letter", () => {
  assert.equal(showsAmounts({ has_compensation: false }), false);
  assert.equal(showsAmounts({ has_compensation: true }), true);
  assert.equal(showsAmounts({}), true);              // older API answers: amounts shown as before
});
