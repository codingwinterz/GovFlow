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
  by_scheme_and_status: {
    land_acquisition: { received: 0, extracted: 0, verified: 0, in_officer_review: 12, needs_info: 2, approved: 4, rejected: 0, withdrawn: 0 },
    disaster_relief: { received: 0, extracted: 0, verified: 0, in_officer_review: 9, needs_info: 1, approved: 2, rejected: 0, withdrawn: 0 },
  },
  average_processing_seconds: 86400, decided_cases: 6, average_processing_source: "decided_cases",
  average_days_open: 14.5, average_days_open_by_scheme: { land_acquisition: 16.2, disaster_relief: 12.0 },
  average_days_open_source: "cases.submitted_at -> reference_date minus needs_info waiting",
  overdue_count: 4, overdue_source: "sla", overdue_by_status: { in_officer_review: 4 }, overdue_by_scheme: { land_acquisition: 4 },
  liability: {
    committed_total: 4250000, committed_by_scheme: { land_acquisition: 4000000, disaster_relief: 250000 },
    pending_total: 12500000, pending_by_scheme: { land_acquisition: 11800000, disaster_relief: 700000 },
    combined_total: 16750000, combined_by_scheme: { land_acquisition: 15800000, disaster_relief: 950000 },
    source: "compensation_items + cases.status (approved vs open pipeline; excludes rejected/withdrawn)",
  },
  flags: {
    total_count: 7, open_count: 5, resolved_count: 2,
    by_kind: { name_match: 3, tenant_claim: 2, low_confidence: 2 },
    by_severity: { high: 5, medium: 2 },
    by_scheme: { land_acquisition: 5, disaster_relief: 2 },
    source: "flags + audit_logs.action=flag_resolution",
  },
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
      const ticks = [...t.querySelectorAll(".axis-track > span")].map((s) => {
        const b = s.getBoundingClientRect();
        return { text: s.textContent, l: b.left, r: b.right, h: b.height, lines: s.getClientRects().length };
      });
      const firstBar = t.querySelector(".bar").getBoundingClientRect().width;
      const firstCount = Number(t.querySelector("td.num").textContent);
      return { trackL: track.left, trackR: track.right, trackW: track.width, ticks, firstBar, firstCount };
    }));
    const layout = await page.evaluate(() => ({
      vw: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      bodyText: document.querySelector("main.content").innerText,
    }));
    await context.close();
    assert.equal(layout.scrollWidth, layout.vw, `analytics page scrolls sideways at ${width}px`);
    assert.match(layout.bodyText, /Average days open \(excluding waiting\)/);
    assert.match(layout.bodyText, /Cases by scheme and stage/);
    assert.match(layout.bodyText, /Committed and pending liability/);
    assert.match(layout.bodyText, /Verification flags/);
    assert.equal(charts.length, 4);
    for (const c of charts) {
      assert.ok(Math.abs(c.trackW - charts[0].trackW) <= 1, `track widths differ: ${charts.map((x) => x.trackW)}`);
      assert.deepEqual(c.ticks.map((t) => t.text), ["0", "10", "20", "30"]);
      assert.ok(c.ticks.every((t) => t.lines === 1 && Math.abs(t.h - c.ticks[0].h) <= 1), `tick label wrapped: ${JSON.stringify(c.ticks)}`);
      assert.ok(Math.abs(c.ticks[0].l - c.trackL) <= 1, "tick 0 is not under the start of the track");
      assert.ok(Math.abs(c.ticks.at(-1).r - c.trackR) <= 1, "top tick is not under the end of the track");
      for (let i = 1; i < c.ticks.length; i++) assert.ok(c.ticks[i].l >= c.ticks[i - 1].r + 2, "tick labels overlap");
      assert.ok(Math.abs(c.firstBar - (c.trackW * c.firstCount) / 30) <= 1, "bar length is not count / shared top");
    }

  });
}

for (const width of [1280, 390]) {
  test(`analytics extended tables at ${width}px: scheme-stage, liability and flags wrapped in .table-scroll with values and no page overflow`, async () => {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    await context.addInitScript(() => localStorage.setItem("govflow-demo-login", JSON.stringify({ role: "admin", user: "demo-admin", token: "mocked",
      expires_at: "2099-01-01T00:00:00Z" })));
    await context.route("**/api/**", (r) => r.fulfill({ json: r.request().url().includes("/analytics") ? ANALYTICS : [] }));
    const page = await context.newPage();
    await page.goto(new URL("#/officer/analytics", base).href);
    await page.waitForSelector(".table-scroll table");
    const info = await page.evaluate(() => {
      const card = (heading) => [...document.querySelectorAll("section.card")]
        .find((s) => s.querySelector("h2")?.textContent?.trim() === heading);
      const inspectTable = (heading) => {
        const c = card(heading);
        const wrap = c?.querySelector(".table-scroll");
        const tbl = wrap?.querySelector("table");
        return {
          hasCard: Boolean(c),
          hasScrollWrap: Boolean(wrap && tbl),
          overflowX: wrap ? getComputedStyle(wrap).overflowX : null,
          inner: wrap ? wrap.scrollWidth : 0,
          outer: wrap ? wrap.clientWidth : 0,
          text: c ? c.innerText : "",
        };
      };
      return {
        vw: document.documentElement.clientWidth,
        pageScroll: document.documentElement.scrollWidth,
        stage: inspectTable("Cases by scheme and stage"),
        liability: inspectTable("Committed and pending liability"),
        flagsText: card("Verification flags")?.innerText || "",
      };
    });
    await context.close();
    assert.equal(info.pageScroll, info.vw, `analytics page scrolls sideways at ${width}px`);
    assert.ok(info.stage.hasScrollWrap && info.stage.overflowX === "auto", "scheme-stage table not in .table-scroll");
    assert.ok(info.liability.hasScrollWrap && info.liability.overflowX === "auto", "liability table not in .table-scroll");
    if (width === 390) {
      assert.ok(info.stage.inner > info.stage.outer, `scheme-stage table should scroll inside .table-scroll at 390px: ${JSON.stringify(info.stage)}`);
    }
    assert.match(info.stage.text, /\b12\b/);
    assert.match(info.stage.text, /\b9\b/);
    assert.match(info.liability.text, /₹42,50,000\.00/);
    assert.match(info.liability.text, /₹1,25,00,000\.00/);
    assert.match(info.liability.text, /₹1,67,50,000\.00/);
    assert.match(info.flagsText, /Open:\s*5/);
    assert.match(info.flagsText, /Resolved:\s*2/);
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
  assert.equal(await page.getByText("clock paused").count(), 0);          // the list (all statuses) shows LA-02 only
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

// --- Citizen document pre-check card (in memory, zero storage) -----------------------------------------------------

const PRECHECK_OPTIONS = {
  schemes: [
    {
      scheme: "land_acquisition",
      title: "Land acquisition compensation",
      documents: [
        { id: "ownership_record", label: "Ownership record (Form I & XIV)" },
        { id: "identity_proof", label: "Identity proof" },
      ],
    },
    {
      scheme: "disaster_relief",
      title: "Disaster relief: housing damage",
      documents: [
        { id: "identity_proof", label: "Identity proof" },
        { id: "damage_assessment", label: "Damage assessment report" },
      ],
    },
  ],
  disclaimer: "A quick check, not an application. An officer reviews every document.",
  language_note: "Document pre-check feedback is in English.",
  nothing_saved_note: "Nothing is saved: your file and its text are checked in memory and never stored.",
};

const PRECHECK_REPLY = {
  scheme_label: "Land acquisition compensation",
  document_label: "Ownership record (Form I & XIV)",
  readable: "partly",
  fields: [
    { label: "Name", status: "found", what_we_read: "Ramesh Naik" },
    { label: "Survey number", status: "could not read", what_we_read: null },
    { label: "Area", status: "found", what_we_read: "1200 sqm" },
  ],
  issues: ["Could not read clearly: Survey number."],
  next_steps: ["Bring a clearer copy or the original Ownership record (Form I & XIV) so every detail can be read."],
  used_fallback: true,
  disclaimer: "A quick check, not an application. An officer reviews every document.",
  language: "en",
  language_note: "Document pre-check feedback is in English.",
  nothing_saved_note: "Nothing is saved: your file and its text are checked in memory and never stored.",
};

function precheckApi({ options = () => ({ json: PRECHECK_OPTIONS }), run = () => ({ json: PRECHECK_REPLY }) } = {}) {
  return (url, method) => {
    const path = new URL(url).pathname;
    if (path.endsWith("/public/self-check")) return { json: SELF_CHECK };
    if (path.endsWith("/public/precheck")) return method === "POST" ? run() : options();
    return { json: [] };
  };
}

test("document pre-check at 390px: no sideways scroll, 24 px targets, English note, nothing-saved disclosure, and no application option", async () => {
  const { page, close } = await open("#/citizen/check", precheckApi());
  await page.locator("section.precheck select").first().waitFor();
  const m = await page.evaluate(() => {
    const box = (el) => el.getBoundingClientRect();
    const card = document.querySelector("section.precheck");
    const small = [...card.querySelectorAll("button, select, input")]
      .filter((el) => { const b = box(el); return b.width > 0 && (b.width < 24 || b.height < 24); }).length;
    const docOptions = [...card.querySelectorAll("select")[1].options].map((o) => o.value);
    return { small, scroll: document.documentElement.scrollWidth, vw: document.documentElement.clientWidth,
      text: card.innerText, docOptions };
  });
  assert.equal(m.scroll, m.vw, "page scrolls sideways");
  assert.equal(m.small, 0, "control under 24x24 px");
  assert.ok(!m.docOptions.includes("application"), "application must not be offered in pre-check");
  assert.match(m.text, /Document pre-check feedback is in English\./);
  assert.match(m.text, /Nothing is saved/);
  assert.match(m.text, /A quick check, not an application\. An officer reviews every document\./);
  await close();
});

test("document pre-check announces results via aria-live and shows what we read for name and area", async () => {
  const { page, close } = await open("#/citizen/check", precheckApi());
  await page.locator("section.precheck input[type=file]").setInputFiles({
    name: "ownership.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Name: Ramesh Naik\nArea: 1200 sqm\n"),
  });
  await page.getByRole("button", { name: "Check document" }).click();
  const live = page.locator("section.precheck [role=status][aria-live=polite]");
  await live.getByText("Readable: Partly").waitFor();
  const content = await live.innerText();
  assert.match(content, /Name: found — What we read: Ramesh Naik/);
  assert.match(content, /Area: found — What we read: 1200 sqm/);
  assert.match(content, /Survey number: could not read/);
  assert.match(content, /Checked with OCR fallback only\./);
  assert.match(content, /Issues found/);
  assert.match(content, /Next steps/);
  await close();
});

test("document pre-check errors offer Retry for options and for checking a document", async () => {
  let failOptions = true, failRun = true;
  const { page, close } = await open("#/citizen/check", precheckApi({
    options: () => (failOptions ? { status: 500, json: {} } : { json: PRECHECK_OPTIONS }),
    run: () => (failRun ? { status: 500, json: {} } : { json: PRECHECK_REPLY }),
  }));
  await page.locator("section.precheck [role=alert]").getByText("Could not load the document pre-check options.").waitFor();
  failOptions = false;
  await page.locator("section.precheck").getByRole("button", { name: "Retry" }).click();
  await page.locator("section.precheck select").first().waitFor();
  await page.locator("section.precheck input[type=file]").setInputFiles({
    name: "ownership.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Name: Ramesh Naik\n"),
  });
  await page.getByRole("button", { name: "Check document" }).click();
  await page.locator("section.precheck [role=alert]").getByText("Could not check the document just now.").waitFor();
  failRun = false;
  await page.locator("section.precheck").getByRole("button", { name: "Retry" }).click();
  await page.locator("section.precheck [role=status]").getByText("Readable: Partly").waitFor();
  await close();
});

test("pre-check status pill wraps inside the card at 390px and queue Case column stays sticky while scrolling", async () => {
  const yesReply = { ...PRECHECK_REPLY, readable: "yes", issues: [] };
  const { page, close } = await open("#/citizen/check", precheckApi({ run: () => ({ json: yesReply }) }), { width: 390 });
  await page.locator("section.precheck input[type=file]").setInputFiles({
    name: "ownership.txt", mimeType: "text/plain", buffer: Buffer.from("Name: Ramesh Naik\n"),
  });
  await page.getByRole("button", { name: "Check document" }).click();
  await page.locator("section.precheck .line.status", { hasText: "Readable: Yes" }).waitFor();
  const pillBounds = await page.evaluate(() => {
    const card = document.querySelector("section.precheck").getBoundingClientRect();
    const pill = document.querySelector("section.precheck .line.status").getBoundingClientRect();
    return { cardR: card.right, pillR: pill.right, pillL: pill.left, cardL: card.left };
  });
  assert.ok(pillBounds.pillR <= pillBounds.cardR - 8, `pill touches or clips card edge: ${JSON.stringify(pillBounds)}`);
  await close();

  const { page: qPage, close: qClose } = await open(
    "#/officer",
    (url) => ({ json: url.includes("/cases?") ? [...Array(4).keys()].map(WIDE_ROW) : [] }),
    { login: OFFICER_LOGIN, width: 390 },
  );
  await qPage.waitForSelector(".table-scroll table");
  const qBounds = await qPage.evaluate(() => {
    const box = document.querySelector(".table-scroll");
    const cell = box.querySelector("tbody tr td:nth-child(2)");
    box.scrollLeft = box.scrollWidth;
    const bRect = box.getBoundingClientRect();
    const cRect = cell.getBoundingClientRect();
    const style = getComputedStyle(cell);
    return { scrollLeft: box.scrollLeft, boxL: bRect.left, cellL: cRect.left, cellR: cRect.right,
      pos: style.position, bg: style.backgroundColor };
  });
  assert.ok(qBounds.scrollLeft > 0, "table did not scroll");
  assert.equal(qBounds.pos, "sticky");
  assert.notEqual(qBounds.bg, "rgba(0, 0, 0, 0)");
  assert.ok(Math.abs(qBounds.cellL - qBounds.boxL) <= 1 && qBounds.cellR > qBounds.boxL + 20,
    `sticky case id not visible after scrolling: ${JSON.stringify(qBounds)}`);
  await qClose();

  // The sticky column belongs to the queue only: the audit page's Time column scrolls with the table.
  const { page: aPage, close: aClose } = await open(
    "#/officer/cases/LA-01/audit",
    (url) => ({ json: url.includes("/audit") ? [...Array(4).keys()].map(AUDIT_ROW) : [] }),
    { login: OFFICER_LOGIN, width: 390 },
  );
  await aPage.waitForSelector(".table-scroll table tbody tr");
  const aPos = await aPage.evaluate(() => {
    const box = document.querySelector(".table-scroll");
    return ["thead tr th:nth-child(2)", "tbody tr td:nth-child(2)"]
      .map((sel) => getComputedStyle(box.querySelector(sel)).position);
  });
  assert.deepEqual(aPos, ["static", "static"], `audit Time column is sticky: ${JSON.stringify(aPos)}`);
  await aClose();
});



// --- audit log integrity button ------------------------------------------------------------------------------

for (const [name, verdict, expected] of [
  ["intact", { ok: true, rows: 12, first_broken_id: null }, /Log intact: all 12 rows chain correctly\./],
  ["broken", { ok: false, rows: 11, first_broken_id: 5 }, /Log altered: the chain breaks at row #5/],
]) {
  test(`audit page: "Verify log integrity" shows the ${name} result as a status`, async () => {
    const { page, calls, close } = await open("#/officer/cases/LA-01/audit", (url) => (
      url.includes("/admin/audit/verify") ? { json: verdict }
        : { json: url.includes("/audit") ? [...Array(3).keys()].map(AUDIT_ROW) : [] }), { login: OFFICER_LOGIN });
    await page.waitForSelector(".table-scroll table tbody tr");
    assert.equal(calls.filter((c) => c.includes("/admin/audit/verify")).length, 0, "verified before the click");
    await page.getByRole("button", { name: "Verify log integrity" }).click();
    const status = page.locator("[role=status].integrity");
    await status.waitFor();
    assert.match(await status.innerText(), expected);
    assert.deepEqual(calls.filter((c) => c.includes("/admin/audit/verify")), ["GET /api/admin/audit/verify"]);
    await close();
  });
}

// --- UI polish, 2026-11-19 ----------------------------------------------------------------------------------------

test("case page: a placeholder clause never shows, in the rule table or in the stored explanation", async () => {
  const detail = { ...CASE, rule_results: [
    { rule_id: "valid_ownership", status: "pass", reason: "ok", clause: "<clause ref>", rules_version: "0.1.0" },
    { rule_id: "residence", status: "pass", reason: "ok", clause: "<DSSS clause: 15-year Goa residence>", rules_version: "0.1.0" }],
    explanation: { text: "- valid_ownership: pass [<clause ref>] ok", warnings: [], used_fallback: true, at: "2026-11-15T06:00:00Z" } };
  const { page, close } = await open("#/officer/cases/LA-01", (url) => ({ json: url.endsWith("/cases/LA-01") ? detail : [] }),
    { login: OFFICER_LOGIN, width: 1280 });
  await page.locator(".explanation").waitFor();
  const body = await page.locator("main").innerText();
  await close();
  assert.doesNotMatch(body, /clause ref|DSSS clause/i);
  assert.match(body, /Valid ownership: pass ok|valid ownership: pass ok/i);
});

for (const width of [1280, 390]) {
  test(`case summary strip at ${width}px: status, stored total, flags by severity and the clock, no sideways scroll`, async () => {
    const detail = { ...CASE, flags: [{ kind: "name_match", severity: "high", detail: "x" },
      { kind: "duplicate_survey_claim", severity: "high", detail: "y" }, { kind: "low_confidence", severity: "medium", detail: "z" }] };
    const queueRow = { case_id: "LA-01", scheme: "land_acquisition", status: "in_officer_review", days_open: 70, sla_days: 60, overdue: true };
    const { page, calls, close } = await open("#/officer/cases/LA-01", (url) => ({
      json: url.endsWith("/cases/LA-01") ? detail : url.includes("/cases?scheme=land_acquisition") ? [queueRow] : [] }),
      { login: OFFICER_LOGIN, width });
    await page.locator(".summary-strip .clock").waitFor();
    const info = await page.evaluate(() => ({ text: document.querySelector(".summary-strip").innerText,
      vw: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth,
      aboveFlags: document.querySelector(".summary-strip").compareDocumentPosition(document.querySelector("ul.flags")) === 4 }));
    await close();
    assert.match(info.text, /Awaiting officer decision/);
    assert.match(info.text, /₹75,00,000\.00/);
    assert.match(info.text, /2 high · 1 medium/);
    assert.match(info.text, /Overdue by 10 days/);
    assert.ok(info.aboveFlags, "summary strip should come before the flags card");
    assert.equal(info.scroll, info.vw, `case page scrolls sideways at ${width}px`);
    assert.ok(calls.some((c) => c.startsWith("GET /api/cases")), "clock read from the queue endpoint");
  });
}

test("case page: every rupee amount reads in Indian grouping, the stored explanation included", async () => {
  const detail = { ...CASE, compensation: { items: [{ component: "land_value", amount: 1800000, formula_note: "x" },
    { component: "solatium", amount: 2016000, formula_note: "y" }], total: 3816000 },
    explanation: { text: "Compensation total: Rs 3,816,000.00\n- land_value: Rs 1,800,000.00", warnings: [], used_fallback: true,
      at: "2026-11-15T06:00:00Z" } };
  const { page, close } = await open("#/officer/cases/LA-01", (url) => ({ json: url.endsWith("/cases/LA-01") ? detail : [] }),
    { login: OFFICER_LOGIN, width: 1280 });
  await page.locator(".explanation").waitFor();
  const body = await page.locator("main").innerText();
  await close();
  assert.match(body, /₹38,16,000\.00/);
  assert.match(body, /₹18,00,000\.00/);
  assert.match(body, /₹20,16,000\.00/);
  assert.doesNotMatch(body, /Rs\s?\d|\d{1,3},\d{3},\d{3}/, "an amount still in Western grouping");
});

// Analytics with the real scheme titles, so labels are as long as they are in the demo.
const SCHEMES = [
  { scheme: "land_acquisition", labels: { title: "Land acquisition compensation" }, terms: {} },
  { scheme: "disaster_relief", labels: { title: "Disaster relief: housing damage" }, terms: {} },
  { scheme: "social_welfare", labels: { title: "Social welfare: pension" }, terms: {} },
];
const ANALYTICS_LONG = { ...ANALYTICS, by_status: { ...ANALYTICS.by_status, needs_info: 3, withdrawn: 1 },
  per_scheme: { ...ANALYTICS.per_scheme, social_welfare: 6 } };

async function openAnalytics(width, payload = ANALYTICS_LONG) {
  return open("#/officer/analytics", (url) => ({ json: url.includes("/analytics") ? payload : url.includes("/schemes") ? SCHEMES : [] }),
    { login: { ...OFFICER_LOGIN, role: "admin", user: "demo-admin" }, width });
}

for (const width of [1280, 390]) {
  test(`analytics bar labels at ${width}px wrap only at spaces, never inside a word`, async () => {
    const { page, close } = await openAnalytics(width);
    await page.locator(".bars .bar-label").first().waitFor();
    const broken = await page.evaluate(() => {
      const out = [];
      for (const cell of document.querySelectorAll(".bars .bar-label")) {
        const words = cell.textContent.split(/(\s+)/);
        cell.textContent = "";
        for (const w of words) {
          if (/^\s+$/.test(w) || w === "") { cell.append(w); continue; }
          const span = document.createElement("span");
          span.textContent = w;
          cell.append(span);
          if (span.getClientRects().length > 1) out.push(w);
        }
      }
      return out;
    });
    const cardMin = await page.evaluate(() => Math.min(...[...document.querySelectorAll(".grid > section.card")]
      .map((c) => c.getBoundingClientRect().width)));
    await close();
    assert.deepEqual(broken, [], `words split across lines at ${width}px`);
    assert.ok(cardMin >= 300 || width === 390, `a chart card is narrower than 300px: ${cardMin}`);
  });
}

for (const width of [1280, 390]) {
  test(`analytics scheme-stage table at ${width}px: ${width === 1280 ? "every column, Withdrawn included, fits without scrolling" : "scrolls inside its wrapper"}`, async () => {
    const { page, close } = await openAnalytics(width);
    await page.locator(".stage-table").waitFor();
    const m = await page.evaluate(() => {
      const wrap = document.querySelector(".stage-table").closest(".table-scroll");
      const last = [...document.querySelectorAll(".stage-table thead th")].pop();
      const w = wrap.getBoundingClientRect(), l = last.getBoundingClientRect();
      return { inner: wrap.scrollWidth, outer: wrap.clientWidth, lastText: last.innerText.trim(), lastRight: l.right, wrapRight: w.right,
        cols: document.querySelectorAll(".stage-table thead th").length,
        vw: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth };
    });
    await close();
    assert.equal(m.cols, 10);
    assert.match(m.lastText, /withdrawn/i);
    assert.equal(m.scroll, m.vw, "page scrolls sideways");
    if (width === 1280) {
      assert.ok(m.inner <= m.outer, `table scrolls at 1280px: ${JSON.stringify(m)}`);
      assert.ok(m.lastRight <= m.wrapRight + 1, `Withdrawn column cut off: ${JSON.stringify(m)}`);
    } else {
      assert.ok(m.inner > m.outer, `expected a scroll box at 390px: ${JSON.stringify(m)}`);
    }
  });
}

for (const width of [1280, 390]) {
  test(`analytics flags at ${width}px: three small tables (severity, scheme, flag type) under one heading`, async () => {
    const { page, close } = await openAnalytics(width);
    await page.locator(".flag-tables").waitFor();
    const m = await page.evaluate(() => {
      const card = [...document.querySelectorAll("section.card")].find((s) => s.querySelector("h2")?.textContent.trim() === "Verification flags");
      const tables = [...card.querySelectorAll(".flag-tables table")].map((t) => ({
        caption: t.querySelector("caption")?.innerText.trim(), rows: [...t.querySelectorAll("tbody tr")].map((r) => r.innerText.replace(/\s+/g, " ").trim()) }));
      return { h2s: card.querySelectorAll("h2").length, tables, vw: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth };
    });
    await close();
    assert.equal(m.h2s, 1);
    assert.deepEqual(m.tables.map((t) => t.caption), ["By severity", "By scheme", "By flag type"]);
    assert.deepEqual(m.tables[0].rows, ["High 5", "Medium 2"]);
    assert.deepEqual(m.tables[1].rows, ["Land acquisition compensation 5", "Disaster relief: housing damage 2"]);
    assert.equal(m.tables[2].rows.length, 3);
    assert.ok(m.tables.every((t) => t.rows.every((r) => !/Severity|Scheme|Flag type/.test(r.split(" ")[0]))), "group column still present");
    assert.equal(m.scroll, m.vw, "page scrolls sideways");
  });
}

test("analytics overdue tile: short text, the full explanation in a 'How this is counted' note", async () => {
  const { page, close } = await openAnalytics(390);
  await page.locator(".overdue-tile details").waitFor();
  const m = await page.evaluate(() => {
    const tile = document.querySelector(".overdue-tile");
    const details = tile.querySelector("details");
    const summary = details.querySelector("summary");
    const visible = [...tile.querySelectorAll(":scope > p")].map((p) => p.innerText.trim()).join(" ");
    const box = summary.getBoundingClientRect();
    return { visible, summary: summary.innerText.trim(), open: details.open, note: details.textContent, h: box.height };
  });
  await close();
  assert.equal(m.summary, "How this is counted");
  assert.equal(m.open, false);
  assert.ok(m.visible.length <= 60, `tile text too long (${m.visible.length}): ${m.visible}`);
  assert.match(m.note, /nothing changes automatically/i);
  assert.match(m.note, /Source:/);
  assert.ok(m.h >= 24, `summary touch target ${m.h}px`);
});

for (const width of [1280, 390]) {
  test(`landing at ${width}px: a plain one-line description under the title, no sideways scroll`, async () => {
    const { page, close } = await open("#/", () => ({ json: [] }), { width });
    await page.locator(".big-brand").waitFor();
    const m = await page.evaluate(() => ({ next: document.querySelector(".big-brand").nextElementSibling?.className,
      tagline: document.querySelector(".tagline")?.innerText.trim() ?? "",
      vw: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
    await close();
    assert.equal(m.next, "tagline");
    assert.match(m.tagline, /checks .* rules/i);
    assert.match(m.tagline, /officer/i);
    assert.doesNotMatch(m.tagline, /_|LLM|agent/i, "plain words only");
    assert.equal(m.scroll, m.vw);
  });
}

test("landing: a small 'Demo with synthetic data' note", async () => {
  const { page, close } = await open("#/", () => ({ json: [] }), { width: 390 });
  await page.locator(".big-brand").waitFor();
  const note = await page.locator(".demo-note").innerText();
  await close();
  assert.match(note, /^Demo with synthetic data/);
});

test("landing: the staff card lists what each role really gets (web/src/lib/nav.js)", async () => {
  const { page, close } = await open("#/", () => ({ json: [] }), { width: 1280 });
  await page.locator(".entry-staff").waitFor();
  const card = await page.locator(".entry-staff").innerText();
  await close();
  assert.match(card, /Officers: case queue, intake, analytics and the rule simulator\./);
  assert.match(card, /Clerks: case queue and intake\./);
  assert.match(card, /Admins: analytics and the rule simulator\./);
});

test("the queue opens on all cases, every filter cleared; the filters still narrow it", async () => {
  const urls = [];
  const { page, close } = await open("#/officer", (url) => { urls.push(url); return { json: [] }; }, { login: OFFICER_LOGIN, width: 1280 });
  await page.getByText("No cases match these filters.").waitFor();
  const list = () => urls.map((u) => new URL(u)).filter((u) => u.pathname.endsWith("/cases") && u.searchParams.get("status") !== "needs_info");
  const first = list()[0];
  const selects = await page.locator(".filters select").evaluateAll((els) => els.map((e) => e.selectedOptions[0].textContent));
  assert.equal(first.searchParams.get("status"), null);
  assert.equal(first.searchParams.get("scheme"), null);
  assert.deepEqual(selects, ["All statuses", "All schemes"]);
  const filtered = page.waitForRequest((r) => new URL(r.url()).searchParams.get("status") === "approved");
  await page.getByLabel("Status").selectOption("approved");
  await filtered;                                                   // the status filter still applies
  await close();
});

// --- UI polish round (ui-polish branch) ------------------------------------------------------------------------------

for (const width of [1280, 390]) {
  test(`analytics at ${width}px: headline tiles come first, then the stage table, then the charts; amounts whole`, async () => {
    const { page, close } = await openAnalytics(width);
    await page.locator(".tiles .tile").first().waitFor();
    const m = await page.evaluate(() => {
      const top = (sel) => document.querySelector(sel).getBoundingClientRect().top;
      const money = [...document.querySelectorAll(".tile .money")].map((e) => ({ text: e.innerText, fits: e.scrollWidth <= e.clientWidth + 1 }));
      return { tiles: top(".tiles"), stage: top(".stage-table"), bars: top(".bars"), money,
        vw: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth };
    });
    await close();
    assert.ok(m.tiles < m.stage && m.stage < m.bars, `order: ${JSON.stringify(m)}`);
    assert.deepEqual(m.money.map((x) => x.text), ["₹42,50,000.00", "₹1,25,00,000.00"]);
    assert.ok(m.money.every((x) => x.fits), `an amount is clipped: ${JSON.stringify(m.money)}`);
    assert.equal(m.scroll, m.vw);
  });
}
