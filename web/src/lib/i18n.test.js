import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { citizenLines, placeholders, t } from "./i18n.js";

const dir = (p) => new URL(p, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const load = (lang) => JSON.parse(readFileSync(dir(`../i18n/${lang}.json`), "utf8"));
const LANGS = ["en", "hi", "mr", "kok"];
const DICTS = Object.fromEntries(LANGS.map((l) => [l, load(l)]));

test("every language file has exactly the English keys", () => {
  const en = Object.keys(DICTS.en).sort();
  for (const lang of LANGS) assert.deepEqual(Object.keys(DICTS[lang]).sort(), en, lang);
});

test("every template keeps the same placeholders as English", () => {
  for (const lang of LANGS)
    for (const [key, text] of Object.entries(DICTS.en))
      assert.deepEqual(placeholders(DICTS[lang][key]), placeholders(text), `${lang} ${key}`);
});

test("no template contains a number: numbers are inserted by code from API values", () => {
  for (const lang of LANGS)
    for (const [key, text] of Object.entries(DICTS[lang]))
      assert.doesNotMatch(text, /[0-9०-९]/, `${lang} ${key}`);
});

test("non-English files are marked as needing native-speaker review; English is the source", () => {
  assert.equal(DICTS.en["_meta.review"], "source");
  for (const lang of ["hi", "mr", "kok"]) assert.equal(DICTS[lang]["_meta.review"], "needs native-speaker review");
});

function yamlIds(scheme, section) {
  const text = readFileSync(dir(`../../../rules/${scheme}.yaml`), "utf8");
  const lines = text.split("\n");
  const ids = [];
  let inside = false;
  for (const line of lines) {
    if (/^\S/.test(line)) inside = line.startsWith(`${section}:`);
    else if (section === "components" && /^  components:/.test(line)) inside = true;
    else if (section === "components" && /^  \S/.test(line)) inside = false;
    const m = inside && line.match(/^\s*- id: (\w+)/);
    if (m) ids.push(m[1]);
  }
  return ids;
}

test("every document and amount component in the rules has a template", () => {
  for (const scheme of ["land_acquisition", "disaster_relief"]) {
    const docs = yamlIds(scheme, "required_documents");
    const components = yamlIds(scheme, "components");
    assert.ok(docs.length >= 4 && components.length >= 3, scheme);
    for (const d of docs) assert.ok(`documents.${d}` in DICTS.en, `documents.${d}`);
    for (const c of components) assert.ok(`component.${scheme}.${c}` in DICTS.en, `component.${scheme}.${c}`);
  }
});

test("t fills placeholders and flags unknown keys instead of inventing text", () => {
  assert.equal(t(DICTS.en, "decision.date", { date: "2026-11-20" }), "Decided on 2026-11-20");
  assert.equal(t(DICTS.en, "no.such.key"), "⟦no.such.key⟧");
  assert.throws(() => t(DICTS.en, "decision.date", {}), /date/);
});

const APPROVED = {
  case_ref: "LA-01", scheme: "land_acquisition", status: "approved", next_step: "approved", missing: [],
  decision: { decision: "approve", date: "2026-11-20" },
  amounts: { rules_version: "0.1.0", total: 17200000, items: [
    { component: "land_value", amount: 7500000, source: "area_sqm * market_value_per_sqm * multiplier with area_sqm=2500" },
    { component: "interest", amount: 1800000, source: "land_value * interest_rate * years_since_notification with ..." },
  ] },
};

test("why-this-amount lines use API amounts formatted by code and cite the officer-view source", () => {
  for (const lang of LANGS) {
    const lines = citizenLines(APPROVED, DICTS[lang]);
    const text = lines.map((l) => l.text).join("\n");
    assert.match(text, /₹75,00,000\.00/);
    assert.match(text, /₹1,72,00,000\.00/);
    assert.match(text, /2026-11-20/);
    assert.ok(text.includes(APPROVED.amounts.items[0].source), lang);
  }
});

test("missing documents are shown with translated names", () => {
  const view = { ...APPROVED, status: "needs_info", next_step: "provide_documents", decision: null, amounts: null,
    missing: [{ document: "mutation_record", reason: "missing" }, { document: "identity_proof", reason: "expired" }] };
  const text = citizenLines(view, DICTS.en).map((l) => l.text).join("\n");
  assert.match(text, /Mutation record: not submitted/);
  assert.match(text, /Identity proof: expired/);
  assert.doesNotMatch(text, /Why this amount/);
});
