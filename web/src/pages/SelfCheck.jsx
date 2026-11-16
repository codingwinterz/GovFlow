import { useEffect, useState } from "react";
import { t } from "../lib/i18n.js";

class CheckError extends Error {}

async function post(path, body) {
  const response = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new CheckError(response.status === 429 ? "track.too_many" : data?.detail || "track.error");
  return data;
}

// Questions, guide label and rule messages come from the scheme YAML (English); the page chrome is translated.
export default function SelfCheck({ dict }) {
  const [schemes, setSchemes] = useState([]);
  const [scheme, setScheme] = useState(null);
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const say = (keyOrText) => (keyOrText in dict ? t(dict, keyOrText) : keyOrText);

  useEffect(() => {
    fetch("/api/public/self-check").then((r) => r.json()).then((list) => {
      setSchemes(list);
      setScheme(list[0] || null);
    }).catch(() => setError("self.load_error"));
  }, []);

  const run = async (e) => {
    e.preventDefault();
    setError("");
    try {
      setResult(await post("/public/self-check", { scheme: scheme.scheme, answers }));
    } catch (err) {
      setResult(null);
      setError(err instanceof CheckError ? err.message : "track.error");
    }
  };

  return (
    <section className="card">
      <h1>{t(dict, "nav.self_check")}</h1>
      {scheme && <p className="banner warn"><strong>{scheme.guide_label}</strong></p>}
      {schemes.length === 0 && !error && <p className="muted">{t(dict, "self.none")}</p>}
      {scheme && (
        <form onSubmit={run}>
          <label>{t(dict, "self.scheme")}
            <select value={scheme.scheme} onChange={(e) => { setScheme(schemes.find((s) => s.scheme === e.target.value)); setAnswers({}); setResult(null); }}>
              {schemes.map((s) => <option key={s.scheme} value={s.scheme}>{s.labels.title}</option>)}
            </select>
          </label>
          {scheme.questions.map((q) => (
            <label key={q.field}>{q.prompt}
              {q.choices.length ? (
                <select value={answers[q.field] || ""} onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })}>
                  <option value="">{t(dict, "self.choose")}</option>
                  {q.choices.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <input value={answers[q.field] || ""} inputMode={q.type === "text" ? "text" : "decimal"}
                  onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })} />
              )}
            </label>
          ))}
          <button type="submit">{t(dict, "self.submit")}</button>
        </form>
      )}
      {error && <p className="error">{say(error)}</p>}
      {result && (
        <div className="citizen-view">
          <h2>{t(dict, `outcome.${result.outcome}`)}</h2>
          <p className="banner warn"><strong>{result.guide_label}</strong></p>
          <ul>{result.rules.map((r) => <li key={r.rule_id}>{r.message}</li>)}</ul>
          <h2>{t(dict, "self.documents")}</h2>
          <ul>{result.documents_to_bring.map((d) => <li key={d}>{t(dict, `documents.${d}`)}</li>)}</ul>
          <p className="muted small">{t(dict, "self.later", { checks: result.checked_when_you_apply.join(", ") })}{" "}
            {t(dict, "self.rules", { version: result.rules_version })}</p>
        </div>
      )}
    </section>
  );
}
