import { useState } from "react";
import en from "../i18n/en.json";
import hi from "../i18n/hi.json";
import mr from "../i18n/mr.json";
import kok from "../i18n/kok.json";
import { citizenLines, t } from "../lib/i18n.js";

const DICTS = { en, hi, mr, kok };
const ERRORS = { 404: "track.not_found", 429: "track.too_many" };

function readLang() {
  try { return localStorage.getItem("govflow-lang") || "en"; } catch { return "en"; }
}

export default function Track() {
  const [lang, setLang] = useState(readLang());
  const [ref, setRef] = useState("");
  const [code, setCode] = useState("");
  const [view, setView] = useState(null);
  const [error, setError] = useState("");
  const dict = DICTS[lang] || en;

  const choose = (value) => {
    setLang(value);
    try { localStorage.setItem("govflow-lang", value); } catch { /* per-visit only */ }
  };

  const submit = async (e) => {
    e.preventDefault();
    setView(null);
    setError("");
    try {
      const response = await fetch("/api/public/status", {     // public: no role headers
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
    <section className="card narrow track" lang={lang === "kok" ? "gom" : lang}>
      <label className="lang">{t(dict, "language.label")}
        <select value={lang} onChange={(e) => choose(e.target.value)}>
          {Object.entries(DICTS).map(([k, d]) => <option key={k} value={k}>{d["_meta.language"]}</option>)}
        </select>
      </label>
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
      <footer className="review-note">
        {lang !== "en" && <p>{t(dict, "footer.review")}</p>}
        <p>{t(en, "footer.review")}</p>
      </footer>
    </section>
  );
}
