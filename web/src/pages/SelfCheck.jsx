import { useEffect, useState } from "react";
import en from "../i18n/en.json";
import { t } from "../lib/i18n.js";

const OUTCOME = {
  likely_eligible: "Likely eligible",
  likely_not_eligible: "Likely not eligible",
  need_more_information: "Need more information",
};

async function post(path, body) {
  const response = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(response.status === 429 ? "Too many attempts. Please try again later."
    : data?.detail || "Something went wrong.");
  return data;
}

export default function SelfCheck() {
  const [schemes, setSchemes] = useState([]);
  const [scheme, setScheme] = useState(null);
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/public/self-check").then((r) => r.json()).then((list) => {
      setSchemes(list);
      setScheme(list[0] || null);
    }).catch(() => setError("Could not load the self-check questions."));
  }, []);

  const run = async (e) => {
    e.preventDefault();
    setError("");
    try {
      setResult(await post("/public/self-check", { scheme: scheme.scheme, answers }));
    } catch (err) {
      setResult(null);
      setError(err.message);
    }
  };

  return (
    <section className="card narrow">
      <h1>Check before you apply</h1>
      <p className="banner warn"><strong>{scheme?.guide_label}</strong></p>
      {schemes.length === 0 && !error && <p className="muted">No scheme offers a self-check yet.</p>}
      {scheme && (
        <form onSubmit={run}>
          <label>Scheme
            <select value={scheme.scheme} onChange={(e) => { setScheme(schemes.find((s) => s.scheme === e.target.value)); setAnswers({}); setResult(null); }}>
              {schemes.map((s) => <option key={s.scheme} value={s.scheme}>{s.labels.title}</option>)}
            </select>
          </label>
          {scheme.questions.map((q) => (
            <label key={q.field}>{q.prompt}
              {q.choices.length ? (
                <select value={answers[q.field] || ""} onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })}>
                  <option value="">(choose)</option>
                  {q.choices.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <input value={answers[q.field] || ""} inputMode={q.type === "text" ? "text" : "decimal"}
                  onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })} />
              )}
            </label>
          ))}
          <button type="submit">Check</button>
        </form>
      )}
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="citizen-view">
          <h2>{OUTCOME[result.outcome]}</h2>
          <p className="banner warn"><strong>{result.guide_label}</strong></p>
          <ul>{result.rules.map((r) => <li key={r.rule_id}>{r.message}</li>)}</ul>
          <h2>Documents to bring</h2>
          <ul>{result.documents_to_bring.map((d) => <li key={d}>{t(en, `documents.${d}`)}</li>)}</ul>
          <p className="muted small">Checked only when you apply, with your documents: {result.checked_when_you_apply.join(", ")}.
            Rules version {result.rules_version}.</p>
        </div>
      )}
    </section>
  );
}
