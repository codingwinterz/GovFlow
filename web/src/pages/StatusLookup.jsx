import { useState } from "react";
import { api } from "../api.js";
import { maskIdentifiers } from "../lib/format.js";

export default function StatusLookup() {
  const [caseId, setCaseId] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const look = async (e) => {
    e.preventDefault();
    try {
      setResult(await api("GET", `/cases/${encodeURIComponent(caseId.trim())}/status`));
      setError("");
    } catch (err) {
      setResult(null);
      setError(err.status === 404 ? "No case with that id." : err.message);
    }
  };
  return (
    <section className="card narrow">
      <h1>Case status</h1>
      <form onSubmit={look}>
        <label>Case id <input value={caseId} onChange={(e) => setCaseId(e.target.value)} placeholder="LA-01" /></label>
        <button type="submit">Check status</button>
      </form>
      {error && <p className="error">{error}</p>}
      {result && (
        <div>
          <p>Status: <strong>{result.status}</strong></p>
          <p>Next step: {result.next_step}</p>
          {result.blockers.length > 0 && <><p>Open items:</p><ul>{result.blockers.map((b) => <li key={b}>{maskIdentifiers(b)}</li>)}</ul></>}
        </div>
      )}
    </section>
  );
}
