import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRoute, href } from "./router.js";

test("hash routes", () => {
  assert.deepEqual(parseRoute(""), { page: "queue" });
  assert.deepEqual(parseRoute("#/"), { page: "queue" });
  assert.deepEqual(parseRoute("#/cases/LA-07"), { page: "case", id: "LA-07" });
  assert.deepEqual(parseRoute("#/cases/LA-07/audit"), { page: "audit", id: "LA-07" });
  assert.deepEqual(parseRoute("#/analytics"), { page: "analytics" });
  assert.deepEqual(parseRoute("#/intake"), { page: "intake" });
  assert.deepEqual(parseRoute("#/status"), { page: "status" });
  assert.deepEqual(parseRoute("#/track"), { page: "track" });
  assert.deepEqual(parseRoute("#/nope"), { page: "notfound" });
});

test("case ids are encoded and decoded", () => {
  assert.equal(href("case", "A B"), "#/cases/A%20B");
  assert.deepEqual(parseRoute("#/cases/A%20B"), { page: "case", id: "A B" });
});
