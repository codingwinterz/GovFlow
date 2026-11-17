import { useState } from "react";
import { citizenLines, noticeLines, t } from "../lib/i18n.js";
import { trackProblem } from "../lib/states.js";

const ERRORS = { 404: "track.not_found", 429: "track.too_many" };

// The only status page. Public: reference + verification code, no role headers.
export default function Track({ dict }) {
  const [ref, setRef] = useState("");
  const [code, setCode] = useState("");
  const [view, setView] = useState(null);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setView(null);
    const problem = trackProblem(ref, code);
    if (problem) return setError(problem);              // checked here: a typo does not use up an attempt
    setError("");
    try {
      const response = await fetch("/api/public/status", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_ref: ref.trim(), code: code.trim() }),
      });
      if (!response.ok) return setError(ERRORS[response.status] || "track.error");
      setView(await response.json());
    } catch {
      setError("track.error");
    }
  };

  return (
    <section className="card track">
      <h1 className="no-print">{t(dict, "track.title")}</h1>
      <form onSubmit={submit} className="no-print">
        <label>{t(dict, "track.case_ref")} <input value={ref} onChange={(e) => setRef(e.target.value)} autoComplete="off" required maxLength={64} /></label>
        <label>{t(dict, "track.code")} <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="off"
          required maxLength={6} pattern="[0-9]{6}" /></label>
        <button type="submit">{t(dict, "track.submit")}</button>
      </form>
      <p className="muted small no-print">{t(dict, "track.demo_hint")}</p>
      {error && <p className="error no-print" role="alert">{t(dict, error)}</p>}
      {view && (
        <div className="citizen-view no-print">
          {citizenLines(view, dict).map((line, i) =>
            line.kind === "heading" ? <h2 key={i}>{line.text}</h2>
              : <p key={i} className={`line ${line.kind}`}>{line.text}</p>)}
        </div>
      )}
      {view?.documents_needed && (
        <article className="letter notice">
          {noticeLines(view.documents_needed, view.case_ref, dict).map((line, i) =>
            line.kind === "heading" ? <h2 key={i}>{line.text}</h2>
              : line.kind === "item" ? <p key={i} className="line item">• {line.text}</p>
                : <p key={i} className={`line ${line.kind}`}>{line.text}</p>)}
          <button className="no-print" onClick={() => window.print()}>{t(dict, "deficiency.print")}</button>
        </article>
      )}
    </section>
  );
}
