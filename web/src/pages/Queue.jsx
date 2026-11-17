import { useState } from "react";
import { Loading, useApi } from "../useApi.jsx";
import { formatDate, formatDay } from "../lib/format.js";
import { href } from "../lib/router.js";
import { appLabel, queueReason, schemeTitle } from "../lib/display.js";

// The most severe flag's reason, with a count of the others; every reason on hover.
function Reason({ flags, terms }) {
  const r = queueReason(flags, terms);
  if (!r) return <span className="muted">—</span>;
  return (
    <span className="badge warn reason" title={r.all.join("\n")}>
      {r.label}{r.more > 0 && <span className="more"> +{r.more} more</span>}
    </span>
  );
}

const STATUSES = ["", "received", "extracted", "verified", "assessed", "in_officer_review", "needs_info",
  "approved", "rejected", "withdrawn"];

export default function Queue() {
  const [status, setStatus] = useState("in_officer_review");
  const [scheme, setScheme] = useState("");
  const schemes = useApi("/schemes");
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (scheme) params.set("scheme", scheme);
  const cases = useApi(`/cases?${params}`);
  const waiting = useApi("/cases?status=needs_info");          // shown whatever the filter: they wait on the citizen
  const termsOf = (id) => (schemes.data || []).find((s) => s.scheme === id)?.terms;
  const waitingCount = Array.isArray(waiting.data) ? waiting.data.length : null;

  return (
    <section>
      <h1>Case queue</h1>
      <p className="muted">
        Order comes from the API: cases with verification flags first, then oldest submission first.
      </p>
      {waitingCount !== null && (
        <p className="waiting-count">
          <strong>{appLabel("status", "needs_info")}: {waitingCount}</strong>{" "}
          <span className="muted">(waiting for the citizen; their SLA clock is paused)</span>{" "}
          {waitingCount > 0 && status !== "needs_info" &&
            <button type="button" className="link" onClick={() => setStatus("needs_info")}>Show these cases</button>}
        </p>
      )}
      <div className="filters">
        <label>Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{s ? appLabel("status", s) : "All statuses"}</option>)}
          </select>
        </label>
        <label>Scheme
          <select value={scheme} onChange={(e) => setScheme(e.target.value)}>
            <option value="">All schemes</option>
            {(schemes.data || []).map((s) => <option key={s.scheme} value={s.scheme}>{s.labels.title}</option>)}
          </select>
        </label>
      </div>
      <Loading state={cases} />
      {cases.data && (
        cases.data.length === 0 ? <p className="muted">No cases match these filters.</p> : (
          <div className="table-scroll"><table>
            <thead>
              <tr><th>#</th><th>Case</th><th>Scheme</th><th>Status</th><th>Reason for review</th><th className="num">Days open</th><th>Submitted</th></tr>
            </thead>
            <tbody>
              {cases.data.map((c, i) => (
                <tr key={c.case_id} className={c.confidence_flag ? "flagged" : ""}>
                  <td>{i + 1}</td>
                  <td><a href={href("case", c.case_id)}>{c.case_id}</a></td>
                  <td>{schemeTitle(schemes.data, c.scheme)}</td>
                  <td><span className={`status s-${c.status}`}>{appLabel("status", c.status)}</span></td>
                  <td><Reason flags={c.flags} terms={termsOf(c.scheme)} /></td>
                  <td className="num" title={`Target ${c.sla_days} days for this scheme. A flag only: nothing changes automatically.`}>
                    {c.days_open}{c.overdue && <span className="badge warn">overdue</span>}
                    {c.status === "needs_info" && <span className="badge" title="Waiting for the citizen: days open do not grow">clock paused</span>}
                  </td>
                  <td title={formatDate(c.submitted_at)}>{formatDay(c.submitted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )
      )}
    </section>
  );
}
