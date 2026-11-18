import { useState } from "react";
import { api } from "../api.js";
import { Loading, useApi } from "../useApi.jsx";
import { integrityMessage } from "../lib/auditChain.js";
import { errorMessage } from "../lib/states.js";
import { formatDate, maskIdentifiers } from "../lib/format.js";
import { href } from "../lib/router.js";
import { appLabel } from "../lib/display.js";

// The check covers the whole log (every case), not only the rows shown here.
function VerifyIntegrity() {
  const [state, setState] = useState({ busy: false, result: null, error: null });
  async function verify() {
    setState({ busy: true, result: null, error: null });
    try {
      setState({ busy: false, result: integrityMessage(await api("GET", "/admin/audit/verify")), error: null });
    } catch (error) {
      setState({ busy: false, result: null, error: errorMessage(error) });
    }
  }
  return (
    <div className="integrity-check">
      <button type="button" onClick={verify} disabled={state.busy}>
        {state.busy ? "Checking the whole log…" : "Verify log integrity"}</button>
      {state.result && <p role="status" className={`integrity ${state.result.ok ? "ok" : "error"}`}>{state.result.text}</p>}
      {state.error && <p role="alert" className="error">{state.error}</p>}
    </div>
  );
}

export default function Audit({ id }) {
  const audit = useApi(`/cases/${encodeURIComponent(id)}/audit`);
  return (
    <section>
      <h1>Audit trail: {id}</h1>
      <p className="muted">Append-only. Every tool call, rule result and officer action, with the rules version used.
        <a href={href("case", id)}> Back to case</a></p>
      <VerifyIntegrity />
      <Loading state={audit} back={<a href={href("queue")}>Back to the queue</a>} />
      {audit.data && (
        <div className="table-scroll"><table>
          <thead><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Rules version</th><th>Details (as stored)</th></tr></thead>
          <tbody>
            {audit.data.map((a) => (
              <tr key={a.id} className={a.action === "officer_decision" ? "decision-row" : ""}>
                <td>{a.id}</td><td className="small">{formatDate(a.ts)}</td><td>{a.actor}</td><td>{appLabel("action", a.action)}</td>
                <td>{a.rules_version}</td>
                <td><details><summary>Technical record</summary><pre>{maskIdentifiers(JSON.stringify(a.payload, null, 2))}</pre></details></td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}
