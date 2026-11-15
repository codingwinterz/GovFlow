// Guard: no rupee amount may be computed in the frontend, only displayed from API responses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

function sources(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(jsx?|tsx?)$/.test(name) && !name.endsWith(".test.js") ? [path] : [];
  });
}

const FORBIDDEN = [
  [/\bamount\s*[-+*/]/, "arithmetic on an amount"],
  [/[-+*/]\s*[\w.]*\.amount\b/, "arithmetic on an amount"],
  [/\.reduce\s*\(/, "reduce (summing in the UI)"],
  [/\btotal\s*[-+*/]=?/, "arithmetic on a total"],
];

test("no file computes money", () => {
  const files = sources(SRC);
  assert.ok(files.length > 3, `expected source files under ${SRC}`);
  const hits = [];
  for (const file of files) {
    readFileSync(file, "utf8").split("\n").forEach((line, i) => {
      for (const [pattern, why] of FORBIDDEN) if (pattern.test(line)) hits.push(`${file}:${i + 1} ${why}: ${line.trim()}`);
    });
  }
  assert.deepEqual(hits, []);
});
