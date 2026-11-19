import { useEffect, useState } from "react";
import { readFileAsBase64 } from "../api.js";
import {
  PRECHECK_DISCLAIMER,
  PRECHECK_LANGUAGE_NOTE,
  PRECHECK_NOTHING_SAVED_NOTE,
  normalizePrecheckOptions,
  precheckBody,
  precheckError,
  precheckView,
  validatePrecheckFile,
} from "../lib/precheck.js";

// Citizen document pre-check: stateless, in-memory check of one document before applying.
// English feedback whatever the page language; nothing is saved on disk, in the database, or in logs.
export default function Precheck({ activeScheme, reloadKey = 0, pageError = false }) {
  const [options, setOptions] = useState({
    state: "loading",
    schemes: [],
    disclaimer: PRECHECK_DISCLAIMER,
    languageNote: PRECHECK_LANGUAGE_NOTE,
    nothingSavedNote: PRECHECK_NOTHING_SAVED_NOTE,
  });
  const [schemeId, setSchemeId] = useState("");
  const [docType, setDocType] = useState("");
  const [file, setFile] = useState(null);
  const [check, setCheck] = useState({ state: "idle", view: null, error: "", canRetry: false });

  const loadOptions = () => {
    setOptions((prev) => ({ ...prev, state: "loading" }));
    fetch("/api/public/precheck")
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((data) => {
        const parsed = normalizePrecheckOptions(data);
        const firstScheme = parsed.schemes.find((s) => s.scheme === activeScheme) || parsed.schemes[0] || null;
        setOptions({
          state: "ready",
          schemes: parsed.schemes,
          disclaimer: parsed.disclaimer,
          languageNote: parsed.language_note,
          nothingSavedNote: parsed.nothing_saved_note,
        });
        setSchemeId(firstScheme ? firstScheme.scheme : "");
        setDocType(firstScheme?.documents[0]?.id || "");
      })
      .catch(() => setOptions((prev) => ({ ...prev, state: "error", schemes: [] })));
  };

  useEffect(() => {
    loadOptions();
  }, [reloadKey]);

  const currentScheme = options.schemes.find((s) => s.scheme === schemeId) || options.schemes[0] || null;
  const documents = currentScheme ? currentScheme.documents : [];
  const currentDoc = documents.find((d) => d.id === docType)?.id || documents[0]?.id || "";

  const runPrecheck = async () => {
    const fileProblem = validatePrecheckFile(file);
    if (fileProblem) {
      setCheck({ state: "error", view: null, error: fileProblem, canRetry: false });
      return;
    }
    if (!currentScheme || !currentDoc) return;
    setCheck({ state: "loading", view: null, error: "", canRetry: true });
    try {
      const b64 = await readFileAsBase64(file);
      const r = await fetch("/api/public/precheck", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(precheckBody(currentScheme.scheme, currentDoc, file.name, b64)),
      });
      const data = await r.json().catch(() => null);
      if (!r.ok) {
        setCheck({
          state: "error",
          view: null,
          error: precheckError(r.status, data?.detail),
          canRetry: true,
        });
        return;
      }
      setCheck({ state: "ready", view: precheckView(data), error: "", canRetry: false });
    } catch {
      setCheck({ state: "error", view: null, error: precheckError(0), canRetry: true });
    }
  };

  return (
    <section className="card precheck" aria-labelledby="precheck-heading" lang="en">
      <h2 id="precheck-heading">Check a document before you apply</h2>
      <p className="muted small">{options.languageNote}</p>
      <p className="banner info precheck-privacy"><strong>{options.nothingSavedNote}</strong></p>
      <p className="banner warn"><strong>{options.disclaimer}</strong></p>

      {options.state === "loading" && !pageError && (
        <p className="muted" role="status" aria-live="polite">Loading document check options…</p>
      )}
      {options.state === "error" && !pageError && (
        <div className="banner warn" role="alert">
          <p>Could not load the document pre-check options.</p>
          <button type="button" onClick={loadOptions}>Retry</button>
        </div>
      )}
      {options.state === "ready" && options.schemes.length === 0 && (
        <p className="muted">No documents are configured for pre-check yet.</p>
      )}

      {options.state === "ready" && currentScheme && (
        <form onSubmit={(e) => { e.preventDefault(); runPrecheck(); }}>
          <label>Scheme for document check
            <select
              value={currentScheme.scheme}
              onChange={(e) => {
                const next = options.schemes.find((s) => s.scheme === e.target.value);
                setSchemeId(e.target.value);
                setDocType(next?.documents[0]?.id || "");
                setCheck({ state: "idle", view: null, error: "", canRetry: false });
              }}
            >
              {options.schemes.map((s) => <option key={s.scheme} value={s.scheme}>{s.title}</option>)}
            </select>
          </label>
          <label>Document type
            <select
              value={currentDoc}
              onChange={(e) => {
                setDocType(e.target.value);
                setCheck({ state: "idle", view: null, error: "", canRetry: false });
              }}
            >
              {documents.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>
          </label>
          <label>Document file (.txt, .png, .jpg, .pdf; maximum 10 MB)
            <input
              type="file"
              accept=".txt,.png,.jpg,.jpeg,.pdf"
              onChange={(e) => {
                setFile(e.target.files?.[0] || null);
                setCheck({ state: "idle", view: null, error: "", canRetry: false });
              }}
            />
          </label>
          <button type="submit" disabled={check.state === "loading"}>
            {check.state === "loading" ? "Checking…" : "Check document"}
          </button>
        </form>
      )}

      <div role="status" aria-live="polite" className="precheck-live">
        {options.state === "ready" && options.schemes.length > 0 && check.state === "idle" && (
          <p className="muted small">
            Choose a scheme, a document type, and a file to check whether its required details can be read clearly.
          </p>
        )}
        {check.state === "loading" && (
          <p className="muted">Checking your document in memory…</p>
        )}
        {check.state === "ready" && check.view && (
          <div className="citizen-view precheck-result">
            <h3>{check.view.documentLabel} ({check.view.schemeLabel})</h3>
            <p className="line status"><strong>Readable: {check.view.readableText}</strong></p>
            <p className="banner warn"><strong>{check.view.disclaimer}</strong></p>
            {check.view.usedFallback && (
              <p className="muted small">Checked with OCR fallback only.</p>
            )}
            <h4>Fields checked</h4>
            <ul>
              {check.view.fields.map((f) => (
                <li key={f.label}>
                  <strong>{f.label}:</strong> {f.readStatus}
                  {f.whatWeRead ? <span> — What we read: {f.whatWeRead}</span> : null}
                </li>
              ))}
            </ul>

            {check.view.issues.length > 0 && (
              <>
                <h4>Issues found</h4>
                <ul>
                  {check.view.issues.map((issue, idx) => <li key={idx}>{issue}</li>)}
                </ul>
              </>
            )}
            {check.view.nextSteps.length > 0 && (
              <>
                <h4>Next steps</h4>
                <ul>
                  {check.view.nextSteps.map((step, idx) => <li key={idx}>{step}</li>)}
                </ul>
              </>
            )}
          </div>
        )}
      </div>

      {check.state === "error" && (
        <div className="banner warn" role="alert">
          <p>{check.error}</p>
          {check.canRetry && <button type="button" onClick={runPrecheck}>Retry</button>}
        </div>
      )}
    </section>
  );
}
