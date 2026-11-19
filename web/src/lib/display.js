// Turns identifiers into words for the screen. Scheme identifiers use the scheme YAML's `terms` (sent by the API);
// app-level identifiers use i18n/labels.en.json. Anything unlabelled is humanized, so no snake_case reaches a user.
import APP from "../i18n/labels.en.json" with { type: "json" };

export const APP_LABELS = APP;
const PROSE_GROUPS = ["status", "recommendation", "result", "flag", "action", "decision", "record"];

export function humanize(id) {
  const last = String(id ?? "").split(".").pop().replace(/_+/g, " ").trim();
  return last ? last[0].toUpperCase() + last.slice(1) : "";
}

export function appLabel(group, id) {
  return APP[group]?.[id] ?? humanize(id);
}

function explicitTerm(terms, id) {
  if (!terms) return undefined;
  if (id in terms) return terms[id];
  return id.includes(".") ? terms[id.split(".").slice(1).join(".")] : undefined;
}

export function termLabel(terms, id) {
  return explicitTerm(terms, id) ?? humanize(id);
}

// A verification flag's kind is either a scheme check id (name_match) or an app-level kind (low_confidence).
export function flagLabel(terms, kind) {
  return explicitTerm(terms, kind) ?? appLabel("flag", kind);
}

function anyLabel(terms, id) {
  const term = explicitTerm(terms, id);
  if (term !== undefined) return term;
  for (const group of PROSE_GROUPS) if (APP[group][id]) return APP[group][id];
  return humanize(id);
}

// Prose from the backend (reasons, flag details, explanations): replace identifiers, leave ordinary words alone.
// An identifier is a lowercase token with an underscore, or dotted with a known first part (document.field).
export function readable(text, terms) {
  if (text === null || text === undefined) return "";
  return String(text).replace(/\b[a-z][a-z0-9]*(?:[._][a-z0-9]+)+\b/g, (token) => {
    const dotted = token.includes(".");
    const known = dotted && terms && token.split(".")[0] in terms;
    return token.includes("_") || known ? anyLabel(terms, token) : token;
  });
}

// A formula (or "formula with a=1, b=2"): every identifier outside quotes becomes its label; operators become symbols.
export function readableFormula(formula, terms) {
  const words = String(formula ?? "").split(/('[^']*')/).map((part, i) => (i % 2 === 1 ? part
    : part.replace(/\b[a-z][a-z0-9_]*\b/g, (id) => (explicitTerm(terms, id) ?? (id.includes("_") ? anyLabel(terms, id) : id)))));
  return words.join("")
    .replace(/\s*==\s*/g, " = ").replace(/\s*!=\s*/g, " ≠ ").replace(/\s*>=\s*/g, " ≥ ").replace(/\s*<=\s*/g, " ≤ ")
    .replace(/\s*\*\s*/g, " × ").replace(/([^\s=<>≥≤≠])=([^\s=])/g, "$1 = $2");
}

const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };

// The queue's reason badge: the most severe flag's label (first stored among equals), plus how many others.
export function queueReason(flags, terms) {
  if (!flags || flags.length === 0) return null;
  const sorted = [...flags].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3));
  const all = sorted.map((f) => flagLabel(terms, f.kind));
  return { label: all[0], more: all.length - 1, all };
}

export function schemeTitle(schemes, id) {
  return (schemes || []).find((s) => s.scheme === id)?.labels?.title ?? humanize(id);
}

// Clause references. Until a clause is confirmed the YAML holds a placeholder in angle brackets ("<clause ref>",
// "<DSSS clause: ...>"; each marked VERIFY). The placeholder is never shown: the cell reads as not yet cited.
const CLAUSE_PLACEHOLDER = /^<[^<>]*>$/;

export function clauseText(clause) {
  const s = String(clause ?? "").trim();
  return s === "" || CLAUSE_PLACEHOLDER.test(s) ? null : s;
}

// The stored explanation (audit log, never edited) quotes each rule's clause as written. On screen, drop a placeholder
// clause with its brackets or parentheses; the surrounding sentence and real references are left as they are.
const CLAUSE_IN_PROSE = /[ \t]*(?:\[<[^<>\n]*clause[^<>\n]*>\]|\(<[^<>\n]*clause[^<>\n]*>\)|<[^<>\n]*clause[^<>\n]*>)/gi;

export function withoutClausePlaceholders(text) {
  if (text === null || text === undefined) return "";
  return String(text).replace(CLAUSE_IN_PROSE, "");
}

// The stored explanation as blocks for reading: lines starting "- " become list items, every other non-blank line a
// paragraph. Layout only: no word is added, removed or changed.
export function explanationBlocks(text) {
  const blocks = [];
  for (const line of String(text ?? "").split("\n")) {
    if (line.trim() === "") continue;
    if (line.startsWith("- ")) {
      const last = blocks[blocks.length - 1];
      if (last?.kind === "list") last.items.push(line.slice(2));
      else blocks.push({ kind: "list", items: [line.slice(2)] });
    } else blocks.push({ kind: "p", text: line });
  }
  return blocks;
}
