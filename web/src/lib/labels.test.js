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

test("the self-check page shows the API's guide label with every result", () => {
  const source = readFileSync(join(PAGES, "SelfCheck.jsx"), "utf8");
  assert.match(source, /result\.guide_label/);
  assert.doesNotMatch(source, /eligible\s*=|\.reduce\(/);   // no eligibility logic in the browser
});

test("days open and overdue come from the API, never from browser date arithmetic", () => {
  for (const name of readdirSync(PAGES)) {
    const source = readFileSync(join(PAGES, name), "utf8");
    assert.doesNotMatch(source, /Date\.now\(|\.getTime\(\)|new Date\(\)\s*-/, name);
  }
  const queue = readFileSync(join(PAGES, "Queue.jsx"), "utf8");
  assert.match(queue, /c\.days_open/);
  assert.match(queue, /c\.overdue/);
});

test("award page prints API values with the demo mark and computes nothing", () => {
  const source = readFileSync(join(PAGES, "Award.jsx"), "utf8");
  assert.match(source, /a\.total/);
  assert.match(source, /window\.print\(\)/);
  assert.match(source, /DEMO/);
});
