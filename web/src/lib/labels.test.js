// Guard: scheme wording comes from the API (YAML labels), never from the pages.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const PAGES = new URL("../pages", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

test("pages contain no scheme-specific wording", () => {
  const hits = [];
  for (const name of readdirSync(PAGES)) {
    readFileSync(join(PAGES, name), "utf8").split("\n").forEach((line, i) => {
      if (/\b(Compensation|Relief|compensation total|land value)\b/.test(line)) hits.push(`${name}:${i + 1}: ${line.trim()}`);
    });
  }
  assert.deepEqual(hits, []);
});

test("the case page reads its section labels from the API", () => {
  const source = readFileSync(join(PAGES, "CasePage.jsx"), "utf8");
  assert.match(source, /labels\.amounts/);
  assert.match(source, /labels\.total/);
});
