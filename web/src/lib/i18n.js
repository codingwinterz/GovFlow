// Translation templates with fixed placeholders. Templates contain no numbers: amounts and dates are
// formatted here, by code, from API values. No LLM generates or translates any text or number.
import { formatRupees, maskIdentifiers } from "./format.js";
import { readableFormula } from "./display.js";

export function placeholders(template) {
  return [...String(template).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
}

export function t(dict, key, vars = {}) {
  if (!(key in dict)) return `⟦${key}⟧`;          // visible gap, never invented wording
  return dict[key].replace(/\{(\w+)\}/g, (_, name) => {
    if (!(name in vars)) throw new Error(`Missing value for {${name}} in ${key}`);
    return String(vars[name]);
  });
}

// The "documents needed" notice from its stored items, in the reader's language. Same fixed templates as the
// server's copy (app/deficiency.py); document names from the dictionary, field names from the scheme's YAML labels.
export function noticeLines(needed, caseRef, dict) {
  const lines = [
    { kind: "heading", text: t(dict, "deficiency.title") },
    { kind: "intro", text: t(dict, "deficiency.intro", { case_ref: caseRef }) },
  ];
  for (const item of needed.items)
    lines.push({ kind: "item", text: t(dict, `deficiency.${item.kind}`,
      item.kind === "unreadable" || item.kind === "missing_field"
        ? { document: t(dict, `documents.${item.document}`), fields: item.field_labels.join(", ") }
        : { document: t(dict, `documents.${item.document}`) }) });
  lines.push({ kind: "footer", text: t(dict, "deficiency.footer") });
  lines.push({ kind: "date", text: t(dict, "deficiency.date", { date: needed.date }) });
  return lines;
}

// The citizen page as a list of lines: { kind, text }.
export function citizenLines(view, dict) {
  const lines = [
    { kind: "status", text: `${t(dict, "status.label")}: ${t(dict, `status.${view.status}`)}` },
    { kind: "next", text: `${t(dict, "next.label")}: ${t(dict, `next.${view.next_step}`)}` },
  ];
  if (view.missing.length) {
    lines.push({ kind: "heading", text: t(dict, "missing.title") });
    for (const m of view.missing)
      lines.push({ kind: "missing", text: t(dict, `missing.${m.reason}`, { document: t(dict, `documents.${m.document}`) }) });
  }
  for (const notice of view.notices || [])                // a key only: no flag detail reaches the public page
    lines.push({ kind: "notice", text: t(dict, `notice.${notice}`) });
  if (view.decision) {
    lines.push({ kind: "heading", text: t(dict, "decision.title") });
    lines.push({ kind: "decision", text: t(dict, `decision.${view.decision.decision}`) });
    lines.push({ kind: "date", text: t(dict, "decision.date", { date: view.decision.date }) });
  }
  if (view.amounts) {
    lines.push({ kind: "heading", text: t(dict, "amounts.title") });
    lines.push({ kind: "intro", text: t(dict, "amounts.intro") });
    for (const item of view.amounts.items) {
      lines.push({ kind: "item", text: t(dict, `component.${view.scheme}.${item.component}`, { amount: formatRupees(item.amount) }) });
      lines.push({ kind: "source", text: t(dict, "amounts.source",
        { source: readableFormula(maskIdentifiers(item.source), view.amounts.terms) }) });
    }
    lines.push({ kind: "total", text: t(dict, "amounts.total", { amount: formatRupees(view.amounts.total) }) });
    lines.push({ kind: "source", text: t(dict, "amounts.rules", { version: view.amounts.rules_version }) });
  }
  return lines;
}
