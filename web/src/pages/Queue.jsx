import { useState } from "react";
import { Loading, useApi } from "../useApi.jsx";
import { formatDate } from "../lib/format.js";
import { href } from "../lib/router.js";
import { appLabel, schemeTitle } from "../lib/display.js";

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

  return (
    <section>
      <h1>Case queue</h1>
      <p className="muted">
        Order comes from the API: cases with verification flags first, then oldest submission first.
      </p>
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
          <table>
            <thead>
              <tr><th>#</th><th>Case</th><th>Scheme</th><th>Status</th><th>Flags</th><th className="num">Days open</th><th>Submitted</th></tr>
            </thead>
            <tbody>
              {cases.data.map((c, i) => (
                <tr key={c.case_id} className={c.confidence_flag ? "flagged" : ""}>
                  <td>{i + 1}</td>
                  <td><a href={href("case", c.case_id)}>{c.case_id}</a></td>
                  <td>{schemeTitle(schemes.data, c.scheme)}</td>
                  <td><span className={`status s-${c.status}`}>{appLabel("status", c.status)}</span></td>
                  <td title="verification flags stored for this case">
                    {c.flags_count}{c.confidence_flag && <span className="badge warn">needs review</span>}
                  </td>
                  <td className="num" title={`target ${c.sla_days} days (scheme sla_days); flag only, nothing changes automatically`}>
                    {c.days_open}{c.overdue && <span className="badge warn">overdue</span>}
                  </td>
                  <td>{formatDate(c.submitted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}
    </section>
  );
}
