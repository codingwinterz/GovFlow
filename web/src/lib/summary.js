// The case page's summary strip. Nothing here touches money: the total is the stored calculation as the API sent it.
// The clock reads the API's own queue row (days_open, sla_days, overdue from app/sla.py, waiting time excluded);
// the only sum is the day difference that turns those two counts into words.

const CLOSED = { approved: "Decided", rejected: "Decided", withdrawn: "Closed" };
const SEVERITIES = ["high", "medium", "low"];
const days = (n) => `${n} ${n === 1 ? "day" : "days"}`;

export function slaClock(row) {
  if (!row || !Number.isFinite(row.days_open) || !Number.isFinite(row.sla_days)) return null;
  const at = `Day ${row.days_open} of a ${row.sla_days}-day target`;
  if (CLOSED[row.status]) return { kind: "closed", text: `${CLOSED[row.status]} after ${days(row.days_open)}`,
    title: `Target was ${row.sla_days} days` };
  if (row.status === "needs_info") return { kind: "paused", text: "Clock paused (waiting for the citizen)",
    title: `${at}; days open do not grow while the citizen is asked for documents` };
  if (row.overdue) return { kind: "overdue", text: `Overdue by ${days(row.days_open - row.sla_days)}`, title: at };
  const left = row.sla_days - row.days_open;
  return { kind: "left", text: left === 0 ? "Due today" : `${days(left)} left`, title: at };
}

export function flagCounts(flags) {
  const counts = {};
  for (const f of flags || []) counts[f.severity] = (counts[f.severity] ?? 0) + 1;
  const known = SEVERITIES.filter((s) => counts[s]).map((s) => ({ severity: s, count: counts[s] }));
  const other = Object.keys(counts).filter((s) => !SEVERITIES.includes(s)).map((s) => ({ severity: s, count: counts[s] }));
  return [...known, ...other];
}

// A scheme with no compensation section calculates no amount: no amounts card, summary total or award letter.
export function showsAmounts(detail) {
  return detail?.has_compensation !== false;
}

export function summaryTotal(detail) {
  const total = detail?.compensation?.total;
  return total === undefined ? null : total;
}
