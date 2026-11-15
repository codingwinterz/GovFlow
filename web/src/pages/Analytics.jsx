import { useState } from "react";
import { Loading, useApi } from "../useApi.jsx";
import { formatDate, formatDuration } from "../lib/format.js";
import { href } from "../lib/router.js";

function Counts({ title, counts, total, source }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      <table className="bars"><tbody>
        {Object.entries(counts).map(([k, n]) => (
          <tr key={k}>
            <td>{k}</td><td className="num">{n}</td>
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
  const d = a.data;
  return (
    <section>
      <h1>Analytics</h1>
      <Loading state={a} />
      {d && (
        <div className="grid">
          <Counts title="Cases by status" counts={d.by_status} total={d.total_cases} source={`${d.total_cases} cases in the database`} />
          <Counts title="Cases per scheme" counts={d.per_scheme} total={d.total_cases} source="case scheme field" />
          <section className="card">
            <h2>Average processing time</h2>
            <p className="big">{formatDuration(d.average_processing_seconds)}</p>
            <p className="muted small">Over {d.decided_cases} decided case(s). Source: {d.average_processing_source}.</p>
          </section>
          <section className="card wide">
            <h2>Stuck cases</h2>
            <label>No movement for at least <input type="number" min="0" step="1" value={days}
              onChange={(e) => setDays(Math.max(0, Number(e.target.value) || 0))} /> days</label>
            {d.stuck_cases.length === 0 ? <p className="muted">None.</p> : (
              <table>
                <thead><tr><th>Case</th><th>Status</th><th>Scheme</th><th>Last movement</th></tr></thead>
                <tbody>{d.stuck_cases.map((c) => (
                  <tr key={c.case_id}><td><a href={href("case", c.case_id)}>{c.case_id}</a></td><td>{c.status}</td>
                    <td>{c.scheme}</td><td>{formatDate(c.last_movement)}</td></tr>
                ))}</tbody>
              </table>
            )}
            <p className="muted small">Source: {d.stuck_source}. Closed cases are excluded.</p>
          </section>
        </div>
      )}
    </section>
  );
}
