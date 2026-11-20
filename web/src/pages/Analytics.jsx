import { useState } from "react";
import { Loading, useApi } from "../useApi.jsx";
import { formatDate, formatDuration, formatRupees } from "../lib/format.js";
import { href } from "../lib/router.js";
import { appLabel, flagLabel, readable, schemeTitle } from "../lib/display.js";
import { barPercent, sharedScale } from "../lib/chart.js";
import { attentionCases, headlineTiles } from "../lib/glance.js";
import { More } from "../Disclosure.jsx";

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

// One small table per grouping of the verification flags; counts exactly as the API sent them.
function FlagTable({ caption, head, counts, label }) {
  const rows = Object.entries(counts || {});
  return (
    <table className="flag-table">
      <caption>{caption}</caption>
      <thead><tr><th>{head}</th><th className="num">Count</th></tr></thead>
      <tbody>
        {rows.length === 0 ? <tr><td className="muted" colSpan={2}>None</td></tr>
          : rows.map(([k, n]) => <tr key={k}><td>{label(k)}</td><td className="num">{n}</td></tr>)}
      </tbody>
    </table>
  );
}

const TILE_NOTE = {
  awaiting: "Ready for an officer to decide.",
  overdue: "Open cases past their scheme's target.",
  days_open: "Waiting for the citizen is not counted.",
  pending: "Cases still in the pipeline.",
};

// Each headline value is the API field as sent; formatting only.
function tileValue(tile) {
  if (tile.value === null || tile.value === undefined) return "—";
  if (tile.key === "pending") return formatRupees(tile.value);
  if (tile.key === "days_open") return `${tile.value} d`;
  return tile.value;
}

// Open cases the API marks overdue, or with a high-severity flag, each linking to the case. Read from the queue
// endpoint (officers and clerks); an administrator sees a plain note instead.
const FIRST = 8;     // the attention list shows this many; the rest are one click away, never dropped

function AttentionItem({ c, schemes }) {
  return (
    <li>
      <a href={href("case", c.case_id)}>{c.case_id}</a>
      <span className="muted small">{schemeTitle(schemes, c.scheme)}</span>
      {c.overdue && <span className="badge warn">overdue</span>}
      {c.high && <span className="sev sev-high">{appLabel("severity", "high")}</span>}
    </li>
  );
}

function Attention({ schemes }) {
  const cases = useApi("/cases");
  const list = attentionCases(cases.data);
  return (
    <section className="card attention-card">
      <h2>Attention needed</h2>
      {cases.error?.status === 403 ? <p className="muted">The case list is for officers and clerks.</p> : (
        <>
          <Loading state={cases} />
          {cases.data && (list.length === 0 ? <p className="muted">Nothing is overdue or flagged high.</p> : (
            <>
              <ul className="attention-list">{list.slice(0, FIRST).map((c) => <AttentionItem key={c.case_id} c={c} schemes={schemes} />)}</ul>
              {list.length > FIRST && (
                <details className="why attention-more">
                  <summary>Show all {list.length}</summary>
                  <ul className="attention-list">{list.slice(FIRST).map((c) => <AttentionItem key={c.case_id} c={c} schemes={schemes} />)}</ul>
                </details>
              )}
            </>
          ))}
        </>
      )}
      <p className="muted small">Source: the case queue (overdue as the API marks it; flags of high severity).</p>
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
        <>
          <div className="headline-tiles">
            {headlineTiles(d).map((tile) => (
              <section key={tile.key} className={`card tile${tile.key === "overdue" ? " overdue-tile" : ""}`} data-source={tile.source}>
                <h2>{tile.label}</h2>
                <p className={`big${tile.key === "pending" ? " money" : ""}`}>{tileValue(tile)}</p>
                <p className="muted small">{TILE_NOTE[tile.key]}</p>
                {tile.key === "overdue" && (
                  <details className="how-counted">
                    <summary>How this is counted</summary>
                    <p className="muted small">Waiting for the citizen does not count. A flag only: nothing changes
                      automatically. Source: {readable(d.overdue_source)}.</p>
                  </details>
                )}
              </section>
            ))}
          </div>
          <div className="grid top-row">
            <Counts title="Cases by stage" counts={d.by_status} scale={scale} label={status}
              source={`${d.total_cases} cases in the database`} />
            <Attention schemes={schemes.data} />
          </div>
          <More title="More detail" term="every table and chart" className="more-detail">
        <div className="grid">
          <div className="tiles wide">
          <section className="card tile">
            <h2>Cases</h2>
            <p className="big">{d.total_cases}</p>
            <p className="muted small">In the database, every status.</p>
          </section>
          <section className="card tile">
            <h2>Awaiting officer decision</h2>
            <p className="big">{d.by_status?.in_officer_review ?? 0}</p>
            <p className="muted small">Ready for an officer to decide.</p>
          </section>
          <section className="card tile">
            <h2>Overdue against SLA</h2>
            <p className="big">{d.overdue_count}</p>
            <p className="muted small">Open cases past their scheme's target.</p>
          </section>
          {d.average_days_open !== undefined && (
            <section className="card tile">
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
          <section className="card tile">
            <h2>Average processing time</h2>
            <p className="big">{formatDuration(d.average_processing_seconds)}</p>
            <p className="muted small">Over {d.decided_cases} decided case(s). Source: {readable(d.average_processing_source)}.</p>
          </section>
          {d.liability && (
            <>
              <section className="card tile">
                <h2>Committed liability</h2>
                <p className="big money">{formatRupees(d.liability.committed_total)}</p>
                <p className="muted small">Approved cases.</p>
              </section>
              <section className="card tile">
                <h2>Pending liability</h2>
                <p className="big money">{formatRupees(d.liability.pending_total)}</p>
                <p className="muted small">Cases still in the pipeline.</p>
              </section>
            </>
          )}
          </div>
          {d.by_scheme_and_status && (
            <section className="card wide">
              <h2>Cases by scheme and stage</h2>
              <div className="table-scroll">
                <table className="stage-table">
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
          <h2 className="group-title wide">Charts</h2>
          <Counts title="Cases per scheme" counts={d.per_scheme} scale={scale} label={scheme}
            source="the scheme each case belongs to" />
          {d.overdue_count > 0 && (
            <>
              <Counts title="Overdue by status (where cases are stuck)" counts={d.overdue_by_status} scale={scale}
                label={status} source="overdue cases, grouped by status" />
              <Counts title="Overdue by scheme" counts={d.overdue_by_scheme} scale={scale}
                label={scheme} source="overdue cases, grouped by scheme" />
            </>
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
              <div className="flag-tables">
                <FlagTable caption="By severity" head="Severity" counts={d.flags.by_severity} label={severity} />
                <FlagTable caption="By scheme" head="Scheme" counts={d.flags.by_scheme} label={scheme} />
                <FlagTable caption="By flag type" head="Flag type" counts={d.flags.by_kind} label={(k) => flagLabel(mergedTerms, k)} />
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
          </More>
        </>
      )}
    </section>
  );
}
