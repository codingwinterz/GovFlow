import { test } from "node:test";
import assert from "node:assert/strict";
import { errorMessage, readList, retryable, trackProblem } from "./states.js";

const err = (status, message = "") => Object.assign(new Error(message), { status });

test("failures read as plain sentences, never 'Error 500'", () => {
  assert.match(errorMessage(new TypeError("Failed to fetch")), /Cannot reach the server/);
  assert.match(errorMessage(err(500, "Internal Server Error")), /server had a problem/);
  assert.match(errorMessage(err(401)), /sign in again/);
  assert.match(errorMessage(err(403)), /role cannot/);
  assert.equal(errorMessage(err(404, "Unknown case NOPE-1")), "Unknown case NOPE-1");   // the API wrote it for people
  for (const s of [undefined, 401, 403, 404, 409, 429, 500, 503]) assert.doesNotMatch(errorMessage(err(s, "x")), /Error \d/);
});

test("Retry is offered only when the same request may work next time", () => {
  assert.equal(retryable(new TypeError("offline")), true);
  assert.equal(retryable(err(503)), true);
  assert.equal(retryable(err(429)), true);
  for (const s of [400, 401, 403, 404, 409]) assert.equal(retryable(err(s)), false);
});

test("tracking input is checked before it is sent", () => {
  assert.equal(trackProblem("", "123456"), "track.invalid_ref");
  assert.equal(trackProblem("LA 01", "123456"), "track.invalid_ref");
  assert.equal(trackProblem("LA-01", ""), "track.invalid_code");
  assert.equal(trackProblem("LA-01", "12345"), "track.invalid_code");
  assert.equal(trackProblem("LA-01", "12a456"), "track.invalid_code");
  assert.equal(trackProblem(" LA-01 ", " 123456 "), null);
});

test("the self-check list must be a successful list, or it is a load error", async () => {
  const response = (ok, body) => ({ ok, status: ok ? 200 : 500, json: async () => body });
  assert.deepEqual(await readList(response(true, [{ scheme: "x" }])), [{ scheme: "x" }]);
  await assert.rejects(readList(response(false, { detail: "boom" })));
  await assert.rejects(readList(response(true, { detail: "not a list" })));   // r.ok but not an array
});
