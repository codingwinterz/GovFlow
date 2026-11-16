import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRoute, href } from "./router.js";

test("landing page at the root", () => {
  assert.deepEqual(parseRoute(""), { page: "home", shell: "landing" });
  assert.deepEqual(parseRoute("#/"), { page: "home", shell: "landing" });
});

test("citizen routes live under #/citizen", () => {
  assert.deepEqual(parseRoute("#/citizen"), { page: "citizen-home", shell: "citizen" });
  assert.deepEqual(parseRoute("#/citizen/check"), { page: "self-check", shell: "citizen" });
  assert.deepEqual(parseRoute("#/citizen/track"), { page: "track", shell: "citizen" });
});

test("old public links still reach the citizen pages", () => {
  assert.deepEqual(parseRoute("#/track"), { page: "track", shell: "citizen" });
  assert.deepEqual(parseRoute("#/self-check"), { page: "self-check", shell: "citizen" });
});

test("officer routes live under #/officer", () => {
  assert.deepEqual(parseRoute("#/officer"), { page: "queue", shell: "officer" });
  assert.deepEqual(parseRoute("#/officer/cases/LA-07"), { page: "case", id: "LA-07", shell: "officer" });
  assert.deepEqual(parseRoute("#/officer/cases/LA-07/audit"), { page: "audit", id: "LA-07", shell: "officer" });
  assert.deepEqual(parseRoute("#/officer/cases/LA-07/award"), { page: "award", id: "LA-07", shell: "officer" });
  for (const page of ["intake", "analytics", "simulator"])
    assert.deepEqual(parseRoute(`#/officer/${page}`), { page, shell: "officer" });
});

test("the duplicate staff status lookup is gone; unknown paths are not found", () => {
  assert.deepEqual(parseRoute("#/status"), { page: "notfound", shell: "landing" });
  assert.deepEqual(parseRoute("#/officer/status"), { page: "notfound", shell: "landing" });
  assert.deepEqual(parseRoute("#/citizen/queue"), { page: "notfound", shell: "landing" });
  assert.deepEqual(parseRoute("#/nope"), { page: "notfound", shell: "landing" });
});

test("href and parseRoute round-trip for every page", () => {
  for (const page of ["home", "citizen-home", "self-check", "track", "queue", "intake", "analytics", "simulator"])
    assert.equal(parseRoute(href(page)).page, page, page);
  for (const page of ["case", "audit", "award"])
    assert.deepEqual(parseRoute(href(page, "LA-07")), { page, id: "LA-07", shell: "officer" });
});

test("case ids are encoded and decoded", () => {
  assert.equal(href("case", "A B"), "#/officer/cases/A%20B");
  assert.deepEqual(parseRoute("#/officer/cases/A%20B"), { page: "case", id: "A B", shell: "officer" });
});
