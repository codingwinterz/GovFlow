// Display helpers. Nothing here computes money: amounts are formatted exactly as the API returned them.

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

export function fieldSource(f) {
  const parts = [`${f.document_type} #${f.document_id}`, `field ${f.field}`];
  if (f.source_page) parts.push(`page ${f.source_page}`);
  parts.push(f.method);
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

export function formatDate(iso) {
  return iso ? new Date(iso).toLocaleString("en-IN") : "—";
}
