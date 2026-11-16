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

export function schemeTitle(schemes, id) {
  return (schemes || []).find((s) => s.scheme === id)?.labels?.title ?? humanize(id);
}
