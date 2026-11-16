// Browser check: citizen content is centred. Starts its own Vite dev server, drives the installed Chrome.
// Run with `npm run test:layout`. Needs Google Chrome; no API server is needed (pages render without data).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "vite";
import { chromium } from "playwright-core";

const PAGES = ["#/citizen", "#/citizen/check", "#/citizen/track"];
let server, browser, base;

before(async () => {
  server = await createServer({ root: new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"),
    server: { port: 0, host: "127.0.0.1" }, logLevel: "silent" });
  await server.listen();
  base = server.resolvedUrls.local[0];
  browser = await chromium.launch({ channel: "chrome" });
});

after(async () => {
  await browser?.close();
  await server?.close();
});

async function measure(width, hash, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  await context.addInitScript((t) => { try { localStorage.setItem("govflow-citizen-theme", t); } catch { /* ignore */ } }, theme);
  const page = await context.newPage();
  await page.goto(new URL(hash, base).href);
  await page.waitForSelector("main.content");
  const m = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const box = (sel) => { const r = document.querySelector(sel).getBoundingClientRect(); return { left: r.left, right: vw - r.right, width: r.width }; };
    return { vw, scrollWidth: document.documentElement.scrollWidth, theme: document.querySelector(".shell").dataset.theme,
      main: box("main.content"), header: box(".topbar-inner") };
  });
  await context.close();
  return m;
}

for (const theme of ["light", "dark"]) {
  for (const hash of PAGES) {
    test(`${hash} (${theme}) at 1280px: content has equal left and right margins, aligned with the header`, async () => {
      const m = await measure(1280, hash, theme);
      assert.equal(m.theme, theme);
      assert.ok(m.main.left > 16, `content touches the left edge: ${JSON.stringify(m.main)}`);
      assert.ok(Math.abs(m.main.left - m.main.right) <= 1, `margins differ: ${JSON.stringify(m.main)}`);
      assert.ok(Math.abs(m.main.left - m.header.left) <= 1, `content and header not aligned: ${JSON.stringify(m)}`);
      assert.equal(m.scrollWidth, m.vw, "page scrolls sideways");
    });
  }
}

// Synthetic analytics payload (no real data): counts chosen so the shared scale is 0..30 with ticks every 10.
const ANALYTICS = {
  total_cases: 30, by_status: { in_officer_review: 21, approved: 6, needs_info: 3 },
  per_scheme: { land_acquisition: 18, disaster_relief: 12 },
  average_processing_seconds: 86400, decided_cases: 6, average_processing_source: "decided_cases",
  overdue_count: 4, overdue_source: "sla", overdue_by_status: { in_officer_review: 4 }, overdue_by_scheme: { land_acquisition: 4 },
  stuck_cases: [], stuck_source: "audit",
};

for (const width of [1280, 390]) {
  test(`analytics at ${width}px: every chart draws the shared scale at the same pixel width, ticks on the track`, async () => {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    await context.addInitScript(() => localStorage.setItem("govflow-demo-login", JSON.stringify({ role: "officer", user: "demo-officer", token: "mocked",
      expires_at: "2099-01-01T00:00:00Z" })));
    await context.route("**/api/**", (r) => r.fulfill({ json: r.request().url().includes("/analytics") ? ANALYTICS : [] }));
    const page = await context.newPage();
    await page.goto(new URL("#/officer/analytics", base).href);
    await page.waitForSelector("table.bars");
    const charts = await page.evaluate(() => [...document.querySelectorAll("table.bars")].map((t) => {
      const track = t.querySelector(".bar-track").getBoundingClientRect();
      const ticks = [...t.querySelectorAll(".axis-track > span")].map((s) => { const b = s.getBoundingClientRect(); return { text: s.textContent, l: b.left, r: b.right }; });
      const firstBar = t.querySelector(".bar").getBoundingClientRect().width;
      const firstCount = Number(t.querySelector("td.num").textContent);
      return { trackL: track.left, trackR: track.right, trackW: track.width, ticks, firstBar, firstCount };
    }));
    await context.close();
    assert.equal(charts.length, 4);
    for (const c of charts) {
      assert.ok(Math.abs(c.trackW - charts[0].trackW) <= 1, `track widths differ: ${charts.map((x) => x.trackW)}`);
      assert.deepEqual(c.ticks.map((t) => t.text), ["0", "10", "20", "30"]);
      assert.ok(Math.abs(c.ticks[0].l - c.trackL) <= 1, "tick 0 is not under the start of the track");
      assert.ok(Math.abs(c.ticks.at(-1).r - c.trackR) <= 1, "top tick is not under the end of the track");
      for (let i = 1; i < c.ticks.length; i++) assert.ok(c.ticks[i].l >= c.ticks[i - 1].r + 2, "tick labels overlap");
      assert.ok(Math.abs(c.firstBar - (c.trackW * c.firstCount) / 30) <= 1, "bar length is not count / shared top");
    }
  });
}

for (const hash of PAGES) {
  test(`${hash} at 390px: full width with no sideways scroll`, async () => {
    const m = await measure(390, hash, "light");
    assert.ok(Math.abs(m.main.left - m.main.right) <= 1, `margins differ: ${JSON.stringify(m.main)}`);
    assert.equal(m.scrollWidth, m.vw, "page scrolls sideways");
  });
}
