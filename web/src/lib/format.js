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

export function validateDecision(decision, comment, confirmFields = [], checked = {}, resolutionsNeeded = [], resolutions = {}) {
  if (!["approve", "reject", "send_back"].includes(decision)) return "Choose approve, reject or send back.";
  if (decision !== "approve" && !String(comment || "").trim()) return "A comment is required to reject or send back.";
  if (decision === "approve" && confirmFields.some((f) => !checked[f.ref]))
    return "Tick each value below once you have checked it against the document.";
  if (decision === "approve" && resolutionsNeeded.some((r) => !String(resolutions[r.flag]?.reference || "").trim()
      || !/^\d{4}-\d{2}-\d{2}$/.test(String(resolutions[r.flag]?.date || ""))))
    return "Record the resolution (reference and date) for each open rights entry below.";
  return null;
}

// What approval sends for each open flag that needs a resolution (the server re-checks every one).
export function resolutionsBody(resolutionsNeeded = [], resolutions = {}) {
  return Object.fromEntries(resolutionsNeeded.map((r) => [r.flag, {
    reference: String(resolutions[r.flag]?.reference || "").trim(), date: resolutions[r.flag]?.date || "" }]));
}

// What approval sends: each field that drives an amount, at the value the officer saw and ticked (the server re-checks).
export function confirmedFields(confirmFields = [], checked = {}) {
  return Object.fromEntries(confirmFields.filter((f) => checked[f.ref]).map((f) => [f.ref, f.value]));
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

// Every date and time is shown in India time, whatever zone the viewer's browser is set to.
const INDIA = "Asia/Kolkata";
const DAY = { day: "numeric", month: "short", year: "numeric", timeZone: INDIA };

export function formatDate(iso) {   // to the minute: "7 Sept 2026, 12:37 pm"
  return iso ? parseUtc(iso).toLocaleString("en-IN", { ...DAY, hour: "numeric", minute: "2-digit" }) : "—";
}

export function formatDay(iso) {    // "7 Sept 2026"
  return iso ? parseUtc(iso).toLocaleDateString("en-IN", DAY) : "—";
}

export function todayInIndia(now = new Date()) {   // "2026-11-20": YYYY-MM-DD for a date input
  return now.toLocaleDateString("en-CA", { timeZone: INDIA });
}
