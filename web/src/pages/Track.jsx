import { useState } from "react";
import { citizenLines, t } from "../lib/i18n.js";

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
      <h1>{t(dict, "track.title")}</h1>
      <form onSubmit={submit}>
        <label>{t(dict, "track.case_ref")} <input value={ref} onChange={(e) => setRef(e.target.value)} autoComplete="off" /></label>
        <label>{t(dict, "track.code")} <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="off" /></label>
        <button type="submit">{t(dict, "track.submit")}</button>
      </form>
      <p className="muted small">{t(dict, "track.demo_hint")}</p>
      {error && <p className="error">{t(dict, error)}</p>}
      {view && (
        <div className="citizen-view">
          {citizenLines(view, dict).map((line, i) =>
            line.kind === "heading" ? <h2 key={i}>{line.text}</h2>
              : <p key={i} className={`line ${line.kind}`}>{line.text}</p>)}
        </div>
      )}
    </section>
  );
}
