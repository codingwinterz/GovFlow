// Human labels for every identifier a user can see. Scheme ids come from the YAML terms (via the API);
// app-level ids (statuses, results, flags, audit actions) from i18n/labels.en.json.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { APP_LABELS, appLabel, humanize, queueReason, readable, readableFormula, schemeTitle, termLabel } from "./display.js";

const SRC = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const APP_DIR = join(SRC, "..", "..", "app");
const python = () => readdirSync(APP_DIR).filter((f) => f.endsWith(".py")).map((f) => readFileSync(join(APP_DIR, f), "utf8")).join("\n");
const TERMS = { area_sqm: "Area (sq m)", market_value_per_sqm: "Market value per sq m", multiplier: "Rural multiplier",
  damage_percent: "Damage (%)", damage_assessment: "Damage assessment report", name_match: "Name matches across documents" };

test("humanize is the floor: never an underscore, first letter capital", () => {
  assert.equal(humanize("in_officer_review"), "In officer review");
  assert.equal(humanize("ownership_record.survey_number"), "Survey number");
  assert.equal(humanize(""), "");
});

test("scheme terms: exact, then the plain field, then humanize", () => {
  assert.equal(termLabel(TERMS, "multiplier"), "Rural multiplier");
  assert.equal(termLabel(TERMS, "damage_assessment.damage_percent"), "Damage (%)");
  assert.equal(termLabel(TERMS, "not_labelled_yet"), "Not labelled yet");
  assert.equal(termLabel(undefined, "x_y"), "X y");
});

test("app labels cover every case status the backend defines", () => {
  const block = python().match(/CASE_STATUSES = \(([^)]*)\)/)[1];
  const statuses = [...block.matchAll(/"(\w+)"/g)].map((m) => m[1]);
  assert.ok(statuses.length >= 9);
  for (const s of statuses) assert.ok(s in APP_LABELS.status, s);
});

test("app labels cover every audit action the backend writes", () => {
  const actions = new Set([...python().matchAll(/log_action\([^,]+, [^,]+, [^,]+, "(\w+)"/g)].map((m) => m[1]));
  assert.ok(actions.size >= 15);
  for (const a of actions) assert.ok(a in APP_LABELS.action, a);
});

test("no app label is itself an identifier", () => {
  for (const [group, labels] of Object.entries(APP_LABELS))
    for (const [id, label] of Object.entries(labels)) assert.doesNotMatch(label, /_/, `${group}.${id}`);
  assert.equal(appLabel("status", "in_officer_review"), "Awaiting officer decision");
  assert.equal(appLabel("result", "needs_review"), "Needs review");
  assert.equal(appLabel("status", "brand_new"), "Brand new");
});

test("readable replaces identifiers inside backend sentences and leaves words alone", () => {
  assert.equal(readable("damage_assessment.damage_percent: below the confidence threshold", TERMS),
    "Damage (%): below the confidence threshold");
  assert.equal(readable("Check name_match failed, e.g. spelling.", TERMS), "Check Name matches across documents failed, e.g. spelling.");
  assert.equal(readable("totally_unknown_thing missing", TERMS), "Totally unknown thing missing");
  assert.doesNotMatch(readable("a_b c_d_e f.g_h", TERMS), /_/);
  assert.equal(readable(null, TERMS), "");
});

test("analytics source notes name record fields in words", () => {
  assert.equal(readable("case created_at to officer_decision audit entry", {}), "case intake date to Officer decision audit entry");
  assert.equal(readable("against the scheme's sla_days; else case updated_at", {}),
    "against the scheme's SLA target (days); else case last update");
});

test("readable keeps masked identifiers and dates intact", () => {
  assert.equal(readable("XXXX XXXX 0001 expires 2030-12-31", TERMS), "XXXX XXXX 0001 expires 2030-12-31");
});

test("formulas read as words and symbols", () => {
  assert.equal(readableFormula("area_sqm * market_value_per_sqm * multiplier with area_sqm=800, multiplier=1", TERMS),
    "Area (sq m) × Market value per sq m × Rural multiplier with Area (sq m) = 800, Rural multiplier = 1");
  assert.equal(readableFormula("4000 * (damage_percent >= 15) * (damage_percent < 75)", TERMS),
    "4000 × (Damage (%) ≥ 15) × (Damage (%) < 75)");
  assert.equal(readableFormula("x != 'hut' and y == 'plain'", {}), "x ≠ 'hut' and y = 'plain'");
  // in a formula a single-word identifier is a term too; quoted category values stay as written
  assert.equal(readableFormula("hut * (house_type == 'hut')", { hut: "Damaged hut", house_type: "House type" }),
    "Damaged hut × (House type = 'hut')");
});

test("a scheme is shown by its YAML title, never its id", () => {
  const schemes = [{ scheme: "disaster_relief", labels: { title: "Disaster relief: housing damage" } }];
  assert.equal(schemeTitle(schemes, "disaster_relief"), "Disaster relief: housing damage");
  assert.equal(schemeTitle(undefined, "land_acquisition"), "Land acquisition");
});

test("pages never print a raw identifier field directly", () => {
  const RAW = /[>}\s]\{\s*[a-z]+\.(status|scheme|rule_id|component|doc_type|kind|action|overall|compensation_status|extraction_status|recommendation|field|name)\s*\}/;
  const hits = [];
  for (const dir of ["pages", "shells"])
    for (const name of readdirSync(join(SRC, dir)))
      readFileSync(join(SRC, dir, name), "utf8").split("\n").forEach((line, i) => {
        if (RAW.test(line)) hits.push(`${dir}/${name}:${i + 1}: ${line.trim()}`);
      });
  assert.deepEqual(hits, []);
});

test("the queue shows the most severe flag's reason, not a generic badge", () => {
  const terms = { name_match: "Name matches across documents" };
  assert.equal(queueReason([], terms), null);
  assert.deepEqual(queueReason([{ kind: "low_confidence", severity: "medium" }], terms),
    { label: "Low-confidence reading", more: 0, all: ["Low-confidence reading"] });
  const mixed = [{ kind: "low_confidence", severity: "medium" }, { kind: "name_match", severity: "high" },
    { kind: "missing_document", severity: "high" }];
  assert.deepEqual(queueReason(mixed, terms), { label: "Name matches across documents", more: 2,
    all: ["Name matches across documents", "Document missing", "Low-confidence reading"] });
});

test("the queue page shows the flag reason and the overdue badge, not a generic needs-review badge", () => {
  const queue = readFileSync(join(SRC, "pages", "Queue.jsx"), "utf8");
  assert.match(queue, /queueReason\(/);
  assert.match(queue, /c\.overdue && <span className="badge warn">overdue<\/span>/);
  assert.doesNotMatch(queue, />needs review</);
});
