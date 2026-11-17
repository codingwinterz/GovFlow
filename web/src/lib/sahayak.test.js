import { test } from "node:test";
import assert from "node:assert/strict";
import { askBody, askError, replyView, selfCheckSummary } from "./sahayak.js";

test("the self-check summary sent to Sahayak holds ids and statuses only, never the messages", () => {
  const result = { scheme: "disaster_relief", outcome: "need_more_information", rules_version: "0.1.0",
    rules: [{ rule_id: "residence_in_affected_area", status: "needs_review", message: "Please answer: x" }] };
  assert.deepEqual(selfCheckSummary(result), { scheme: "disaster_relief", outcome: "need_more_information",
    rules: [{ rule_id: "residence_in_affected_area", status: "needs_review" }] });
  assert.equal(selfCheckSummary(null), null);
  assert.deepEqual(askBody("  what is a notified area? ", "disaster_relief", null),
    { message: "what is a notified area?", scheme: "disaster_relief" });
});

test("a fallback reply shows its source and the verify tag exactly as the API sent them", () => {
  const view = replyView({ answer: "Bring Form I & XIV.", used_fallback: true, entries: [
    { id: "land_record_to_bring", title: "Which land record?", verify: true, tag: "Verify with the Collectorate",
      source: { name: "goaonline.gov.in", url: "https://goaonline.gov.in" } },
    { id: "what_this_tool_does", title: "What does this helper do?", verify: false, tag: null,
      source: { name: "GovFlow", url: "VERIFY" } }] });
  assert.equal(view.text, "Bring Form I & XIV.") ;
  assert.equal(view.fallback, true);
  assert.deepEqual(view.sources.map((s) => [s.url, s.unconfirmed, s.tag]),
    [["https://goaonline.gov.in", false, "Verify with the Collectorate"], [null, true, null]]);
});

test("errors read plainly, with the rate limit explained", () => {
  assert.match(askError(429), /Too many questions/);
  assert.match(askError(422), /500 characters/);
  assert.match(askError(500), /could not answer/);
});
