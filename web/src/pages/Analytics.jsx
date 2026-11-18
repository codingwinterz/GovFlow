import { useState } from "react";
import { Loading, useApi } from "../useApi.jsx";
import { formatDate, formatDuration, formatRupees } from "../lib/format.js";
import { href } from "../lib/router.js";
import { appLabel, flagLabel, readable, schemeTitle } from "../lib/display.js";
import { barPercent, sharedScale } from "../lib/chart.js";

const STAGES = [
  "received", "extracted", "verified", "assessed", "in_officer_review",
  "needs_info", "approved", "rejected", "withdrawn",
];

// Bars use the page's shared scale (sharedScale over every chart), so lengths compare across charts.
function Counts({ title, counts, scale, source, label }) {
  const rows = Object.entries(counts || {});
  return (
    <section className="card">
      <h2>{title}</h2>
      {rows.length === 0 ? <p className="muted">None.</p> : (
        <table className="bars">
          <tbody>
            {rows.map(([k, n]) => (
              <tr key={k}>
                <td className="bar-label">{label(k)}</td>
                <td className="bar-cell" aria-hidden="true">
                  <span className="bar-track"><span className={`bar${n === 0 ? " zero" : ""}`} style={{ width: `${barPercent(n, scale.top)}%` }} /></span>
                </td>
                <td className="num">{n}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr><td /><td className="axis" aria-hidden="true"><span className="axis-track">
              {scale.ticks.map((tick) => <span key={tick} style={{ left: `${barPercent(tick, scale.top)}%` }}>{tick}</span>)}
            </span></td><td /></tr>
          </tfoot>
        </table>
      )}
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
  const severity = (k) => appLabel("severity", k);
  const scheme = (k) => schemeTitle(schemes.data, k);
  const mergedTerms = Object.assign({}, ...(schemes.data || []).map((s) => s.terms || {}));
  const scale = d && sharedScale([d.by_status, d.per_scheme, d.overdue_by_status, d.overdue_by_scheme]);

  return (
    <section>
      <h1>Analytics</h1>
      <Loading state={a} />
      {d && (
        <div role="status" aria-live="polite">
          {d.total_cases === 0
            ? <p className="muted">No cases yet. The charts fill in once cases are created at intake.</p>
            : <p className="muted">Every bar chart below uses the same scale, 0 to {scale.top} cases, so bar lengths compare across charts.</p>}
        </div>
      )}
      {d && (
        <div className="grid">
          <Counts title="Cases by status" counts={d.by_status} scale={scale} label={status}
            source={`${d.total_cases} cases in the database`} />
          <Counts title="Cases per scheme" counts={d.per_scheme} scale={scale} label={scheme}
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
          {d.average_days_open !== undefined && (
            <section className="card">
              <h2>Average days open (excluding waiting)</h2>
              <p className="big">{d.average_days_open === null ? "—" : `${d.average_days_open} d`}</p>
              {d.average_days_open_by_scheme && (
                <ul>
                  {Object.entries(d.average_days_open_by_scheme).map(([s, avg]) => (
                    <li key={s}>{scheme(s)}: <strong>{avg === null ? "—" : `${avg} d`}</strong></li>
                  ))}
                </ul>
              )}
              <p className="muted small">Source: {readable(d.average_days_open_source)}.</p>
            </section>
          )}
          {d.overdue_count > 0 && (
            <>
              <Counts title="Overdue by status (where cases are stuck)" counts={d.overdue_by_status} scale={scale}
                label={status} source="overdue cases, grouped by status" />
              <Counts title="Overdue by scheme" counts={d.overdue_by_scheme} scale={scale}
                label={scheme} source="overdue cases, grouped by scheme" />
            </>
          )}
          {d.by_scheme_and_status && (
            <section className="card wide">
              <h2>Cases by scheme and stage</h2>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Scheme</th>
                      {STAGES.map((st) => <th key={st} className="num">{status(st)}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(d.by_scheme_and_status).map(([s, stageMap]) => (
                      <tr key={s}>
                        <td>{scheme(s)}</td>
                        {STAGES.map((st) => <td key={st} className="num">{stageMap[st] ?? 0}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">Source: all loaded schemes and case lifecycle stages.</p>
            </section>
          )}
          {d.liability && (
            <section className="card wide">
              <h2>Committed and pending liability</h2>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Scheme</th>
                      <th className="num">Approved (committed)</th>
                      <th className="num">In pipeline (pending)</th>
                      <th className="num">Combined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(d.liability.committed_by_scheme || {}).map((s) => (
                      <tr key={s}>
                        <td>{scheme(s)}</td>
                        <td className="num">{formatRupees(d.liability.committed_by_scheme[s])}</td>
                        <td className="num">{formatRupees(d.liability.pending_by_scheme?.[s] ?? 0)}</td>
                        <td className="num">{formatRupees(d.liability.combined_by_scheme?.[s] ?? 0)}</td>
                      </tr>
                    ))}
                    <tr className="total">
                      <td>Overall</td>
                      <td className="num">{formatRupees(d.liability.committed_total)}</td>
                      <td className="num">{formatRupees(d.liability.pending_total)}</td>
                      <td className="num">{formatRupees(d.liability.combined_total)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="muted small">Source: {readable(d.liability.source)}.</p>
            </section>
          )}
          {d.flags && (
            <section className="card wide">
              <h2>Verification flags</h2>
              <p>
                <strong>Open: {d.flags.open_count}</strong> ·{" "}
                <strong>Resolved: {d.flags.resolved_count}</strong> ·{" "}
                All recorded: {d.flags.total_count}
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr><th>Group</th><th>Category</th><th className="num">Count</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(d.flags.by_severity || {}).map(([sev, count]) => (
                      <tr key={`sev-${sev}`}>
                        <td>Severity</td>
                        <td>{severity(sev)}</td>
                        <td className="num">{count}</td>
                      </tr>
                    ))}
                    {Object.entries(d.flags.by_scheme || {}).map(([s, count]) => (
                      <tr key={`sch-${s}`}>
                        <td>Scheme</td>
                        <td>{scheme(s)}</td>
                        <td className="num">{count}</td>
                      </tr>
                    ))}
                    {Object.entries(d.flags.by_kind || {}).map(([k, count]) => (
                      <tr key={`kind-${k}`}>
                        <td>Flag type</td>
                        <td>{flagLabel(mergedTerms, k)}</td>
                        <td className="num">{count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">Source: {readable(d.flags.source)}.</p>
            </section>
          )}
          <section className="card wide">
            <h2>Stuck cases</h2>
            <label>No movement for at least <input type="number" min="0" step="1" value={days}
              onChange={(e) => setDays(Math.max(0, Number(e.target.value) || 0))} /> days</label>
            {d.stuck_cases.length === 0 ? <p className="muted">None.</p> : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Case</th><th>Status</th><th>Scheme</th><th>Last movement</th></tr></thead>
                  <tbody>{d.stuck_cases.map((c) => (
                    <tr key={c.case_id}><td><a href={href("case", c.case_id)}>{c.case_id}</a></td><td>{status(c.status)}</td>
                      <td>{scheme(c.scheme)}</td><td>{formatDate(c.last_movement)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <p className="muted small">Source: {readable(d.stuck_source)}. Closed cases are excluded.</p>
          </section>
        </div>
      )}
    </section>
  );
}
