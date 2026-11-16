import { useState } from "react";
import { Loading, useApi } from "../useApi.jsx";
import { formatDate, formatDuration } from "../lib/format.js";
import { href } from "../lib/router.js";
import { appLabel, readable, schemeTitle } from "../lib/display.js";

function Counts({ title, counts, total, source, label }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      <table className="bars"><tbody>
        {Object.entries(counts).map(([k, n]) => (
          <tr key={k}>
            <td>{label(k)}</td><td className="num">{n}</td>
            <td className="bar-cell"><span className="bar" style={{ width: `${total ? (100 * n) / total : 0}%` }} /></td>
          </tr>
        ))}
      </tbody></table>
      <p className="muted small">Source: {source}</p>
    </section>
  );
}

export default function Analytics() {
  const [days, setDays] = useState(7);
  const a = useApi(`/analytics?stuck_days=${days}`);
  const schemes = useApi("/schemes");
  const d = a.data;
  const status = (k) => appLabel("status", k);
  const scheme = (k) => schemeTitle(schemes.data, k);
  return (
    <section>
      <h1>Analytics</h1>
      <Loading state={a} />
      {d && (
        <div className="grid">
          <Counts title="Cases by status" counts={d.by_status} total={d.total_cases} label={status}
            source={`${d.total_cases} cases in the database`} />
          <Counts title="Cases per scheme" counts={d.per_scheme} total={d.total_cases} label={scheme}
            source="the scheme each case belongs to" />
          <section className="card">
            <h2>Average processing time</h2>
            <p className="big">{formatDuration(d.average_processing_seconds)}</p>
            <p className="muted small">Over {d.decided_cases} decided case(s). Source: {readable(d.average_processing_source)}.</p>
          </section>
          <section className="card">
            <h2>Overdue against SLA</h2>
            <p className="big">{d.overdue_count}</p>
            <p className="muted small">Flag only; nothing changes automatically. Source: {readable(d.overdue_source)}.</p>
          </section>
          {d.overdue_count > 0 && (
            <>
              <Counts title="Overdue by status (where cases are stuck)" counts={d.overdue_by_status} total={d.overdue_count}
                label={status} source="overdue cases, grouped by status" />
              <Counts title="Overdue by scheme" counts={d.overdue_by_scheme} total={d.overdue_count}
                label={scheme} source="overdue cases, grouped by scheme" />
            </>
          )}
          <section className="card wide">
            <h2>Stuck cases</h2>
            <label>No movement for at least <input type="number" min="0" step="1" value={days}
              onChange={(e) => setDays(Math.max(0, Number(e.target.value) || 0))} /> days</label>
            {d.stuck_cases.length === 0 ? <p className="muted">None.</p> : (
              <table>
                <thead><tr><th>Case</th><th>Status</th><th>Scheme</th><th>Last movement</th></tr></thead>
                <tbody>{d.stuck_cases.map((c) => (
                  <tr key={c.case_id}><td><a href={href("case", c.case_id)}>{c.case_id}</a></td><td>{status(c.status)}</td>
                    <td>{scheme(c.scheme)}</td><td>{formatDate(c.last_movement)}</td></tr>
                ))}</tbody>
              </table>
            )}
            <p className="muted small">Source: {readable(d.stuck_source)}. Closed cases are excluded.</p>
          </section>
        </div>
      )}
    </section>
  );
}
