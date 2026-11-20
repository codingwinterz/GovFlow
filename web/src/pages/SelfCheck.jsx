import { useEffect, useState } from "react";
import { t } from "../lib/i18n.js";
import { readable, termLabel } from "../lib/display.js";
import { readList } from "../lib/states.js";
import Precheck from "./Precheck.jsx";
import Sahayak from "./Sahayak.jsx";


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
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [part, setPart] = useState("questions");
  const say = (keyOrText) => (keyOrText in dict ? t(dict, keyOrText) : keyOrText);

  const load = () => {
    setLoading(true);
    setError("");
    setReloadKey((k) => k + 1);
    fetch("/api/public/self-check").then(readList).then((list) => {
      setSchemes(list);
      setScheme(list[0] || null);
    }).catch(() => setError("self.load_error")).finally(() => setLoading(false));
  };
  useEffect(load, []);

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

  // One action per screen: the questions, or the document check. Both stay mounted, so switching keeps what was entered.
  return (
    <>
      <div className="self-head">
        <h1>{t(dict, "nav.self_check")}</h1>
        <Sahayak scheme={scheme?.scheme} result={result} />
      </div>
      <div className="switch" role="group" aria-label={t(dict, "nav.self_check")}>
        {[["questions", "self.tab_questions"], ["document", "self.tab_document"]].map(([value, key]) => (
          <button key={value} type="button" aria-pressed={part === value} onClick={() => setPart(value)}>{t(dict, key)}</button>
        ))}
      </div>
      <section className="card" hidden={part !== "questions"}>
        <ol className="progress">
          <li className={result ? "done" : undefined} aria-current={result ? undefined : "step"}>{t(dict, "self.step_answer")}</li>
          <li aria-current={result ? "step" : undefined}>{t(dict, "self.step_result")}</li>
        </ol>
        {scheme && <p className="banner warn"><strong>{scheme.guide_label}</strong></p>}
        {loading && <p className="muted" role="status">{t(dict, "self.loading")}</p>}
        {!loading && schemes.length === 0 && !error && <p className="muted">{t(dict, "self.none")}</p>}
        {error === "self.load_error" && (
          <div className="banner warn" role="alert">
            <p>{t(dict, "self.load_error")}</p>
            <button type="button" onClick={load}>{t(dict, "self.retry")}</button>
          </div>
        )}
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
        {error && error !== "self.load_error" && <p className="error" role="alert">{say(error)}</p>}
        {result && (
          <div className="citizen-view">
            <h2>{t(dict, `outcome.${result.outcome}`)}</h2>
            <p className="banner warn"><strong>{result.guide_label}</strong></p>
            <ul>{result.rules.map((r) => <li key={r.rule_id}>{readable(r.message, scheme.terms)}</li>)}</ul>
            <h2>{t(dict, "self.documents")}</h2>
            <ul>{result.documents_to_bring.map((d) => <li key={d}>{t(dict, `documents.${d}`)}</li>)}</ul>
            <p className="muted small">{t(dict, "self.later", { checks: result.checked_when_you_apply.map((c) => termLabel(scheme.terms, c)).join(", ") })}{" "}
              {t(dict, "self.rules", { version: result.rules_version })}</p>
          </div>
        )}
      </section>
      <div hidden={part !== "document"}>
        <Precheck activeScheme={scheme?.scheme} reloadKey={reloadKey} pageError={error === "self.load_error"} />
      </div>
    </>
  );
}

