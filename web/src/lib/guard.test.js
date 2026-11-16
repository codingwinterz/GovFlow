// Guard: no rupee amount may be computed in the frontend, only displayed from API responses (CLAUDE.md rule 1).
// Scans code with comments and string text removed (template ${...} expressions are kept), and flags arithmetic
// where either operand names money: amount, total, sum, cost, price, rupee, compensation, relief, solatium,
// interest, award, assets. Also any .reduce( (summing in the UI). Words are matched per identifier part, so
// `totalAmount`, `item.cost` and `relief_total` count, while `summary` or `e.target.value` do not.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const MONEY = new Set(["amount", "amounts", "total", "totals", "subtotal", "sum", "cost", "costs", "price", "prices",
  "rupee", "rupees", "compensation", "relief", "solatium", "interest", "award", "assets"]);

function sources(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(jsx?|tsx?)$/.test(name) && !name.endsWith(".test.js") ? [path] : [];
  });
}

// Comments and string text become spaces (newlines kept, so line numbers hold); ${...} code inside templates stays.
export function codeOnly(src) {
  let out = "";
  const stack = [];   // template nesting: "`" while in template text, "{" while in a ${...} expression
  for (let i = 0; i < src.length; i++) {
    const c = src[i], next = src[i + 1], inTemplate = stack.at(-1) === "`";
    if (inTemplate) {
      if (c === "\\") { out += "  "; i++; continue; }
      if (c === "`") { stack.pop(); out += " "; continue; }
      if (c === "$" && next === "{") { stack.push("{"); out += "  "; i++; continue; }
      out += c === "\n" ? "\n" : " ";
      continue;
    }
    if (c === "/" && next === "/") { while (i < src.length && src[i] !== "\n") { out += " "; i++; } out += "\n"; continue; }
    if (c === "/" && next === "*") { const end = src.indexOf("*/", i + 2); const stop = end < 0 ? src.length : end + 2;
      out += src.slice(i, stop).replace(/[^\n]/g, " "); i = stop - 1; continue; }
    if (c === "'" || c === '"') { let j = i + 1; while (j < src.length && src[j] !== c && src[j] !== "\n") j += src[j] === "\\" ? 2 : 1;
      out += " ".repeat(j - i + 1); i = j; continue; }
    if (c === "`") { stack.push("`"); out += " "; continue; }
    if (c === "{" && stack.length) stack.push("{");
    if (c === "}" && stack.at(-1) === "{") { stack.pop(); if (stack.at(-1) === "`") { out += " "; continue; } }
    out += c;
  }
  return out;
}

const words = (id) => id.replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase().split(/[._$]+/);
const isMoney = (id) => /^[A-Za-z_$]/.test(id) && words(id).some((w) => MONEY.has(w));
const OPERAND = String.raw`[A-Za-z_$][\w$.]*|\d[\d.]*|\)|\]`;
const ARITH = new RegExp(String.raw`(${OPERAND})\s*(\*\*|[-+*/%])=?\s*(?=([A-Za-z_$][\w$.]*|\d|\())`, "g");

export function moneyArithmetic(src) {
  const hits = [];
  codeOnly(src).split("\n").forEach((line, i) => {
    if (/\.reduce\s*\(/.test(line)) hits.push(`${i + 1}: reduce (summing in the UI)`);
    for (const m of line.matchAll(ARITH)) {
      if (isMoney(m[1]) || isMoney(m[3] || "")) hits.push(`${i + 1}: ${m[1]} ${m[2]} ${m[3] || "("}`);
    }
  });
  return hits;
}

test("the guard catches money arithmetic under any money name, and ignores words in text", () => {
  const caught = ["const sum = a.cost + b.cost;", "total += row.value;", "items.map((i) => i.amount * 2)",
    "const half = relief / 2;", "x = 100 - item.price", "const s = `${c.solatium * 1.1}`", "list.reduce((a, b) => a + b)",
    "const n = landCompensation - deductions;", "awardTotal ** 2"];
  for (const line of caught) assert.notDeepEqual(moneyArithmetic(line), [], `missed: ${line}`);
  const fine = ['// fields that drive the amount-driving checks', 'const s = "total - see below";', "const t = `amount-${id}`;",
    "const pct = (100 * count) / top;", "const i = summary.length - 1;", "e.target.value", "formatRupees(item.amount)",
    "const width = `${barPercent(n, scale.top)}%`;", "/* total * 2 */ ok()"];
  for (const line of fine) assert.deepEqual(moneyArithmetic(line), [], `false alarm: ${line}`);
});

test("no file computes money", () => {
  const files = sources(SRC);
  assert.ok(files.length > 3, `expected source files under ${SRC}`);
  const hits = files.flatMap((file) => moneyArithmetic(readFileSync(file, "utf8")).map((h) => `${file}:${h}`));
  assert.deepEqual(hits, []);
});
