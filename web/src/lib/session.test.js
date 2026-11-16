import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { authHeaders, isCurrent } from "./session.js";

const NOW = new Date("2026-11-16T09:00:00Z");
const LOGIN = { role: "officer", user: "O-1", token: "abc.def", expires_at: "2026-11-16T17:00:00Z" };

test("a signed-in officer sends the token as a Bearer header, never role headers", () => {
  assert.deepEqual(authHeaders(LOGIN, NOW), { Authorization: "Bearer abc.def" });
});

test("an expired, token-less or missing login sends nothing (the shell shows sign-in)", () => {
  assert.equal(isCurrent({ ...LOGIN, expires_at: "2026-11-16T08:59:59Z" }, NOW), false);
  assert.equal(isCurrent({ role: "officer", user: "O-1" }, NOW), false);   // a login saved before tokens
  assert.equal(isCurrent(null, NOW), false);
  assert.deepEqual(authHeaders({ ...LOGIN, expires_at: "2026-11-16T09:00:00Z" }, NOW), {});
});

test("no client code sends X-Role or X-User", () => {
  const api = readFileSync(new URL("../api.js", import.meta.url), "utf8");
  assert.doesNotMatch(api, /X-Role|X-User/);
  assert.match(api, /authHeaders\(/);
});
