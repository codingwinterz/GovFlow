// Display helpers. Nothing here computes money: amounts are formatted exactly as the API returned them.
import { appLabel, termLabel } from "./display.js";

const RUPEES = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2 });
const ID_PATTERN = /(?<!\d)\d{4}[ -]?\d{4}[ -]?(\d{4})(?!\d)/g;   // same rule as app/privacy.py

export function formatRupees(amount) {
  return amount === null || amount === undefined ? "—" : RUPEES.format(amount);
}

export function maskIdentifiers(value) {
  return String(value).replace(ID_PATTERN, (_, last4) => `XXXX XXXX ${last4}`);
}

export function formatConfidence(c) {
  return c === null || c === undefined ? "—" : Number(c).toFixed(2);
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (days > 0) return `${days} d ${hours} h`;
  if (hours > 0) return `${hours} h ${minutes} min`;
  return `${minutes} min`;
}

export function fieldSource(f, terms) {
  const parts = [`${termLabel(terms, f.document_type)} #${f.document_id}`, termLabel(terms, `${f.document_type}.${f.field}`)];
  if (f.source_page) parts.push(`page ${f.source_page}`);
  parts.push(appLabel("method", f.method));
  return parts.join(" · ");
}

export function validateDecision(decision, comment) {
  if (!["approve", "reject", "send_back"].includes(decision)) return "Choose approve, reject or send back.";
  if (decision !== "approve" && !String(comment || "").trim()) return "A comment is required to reject or send back.";
  return null;
}

export function unavailableDocuments(detail) {
  return (detail.documents || []).filter((d) => d.current && d.extraction_status === "extraction_unavailable");
}

// The API sends UTC with an explicit Z (app.models.iso_utc). A value without a zone is still read as UTC,
// never browser-local, as a safety net for older saved responses.
function parseUtc(iso) {
  const s = String(iso);
  return new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(s) || !s.includes("T") ? s : `${s}Z`);
}

const DAY = { day: "numeric", month: "short", year: "numeric" };

export function formatDate(iso) {   // to the minute: "7 Sept 2026, 12:37 pm"
  return iso ? parseUtc(iso).toLocaleString("en-IN", { ...DAY, hour: "numeric", minute: "2-digit" }) : "—";
}

export function formatDay(iso) {    // "7 Sept 2026"
  return iso ? parseUtc(iso).toLocaleDateString("en-IN", DAY) : "—";
}
