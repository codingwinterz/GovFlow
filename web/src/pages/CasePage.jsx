import { useState } from "react";
import { api } from "../api.js";
import { Loading, useApi } from "../useApi.jsx";
import {
  fieldSource, formatConfidence, formatDate, formatRupees, maskIdentifiers, unavailableDocuments, validateDecision, confirmedFields,
  resolutionsBody,
} from "../lib/format.js";
import { href } from "../lib/router.js";
import { appLabel, flagLabel, readable, readableFormula, termLabel } from "../lib/display.js";
import { DICTS } from "../i18n/index.js";

function RetryBanner({ caseId, docs, onDone, terms }) {
  const docName = (doc) => termLabel(terms, doc.doc_type);
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState("");
  if (docs.length === 0) return null;
  const retry = async (doc) => {
    setBusy(doc.id);
    setMessage("");
    try {
      const r = await api("POST", `/cases/${encodeURIComponent(caseId)}/documents/${doc.id}/extract`);
      setMessage(r.status === "ok" ? `${docName(doc)}: read ${r.fields.length} fields.`
        : `${docName(doc)}: still unavailable (${appLabel("error_kind", r.error_kind).toLowerCase()}).`);
      onDone();
    } catch (e) {
      setMessage(`${docName(doc)}: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="banner warn">
      {docs.map((d) => (
        <div key={d.id}>
          <strong>{docName(d)}: {d.message}</strong> <span className="muted">({appLabel("error_kind", d.extraction_error_kind)})</span>{" "}
          <button disabled={busy === d.id} onClick={() => retry(d)}>{busy === d.id ? "Retrying…" : "Retry extraction"}</button>
        </div>
      ))}
      {message && <p>{message}</p>}
    </div>
  );
}

function Documents({ documents, terms }) {
  return (
    <section className="card">
      <h2>Documents and extracted fields</h2>
      {documents.length === 0 && <p className="muted">No documents.</p>}
      {documents.map((d) => (
        <div key={d.id} className={d.current ? "" : "superseded"}>
          <h3>{termLabel(terms, d.doc_type)} <span className="muted">#{d.id}</span> {!d.current && <span className="badge">superseded</span>}
            {d.extraction_status && <span className={`badge ${d.extraction_status === "ok" ? "" : "warn"}`}>{appLabel("extraction", d.extraction_status)}</span>}
          </h3>
          {d.fields.length > 0 && (
            <table>
              <thead><tr><th>Field</th><th>Value</th><th>Confidence</th><th>Source</th></tr></thead>
              <tbody>
                {d.fields.map((f) => (
                  <tr key={f.field} className={f.needs_review ? "flagged" : ""}>
                    <td>{termLabel(terms, `${d.doc_type}.${f.field}`)}</td>
                    <td>{maskIdentifiers(f.value)}{f.note && <div className="muted small">{f.note}</div>}</td>
                    <td>{formatConfidence(f.confidence)}{f.needs_review && <span className="badge warn">{f.review_reason ? `${f.review_reason}: review` : "at or below threshold: review"}</span>}</td>
                    <td className="small">{fieldSource(f, terms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </section>
  );
}

function Rules({ detail }) {
  return (
    <section className="card">
      <h2>Eligibility <span className="badge rec">recommendation only</span></h2>
      {detail.recommendation
        ? <p>Rules engine recommendation: <strong>{appLabel("recommendation", detail.recommendation)}</strong> <span className="muted">(rules version {detail.rules_version}). Only an officer decides.</span></p>
        : <p className="muted">Not assessed yet.</p>}
      {detail.rule_results.length > 0 && (
        <table>
          <thead><tr><th>Rule</th><th>Result</th><th>Clause</th><th>Reason</th><th>Version</th></tr></thead>
          <tbody>
            {detail.rule_results.map((r) => (
              <tr key={r.rule_id} className={r.status === "pass" ? "" : "flagged"}>
                <td>{termLabel(detail.terms, r.rule_id)}</td><td>{appLabel("result", r.status)}</td><td>{r.clause}</td>
                <td className="small">{readable(r.reason, detail.terms)}</td><td>{r.rules_version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Amounts({ compensation, version, labels, terms }) {
  return (
    <section className="card">
      <h2>{labels.amounts} <span className="badge rec">recommendation only</span></h2>
      {compensation.items.length === 0 ? <p className="muted">Not computed yet.</p> : (
        <table>
          <thead><tr><th>Component</th><th className="num">Amount</th><th>Formula (source)</th></tr></thead>
          <tbody>
            {compensation.items.map((i) => (
              <tr key={i.component}><td>{termLabel(terms, i.component)}</td><td className="num">{formatRupees(i.amount)}</td>
                <td className="small">{readableFormula(i.formula_note, terms)}</td></tr>
            ))}
            <tr className="total">
              <td>{labels.total}</td><td className="num">{formatRupees(compensation.total)}</td>
              <td className="small">as returned by the API (rules version {version}); not computed in the browser</td>
            </tr>
          </tbody>
        </table>
      )}
    </section>
  );
}

function Explanation({ explanation, terms }) {
  if (!explanation) return null;
  return (
    <section className="card">
      <h2>Agent explanation <span className="badge rec">recommendation only</span></h2>
      {explanation.warnings.length > 0 && (
        <div className="banner warn">
          <strong>Check this explanation:</strong> it quotes numbers no tool produced.
          <ul>{explanation.warnings.map((w) => <li key={w}>{readable(w, terms)}</li>)}</ul>
        </div>
      )}
      <pre className="explanation">{readable(maskIdentifiers(explanation.text), terms)}</pre>
      <p className="muted small">Written {formatDate(explanation.at)}{explanation.used_fallback ? " without the LLM (deterministic summary)" : " by the agent"}. Figures above come from the tools, not from this text.</p>
    </section>
  );
}

function DecisionPanel({ caseId, confirmFields = [], resolutionsNeeded = [], terms, onDone }) {
  const [decision, setDecision] = useState("");
  const [comment, setComment] = useState("");
  const [checked, setChecked] = useState({});
  const [resolutions, setResolutions] = useState({});
  const [error, setError] = useState("");
  const setResolution = (flag, key, value) => setResolutions({ ...resolutions, [flag]: { ...resolutions[flag], [key]: value } });
  const submit = async (e) => {
    e.preventDefault();
    const problem = validateDecision(decision, comment, confirmFields, checked, resolutionsNeeded, resolutions);
    if (problem) return setError(problem);
    const approving = decision === "approve";
    const body = { decision, comment, confirmed_fields: approving ? confirmedFields(confirmFields, checked) : {},
      resolutions: approving ? resolutionsBody(resolutionsNeeded, resolutions) : {},
      confirmed_case: approving ? caseId : null };      // the server refuses a confirmation made for another case
    try {
      await api("POST", `/cases/${encodeURIComponent(caseId)}/decision`, body);
      setError("");
      onDone();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="card decision">
      <h2>Officer decision</h2>
      <p className="muted">The agent's results above are recommendations. This decision is yours and is recorded in the audit trail.</p>
      <form onSubmit={submit}>
        <div className="choices">
          {[["approve", "Approve"], ["reject", "Reject"], ["send_back", "Send back"]].map(([value, label]) => (
            <label key={value}><input type="radio" name="decision" value={value} checked={decision === value}
              onChange={() => setDecision(value)} /> {label}</label>
          ))}
        </div>
        {decision === "approve" && confirmFields.length > 0 && (
          <fieldset className="confirm">
            <legend>Check these values against the documents</legend>
            <p className="muted small">They decide the amount. Tick each one after reading it on the document itself,
              whatever confidence the extraction reported.</p>
            {confirmFields.map((f) => (
              <label key={f.ref} className="confirm-item">
                <input type="checkbox" checked={!!checked[f.ref]}
                  onChange={(e) => setChecked({ ...checked, [f.ref]: e.target.checked })} />
                {termLabel(terms, f.ref)}: <strong>{String(f.value)}</strong>
              </label>
            ))}
          </fieldset>
        )}
        {decision === "approve" && resolutionsNeeded.map((r) => (
          <fieldset key={r.flag} className="confirm">
            <legend>Resolution: {termLabel(terms, r.flag)}</legend>
            <p className="muted small">Approval needs the resolution you relied on: its reference and date. It is
              recorded in the audit trail.{r.basis && <> Basis: {r.basis}.</>}</p>
            <label>Resolution reference
              <input value={resolutions[r.flag]?.reference || ""} maxLength={200}
                onChange={(e) => setResolution(r.flag, "reference", e.target.value)} /></label>
            <label>Resolution date
              <input type="date" value={resolutions[r.flag]?.date || ""}
                onChange={(e) => setResolution(r.flag, "date", e.target.value)} /></label>
          </fieldset>
        ))}
        <label>Comment {decision && decision !== "approve" && <span className="muted">(required)</span>}
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit">Record decision</button>
      </form>
    </section>
  );
}

// "Request documents": a notice built by the server from the open problems the citizen can fix (fixed
// templates, no LLM). Preview first; sending stores it, audits it and moves the case to "More information needed".
function RequestDocuments({ caseId, onDone }) {
  const [language, setLanguage] = useState("en");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (method) => {
    setBusy(true);
    setError("");
    try {
      const path = `/cases/${encodeURIComponent(caseId)}/notice`;
      const r = method === "GET" ? await api("GET", `${path}?language=${language}`) : await api("POST", path, { language });
      setPreview(r);
      if (method === "POST") onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card">
      <h2>Request documents</h2>
      <p className="muted">Asks the citizen only for what they can fix: missing, expired or unreadable documents, a
        name that does not match, a missing entry. It does not approve, reject or change any amount.</p>
      <label>Language of the notice{" "}
        <select value={language} onChange={(e) => { setLanguage(e.target.value); setPreview(null); }}>
          {Object.entries(DICTS).map(([code, dict]) => (
            <option key={code} value={code}>{dict["_meta.language"]}{code === "en" ? "" : " (draft translation)"}</option>
          ))}
        </select>
      </label>
      <div className="actions">
        <button onClick={() => run("GET")} disabled={busy}>Preview notice</button>
        {preview && preview.items.length > 0 && preview.language === language &&
          <button onClick={() => run("POST")} disabled={busy}>Send to citizen</button>}
      </div>
      {preview && preview.items.length === 0 && <p className="muted">Nothing on this case is for the citizen to fix.</p>}
      {preview && preview.items.length > 0 && (
        <div className="notice-preview">{preview.lines.map((line, i) => <p key={i}>{line}</p>)}</div>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}

export default function CasePage({ id, login }) {
  const detail = useApi(`/cases/${encodeURIComponent(id)}`);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState("");
  const d = detail.data;
  const runAgent = async () => {
    setRunning(true);
    setRunError("");
    try {
      await api("POST", `/cases/${encodeURIComponent(id)}/run`);
      detail.reload();
    } catch (e) {
      setRunError(e.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <section>
      <Loading state={detail} back={<a href={href("queue")}>Back to the queue</a>} />
      {d && (
        <>
          <div className="case-head">
            <h1>{d.case_id} <span className={`status s-${d.status}`}>{appLabel("status", d.status)}</span></h1>
            <p className="muted">{d.labels.title} · rules version {d.rules_version} · reference date {d.reference_date}
              {d.officer_id && <> · officer {d.officer_id}</>}</p>
            <div className="actions">
              <button onClick={runAgent} disabled={running}>{running ? "Running agent…" : "Run agent"}</button>
              {login.role === "officer" && <a href={href("audit", d.case_id)}>Audit trail</a>}
              {login.role === "officer" && d.status === "approved" && <a href={href("award", d.case_id)}>Award letter</a>}
            </div>
            {runError && <p className="error">{runError}</p>}
          </div>
          <RetryBanner caseId={d.case_id} docs={unavailableDocuments(d)} onDone={detail.reload} terms={d.terms} />
          {d.flags.length > 0 && (
            <section className="card">
              <h2>Verification flags</h2>
              <ul className="flags">{d.flags.map((f, i) => (
                <li key={i} className={`sev-${f.severity}`}><strong>{flagLabel(d.terms, f.kind)}</strong>{" "}
                  ({appLabel("severity", f.severity).toLowerCase()}): {readable(maskIdentifiers(f.detail), d.terms)}</li>
              ))}</ul>
            </section>
          )}
          <Explanation explanation={d.explanation} terms={d.terms} />
          <Rules detail={d} />
          <Amounts compensation={d.compensation} version={d.rules_version} labels={d.labels} terms={d.terms} />
          <Documents documents={d.documents} terms={d.terms} />
          <section className="card">
            <h2>Officer-entered inputs</h2>
            <table><tbody>{Object.entries(d.inputs).map(([k, v]) => (
              <tr key={k}><td>{termLabel(d.terms, k)}</td><td>{maskIdentifiers(v)}</td><td className="small muted">source: case inputs (officer/clerk)</td></tr>
            ))}</tbody></table>
          </section>
          {login.role === "officer" && d.status === "in_officer_review" && <RequestDocuments caseId={d.case_id} onDone={detail.reload} />}
          {login.role === "officer" && d.status === "in_officer_review" && <DecisionPanel caseId={d.case_id} confirmFields={d.confirm_fields} resolutionsNeeded={d.resolutions_needed} terms={d.terms} onDone={detail.reload} />}
        </>
      )}
    </section>
  );
}
