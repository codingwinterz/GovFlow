import { Loading, useApi } from "../useApi.jsx";
import { formatDate, formatRupees, maskIdentifiers } from "../lib/format.js";
import { href } from "../lib/router.js";

// Print-friendly award letter. Every value comes from GET /cases/{id}/award; the browser's
// "Save as PDF" produces the file. Nothing is computed here.
export default function Award({ id }) {
  const award = useApi(`/cases/${encodeURIComponent(id)}/award`);
  const a = award.data;
  return (
    <section>
      <div className="no-print actions">
        <a href={href("case", id)}>Back to case</a>
        <button onClick={() => window.print()} disabled={!a}>Print / Save as PDF</button>
      </div>
      <Loading state={award} />
      {a && (
        <article className="letter">
          {a.demo && <p className="demo-mark">DEMO — synthetic data, not a real award</p>}
          <h1>{a.labels.title}: award summary</h1>
          <table className="plain"><tbody>
            <tr><th>Case</th><td>{a.case_id}</td></tr>
            <tr><th>Applicant</th><td>{maskIdentifiers(a.applicant_name ?? "—")}</td></tr>
            <tr><th>Identity number</th><td>{maskIdentifiers(a.applicant_id ?? "—")}</td></tr>
            <tr><th>Decision</th><td>Approved by officer {a.decision.officer_id} on {a.decision.date}</td></tr>
            <tr><th>Rules version</th><td>{a.rules_version}</td></tr>
          </tbody></table>

          <h2>{a.labels.amounts}</h2>
          <table>
            <thead><tr><th>Item</th><th className="num">Amount</th><th>Formula and inputs (source)</th></tr></thead>
            <tbody>
              {a.items.map((i) => (
                <tr key={i.component}><td>{i.component}</td><td className="num">{formatRupees(i.amount)}</td>
                  <td className="small">{maskIdentifiers(i.formula_note)}</td></tr>
              ))}
              <tr className="total"><td>{a.labels.total}</td><td className="num">{formatRupees(a.total)}</td>
                <td className="small">as recorded by the rules engine (version {a.rules_version})</td></tr>
            </tbody>
          </table>

          <h2>Rules applied</h2>
          <table>
            <thead><tr><th>Rule</th><th>Result</th><th>Clause</th></tr></thead>
            <tbody>{a.rule_results.map((r) => (
              <tr key={r.rule_id}><td>{r.rule_id}</td><td>{r.status}</td><td>{r.clause}</td></tr>
            ))}</tbody>
          </table>
          <p className="muted small">Generated {formatDate(a.generated_at)} from GovFlow case records. The decision is the
            officer's; the amounts and rule results are as computed and stored by the rules engine.</p>
          {a.demo && <p className="demo-mark">DEMO — synthetic data, not a real award</p>}
        </article>
      )}
    </section>
  );
}
