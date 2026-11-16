// Finding 5: shared analytics scale, light-by-default citizen theme, styled navigation.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { barPercent, sharedScale } from "./chart.js";
import { nextTheme, themeFor } from "./theme.js";

const SRC = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const read = (p) => readFileSync(join(SRC, p), "utf8");

test("one scale for every bar chart: round ticks that cover the largest count", () => {
  assert.deepEqual(sharedScale([{ a: 3, b: 1 }, { c: 2 }]), { top: 3, ticks: [0, 1, 2, 3] });
  assert.deepEqual(sharedScale([{ a: 21 }, { b: 9 }]), { top: 30, ticks: [0, 10, 20, 30] });
  assert.deepEqual(sharedScale([{ a: 7 }]), { top: 8, ticks: [0, 2, 4, 6, 8] });
  assert.deepEqual(sharedScale([{}, {}]), { top: 1, ticks: [0, 1] });         // nothing to draw: still a valid axis
  assert.deepEqual(sharedScale([{ a: 120 }]), { top: 150, ticks: [0, 50, 100, 150] });
});

test("bar widths are a share of the shared top, never of each chart's own total", () => {
  assert.equal(barPercent(15, 30), 50);
  assert.equal(barPercent(0, 30), 0);
  assert.equal(barPercent(5, 0), 0);
  const analytics = read("pages/Analytics.jsx");
  assert.match(analytics, /sharedScale\(/);
  assert.match(analytics, /barPercent\(/);
  assert.doesNotMatch(analytics, /\/ total/);
});

test("citizen pages are light unless the citizen chose dark; staff pages follow the system", () => {
  assert.equal(themeFor("citizen", null), "light");
  assert.equal(themeFor("citizen", "dark"), "dark");
  assert.equal(themeFor("citizen", "nonsense"), "light");
  assert.equal(themeFor("officer", null), "system");
  assert.equal(themeFor("landing", null), "light");
  assert.equal(nextTheme("light"), "dark");
  assert.equal(nextTheme("dark"), "light");
});

test("the citizen shell sets its theme and offers the switch", () => {
  const shell = read("shells/CitizenShell.jsx");
  assert.match(shell, /data-theme=\{theme\}/);
  assert.match(shell, /nextTheme\(/);
});

test("stylesheet: light by default, dark only by choice or (for staff) by system preference", () => {
  const css = read("styles.css");
  const root = css.match(/:root\s*\{([^}]*)\}/)[1];
  assert.match(root, /--bg:\s*#f6f7f9/);                                    // light tokens on :root
  assert.match(css, /\[data-theme="dark"\]\s*\{/);                           // chosen dark
  assert.match(css, /prefers-color-scheme: dark[\s\S]*?\[data-theme="system"\]/);   // system dark: staff only
});

test("navigation links have a visible current-page state and focus ring", () => {
  const css = read("styles.css");
  assert.match(css, /\.topbar nav a\[aria-current="page"\]/);
  assert.match(css, /\.topbar nav a:focus-visible/);
});
