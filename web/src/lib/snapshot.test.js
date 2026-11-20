// Regression snapshot: the citizen page lines for LA-01, DR-01 and SW-01 (approved), in all four languages,
// built from the API output captured on main (tests/snapshots/*.json) before the revenue mutation changes.
// The golden lines (citizen_snapshots.json) were written once on main and must never be rewritten to pass.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { citizenLines } from "./i18n.js";

const dir = (p) => new URL(p, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const read = (p) => JSON.parse(readFileSync(dir(p), "utf8"));
const LANGS = ["en", "hi", "mr", "kok"];
const CASES = ["LA-01", "DR-01", "SW-01"];
const golden = read("./citizen_snapshots.json");

for (const id of CASES)
  test(`citizen page for ${id} is unchanged in every language`, () => {
    const view = read(`../../../tests/snapshots/${id}.json`).citizen_view;
    for (const lang of LANGS)
      assert.deepEqual(citizenLines(view, read(`../i18n/${lang}.json`)), golden[id][lang], `${id} ${lang}`);
  });

test("the golden citizen pages include the amounts section", () => {
  for (const id of CASES) assert.ok(golden[id].en.some((l) => l.kind === "total"), id);
});
