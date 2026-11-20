import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApi } from "../useApi.jsx";
import { formatRupees } from "../lib/format.js";
import { appLabel, termLabel } from "../lib/display.js";

function Outcome({ o }) {
  return <>{appLabel("recommendation", o.overall)}<div className="small muted">{appLabel("compensation", o.compensation_status)}</div></>;
}

export default function Simulator() {
  const schemes = useApi("/schemes");
  const [scheme, setScheme] = useState("");
  const [knobList, setKnobList] = useState(null);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const chosen = scheme || schemes.data?.[0]?.scheme || "";
  const terms = schemes.data?.find((s) => s.scheme === chosen)?.terms;

  useEffect(() => {
    if (!chosen) return;
    setResult(null);
    api("GET", `/simulate/${encodeURIComponent(chosen)}`).then((k) => {
      setKnobList(k);
      setName(k.knobs[0]?.name || "");
      setValue(String(k.knobs[0]?.value ?? ""));
    }).catch((e) => setError(e.message));
  }, [chosen]);

  const run = async (e) => {
    e.preventDefault();
    setError("");
    try {
      setResult(await api("POST", "/simulate", { scheme: chosen, name, value: Number(value) }));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section>
      <h1>Rule simulator</h1>
      <p className="banner warn">Read-only what-if over the synthetic test cases. It never edits the rules file;
        results are not decisions. Every amount below is computed by the rules engine on the server.</p>
      <form className="card filters" onSubmit={run}>
        <label>Scheme
          <select value={chosen} onChange={(e) => setScheme(e.target.value)}>
            {(schemes.data || []).map((s) => <option key={s.scheme} value={s.scheme}>{s.labels.title}</option>)}
          </select>
        </label>
        {knobList && knobList.knobs.length === 0 && (
          <p className="muted">This scheme has no parameters or input defaults to change: it calculates no amount.</p>
        )}
        {knobList?.knobs.length !== 0 && <>
        <label>Value to change
          <select value={name} onChange={(e) => {
            setName(e.target.value);
            setValue(String(knobList.knobs.find((k) => k.name === e.target.value)?.value ?? ""));
          }}>
            {(knobList?.knobs || []).map((k) => <option key={k.name} value={k.name}>{termLabel(terms, k.name)} ({appLabel("knob", k.kind).toLowerCase()}, now {k.value})</option>)}
          </select>
        </label>
        <label>New value <input value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" /></label>
        <button type="submit">Run simulation</button>
        </>}
      </form>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="card">
          <h2>{termLabel(terms, result.name)}: {result.original_value} → {result.new_value}</h2>
          <p className="muted">{result.changed_count} of {result.case_count} cases change · rules version {result.rules_version} · source: POST /simulate</p>
          <table>
            <thead><tr><th>Case</th><th>Before</th><th>After</th><th className="num">Total before</th><th className="num">Total after</th><th className="num">Change</th></tr></thead>
            <tbody>
              {result.cases.map((c) => (
                <tr key={c.case_id} className={c.changed ? "flagged" : ""}>
                  <td>{c.case_id}</td><td><Outcome o={c.before} /></td><td><Outcome o={c.after} /></td>
                  <td className="num">{formatRupees(c.before.total)}</td>
                  <td className="num">{formatRupees(c.after.total)}</td>
                  <td className="num">{formatRupees(c.total_change)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
