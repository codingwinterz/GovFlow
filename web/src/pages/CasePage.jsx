import { useState } from "react";
import { api } from "../api.js";
import { Loading, useApi } from "../useApi.jsx";
import {
  fieldSource, formatConfidence, formatDate, formatRupees, maskIdentifiers, unavailableDocuments, validateDecision,
} from "../lib/format.js";
import { href } from "../lib/router.js";

function RetryBanner({ caseId, docs, onDone }) {
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState("");
  if (docs.length === 0) return null;
  const retry = async (doc) => {
    setBusy(doc.id);
    setMessage("");
    try {
      const r = await api("POST", `/cases/${encodeURIComponent(caseId)}/documents/${doc.id}/extract`);
      setMessage(r.status === "ok" ? `${doc.doc_type}: read ${r.fields.length} fields.`
        : `${doc.doc_type}: still unavailable (${r.error_kind}).`);
      onDone();
    } catch (e) {
      setMessage(`${doc.doc_type}: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="banner warn">
      {docs.map((d) => (
        <div key={d.id}>
          <strong>{d.doc_type}: {d.message}</strong> <span className="muted">({d.extraction_error_kind})</span>{" "}
          <button disabled={busy === d.id} onClick={() => retry(d)}>{busy === d.id ? "Retrying…" : "Retry extraction"}</button>
        </div>
      ))}
      {message && <p>{message}</p>}
    </div>
  );
}

function Documents({ documents }) {
  return (
    <section className="card">
      <h2>Documents and extracted fields</h2>
      {documents.length === 0 && <p className="muted">No documents.</p>}
      {documents.map((d) => (
        <div key={d.id} className={d.current ? "" : "superseded"}>
          <h3>{d.doc_type} <span className="muted">#{d.id}</span> {!d.current && <span className="badge">superseded</span>}
            {d.extraction_status && <span className={`badge ${d.extraction_status === "ok" ? "" : "warn"}`}>{d.extraction_status}</span>}
          </h3>
          {d.fields.length > 0 && (
            <table>
              <thead><tr><th>Field</th><th>Value</th><th>Confidence</th><th>Source</th></tr></thead>
              <tbody>
                {d.fields.map((f) => (
                  <tr key={f.field} className={f.needs_review ? "flagged" : ""}>
                    <td>{f.field}</td>
                    <td>{maskIdentifiers(f.value)}{f.note && <div className="muted small">{f.note}</div>}</td>
                    <td>{formatConfidence(f.confidence)}{f.needs_review && <span className="badge warn">below threshold: review</span>}</td>
                    <td className="small">{fieldSource(f)}</td>
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
        ? <p>Rules engine recommendation: <strong>{detail.recommendation}</strong> <span className="muted">(rules version {detail.rules_version}). Only an officer decides.</span></p>
        : <p className="muted">Not assessed yet.</p>}
      {detail.rule_results.length > 0 && (
        <table>
          <thead><tr><th>Rule</th><th>Result</th><th>Clause</th><th>Reason</th><th>Version</th></tr></thead>
          <tbody>
            {detail.rule_results.map((r) => (
              <tr key={r.rule_id} className={r.status === "pass" ? "" : "flagged"}>
                <td>{r.rule_id}</td><td>{r.status}</td><td>{r.clause}</td><td className="small">{r.reason}</td><td>{r.rules_version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Amounts({ compensation, version, labels }) {
  return (
    <section className="card">
      <h2>{labels.amounts} <span className="badge rec">recommendation only</span></h2>
      {compensation.items.length === 0 ? <p className="muted">Not computed yet.</p> : (
        <table>
          <thead><tr><th>Component</th><th className="num">Amount</th><th>Formula (source)</th></tr></thead>
          <tbody>
            {compensation.items.map((i) => (
              <tr key={i.component}><td>{i.component}</td><td className="num">{formatRupees(i.amount)}</td><td className="small">{i.formula_note}</td></tr>
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

function Explanation({ explanation }) {
  if (!explanation) return null;
  return (
    <section className="card">
      <h2>Agent explanation <span className="badge rec">recommendation only</span></h2>
      {explanation.warnings.length > 0 && (
        <div className="banner warn">
          <strong>Check this explanation:</strong> it quotes numbers no tool produced.
          <ul>{explanation.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      <pre className="explanation">{maskIdentifiers(explanation.text)}</pre>
      <p className="muted small">Written {formatDate(explanation.at)}{explanation.used_fallback ? " without the LLM (deterministic summary)" : " by the agent"}. Figures above come from the tools, not from this text.</p>
    </section>
  );
}

function DecisionPanel({ caseId, onDone }) {
  const [decision, setDecision] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const problem = validateDecision(decision, comment);
    if (problem) return setError(problem);
    try {
      await api("POST", `/cases/${encodeURIComponent(caseId)}/decision`, { decision, comment });
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
        <label>Comment {decision && decision !== "approve" && <span className="muted">(required)</span>}
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit">Record decision</button>
      </form>
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
      <Loading state={detail} />
      {d && (
        <>
          <div className="case-head">
            <h1>{d.case_id} <span className={`status s-${d.status}`}>{d.status}</span></h1>
            <p className="muted">{d.labels.title} · rules version {d.rules_version} · reference date {d.reference_date}
              {d.officer_id && <> · officer {d.officer_id}</>}</p>
            <div className="actions">
              <button onClick={runAgent} disabled={running}>{running ? "Running agent…" : "Run agent"}</button>
              {login.role === "officer" && <a href={href("audit", d.case_id)}>Audit trail</a>}
              {login.role === "officer" && d.status === "approved" && <a href={href("award", d.case_id)}>Award letter</a>}
            </div>
            {runError && <p className="error">{runError}</p>}
          </div>
          <RetryBanner caseId={d.case_id} docs={unavailableDocuments(d)} onDone={detail.reload} />
          {d.flags.length > 0 && (
            <section className="card">
              <h2>Verification flags</h2>
              <ul className="flags">{d.flags.map((f, i) => (
                <li key={i} className={`sev-${f.severity}`}><strong>{f.kind}</strong> ({f.severity}): {maskIdentifiers(f.detail)}</li>
              ))}</ul>
            </section>
          )}
          <Explanation explanation={d.explanation} />
          <Rules detail={d} />
          <Amounts compensation={d.compensation} version={d.rules_version} labels={d.labels} />
          <Documents documents={d.documents} />
          <section className="card">
            <h2>Officer-entered inputs</h2>
            <table><tbody>{Object.entries(d.inputs).map(([k, v]) => (
              <tr key={k}><td>{k}</td><td>{maskIdentifiers(v)}</td><td className="small muted">source: case inputs (officer/clerk)</td></tr>
            ))}</tbody></table>
          </section>
          {login.role === "officer" && d.status === "in_officer_review" && <DecisionPanel caseId={d.case_id} onDone={detail.reload} />}
        </>
      )}
    </section>
  );
}
