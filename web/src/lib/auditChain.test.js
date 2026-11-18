import { test } from "node:test";
import assert from "node:assert/strict";
import { integrityMessage } from "./auditChain.js";

test("an intact chain reads as intact, with the row count", () => {
  assert.deepEqual(integrityMessage({ ok: true, rows: 388, first_broken_id: null }),
    { ok: true, text: "Log intact: all 388 rows chain correctly." });
  assert.equal(integrityMessage({ ok: true, rows: 1, first_broken_id: null }).text, "Log intact: all 1 row chains correctly.");
  assert.equal(integrityMessage({ ok: true, rows: 0, first_broken_id: null }).text, "Log intact: the log is empty.");
});

test("a broken chain names the first broken row and what it means", () => {
  assert.deepEqual(integrityMessage({ ok: false, rows: 4, first_broken_id: 3 }), {
    ok: false,
    text: "Log altered: the chain breaks at row #3 (4 rows checked). That row, or the one before it, was edited, deleted or moved.",
  });
});

test("anything else is not reported as intact", () => {
  for (const bad of [null, {}, { ok: "yes", rows: 3 }, { ok: true }]) {
    assert.equal(integrityMessage(bad).ok, false);
    assert.equal(integrityMessage(bad).text, "The integrity check gave no result. Try again.");
  }
});
