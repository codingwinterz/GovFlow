import { useState } from "react";
import { api } from "../api.js";
import { Loading, useApi } from "../useApi.jsx";
import {
  fieldSource, formatConfidence, formatDate, formatRupees, maskIdentifiers, rupeesInText, unavailableDocuments, validateDecision, confirmedFields,
  resolutionsBody,
} from "../lib/format.js";
import { href } from "../lib/router.js";
import {
  appLabel, clauseText, explanationBlocks, flagLabel, readable, readableFormula, termLabel, withoutClausePlaceholders,
  recommendationLabel,
} from "../lib/display.js";
import { DICTS } from "../i18n/index.js";
import { flagCounts, showsAmounts, slaClock, summaryTotal } from "../lib/summary.js";
import { timelineNote, timelineRows } from "../lib/timelines.js";

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
            <div className="table-scroll"><table>
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
            </table></div>
          )}
        </div>
      ))}
    </section>
  );
}

// A clause still marked VERIFY in the YAML shows as a dash, never as its "<clause ref>" placeholder.
function Clause({ clause }) {
  const text = clauseText(clause);
  return text ?? <span className="muted" title="No clause reference recorded yet (to be confirmed)">—</span>;
}

function Rules({ detail }) {
  return (
    <section className="card">
      <h2>Eligibility <span className="badge rec">recommendation only</span></h2>
      {detail.recommendation
        ? <p>Rules engine recommendation: <strong>{recommendationLabel(detail.recommendation, detail.recommendation_labels)}</strong> <span className="muted">(rules version {detail.rules_version}). Only an officer decides.</span></p>
        : <p className="muted">Not assessed yet.</p>}
      {detail.rule_results.length > 0 && (
        <div className="table-scroll"><table className="rules-table">
          <thead><tr><th>Rule</th><th>Result</th><th>Clause</th><th>Reason</th><th>Version</th></tr></thead>
          <tbody>
            {detail.rule_results.map((r) => (
              <tr key={r.rule_id} className={r.status === "pass" ? "" : "flagged"}>
                <td>{termLabel(detail.terms, r.rule_id)}</td><td><span className={`result r-${r.status}`}>{appLabel("result", r.status)}</span></td><td><Clause clause={r.clause} /></td>
                <td className="small">{readable(rupeesInText(r.reason), detail.terms)}</td><td>{r.rules_version}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}

function Amounts({ compensation, version, labels, terms }) {
  return (
    <section className="card">
      <h2>{labels.amounts} <span className="badge rec">recommendation only</span></h2>
      {compensation.items.length === 0 ? <p className="muted">Not computed yet.</p> : (
        <div className="table-scroll"><table className="steps-table">
          <thead><tr><th className="num">Step</th><th>Component</th><th>Formula (source)</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {compensation.items.map((i, n) => (
              <tr key={i.component}><td className="num step">{n + 1}</td><td>{termLabel(terms, i.component)}</td>
                <td className="small">{readableFormula(i.formula_note, terms)}</td><td className="num">{formatRupees(i.amount)}</td></tr>
            ))}
            <tr className="total">
              <td /><td>{labels.total}</td>
              <td className="small">as returned by the API (rules version {version}); not computed in the browser</td>
              <td className="num">{formatRupees(compensation.total)}</td>
            </tr>
          </tbody>
        </table></div>
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
      <div className="explanation">
        {explanationBlocks(readable(rupeesInText(maskIdentifiers(withoutClausePlaceholders(explanation.text))), terms)).map((b, i) => (
          b.kind === "list"
            ? <ul key={i}>{b.items.map((item, j) => <li key={j}>{item}</li>)}</ul>
            : <p key={i}>{b.text}</p>
        ))}
      </div>
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

// Source-cited periods from the scheme YAML (data only). The SLA clock counts sla_days alone.
function Timelines({ timelines }) {
  const rows = timelineRows(timelines);
  if (rows.length === 0) return null;
  return (
    <section className="card">
      <h2>Timelines</h2>
      <p className="muted small">{timelineNote(timelines)}</p>
      <div className="table-scroll"><table>
        <thead><tr><th>Step</th><th>Period</th><th>Source</th><th>Status</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.id}>
            <td>{r.step}{r.clock && <> <span className="badge">drives the SLA clock</span></>}</td>
            <td>{r.period}</td><td className="small">{r.source}</td>
            <td className={r.verify ? "small verify" : "small"}>{r.verifyText}</td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}

// At a glance: status, the stored total, flags by severity and the SLA clock. The clock is the case's own row from
// the queue endpoint (days open with waiting excluded, the scheme's target, the overdue flag), as the queue shows it.
function SummaryStrip({ detail }) {
  const queue = useApi(`/cases?scheme=${encodeURIComponent(detail.scheme)}`);
  const row = Array.isArray(queue.data) ? queue.data.find((c) => c.case_id === detail.case_id) : null;
  const clock = slaClock(row);
  const total = summaryTotal(detail);
  const counts = flagCounts(detail.flags);
  return (
    <dl className={`summary-strip strip-${detail.status}`} aria-label="Case summary">
      <div><dt>Status</dt><dd><span className={`status s-${detail.status}`}>{appLabel("status", detail.status)}</span></dd></div>
      {showsAmounts(detail) && <div><dt>{detail.labels.total}</dt><dd className="num">{total === null ? <span className="muted">Not computed yet</span> : formatRupees(total)}</dd></div>}
      <div><dt>Flags</dt><dd>{counts.length === 0 ? <span className="muted">None</span>
        : counts.map((c, i) => <span key={c.severity}>{i > 0 && " · "}<span className={`flag-count sev sev-${c.severity}`}>{c.count} {appLabel("severity", c.severity).toLowerCase()}</span></span>)}</dd></div>
      <div><dt>SLA clock</dt><dd>{clock
        ? <span className={`clock clock-${clock.kind}`} title={clock.title}>{clock.text}</span>
        : <span className="muted">{queue.loading ? "…" : "—"}</span>}</dd></div>
    </dl>
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
              {login.role === "officer" && d.status === "approved" && showsAmounts(d) && <a href={href("award", d.case_id)}>Award letter</a>}
            </div>
            {runError && <p className="error">{runError}</p>}
          </div>
          <SummaryStrip key={d.case_id} detail={d} />
          <RetryBanner caseId={d.case_id} docs={unavailableDocuments(d)} onDone={detail.reload} terms={d.terms} />
          {d.flags.length > 0 && (
            <section className="card">
              <h2>Verification flags</h2>
              <ul className="flags">{d.flags.map((f, i) => (
                <li key={i} className={`flag-item flag-${f.severity}`}>
                  <span className={`sev sev-${f.severity}`}>{appLabel("severity", f.severity)}</span>{" "}
                  <strong>{flagLabel(d.terms, f.kind)}</strong>: {readable(rupeesInText(maskIdentifiers(f.detail)), d.terms)}</li>
              ))}</ul>
            </section>
          )}
          <Explanation explanation={d.explanation} terms={d.terms} />
          <Rules detail={d} />
          <Timelines timelines={d.timelines} />
          {showsAmounts(d) && <Amounts compensation={d.compensation} version={d.rules_version} labels={d.labels} terms={d.terms} />}
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
