// One scale for all of Analytics' count bars, so a bar in one chart compares with a bar in another.
// Counts only: nothing here touches money.

function niceStep(raw) {
  const power = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 5, 10]) if (m * power >= raw) return Math.max(1, m * power);
  return Math.max(1, 10 * power);
}

export function sharedScale(groups) {
  const max = Math.max(0, ...groups.flatMap((g) => Object.values(g || {})));
  if (max === 0) return { top: 1, ticks: [0, 1] };
  const step = niceStep(max / 4);
  const top = step * Math.ceil(max / step);
  const ticks = [];
  for (let v = 0; v <= top; v += step) ticks.push(v);
  return { top, ticks };
}

export function barPercent(count, top) {
  return top > 0 ? (100 * count) / top : 0;
}
