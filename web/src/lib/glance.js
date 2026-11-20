// At-a-glance helpers for the simplified pages. Words and filters only: no money, no dates, no arithmetic on API values.
import { appLabel, recommendationLabel } from "./display.js";

const SEVERITY_ORDER = ["high", "medium", "low"];
const CLOSED = ["approved", "rejected", "withdrawn"];
const items = (n, verb) => `${n} ${n === 1 ? "item" : "items"} ${n === 1 ? verb[0] : verb[1]}`;

// One plain line at the top of the case page. A recommendation, never a decision.
export function caseHeadline(d) {
  const n = (d.flags || []).length;
  if (d.status === "in_officer_review") {
    const attention = n === 0 ? "Nothing needs your attention." : `${items(n, ["needs", "need"])} your attention.`;
    const rec = d.recommendation ? ` The checks recommend: ${recommendationLabel(d.recommendation, d.recommendation_labels)}.` : "";
    return `Ready for your decision.${rec} ${attention}`;
  }
  if (d.status === "needs_info") return "Waiting for the citizen to send documents. The clock is paused.";
  if (d.status === "approved" || d.status === "rejected") return `Decided by an officer: ${appLabel("status", d.status)}.`;
  if (d.status === "withdrawn") return "Closed: the application was withdrawn.";
  return `Still being processed, not ready for a decision.${n ? ` ${items(n, ["needs", "need"])} attention.` : ""}`;
}

export function topSeverity(flags) {
  const present = new Set((flags || []).map((f) => f.severity));
  return SEVERITY_ORDER.find((s) => present.has(s)) ?? null;
}

// The queue's one-click filters, over the rows the API sent (its order kept).
export function queueRows(rows, filter) {
  const list = Array.isArray(rows) ? rows : [];
  if (filter === "attention") return list.filter((r) => (r.flags || []).length > 0);
  if (filter === "overdue") return list.filter((r) => r.overdue);
  return list;
}

// Analytics "Attention needed": open cases the API marks overdue, or with a high-severity flag.
export function attentionCases(rows) {
  return (Array.isArray(rows) ? rows : [])
    .filter((r) => !CLOSED.includes(r.status))
    .map((r) => ({ case_id: r.case_id, scheme: r.scheme, overdue: Boolean(r.overdue), high: topSeverity(r.flags) === "high" }))
    .filter((r) => r.overdue || r.high);
}

// The four analytics headline numbers, each the API field it names, as sent.
export function headlineTiles(a) {
  return [
    { key: "awaiting", label: "Cases awaiting a decision", value: a.by_status?.in_officer_review ?? 0, source: "by_status.in_officer_review" },
    { key: "overdue", label: "Overdue", value: a.overdue_count ?? 0, source: "overdue_count" },
    { key: "days_open", label: "Average days open", value: a.average_days_open ?? null, source: "average_days_open" },
    { key: "pending", label: "Total pending liability", value: a.liability?.pending_total ?? null, source: "liability.pending_total" },
  ];
}
