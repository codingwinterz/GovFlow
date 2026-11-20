// Usability measurement and screenshots against the real app (not part of test:all).
// Needs: a fresh `python -m scripts.seed_demo --reset` and the API on 127.0.0.1:8000 (start it with GEMINI_API_KEY=
// set to empty so the document pre-check uses its offline fallback and every run is the same). Starts its own Vite.
//   node e2e/usability.mjs --label before --shots ../docs/screenshots/simplify/before --out ../docs/usability-before.json
// Counting rules (written into docs/USABILITY_BASELINE.md): every click, tick or focus click on a field is 1; a native
// select is 2 (open, choose); a file chooser is 1; typing is not counted. Scroll is measured at 1280 x 800 per page as
// max(0, bottom of the deepest thing the user must see or press - viewport height), with the page at the top, summed
// over the pages of the task. Sign-in is not counted: officer tasks start signed in on the queue.
// The citizen tracking code is computed in memory (app.citizen.citizen_code) and never printed or saved.
import { createServer } from "vite";
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : fallback; };
const LABEL = arg("label", "run");
const SHOTS = arg("shots", null);
const OUT = arg("out", null);
const ONLY = arg("only", "all");            // all | tasks | shots
const ROOT = resolve(new URL("../..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const WEB = resolve(ROOT, "web");
const WIDE = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };
const EN = JSON.parse(readFileSync(resolve(WEB, "src/i18n/en.json"), "utf8"));

function citizenCode(ref) {
  const py = resolve(ROOT, ".venv/Scripts/python.exe");
  return execFileSync(py, ["-c", "import sys; from pathlib import Path; from app.citizen import citizen_code; "
    + "from app.env_file import env_value; sys.stdout.write(citizen_code(sys.argv[1], env_value('GOVFLOW_CITIZEN_SECRET', Path('.env'))))", ref],
  { cwd: ROOT, encoding: "utf8" }).trim();
}

const server = await createServer({ root: WEB, server: { port: 0, host: "127.0.0.1" }, logLevel: "silent" });
await server.listen();
const base = server.resolvedUrls.local[0];
const browser = await chromium.launch({ channel: "chrome" });
const login = await (await fetch(new URL("/api/auth/demo-login", base), { method: "POST",
  headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: "officer", user: "O-1" }) })).json();
if (!login.token) throw new Error("demo sign-in failed: is the API running on 8000?");

async function context(viewport, signedIn) {
  const ctx = await browser.newContext({ viewport });
  if (signedIn) await ctx.addInitScript((l) => localStorage.setItem("govflow-demo-login", JSON.stringify(l)), login);
  return ctx;
}
const go = async (page, hash) => { await page.goto(new URL(hash, base).href); await page.waitForSelector("main.content"); await settle(page); };
async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => !document.querySelector("main [role=status]")?.textContent?.includes("Loading…"));
}

// --- the five tasks ----------------------------------------------------------------------------------------------

class Task {
  constructor(page, name) { this.page = page; this.name = name; this.clicks = 0; this.pages = []; this.steps = []; this.newPage("start"); }
  newPage(label) { this.pages.push({ label, scroll: 0, height: 0 }); }
  async height() { this.pages.at(-1).height = await this.page.evaluate(() => document.documentElement.scrollHeight); }
  async need(locator, what) {                                  // the user must see or reach this on the current page
    const el = locator.first();
    await el.waitFor({ state: "visible" });
    await this.page.evaluate(() => window.scrollTo(0, 0));
    const bottom = await el.evaluate((n) => n.getBoundingClientRect().bottom);
    const px = Math.max(0, Math.round(bottom - WIDE.height));
    const p = this.pages.at(-1);
    p.scroll = Math.max(p.scroll, px);
    this.steps.push(`see ${what} (${px} px below the fold)`);
  }
  async click(locator, what, { navigates = false } = {}) {
    await this.need(locator, what);
    await locator.first().click();
    this.clicks += 1;
    this.steps.push(`click ${what}`);
    if (navigates) { await settle(this.page); this.newPage(what); await this.height(); }
  }
  async select(locator, value, what) { await this.need(locator, what); await locator.first().selectOption(value); this.clicks += 2; this.steps.push(`choose ${what}`); }
  async upload(locator, file, what) { await this.need(locator, what); await locator.first().setInputFiles(file); this.clicks += 1; this.steps.push(`choose file ${what}`); }
  async type(locator, text, what) { await this.click(locator, `${what} field`); await locator.first().fill(text); this.steps.push(`type ${what}`); }
  result() {
    return { task: this.name, clicks: this.clicks, scroll_px: this.pages.reduce((s, p) => s + p.scroll, 0),
      pages: this.pages.map((p) => ({ ...p })), steps: this.steps };
  }
}

async function task1(page) {           // flag reason and total of a flagged case
  const t = new Task(page, "Officer finds why LA-18 is flagged and its total");
  await go(page, "#/officer"); await t.height();
  await t.click(page.getByRole("link", { name: "LA-18", exact: true }), "LA-18 in the queue", { navigates: true });
  await t.need(page.locator(".flag-item"), "the first flag's reason");
  await t.need(page.locator(".summary-strip dd.num"), "the total");
  return t.result();
}

async function task2(page) {           // approve a clean case
  const t = new Task(page, "Officer approves clean case LA-16");
  await go(page, "#/officer"); await t.height();
  await t.click(page.getByRole("link", { name: "LA-16", exact: true }), "LA-16 in the queue", { navigates: true });
  await t.click(page.getByRole("radio", { name: "Approve" }), "Approve");
  const boxes = page.locator("fieldset.confirm input[type=checkbox]");
  const n = await boxes.count();
  for (let i = 0; i < n; i++) await t.click(boxes.nth(i), `confirm value ${i + 1} of ${n}`);
  await t.click(page.getByRole("button", { name: "Record decision" }), "Record decision");
  await page.waitForFunction(() => document.querySelector(".summary-strip")?.className.includes("strip-approved"));
  t.steps.push("case shows Approved");
  return t.result();
}

async function task3(page) {           // overdue count
  const t = new Task(page, "Manager checks how many cases are overdue");
  await go(page, "#/officer"); await t.height();
  await t.click(page.getByRole("link", { name: "Analytics", exact: true }), "Analytics in the menu", { navigates: true });
  await t.need(page.locator(".overdue-tile .big"), "the overdue number");
  return t.result();
}

function findImage(scheme, docType) {
  for (let n = 1; n <= 21; n++) {
    const p = resolve(ROOT, `data/synthetic/${scheme}/case_${String(n).padStart(2, "0")}/images/${docType}_clean.png`);
    try { readFileSync(p); return p; } catch { /* next */ }
  }
  throw new Error(`no synthetic image for ${scheme}/${docType}`);
}

// After the simplification the self-check page shows one part at a time: open the document check (a counted click).
// Before it, the document check was further down the same page, so there is nothing to click.
async function openDocumentCheck(page, t) {
  await page.locator("section.precheck").waitFor({ state: "attached" });   // the self-check page has rendered
  const sw = page.getByRole("button", { name: EN["self.tab_document"] ?? "Check a document" });
  if (await sw.count()) {
    if (t) await t.click(sw, "Check a document"); else await sw.click();
  }
}

async function task4(page) {           // citizen pre-check of one document
  const t = new Task(page, "Citizen checks a document before applying");
  await go(page, "#/"); await t.height();
  await t.click(page.getByRole("link", { name: /Citizen services/ }), "Citizen services", { navigates: true });
  await t.click(page.locator(`main a[href="#/citizen/check"]`), "Check before you apply", { navigates: true });
  await openDocumentCheck(page, t);
  const docSelect = page.getByLabel("Document type");
  await docSelect.waitFor();
  const docType = await docSelect.inputValue();
  const scheme = await page.getByLabel("Scheme for document check").inputValue();
  await t.upload(page.locator("input[type=file]"), findImage(scheme, docType), `${docType} image`);
  await t.click(page.getByRole("button", { name: "Check document" }), "Check document");
  await page.locator(".precheck-result, .precheck [role=alert]").first().waitFor();
  await t.need(page.locator(".precheck-result .line.status, .precheck [role=alert]"), "the result");
  return { ...t.result(), document: `${scheme} / ${docType}` };
}

async function task5(page, code) {     // citizen tracking
  const t = new Task(page, "Citizen tracks application LA-01");
  await go(page, "#/"); await t.height();
  await t.click(page.getByRole("link", { name: /Citizen services/ }), "Citizen services", { navigates: true });
  await t.click(page.locator(`main a[href="#/citizen/track"]`), "Track", { navigates: true });
  await t.type(page.getByLabel(EN["track.case_ref"]), "LA-01", "reference");
  await t.type(page.getByLabel(EN["track.code"]), code, "verification code");
  await t.click(page.getByRole("button", { name: EN["track.submit"] }), EN["track.submit"]);
  await t.need(page.locator(".citizen-view .line.status"), "the status");
  await page.getByLabel(EN["track.code"]).fill("");               // never leave the code on screen
  return t.result();
}

// --- screenshots ---------------------------------------------------------------------------------------------------

const PAGES = [
  ["01-landing", "#/", false], ["02-citizen-home", "#/citizen", false], ["03-self-check", "#/citizen/check", false],
  ["06-queue", "#/officer", true], ["07-case-LA-18", "#/officer/cases/LA-18", true],
  ["08-case-LA-16", "#/officer/cases/LA-16", true], ["09-case-RM-02", "#/officer/cases/RM-02", true],
  ["10-intake", "#/officer/intake", true], ["11-analytics", "#/officer/analytics", true],
  ["12-audit-LA-18", "#/officer/cases/LA-18/audit", true], ["13-simulator", "#/officer/simulator", true],
  ["14-award-LA-01", "#/officer/cases/LA-01/award", true], ["15-sign-in", "#/officer", false],
];

async function screenshots(code) {
  mkdirSync(SHOTS, { recursive: true });
  const heights = {};
  for (const [vp, suffix] of [[WIDE, "1280"], [PHONE, "390"]]) {
    for (const [name, hash, signedIn] of PAGES) {
      const ctx = await context(vp, signedIn);
      const page = await ctx.newPage();
      await go(page, hash);
      await page.screenshot({ path: resolve(SHOTS, `${name}-${suffix}.png`), fullPage: true });
      heights[`${name}-${suffix}`] = await page.evaluate(() => document.documentElement.scrollHeight);
      await ctx.close();
    }
    {   // pre-check result
      const ctx = await context(vp, false);
      const page = await ctx.newPage();
      await go(page, "#/citizen/check");
      await openDocumentCheck(page, null);
      const scheme = await page.getByLabel("Scheme for document check").inputValue();
      const docType = await page.getByLabel("Document type").inputValue();
      await page.locator("input[type=file]").setInputFiles(findImage(scheme, docType));
      await page.getByRole("button", { name: "Check document" }).click();
      await page.locator(".precheck-result, .precheck [role=alert]").first().waitFor();
      await page.screenshot({ path: resolve(SHOTS, `04-precheck-result-${suffix}.png`), fullPage: true });
      await ctx.close();
    }
    {   // tracking result (the code field is cleared before the picture)
      const ctx = await context(vp, false);
      const page = await ctx.newPage();
      await go(page, "#/citizen/track");
      await page.getByLabel(EN["track.case_ref"]).fill("LA-01");
      await page.getByLabel(EN["track.code"]).fill(code);
      await page.getByRole("button", { name: EN["track.submit"] }).click();
      await page.locator(".citizen-view .line.status").waitFor();
      await page.getByLabel(EN["track.code"]).fill("");
      await page.screenshot({ path: resolve(SHOTS, `05-track-result-${suffix}.png`), fullPage: true });
      await ctx.close();
    }
  }
  return heights;
}

// --- run ---------------------------------------------------------------------------------------------------------

const code = citizenCode("LA-01");
const report = { label: LABEL, viewport: WIDE, tasks: [], page_heights: {} };
try {
  if (ONLY !== "tasks" && SHOTS) report.page_heights = await screenshots(code);
  if (ONLY !== "shots") {
    const pick = (arg("pick", "1,2,3,4,5")).split(",").map(Number);       // e.g. --pick 4 to rerun one task
    const all = [task1, task2, task3, task4, (p) => task5(p, code)];
    for (const fn of all.filter((_, i) => pick.includes(i + 1))) {
      const ctx = await context(WIDE, true);
      const page = await ctx.newPage();
      report.tasks.push(await fn(page));
      await ctx.close();
    }
  }
} finally {
  await browser.close();
  await server.close();
}
if (OUT) writeFileSync(OUT, JSON.stringify(report, null, 2) + "\n");
for (const t of report.tasks) console.log(`${t.task}: ${t.clicks} clicks, ${t.scroll_px} px`);
