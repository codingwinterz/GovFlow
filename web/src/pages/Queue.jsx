import { useState } from "react";
import { Loading, useApi } from "../useApi.jsx";
import { formatDate, formatDay } from "../lib/format.js";
import { href } from "../lib/router.js";
import { appLabel, queueReason, schemeTitle } from "../lib/display.js";
import { queueRows, topSeverity } from "../lib/glance.js";

// The most severe flag's reason, with its severity as a word and shape, a count of the others; every reason on hover.
function Reason({ flags, terms }) {
  const r = queueReason(flags, terms);
  if (!r) return <span className="muted">—</span>;
  const sev = topSeverity(flags);
  return (
    <>
      {sev && <span className={`sev sev-${sev}`}>{appLabel("severity", sev)}</span>}
      <span className="badge warn reason" title={r.all.join("\n")}>
        {r.label}{r.more > 0 && <span className="more"> +{r.more} more</span>}
      </span>
    </>
  );
}

const VIEWS = [["all", "All cases"], ["attention", "Needs attention"], ["overdue", "Overdue"]];

const STATUSES = ["", "received", "extracted", "verified", "assessed", "in_officer_review", "needs_info",
  "approved", "rejected", "withdrawn"];

export default function Queue() {
  const [status, setStatus] = useState("");                   // opens on every case; the filters narrow it
  const [scheme, setScheme] = useState("");
  const [view, setView] = useState("all");                     // one-click views over the rows the API sent
  const [allColumns, setAllColumns] = useState(false);
  const schemes = useApi("/schemes");
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (scheme) params.set("scheme", scheme);
  const cases = useApi(`/cases?${params}`);
  const waiting = useApi("/cases?status=needs_info");          // shown whatever the filter: they wait on the citizen
  const termsOf = (id) => (schemes.data || []).find((s) => s.scheme === id)?.terms;
  const waitingCount = Array.isArray(waiting.data) ? waiting.data.length : null;
  const rows = queueRows(cases.data, view);
  const viewCount = (v) => queueRows(cases.data, v).length;

  return (
    <section>
      <h1>Case queue</h1>
      <p className="muted">
        Cases that need attention come first, then the oldest. (Order comes from the API: cases with verification flags
        first, then oldest submission first.)
      </p>
      {cases.data && (
        <div className="views" role="group" aria-label="Show">
          {VIEWS.map(([v, label]) => (
            <button key={v} type="button" className="secondary" aria-pressed={view === v} onClick={() => setView(v)}>
              {label} ({viewCount(v)})</button>
          ))}
        </div>
      )}
      {waitingCount !== null && (
        <p className="waiting-count">
          <strong>{appLabel("status", "needs_info")}: {waitingCount}</strong>{" "}
          <span className="muted">(waiting for the citizen; their SLA clock is paused)</span>{" "}
          {waitingCount > 0 && status !== "needs_info" &&
            <button type="button" className="link" onClick={() => setStatus("needs_info")}>Show these cases</button>}
        </p>
      )}
      <div className="filters filter-bar">
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
        <label className="inline-check"><input type="checkbox" checked={allColumns}
          onChange={(e) => setAllColumns(e.target.checked)} /> All columns</label>
      </div>
      <Loading state={cases} />
      {cases.data && (
        rows.length === 0 ? <p className="muted">No cases match these filters.</p> : (
          <div className="table-scroll queue-scroll"><table className="queue-table">
            <thead>
              <tr>{allColumns && <th>#</th>}<th className="col-case">Case</th><th>Scheme</th><th>Status</th>
                <th>Why it needs attention <span className="term">reason for review</span></th>
                <th className="num">Days open</th>{allColumns && <th>Submitted</th>}</tr>
            </thead>
            <tbody>
              {rows.map((c, i) => (
                <tr key={c.case_id} className={c.confidence_flag ? "flagged" : ""}>
                  {allColumns && <td>{i + 1}</td>}
                  <td className="col-case"><a href={href("case", c.case_id)}>{c.case_id}</a></td>
                  <td>{schemeTitle(schemes.data, c.scheme)}</td>
                  <td><span className={`status s-${c.status}`}>{appLabel("status", c.status)}</span></td>
                  <td className="why"><Reason flags={c.flags} terms={termsOf(c.scheme)} /></td>
                  <td className="num" title={`Target ${c.sla_days} days for this scheme. A flag only: nothing changes automatically.`}>
                    {c.days_open}{c.overdue && <span className="badge warn">overdue</span>}
                    {c.status === "needs_info" && <span className="badge" title="Waiting for the citizen: days open do not grow">clock paused</span>}
                  </td>
                  {allColumns && <td title={formatDate(c.submitted_at)}>{formatDay(c.submitted_at)}</td>}
                </tr>
              ))}
            </tbody>
          </table></div>
        )
      )}
    </section>
  );
}
