// Timelines from the scheme YAML (source-cited periods), as rows for the case page. Nothing here counts days:
// the SLA clock comes from the API (sla_days); a timeline marked drives_sla is the one that target stands for.
import { appLabel } from "./display.js";

export function timelineRows(timelines) {
  return (timelines || []).map((t) => ({
    id: t.id,
    step: t.label,
    period: t.period,
    source: `${appLabel("source_type", t.source_type)}: ${t.source}`,
    verifyText: t.verify ? `To verify: ${t.verify_note}` : "Sourced",
    verify: Boolean(t.verify),
    clock: Boolean(t.drives_sla),
  }));
}

export function timelineNote(timelines) {
  const clock = (timelines || []).find((t) => t.drives_sla);
  return clock
    ? `For reference. The SLA clock counts only “${clock.label}” (${clock.days} calendar days); working days are not counted.`
    : "For reference. None of these drives the SLA clock; it counts the scheme's target in calendar days.";
}
