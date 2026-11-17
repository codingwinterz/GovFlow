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

// --- states: loading, error, empty, invalid input (audit findings 5, 10, 11, 13, 15, 16) ---------------------------

const OFFICER_LOGIN = { role: "officer", user: "demo-officer", token: "mocked", expires_at: "2099-01-01T00:00:00Z" };

// Opens a page with /api answered by `answer(url, method)`: an object to fulfil, "hang" to never answer.
async function open(hash, answer, { width = 390, login = null } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  if (login) await context.addInitScript((l) => localStorage.setItem("govflow-demo-login", JSON.stringify(l)), login);
  const calls = [];
  await context.route("**/api/**", (r) => {
    calls.push(`${r.request().method()} ${new URL(r.request().url()).pathname}`);
    const res = answer(r.request().url(), r.request().method());
    return res === "hang" ? undefined : r.fulfill(res);
  });
  const page = await context.newPage();
  await page.goto(new URL(hash, base).href);
  return { page, calls, close: () => context.close() };
}

const text = (page, sel) => page.locator(sel).first().innerText();

test("self-check while loading says so (not 'no scheme'), announced as a status", async () => {
  const { page, close } = await open("#/citizen/check", () => "hang");
  await page.waitForSelector("[role=status]");
  assert.match(await text(page, "[role=status]"), /Loading the questions/);
  assert.equal(await page.getByText("No scheme offers a self-check yet.").count(), 0);
  await close();
});

for (const [name, res] of [["a server error", { status: 500, json: { detail: "Internal Server Error" } }],
                           ["a success that is not a list", { json: { detail: "unexpected" } }]]) {
  test(`self-check after ${name} shows an alert with Try again, which reloads`, async () => {
    let fail = true;
    const { page, close } = await open("#/citizen/check", () => (fail ? res : { json: [] }));
    await page.waitForSelector("[role=alert]");
    assert.match(await text(page, "[role=alert]"), /Could not load the questions/);
    fail = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await page.getByText("No scheme offers a self-check yet.").waitFor();
    assert.equal(await page.locator("[role=alert]").count(), 0);
    await close();
  });
}

test("officer page error: plain alert with Retry, never 'Error 500'", async () => {
  let fail = true;
  const { page, close } = await open("#/officer", (url) => (url.includes("/cases") && fail
    ? { status: 500, json: { detail: "Internal Server Error" } } : { json: [] }), { login: OFFICER_LOGIN });
  await page.waitForSelector("[role=alert]");
  const alert = await text(page, "[role=alert]");
  assert.match(alert, /server had a problem/);
  assert.doesNotMatch(alert, /Error 500/);
  fail = false;
  await page.getByRole("button", { name: "Retry" }).click();
  await page.getByText("No cases match these filters.").waitFor();
  await close();
});

test("an unknown case says so and links back to the queue", async () => {
  const { page, close } = await open("#/officer/cases/NOPE-1", (url) => (url.includes("/cases/NOPE-1")
    ? { status: 404, json: { detail: "Unknown case NOPE-1" } } : { json: [] }), { login: OFFICER_LOGIN });
  await page.waitForSelector("[role=alert]");
  assert.match(await text(page, "[role=alert]"), /Unknown case NOPE-1/);
  assert.equal(await page.getByRole("button", { name: "Retry" }).count(), 0);          // retrying cannot help
  assert.equal(await page.getByRole("link", { name: "Back to the queue" }).getAttribute("href"), "#/officer");
  await close();
});

const WIDE_ROW = (i) => ({ case_id: `LA-${String(i).padStart(2, "0")}`, scheme: "land_acquisition", status: "in_officer_review",
  confidence_flag: true, flags_count: 3, flags: [{ kind: "name_match", severity: "high" }, { kind: "low_confidence", severity: "medium" }],
  days_open: 70, sla_days: 60, overdue: true, submitted_at: "2026-11-01T06:00:00Z", created_at: "2026-09-01T06:00:00Z" });
const AUDIT_ROW = (i) => ({ id: i, ts: "2026-11-16T06:51:00Z", actor: "officer:a-rather-long-user-id", action: "officer_decision",
  rules_version: "0.1.0", payload: { decision: "approve" } });

for (const [hash, rows] of [["#/officer", (url) => (url.includes("/cases?") ? [...Array(12).keys()].map(WIDE_ROW) : [])],
                            ["#/officer/cases/LA-01/audit", (url) => (url.includes("/audit") ? [...Array(12).keys()].map(AUDIT_ROW) : [])]]) {
  test(`${hash} at 390px: the wide table scrolls in its own box, the page does not`, async () => {
    const { page, close } = await open(hash, (url) => ({ json: rows(url) }), { login: OFFICER_LOGIN });
    await page.waitForSelector(".table-scroll table");
    const m = await page.evaluate(() => {
      const box = document.querySelector(".table-scroll");
      return { vw: document.documentElement.clientWidth, page: document.documentElement.scrollWidth,
        inner: box.scrollWidth, outer: box.clientWidth, overflow: getComputedStyle(box).overflowX };
    });
    assert.equal(m.page, m.vw, `page scrolls sideways: ${JSON.stringify(m)}`);
    assert.ok(m.inner > m.outer && m.overflow === "auto", `table is not in a scrolling box: ${JSON.stringify(m)}`);
    await close();
  });
}

test("analytics with no cases says so instead of describing an empty scale", async () => {
  const empty = { ...ANALYTICS, total_cases: 0, by_status: {}, per_scheme: {}, decided_cases: 0, average_processing_seconds: null,
    overdue_count: 0, overdue_by_status: {}, overdue_by_scheme: {} };
  const { page, close } = await open("#/officer/analytics", (url) => ({ json: url.includes("/analytics") ? empty : [] }),
    { login: OFFICER_LOGIN });
  await page.getByText("No cases yet.", { exact: false }).waitFor();
  assert.equal(await page.getByText("same scale", { exact: false }).count(), 0);
  await close();
});

for (const [name, ref, code, message] of [["blank", "", "", /reference exactly as it is printed/],
                                          ["a short code", "LA-01", "123", /six digits/],
                                          ["a reference with a space", "LA 01", "123456", /reference exactly as it is printed/]]) {
  test(`tracking with ${name} explains the format and sends nothing`, async () => {
    const { page, calls, close } = await open("#/citizen/track", () => ({ status: 404, json: { detail: "not_found" } }));
    await page.locator("main input").nth(0).fill(ref);
    await page.locator("main input").nth(1).fill(code);
    await page.locator("main form").evaluate((f) => f.requestSubmit ? f.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true })) : f.submit());
    await page.waitForSelector("[role=alert]");
    assert.match(await text(page, "[role=alert]"), message);
    assert.deepEqual(calls.filter((c) => c.includes("/public/status")), []);
    await close();
  });
}

test("tracking inputs are required and the code accepts six digits", async () => {
  const { page, close } = await open("#/citizen/track", () => ({ json: {} }));
  const attrs = await page.locator("main input").evaluateAll((els) => els.map((e) => ({ required: e.required, pattern: e.pattern, max: e.maxLength })));
  assert.deepEqual(attrs, [{ required: true, pattern: "", max: 64 }, { required: true, pattern: "[0-9]{6}", max: 6 }]);
  await close();
});

// --- touch targets and favicon (audit findings 14, 17) -------------------------------------------------------------

const CASE = { case_id: "LA-01", scheme: "land_acquisition", status: "in_officer_review", confidence_flag: false,
  officer_id: null, reference_date: "2026-11-15", submitted_at: "2026-11-10T06:00:00Z", created_at: "2026-11-01T06:00:00Z",
  inputs: {}, rules_version: "0.1.0", labels: { title: "Land acquisition", amounts: "Compensation", total: "Total" }, terms: {},
  documents: [], flags: [], rule_results: [], recommendation: "eligible", explanation: null,
  compensation: { items: [{ component: "land_value", amount: 7500000, formula_note: "x" }], total: 7500000 },
  confirm_fields: [{ ref: "ownership_record.area", value: 0.25 }, { ref: "ownership_record.area_unit", value: "hectare" }] };

test("case page at 390px: every control is at least 24 x 24 px (links inside sentences excepted)", async () => {
  const { page, close } = await open("#/officer/cases/LA-01", (url) => ({ json: url.endsWith("/cases/LA-01") ? CASE : [] }),
    { login: OFFICER_LOGIN });
  await page.locator("section.decision form").waitFor();
  await page.getByLabel("Approve").check();                         // shows the confirmation checkboxes too
  await page.locator(".confirm-item").first().waitFor();
  const small = await page.evaluate(() => {
    const box = (el) => el.getBoundingClientRect();
    const targets = [...document.querySelectorAll("button, select, .actions a, .topbar nav a")]
      .concat([...document.querySelectorAll("input[type=radio], input[type=checkbox]")].map((i) => i.closest("label") || i));
    return targets.filter((el) => { const b = box(el); return b.width > 0 && (b.width < 24 || b.height < 24); })
      .map((el) => `${el.tagName}:${el.textContent.trim().slice(0, 20)} ${Math.round(box(el).width)}x${Math.round(box(el).height)}`);
  });
  assert.deepEqual(small, []);
  await close();
});

test("the landing page loads with no failed requests (favicon included)", async () => {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
  const page = await context.newPage();
  const failed = [];
  page.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  await page.goto(new URL("#/", base).href);
  await page.waitForLoadState("networkidle");
  const icon = await page.locator("link[rel=icon]").getAttribute("href");
  await context.close();
  assert.deepEqual(failed, []);
  assert.equal(icon, "/favicon.svg");
});

for (const hash of PAGES) {
  test(`${hash} at 390px: full width with no sideways scroll`, async () => {
    const m = await measure(390, hash, "light");
    assert.ok(Math.abs(m.main.left - m.main.right) <= 1, `margins differ: ${JSON.stringify(m.main)}`);
    assert.equal(m.scrollWidth, m.vw, "page scrolls sideways");
  });
}

// --- Sahayak helper drawer (text only, English only) ---------------------------------------------------------------

const SELF_CHECK = [{ scheme: "disaster_relief", labels: { title: "Disaster relief: housing damage" },
  guide_label: "This is a guide, not a decision. Only an officer decides.", documents: [], terms: {},
  questions: [{ field: "damage_assessment.notified_area", prompt: "Is your house in the notified area?",
    choices: ["yes", "no"], type: "one_of" }] }];
const TOPICS = { topics: [{ id: "relief_notified_area", title: "What is a notified area?" },
  { id: "what_this_tool_does", title: "What does this helper do?" }], guide: "", language_note: "" };
const FALLBACK = { answer: "The self-check asks whether your house is in the area notified as affected.",
  used_fallback: true, reason: "guard", language: "en", entries: [{ id: "relief_notified_area",
    title: "What is a notified area?", verify: true, tag: "Verify with the relief office",
    source: { name: "GovFlow disaster relief self-check questions", url: "VERIFY" } }] };

function sahayakApi({ ask = () => ({ json: FALLBACK }), topics = () => ({ json: TOPICS }) } = {}) {
  return (url, method) => {
    const path = new URL(url).pathname;
    if (path.endsWith("/public/self-check")) return { json: SELF_CHECK };
    if (path.endsWith("/public/sahayak")) return method === "POST" ? ask() : topics();
    return { json: [] };
  };
}

test("Sahayak drawer at 390px: no sideways scroll, 24 px targets, guide banner, English note", async () => {
  const { page, close } = await open("#/citizen/check", sahayakApi());
  await page.getByRole("button", { name: "Sahayak" }).click();
  await page.locator(".chip").first().waitFor();
  const m = await page.evaluate(() => {
    const box = (el) => el.getBoundingClientRect();
    const small = [...document.querySelectorAll(".drawer button, .drawer textarea")]
      .filter((el) => { const b = box(el); return b.width > 0 && (b.width < 24 || b.height < 24); }).length;
    return { small, scroll: document.documentElement.scrollWidth, vw: window.innerWidth,
      drawer: Math.round(box(document.querySelector(".drawer")).width), text: document.querySelector(".drawer").innerText };
  });
  assert.equal(m.scroll, m.vw, "page scrolls sideways");
  assert.equal(m.drawer, m.vw, "drawer should be full width on a phone");
  assert.equal(m.small, 0);
  assert.match(m.text, /Sahayak answers in English\./);
  assert.match(m.text, /A guide, not a decision\. Only an officer decides\./);
  await close();
});

test("a Sahayak fallback answer is announced and shows its source and the verify tag", async () => {
  const { page, close } = await open("#/citizen/check", sahayakApi());
  await page.getByRole("button", { name: "Sahayak" }).click();
  await page.getByRole("button", { name: "What is a notified area?" }).click();
  const reply = page.locator(".drawer [role=status][aria-live=polite]");
  await reply.getByText("The self-check asks whether").waitFor();
  const text = await reply.innerText();
  assert.match(text, /Source: GovFlow disaster relief self-check questions \(source to be confirmed\)/);
  assert.match(text, /Verify with the relief office/);
  await close();
});

test("Sahayak errors offer Retry, for the question and for the suggestions", async () => {
  let failAsk = true, failTopics = true;
  const { page, close } = await open("#/citizen/check", sahayakApi({
    ask: () => (failAsk ? { status: 500, json: {} } : { json: FALLBACK }),
    topics: () => (failTopics ? { status: 500, json: {} } : { json: TOPICS }) }));
  await page.getByRole("button", { name: "Sahayak" }).click();
  await page.locator(".drawer [role=alert]").getByText("Could not load the suggested questions.").waitFor();
  failTopics = false;
  await page.locator(".drawer").getByRole("button", { name: "Retry" }).click();
  await page.locator(".chip").first().waitFor();
  await page.locator(".drawer textarea").fill("what is a notified area");
  await page.getByRole("button", { name: "Ask" }).click();
  await page.locator(".drawer [role=alert]").getByText("Sahayak could not answer just now.").waitFor();
  failAsk = false;
  await page.locator(".drawer").getByRole("button", { name: "Retry" }).click();
  await page.locator(".drawer [role=status]").getByText("The self-check asks whether").waitFor();
  await close();
});

// --- moving from one case to another never shows the previous case (bug-fix round A) --------------------------------

test("opening another case shows a loading state, never the previous case's heading, flags or decision panel", async () => {
  const flagged = { ...CASE, flags: [{ kind: "name_match", severity: "high", detail: "Lowest similarity 0.5" }] };
  const { page, close } = await open("#/officer/cases/LA-01", (url) => {
    const path = new URL(url).pathname;
    if (path.endsWith("/cases/LA-01")) return { json: flagged };
    if (path.endsWith("/cases/LA-02")) return "hang";                       // the next case is slow to arrive
    return { json: [] };
  }, { login: OFFICER_LOGIN });
  await page.locator(".case-head h1", { hasText: "LA-01" }).waitFor();
  await page.locator("section.decision").waitFor();
  await page.evaluate(() => { location.hash = "#/officer/cases/LA-02"; });
  await page.locator("main [role=status]", { hasText: "Loading" }).waitFor();
  assert.equal(await page.locator(".case-head").count(), 0, "the previous case's heading is still shown");
  assert.equal(await page.locator("ul.flags").count(), 0, "the previous case's flags are still shown");
  assert.equal(await page.locator("section.decision").count(), 0, "the previous case's decision panel is still shown");
  assert.equal(await page.getByText("LA-01").count(), 0);
  await close();
});

// --- keyboard focus is visible on every control, including radios, checkboxes and text areas (round B) ---------------

test("keyboard focus is visible on radios, checkboxes, text areas and inputs of the decision panel", async () => {
  const { page, close } = await open("#/officer/cases/LA-01", (url) => ({ json: url.endsWith("/cases/LA-01") ? CASE : [] }),
    { login: OFFICER_LOGIN });
  await page.locator("section.decision form").waitFor();
  await page.getByLabel("Approve").check();
  await page.locator(".confirm-item").first().waitFor();
  await page.getByLabel("Approve").focus();
  const seen = [];
  for (let i = 0; i < 12; i++) {
    const f = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || !el.closest("section.decision")) return null;
      const s = getComputedStyle(el);
      return { what: `${el.tagName.toLowerCase()}${el.type ? `[${el.type}]` : ""}`,
        visible: s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2 };
    });
    if (f) seen.push(f);
    await page.keyboard.press("Tab");
  }
  const kinds = new Set(seen.map((f) => f.what));
  for (const k of ["input[radio]", "input[checkbox]", "textarea[textarea]"]) assert.ok(kinds.has(k), `never reached ${k}`);
  assert.deepEqual(seen.filter((f) => !f.visible).map((f) => f.what), []);
  await close();
});

// --- the queue shows paused clocks and how many cases wait for the citizen (round D) ----------------------------------

test("the queue counts cases waiting for the citizen, links to them, and marks their clock as paused", async () => {
  const row = (id, status) => ({ case_id: id, scheme: "land_acquisition", status, confidence_flag: false, flags: [],
    flags_count: 0, days_open: 27, sla_days: 60, overdue: false, submitted_at: "2026-10-21T06:00:00Z" });
  const requested = [];
  const { page, close } = await open("#/officer", (url) => {
    const u = new URL(url);
    if (!u.pathname.endsWith("/cases")) return { json: [] };
    requested.push(u.searchParams.get("status"));
    return { json: u.searchParams.get("status") === "needs_info" ? [row("LA-05", "needs_info")] : [row("LA-02", "in_officer_review")] };
  }, { login: OFFICER_LOGIN, width: 1280 });
  await page.locator(".waiting-count").getByText("More information needed: 1").waitFor();
  assert.equal(await page.getByText("clock paused").count(), 0);          // the default filter shows LA-02 only
  await page.getByRole("button", { name: "Show these cases" }).click();
  await page.locator("table tbody tr", { hasText: "LA-05" }).waitFor();
  const cell = await page.locator("table tbody tr", { hasText: "LA-05" }).locator("td.num").innerText();
  assert.match(cell, /27\s*clock paused/);
  assert.equal(await page.locator("select").first().inputValue(), "needs_info");
  await close();
});

// --- the tracking status pill sizes to its text (round G) -------------------------------------------------------------

test("the tracking page's status pill is as wide as its text, not the page", async () => {
  const view = { case_ref: "LA-01", scheme: "land_acquisition", status: "approved", next_step: "approved", missing: [],
    notices: [], documents_needed: null, decision: { decision: "approve", date: "2026-11-17" }, amounts: null };
  const { page, close } = await open("#/citizen/track", () => ({ json: view }), { width: 1280 });
  await page.locator("main input").nth(0).fill("LA-01");
  await page.locator("main input").nth(1).fill("123456");
  await page.locator("main form button").click();
  const pill = page.locator(".citizen-view .line.status");
  await pill.waitFor();
  const { pillW, textW, viewW } = await pill.evaluate((el) => {
    const r = document.createRange(); r.selectNodeContents(el);
    return { pillW: el.getBoundingClientRect().width, textW: r.getBoundingClientRect().width,
      viewW: el.parentElement.getBoundingClientRect().width };
  });
  assert.ok(pillW <= textW + 40, `pill ${pillW}px for ${textW}px of text`);
  assert.ok(pillW < viewW / 2, `pill ${pillW}px stretches across ${viewW}px`);
  assert.match(await page.locator(".citizen-view").innerText(), /17 Nov 2026/);   // round E, in the browser
  await close();
});
