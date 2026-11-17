// Citizen document pre-check helper logic (pure functions tested in node).
// English only; no arithmetic, no decisions, nothing saved.

export const PRECHECK_DISCLAIMER = "A quick check, not an application. An officer reviews every document.";
export const PRECHECK_LANGUAGE_NOTE = "Document pre-check feedback is in English.";
export const PRECHECK_NOTHING_SAVED_NOTE =
  "Nothing is saved: your file and its text are checked in memory and never stored.";
export const MAX_PRECHECK_BYTES = 10 * 1024 * 1024;
export const ALLOWED_EXTENSIONS = [".txt", ".png", ".jpg", ".jpeg", ".pdf"];

export function filterUploadableDocs(documents) {
  return (Array.isArray(documents) ? documents : []).filter(
    (d) => d && typeof d === "object" && d.id && d.id !== "application",
  );
}

export function normalizePrecheckOptions(data) {
  // An array (e.g. generic empty mock in layout tests) maps cleanly to an empty schemes list.
  if (Array.isArray(data)) {
    const valid = data
      .filter((s) => s && typeof s === "object" && typeof s.scheme === "string" && typeof s.title === "string")
      .map((s) => ({ ...s, documents: filterUploadableDocs(s.documents) }))
      .filter((s) => s.documents.length > 0);
    return {
      schemes: valid,
      disclaimer: PRECHECK_DISCLAIMER,
      language_note: PRECHECK_LANGUAGE_NOTE,
      nothing_saved_note: PRECHECK_NOTHING_SAVED_NOTE,
    };
  }
  if (!data || typeof data !== "object" || !Array.isArray(data.schemes)) {
    throw new Error("Invalid precheck options response");
  }
  const schemes = data.schemes
    .filter((s) => s && typeof s === "object" && typeof s.scheme === "string")
    .map((s) => ({
      scheme: s.scheme,
      title: s.title || s.scheme,
      documents: filterUploadableDocs(s.documents),
    }))
    .filter((s) => s.documents.length > 0);
  return {
    schemes,
    disclaimer: data.disclaimer || PRECHECK_DISCLAIMER,
    language_note: data.language_note || PRECHECK_LANGUAGE_NOTE,
    nothing_saved_note: data.nothing_saved_note || PRECHECK_NOTHING_SAVED_NOTE,
  };
}

export function validatePrecheckFile(file) {
  if (!file || !file.name) return "Choose a document file (.txt, .png, .jpg, or .pdf) to check.";
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return "Unsupported file type. Choose a .txt, .png, .jpg, or .pdf file.";
  }
  if (typeof file.size === "number" && file.size > MAX_PRECHECK_BYTES) {
    return "File is too large (maximum 10 MB).";
  }
  return null;
}

export function precheckBody(scheme, documentType, filename, contentBase64) {
  return {
    scheme: String(scheme || "").trim(),
    document_type: String(documentType || "").trim(),
    filename: String(filename || "").trim(),
    content_base64: String(contentBase64 || ""),
  };
}

export function precheckError(status, detail) {
  if (status === 429) return "Too many document checks. Please wait a few minutes and try again.";
  if (status === 413) return "File is too large (maximum 10 MB).";
  if (status === 400 && typeof detail === "string" && detail.trim()) return detail;
  if (status === 422) return "Could not check that document selection. Please choose a scheme, document type, and file.";
  return "Could not check the document just now. Please try again.";
}

const READABLE_TEXT = {
  yes: "Yes — all required details were read clearly",
  partly: "Partly — some details need attention",
  no: "No — could not read the required details",
};

export function precheckView(reply) {
  const readable = reply?.readable || "no";
  return {
    schemeLabel: reply?.scheme_label || "",
    documentLabel: reply?.document_label || "",
    readable,
    readableText: READABLE_TEXT[readable] || READABLE_TEXT.no,
    fields: (reply?.fields || []).map((f) => ({
      label: f.label,
      readStatus: f.status,
      whatWeRead: f.what_we_read ?? null,
    })),

    issues: Array.isArray(reply?.issues) ? reply.issues : [],
    nextSteps: Array.isArray(reply?.next_steps) ? reply.next_steps : [],
    usedFallback: !!reply?.used_fallback,
    disclaimer: reply?.disclaimer || PRECHECK_DISCLAIMER,
    languageNote: reply?.language_note || PRECHECK_LANGUAGE_NOTE,
    nothingSavedNote: reply?.nothing_saved_note || PRECHECK_NOTHING_SAVED_NOTE,
  };
}
