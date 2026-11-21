// Scripted screen recording of the real GovFlow app (the whole pipeline), with captions, cards and narration.
//   node scripts/make_demo_video.mjs
// Output (gitignored): docs/video/raw.mp4, docs/video/govflow_demo_captioned.mp4, frames, timeline.json.
// Capture: Playwright recordVideo at 30 fps (needs `npx playwright-core install ffmpeg` once, in web/), re-encoded to
// constant 30 fps H.264. The cursor glides in 20+ eased steps, every scroll is eased over 600 ms, and waits over 3 s are
// a 4x time-lapse of the real frames. Smoothness is measured at the end with scripts/measure_video.mjs (mpdecimate).
// Committed: this script and docs/video/narration.txt (written by this script with the final timestamps).
//
// Safety: everything runs against a throwaway database in docs/video/run/ (seeded with --reset there, then copied),
// a throwaway upload folder, and fresh random citizen and sign-in secrets, so the tracking code typed on screen works
// only for this run's API. The real govflow.db, uploads/ and .env are never written. No app code is changed: the API is
// started through create_app() with those settings. The only outside calls are the app's own Gemini calls; the run
// stops before recording if a one-call Gemini preflight (no retries) fails.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { createHmac, randomBytes } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const WEB = join(ROOT, "web");
const OUT = join(ROOT, "docs", "video");
const RUN = join(OUT, "run");
const PY = join(ROOT, ".venv", "Scripts", "python.exe");
const API_PORT = 8765;
const require = createRequire(join(WEB, "package.json"));
const { chromium } = require("playwright-core");
const { createServer } = await import(pathToFileURL(join(WEB, "node_modules", "vite", "dist", "node", "index.js")).href);

const CAP_WORDS = 12;            // every caption at most 12 words
const FAST_OVER = 3.0;           // a wait longer than this (seconds) is time-lapsed ...
const FAST_SPEED = 4;            // ... at 4x (every 4th real frame), labelled "Sped up"
const CAP_TOTAL = 192.0;         // hard cap: 3 min 12 s
const PLAN_CAP = CAP_TOTAL - 0.6; // planning margin: every piece rounds to whole frames at 30 fps
const TITLE_S = 4.0, CLOSING_S = 10.0;
const APP_H = 972;                // the app's height in the 1080-line frame; the band below holds the captions
const BAND = "0x0b1b2e";
const HOLD = 0.65;                // scales every hold (show, pause, settle after an action) so the 4x time-lapses fit the cap
const SCROLL_MS = 600;            // every scroll is eased over this long; no instant jumps
const RENDER_LAG = 0.1;           // seconds from sending input to it showing in the recording (measuring only)
// Captions placed by their screen, not by when the script set them. A number n: the caption shows from the end of the
// n-th screen change after its mark (it was set before the action that brings its screen up). An object: { before }
// counts back from the mark instead, { until } ends the caption at that change after the mark, { min } is the
// threshold (screenChanges). The counts were read off the 2026-11-21 recording's frames (a sign-in page or a loading
// blank counts as a change); a missing change stops the build rather than guess.
const CAPTION_SCREEN = {
  "Tracking with a reference and code from this throwaway demo.": 2,      // the pre-check top, then the tracking form
  "Approved: the amount, and the basis of each item.": 1,                 // "Why this amount" opens
  // Set after the Hindi hold (the page goes back to English straight after): from the switch to Hindi until the switch
  // back. A language swap redraws only text on a white page, so it is found with the lower text threshold.
  "The same page in Hindi, from fixed templates.": { before: 1, until: 1, min: 0.8 },
  "Waiting for documents: the page says exactly what is needed.": 1,      // LA-05's result
  "Explanation written by the model; every figure comes from tools.": 1,  // the explanation row opens
  // From LA-06 loading until LA-18 loads again (the 8th change: two previews, the language list, a scroll in between).
  "LA-06 has an expired document: notice previewed in English, Hindi.": { after: 1, until: 8 },
  "Approval: confirm every money field and record the resolution.": 2,    // scroll down, then the approval form
  "A clerk opens a case: no decision controls. Only officers decide.": 3, // sign-in, LA-18 as clerk, then LA-12
  "Admin: headline numbers read straight from the system.": 3,            // sign-in, a loading blank, then analytics
  "More detail: every scheme by stage, and the liability table.": 1,      // the detail section opens
  "Rule simulator: change one parameter, see which cases change.": 2,     // scroll to top, then the simulator
};
// Whole-screen changes in the app area of raw.mp4: frames whose mean absolute difference from the previous frame (on a
// 96x48 grey thumbnail) is over min levels (1.5 by default), joined into one change when less than 0.25 s apart. A
// cursor glide stays under 1; a page load, an opened section or a scroll is over 1.5; a text-only redraw is about 1.
function screenChanges(gray, min = 1.5) {
  const N = 96 * 48, buf = gray, frames = buf.length / N, changes = [];
  for (let i = 1; i < frames; i++) {
    let s = 0;
    for (let j = 0; j < N; j++) s += Math.abs(buf[i * N + j] - buf[(i - 1) * N + j]);
    if (s / N <= min) continue;
    const t = i / 30, last = changes.at(-1);
    if (last && t - last.b <= 0.25) last.b = t; else changes.push({ a: t, b: t });
  }
  return changes;
}
function grayFrames() {
  const W = 96, H = 48;
  const r = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-i", join(OUT, "raw.mp4"), "-vf",
    `crop=1920:${APP_H}:0:0,scale=${W}:${H},format=gray`, "-f", "rawvideo", "-"], { maxBuffer: 1 << 30 });
  if (r.status !== 0) throw new Error(`screen changes: ${String(r.stderr).slice(-400)}`);
  return r.stdout;
}
// Target length of each recorded beat (the title and closing cards are added around them); a short beat is padded.
const TARGET = { 1: 7, 2: 28, 3: 13, 4: 32, 5: 27, 6: 36, 7: 20, 8: 14.4 };

// --- small helpers --------------------------------------------------------------------------------------------------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ease = (t) => (1 - Math.cos(Math.PI * t)) / 2;   // ease-in-out sine: gentle ends, never sub-pixel for long
const log = (...a) => console.log("[video]", ...a);
const redact = (s) => String(s).replace(/AIza[0-9A-Za-z_\-]{20,}/g, "[redacted]").replace(/\b\d{6}\b/g, "[code]");
function py(args, opts = {}) {
  const r = spawnSync(PY, args, { cwd: ROOT, encoding: "utf8", ...opts });
  if (r.status !== 0) throw new Error(`python ${args[0]} failed: ${redact(r.stderr || r.stdout).slice(-600)}`);
  return r.stdout;
}
function ff(args, cwd = OUT) {
  const r = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", ...args], { cwd, encoding: "utf8" });
  if (r.status !== 0) throw new Error(`ffmpeg failed: ${r.stderr.slice(-800)}`);
}
function probeSeconds(file) {
  const r = spawnSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file], { encoding: "utf8" });
  return Number(r.stdout.trim());
}
// Same as app.citizen.citizen_code: HMAC-SHA256(secret, REF), first 4 bytes mod 1e6, six digits. Never printed.
const citizenCode = (ref, secret) =>
  String(createHmac("sha256", secret).update(ref.trim().toUpperCase()).digest().readUInt32BE(0) % 1_000_000).padStart(6, "0");

// --- narration (one spoken line per beat; the captions are in record()) ---------------------------------------------

const NARRATION = {
  1: "GovFlow is one AI agent for government case processing. Today, files are retyped by hand, checked from memory, and citizens cannot track their application.",
  2: "A citizen can check a document before applying. Here is a synthetic ownership record, a clear scan. Each required field is either found or marked as unreadable, and nothing is saved: the file is checked in memory and thrown away. Now a blurred phone photo of the same record. It is only partly readable, and the page says in plain words what to do next.",
  3: "A citizen tracks an application with a reference and code. This approved case shows the amount and its basis. The page reads in Hindi too. A waiting case lists what is missing.",
  4: "A clerk opens a new land case and uploads its documents. They are synthetic: one ownership record image and four short printed records. The language model reads each document and returns every field with a confidence score. Waiting time is sped up on screen, and marked. The model only reads; it decides nothing. Then the agent runs the checks, the eligibility rules and the amount.",
  5: "The officer opens the new case. One plain sentence says where it stands, then the total and what needs attention. The checks are fixed rules in the scheme file, not the model, and each shows its result and version. Each field shows how sure the reading was. The amount is worked out in steps: area, value and multiplier, then solatium and the additional amount.",
  6: "On LA-18, a tenant entry on the record of rights is flagged, citing the Goa tenancy and mundkar Acts. The model writes the explanation, but every figure in it comes from the tools. On LA-06, where a document has expired, the officer previews a notice to the citizen in English and Hindi. Back on LA-18, the officer confirms each money field, records the resolution, and approves. A clerk sees no decision controls. Only an officer decides.",
  7: "An administrator sees four headline numbers, read from the system, then one chart, and more detail only when asked. The case list is for officers and clerks. The rule simulator changes one parameter on the synthetic cases and shows which would change. It never edits the rules.",
  8: "Every action goes into a hash-chained audit log, and it checks out intact. Duplicate claims and open mutations go to review, never rejection. Four schemes, one engine, each defined in a rules file.",
  9: "These results come from our own tests on synthetic data. Legal values stay placeholders until the offices confirm. A scripted walkthrough of the live prototype.",
};

// --- throwaway environment ------------------------------------------------------------------------------------------

function prepare() {
  rmSync(RUN, { recursive: true, force: true });
  for (const d of [OUT, RUN, join(RUN, "uploads"), join(RUN, "intake")]) mkdirSync(d, { recursive: true });
  const pristine = join(RUN, "pristine.db"), demo = join(RUN, "demo.db");
  // Seed a fresh demo database here (never the real govflow.db); its output lists codes, so it is discarded.
  py(["-m", "scripts.seed_demo", "--db", pristine, "--reset"], { stdio: ["ignore", "ignore", "pipe"] });
  copyFileSync(pristine, demo);
  // The new intake case's documents: case 09's ownership record image, and its other synthetic fields printed as text.
  const c = JSON.parse(readFileSync(join(ROOT, "data/synthetic/land_acquisition/case_09/case.json"), "utf8")).documents;
  const v = (doc, f) => c[doc].fields[f].value;
  const dmy = (iso) => iso.split("-").reverse().join("/");
  const docs = {
    application: `APPLICATION FOR COMPENSATION (SYNTHETIC)\nName of applicant: ${v("application", "name")}\nSurvey No.: ${v("ownership_record", "survey_number")}\n`,
    identity_proof: `GOVERNMENT IDENTITY CARD (SYNTHETIC)\nName : ${v("identity_proof", "name").toUpperCase()}\nID No: ${v("identity_proof", "id_number")}\nValid upto: ${dmy(v("identity_proof", "expiry_date"))}\n`,
    survey_sheet: `SURVEY PLAN (SYNTHETIC)\nVillage: Example\nSurvey No.: ${v("survey_sheet", "survey_number")}\nTotal area: ${v("survey_sheet", "area")} sq. m.\n`,
    mutation_record: `MUTATION ENTRY (SYNTHETIC)\nName: ${v("mutation_record", "name")}\nDate of entry: ${dmy(v("mutation_record", "issue_date"))}\n`,
  };
  for (const [k, text] of Object.entries(docs)) writeFileSync(join(RUN, "intake", `${k}.txt`), text);
  return demo;
}

function preflight() {
  const out = py(["-c", [
    "from pathlib import Path", "from app.env_file import load_env_file", "load_env_file(Path('.env'))",
    "from scripts.benchmark_processing import preflight, _gemini_call", "from app.providers.gemini import GeminiClient",
    "ok, why = preflight(_gemini_call())", "print(('OK ' if ok else 'FAIL ') + GeminiClient().model + ' ' + (why or ''))"].join("\n")]);
  return { ok: out.startsWith("OK "), detail: redact(out.trim()) };
}

function startApi(db, secrets) {
  const launcher = [
    "import os, uvicorn", "from pathlib import Path",
    "from app.main import create_app, _default_llm, _default_extraction, _default_cross_check, _default_sahayak",
    "from app.models import make_engine",
    "app = create_app(engine=make_engine('sqlite:///' + os.environ['VIDEO_DB'].replace(os.sep, '/')),",
    "    agent_llm_factory=_default_llm, extraction_factory=_default_extraction, cross_check_factory=_default_cross_check,",
    "    sahayak_llm_factory=_default_sahayak, upload_dir=Path(os.environ['VIDEO_UPLOADS']),",
    "    citizen_secret=os.environ['VIDEO_CITIZEN_SECRET'], auth_secret=os.environ['VIDEO_AUTH_SECRET'], demo_insecure=False)",
    `uvicorn.run(app, host='127.0.0.1', port=${API_PORT}, log_level='warning')`].join("\n");
  const env = { ...process.env, PYTHONPATH: ROOT, VIDEO_DB: db, VIDEO_UPLOADS: join(RUN, "uploads"),
    VIDEO_CITIZEN_SECRET: secrets.citizen, VIDEO_AUTH_SECRET: secrets.auth };
  const proc = spawn(PY, ["-c", launcher], { cwd: RUN, env, stdio: ["ignore", "ignore", "pipe"] });
  proc.stderr.on("data", (d) => { const s = String(d); if (/error|traceback/i.test(s)) log("api:", redact(s).slice(0, 300)); });
  return proc;
}

async function waitForApi() {
  for (let i = 0; i < 60; i++) {
    try { await fetch(`http://127.0.0.1:${API_PORT}/schemes`); return; } catch { await sleep(500); }
  }
  throw new Error("API did not start");
}

// --- recording ------------------------------------------------------------------------------------------------------

const CURSOR = () => {
  const make = () => {
    if (document.getElementById("demo-cursor")) return;
    const c = document.createElement("div");
    c.id = "demo-cursor";
    c.style.cssText = "position:fixed;left:-40px;top:-40px;width:26px;height:26px;z-index:2147483647;pointer-events:none;";
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M3 2 L3 19 L7.6 14.6 L10.8 21.4 L13.6 20.2 L10.4 13.5 L16.8 13.5 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    addEventListener("mousemove", (e) => { c.style.left = `${e.clientX - 3}px`; c.style.top = `${e.clientY - 2}px`; }, true);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", make); else make();
};

// Eased page scroll over SCROLL_MS, driven by requestAnimationFrame so every captured frame moves a little.
// Runs in the page as el.evaluate(SMOOTH_SCROLL, { ms, top }): with top, scroll to the top; otherwise bring the element
// into view (centred; a tall element is aligned near the top). Resolves true if it scrolled.
const SMOOTH_SCROLL = (target, { ms, top }) => new Promise((resolve) => {
  let goal = 0;
  if (!top) {
    const r = target.getBoundingClientRect();
    if (r.top >= 60 && r.bottom <= innerHeight - 60) { resolve(false); return; }   // already on screen
    goal = scrollY + (r.height > innerHeight - 160 ? r.top - 80 : r.top + r.height / 2 - innerHeight / 2);
  }
  goal = Math.max(0, Math.min(goal, document.documentElement.scrollHeight - innerHeight));
  const from = scrollY, dist = goal - from;
  if (Math.abs(dist) < 2) { resolve(false); return; }
  const e = (t) => (1 - Math.cos(Math.PI * t)) / 2;
  const t0 = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - t0) / ms);
    scrollTo(0, from + dist * e(k));
    if (k < 1) requestAnimationFrame(step); else resolve(true);
  };
  requestAnimationFrame(step);
});

class Director {
  constructor(page) {
    this.page = page; this.t0 = performance.now(); this.marks = []; this.waits = []; this.warnings = []; this.beat = 0;
    this.pos = { x: 640, y: 600 };
    this.motion = [];                                         // scripted cursor glides and scrolls, for measuring

  }
  now() { return (performance.now() - this.t0) / 1000; }       // monotonic clock
  startBeat(n) { this.beat = n; this.marks.push({ type: "beat", beat: n, t: this.now() }); log(`beat ${n} at ${this.now().toFixed(1)} s`); }
  cap(text) {
    const words = text.trim().split(/\s+/).length;
    if (words > CAP_WORDS) throw new Error(`caption over ${CAP_WORDS} words: ${text}`);
    this.marks.push({ type: "cap", beat: this.beat, t: this.now(), text });
  }
  async pause(ms = 1000) { await sleep(ms * HOLD); }
  async slow(label, fn) {                                   // a wait on the app; time-lapsed if long
    const a = this.now();
    const r = await fn();
    const b = this.now();
    if (b - a > FAST_OVER) this.waits.push({ beat: this.beat, a, b, label });
    log(`  wait ${label}: ${(b - a).toFixed(1)} s${b - a > FAST_OVER ? " (sped up)" : ""}`);
    return r;
  }
  // The cursor glides: at least 20 eased steps, paced on the monotonic clock (220-500 ms by distance).
  async moveTo(x, y) {
    const a = this.pos, dist = Math.hypot(x - a.x, y - a.y);
    if (dist < 1) return;
    const ms = Math.min(500, Math.max(220, 180 + dist * 0.3));
    const steps = Math.max(20, Math.round(ms / 15));
    const t0 = performance.now(), from = this.now();
    for (let i = 1; i <= steps; i++) {
      const k = ease(i / steps);
      await this.page.mouse.move(a.x + (x - a.x) * k, a.y + (y - a.y) * k);
      const due = t0 + (ms * i) / steps - performance.now();
      if (due > 0) await sleep(due);
    }
    this.pos = { x, y };
    this.motion.push({ kind: "cursor", a: from, b: this.now() });
  }
  async scrollTo(el) {                                       // logged as motion only when the page actually scrolled
    const from = this.now();
    const moved = await el.evaluate(SMOOTH_SCROLL, { ms: SCROLL_MS, top: false });
    if (moved) this.motion.push({ kind: "scroll", a: from, b: this.now() });
    return moved;
  }
  // Bring the element into view (eased scroll), then glide the cursor onto it. Returns the element and the point
  // (relative to the element) the cursor rests on, so a click lands exactly there and the cursor never jumps.
  // inset: how far in from the left edge to rest (a typed field uses 20 px: a date input's day segment).
  async point(locator, { cursor = true, inset = 60 } = {}) {
    const el = locator.first();
    await el.waitFor({ state: "visible", timeout: 60000 });
    if (await this.scrollTo(el)) await sleep(60);
    if (!cursor) return { el };
    const box = await el.boundingBox();
    const at = { x: Math.min(box.width / 2, inset), y: box.height / 2 };
    await this.moveTo(box.x + at.x, box.y + at.y);
    await sleep(100);
    return { el, at };
  }
  async click(locator, after = 700) { const { el, at } = await this.point(locator); await el.click({ position: at }); await sleep(after * HOLD); }
  async type(locator, text, after = 300) {
    const { el, at } = await this.point(locator, { inset: 20 });
    await el.click({ position: at });
    await el.fill("");
    await el.pressSequentially(String(text), { delay: 18 });
    await sleep(after * HOLD);
  }
  async select(locator, value, after = 500) { const { el } = await this.point(locator); await el.selectOption(value); await sleep(after * HOLD); }
  async upload(locator, file, after = 300) { const { el } = await this.point(locator); await el.setInputFiles(file); await sleep(after * HOLD); }
  async show(locator, ms = 1100) { await this.point(locator, { cursor: false }); await sleep(ms * HOLD); }
  async scrollTop(ms = 600) {
    const from = this.now();
    if (await this.page.locator("body").evaluate(SMOOTH_SCROLL, { ms: SCROLL_MS, top: true }))
      this.motion.push({ kind: "scroll", a: from, b: this.now() });
    await sleep(Math.max(0, ms - SCROLL_MS));
  }
  async hash(h, waitFor) {
    await this.page.evaluate((x) => { location.hash = x; }, h);
    if (waitFor) await this.page.locator(waitFor).first().waitFor({ timeout: 60000 });
    await sleep(700);
  }
  async clean(what) {                                        // nothing on screen looks like a failure
    const bad = await this.page.evaluate(() => [...document.querySelectorAll("main [role=alert], main .error")]
      .filter((e) => e.checkVisibility() && e.textContent.trim()).map((e) => e.textContent.trim().slice(0, 120)));
    if (bad.length) this.warnings.push({ beat: this.beat, what, bad });
  }
}

async function signIn(d, role, user) {
  const page = d.page;
  const switcher = page.getByRole("button", { name: "Switch user" });
  if (await switcher.count()) await d.click(switcher, 600);
  await page.getByRole("heading", { name: "Demo sign-in" }).waitFor();
  await d.select(page.getByLabel("Role"), role, 400);
  await d.type(page.getByLabel("User id"), user, 300);
  await d.click(page.getByRole("button", { name: "Continue" }), 900);
}

const openRow = (d, title) => d.click(d.page.locator("details.more > summary").filter({ hasText: title }), 1100);

async function record(secrets) {
  const browser = await chromium.launch({ channel: "chrome" });
  // 1280 x 648 CSS pixels at 1.5x: frames are 1920 x 972 with large, sharp text; the 108 px band below holds the
  // captions, so a caption never covers the app (the case page's decision bar sits at the bottom of the window).
  // Playwright's recordVideo at 30 fps (its own ffmpeg, `npx playwright-core install ffmpeg`), 1920 x 972: the app's
  // area of the 1080-line frame; the caption band is added when it is re-encoded.
  const videoDir = join(RUN, "video");
  const context = await browser.newContext({ viewport: { width: 1280, height: APP_H / 1.5 }, deviceScaleFactor: 1.5,
    recordVideo: { dir: videoDir, size: { width: 1920, height: APP_H }, fps: 30 } });
  await context.addInitScript(CURSOR);
  const vite = await createServer({ configFile: false, root: WEB, logLevel: "silent",
    server: { port: 0, host: "127.0.0.1", proxy: { "/api": { target: `http://127.0.0.1:${API_PORT}`, changeOrigin: true,
      rewrite: (p) => p.replace(/^\/api/, "") } } } });
  await vite.listen();
  const base = vite.resolvedUrls.local[0];
  const page = await context.newPage();
  const video = page.video();
  const d = new Director(page);
  // Sync flash: red, then blue at a known director time; the first blue frame in the video ties the two clocks.
  await page.setContent('<body style="margin:0;height:100vh;background:#ff0000"></body>');
  await sleep(700);
  const syncAt = d.now();
  let endSyncAt = null;
  await page.evaluate(() => { document.body.style.background = "#0000ff"; });
  await sleep(500);
  const img = (f) => join(ROOT, "data/synthetic/land_acquisition/case_09/images", f);
  try {
    // 1. Landing ----------------------------------------------------------------------------------------------------
    await page.goto(new URL("#/", base).href);
    await page.locator(".big-brand").waitFor();
    await page.mouse.move(d.pos.x, d.pos.y);
    d.startBeat(1);
    d.cap("Today: files retyped, checked from memory, status invisible to citizens.");
    await d.pause(4500);
    await d.show(page.locator("a.entry").first(), 1500);
    await d.clean("landing");

    // 2. Citizen pre-check --------------------------------------------------------------------------------------------
    d.startBeat(2);
    d.cap("A citizen checks a document before applying.");
    await d.click(page.locator("a.entry").first(), 700);
    await d.click(page.locator('main a[href="#/citizen/check"]'), 700);
    await d.click(page.getByRole("button", { name: "Check a document" }), 600);
    await d.select(page.getByLabel("Scheme for document check"), "land_acquisition");
    await d.select(page.getByLabel("Document type"), "ownership_record");
    await d.upload(page.locator("section.precheck input[type=file]"), img("ownership_record_clean.png"));
    await d.show(page.locator(".precheck-privacy"), 2000);
    d.cap("Nothing is saved: the file is checked in memory only.");
    await d.click(page.getByRole("button", { name: "Check document" }), 200);
    const result = page.locator(".precheck-result .line.status");
    await d.slow("pre-check clean scan", () => result.waitFor({ timeout: 90000 }));
    d.cap("Clear scan: each required field found, or marked unreadable.");
    await d.show(result, 1800);
    await d.show(page.locator(".precheck-result ul").first(), 3200);
    const cleanText = await result.innerText();
    d.cap("Blurred phone photo: partly readable, with plain next steps.");
    await d.upload(page.locator("section.precheck input[type=file]"), img("ownership_record_hard.jpg"));
    await d.click(page.getByRole("button", { name: "Check document" }), 200);
    await d.slow("pre-check phone photo", () => page.waitForFunction(() => {
      const s = document.querySelector(".precheck-result .line.status");
      return s && !document.querySelector(".precheck-live")?.textContent.includes("Checking");
    }, null, { timeout: 90000 }));
    await d.show(result, 1800);
    await d.show(page.locator(".precheck-result ul").first(), 2000);
    await d.show(page.locator(".precheck-result h4").last(), 3000);
    const hardText = await result.innerText();
    log(`  pre-check: clean "${cleanText}", hard "${hardText}"`);
    await d.clean("pre-check");

    // 3. Citizen tracking ----------------------------------------------------------------------------------------------
    d.startBeat(3);
    d.cap("Tracking with a reference and code from this throwaway demo.");
    await d.click(page.getByRole("link", { name: "Track an application" }), 600);
    await d.type(page.getByLabel("Application reference"), "LA-01", 200);
    await d.type(page.getByLabel("Verification code"), citizenCode("LA-01", secrets.citizen), 200);
    await d.click(page.getByRole("button", { name: "Check status" }), 900);
    await page.locator(".citizen-view .line.status").waitFor();
    await page.getByLabel("Verification code").fill("");
    d.cap("Approved: the amount, and the basis of each item.");
    await d.click(page.locator(".citizen-view details.why summary").first(), 1000);
    await d.select(page.locator(".lang select"), "hi", 2000);
    d.cap("The same page in Hindi, from fixed templates.");
    await d.select(page.locator(".lang select"), "en", 500);
    await d.type(page.getByLabel("Application reference"), "LA-05", 150);
    await d.type(page.getByLabel("Verification code"), citizenCode("LA-05", secrets.citizen), 150);
    await d.click(page.getByRole("button", { name: "Check status" }), 600);
    await page.getByLabel("Verification code").fill("");
    d.cap("Waiting for documents: the page says exactly what is needed.");
    await page.locator(".citizen-view .line.status").waitFor();
    // A stored deficiency notice prints as a letter; the seed has none, so LA-05 shows its missing documents as lines.
    const letter = page.locator("article.letter.notice");
    await d.show((await letter.count()) ? letter : page.locator(".citizen-view h2").last(), 1600);
    await d.clean("tracking");

    // 4. Clerk intake ------------------------------------------------------------------------------------------------
    d.startBeat(4);
    d.cap("A clerk opens a new land case with synthetic documents.");
    await d.hash("#/officer");
    await signIn(d, "clerk", "C-1");
    await d.click(page.getByRole("link", { name: "Intake", exact: true }), 600);
    await d.type(page.getByLabel("Case id"), "LA-50", 200);
    await d.select(page.getByLabel("Scheme"), "land_acquisition", 300);
    const inputs = { market_value_per_sqm: "2500", assets_total: "30000", multiplier: "1.5",
      sia_notification_date: "2025-11-15", award_date: "2026-11-15" };
    const names = await page.evaluate(async () => {
      const login = JSON.parse(localStorage.getItem("govflow-demo-login"));
      const r = await fetch("/api/schemes", { headers: { Authorization: `Bearer ${login.token}` } });
      return (await r.json()).find((s) => s.scheme === "land_acquisition").officer_inputs;
    });
    const fields = page.locator("fieldset label input");
    for (const [i, name] of names.entries()) if (inputs[name]) await d.type(fields.nth(i), inputs[name], 80);
    await d.click(page.getByRole("button", { name: "Create case" }), 700);
    d.cap("Gemini reads each document; every field keeps its confidence.");
    const uploads = [["application", join(RUN, "intake/application.txt")], ["ownership_record", img("ownership_record_clean.png")],
      ["identity_proof", join(RUN, "intake/identity_proof.txt")], ["survey_sheet", join(RUN, "intake/survey_sheet.txt")],
      ["mutation_record", join(RUN, "intake/mutation_record.txt")]];
    for (const [i, [docType, file]] of uploads.entries()) {
      await d.select(page.getByLabel("Document type"), docType, 250);
      await d.upload(page.locator("form input[type=file]"), file, 250);
      await d.click(page.getByRole("button", { name: "Upload" }), 100);
      await d.slow(`read ${docType}`, () => page.locator("main li").nth(i).waitFor({ timeout: 120000 }));
      await sleep(400);
    }
    log("  intake:", (await page.locator("main li").allInnerTexts()).join(" | "));
    d.cap("The agent runs verification, eligibility rules and the amount.");
    await d.click(page.getByRole("button", { name: "Run agent and open case" }), 100);
    await d.slow("agent run on LA-50", () => page.locator(".case-head h1", { hasText: "LA-50" }).waitFor({ timeout: 180000 }));
    await d.show(page.locator(".summary-strip"), 1200);
    await d.clean("intake");

    // 5. The new case as the officer -----------------------------------------------------------------------------------
    d.startBeat(5);
    d.cap("Officer view: plain summary, total, and what needs attention.");
    await signIn(d, "officer", "O-1");
    await d.hash("#/officer/cases/LA-50", ".case-head");
    await d.show(page.locator(".headline"), 1800);
    await d.show(page.locator(".summary-strip"), 1500);
    if (await page.locator(".attention").count()) await d.show(page.locator(".attention"), 2000);
    d.cap("Checks are fixed rules, each with its result and version.");
    await openRow(d, "Checks");
    await d.show(page.locator(".rules-table"), 2200);
    d.cap("Each field read, with its confidence and source.");
    await openRow(d, "Documents and what was read");
    await d.show(page.locator("details.more[open] table").last(), 2400);
    d.cap("Amount steps: area × value × multiplier, solatium, additional amount.");
    await openRow(d, "How the amount was worked out");
    await d.show(page.locator(".steps-table"), 3500);
    const explained = await page.locator("details.more .more-hint").first().innerText();
    log("  LA-50 explanation:", explained);
    await d.clean("LA-50 officer");

    // 6. Officer decision on LA-18 ---------------------------------------------------------------------------------
    d.startBeat(6);
    await d.hash("#/officer/cases/LA-18", ".case-head");
    d.cap("LA-18: tenant entry flagged, citing the Goa tenancy and mundkar Acts.");
    await d.show(page.locator(".attention .flag-item").first(), 2200);
    await d.click(page.getByRole("button", { name: "Run agent" }), 100);
    await d.slow("agent run on LA-18", () => page.waitForFunction(() =>
      [...document.querySelectorAll("details.more .more-hint")].some((h) => h.textContent.includes("written by the agent")), null, { timeout: 180000 }));
    const by = await page.locator("details.more .more-hint").first().innerText();
    if (!by.includes("written by the agent")) throw new Error("LA-18 explanation fell back to the deterministic summary; not recording it");
    d.cap("Explanation written by the model; every figure comes from tools.");
    await openRow(d, "Why the system recommends this");
    await d.show(page.locator(".explanation"), 2600);
    // A tenant entry is not something the citizen can fix, so LA-18's notice would be empty ("Nothing on this case is
    // for the citizen to fix"). The notice is shown on LA-06 (an expired document), previewed only, never sent.
    d.cap("LA-06 has an expired document: notice previewed in English, Hindi.");
    await d.hash("#/officer/cases/LA-06", ".case-head");
    await openRow(d, "Ask the citizen for documents");
    await d.click(page.getByRole("button", { name: "Preview notice" }), 700);
    await page.locator(".notice-preview").waitFor({ timeout: 30000 });
    await d.select(page.getByLabel(/Language of the notice/), "hi", 200);
    await d.click(page.getByRole("button", { name: "Preview notice" }), 1300);
    await d.hash("#/officer/cases/LA-18", ".case-head");
    d.cap("Approval: confirm every money field and record the resolution.");
    await d.click(page.getByLabel("Approve"), 500);
    const boxes = page.locator("section.decision-bar .confirm-item input");
    for (let i = 0; i < await boxes.count(); i++) await d.click(boxes.nth(i), 250);
    if (await page.getByLabel("Resolution reference").count()) {
      await d.type(page.getByLabel("Resolution reference"), "MAM/TEN/2026/018 (synthetic)", 200);
      await d.type(page.getByLabel("Resolution date"), "19112026", 200);
    }
    await d.click(page.getByRole("button", { name: "Record decision" }), 200);
    await page.locator(".summary-strip.strip-approved").waitFor({ timeout: 30000 });
    await d.scrollTop(900);
    d.cap("A clerk opens a case: no decision controls. Only officers decide.");
    await signIn(d, "clerk", "C-1");
    await d.hash("#/officer/cases/LA-12", ".case-head");
    await d.pause(1800);
    log(`  clerk decision controls on LA-12: ${await page.locator("section.decision-bar").count() ? "SHOWN" : "absent"}`);
    await d.clean("LA-18 decision");

    // 7. Admin and monitoring --------------------------------------------------------------------------------------
    d.startBeat(7);
    d.cap("Admin: headline numbers read straight from the system.");
    await signIn(d, "admin", "A-1");
    await d.hash("#/officer/analytics", ".headline-tiles");
    await d.show(page.locator(".headline-tiles"), 1600);
    await d.show(page.locator(".grid.top-row"), 1200);
    d.cap("More detail: every scheme by stage, and the liability table.");
    await openRow(d, "More detail");
    await d.show(page.locator(".stage-table"), 1500);
    await d.show(page.locator(".card", { hasText: "Committed and pending liability" }).locator("table"), 1300);
    d.cap("Rule simulator: change one parameter, see which cases change.");
    await d.click(page.getByRole("link", { name: "Simulator", exact: true }), 600);
    await d.select(page.getByLabel("Scheme"), "land_acquisition", 400);
    const knob = page.getByLabel("Value to change");
    const option = await knob.locator("option").evaluateAll((os) => (os.find((o) => o.value === "interest_rate") || os[0]).value);
    await d.select(knob, option, 300);
    await d.type(page.getByLabel("New value"), "0.10", 200);
    await d.click(page.getByRole("button", { name: "Run simulation" }), 100);
    await d.slow("simulation", () => page.locator("main table").last().waitFor({ timeout: 60000 }));
    await d.show(page.locator("main .card h2").last(), 2200);
    await d.clean("admin");

    // 8. Trust --------------------------------------------------------------------------------------------------------
    d.startBeat(8);
    d.cap("Every action is in a hash-chained audit log.");
    await signIn(d, "officer", "O-1");
    await d.hash("#/officer/cases/LA-18/audit", "table");
    await d.click(page.getByRole("button", { name: "Verify log integrity" }), 100);
    await page.getByText(/Log intact/).waitFor({ timeout: 30000 });
    await d.show(page.getByText(/Log intact/), 1500);
    d.cap("Duplicate claims and open mutations go to review, never rejection.");
    await d.hash("#/officer/cases/LA-12", ".attention");
    await d.show(page.locator(".attention"), 1800);
    await d.hash("#/officer/cases/RM-02", ".attention");
    await d.show(page.locator(".attention"), 1700);
    d.cap("Four schemes on one engine, each defined in a YAML file.");
    await d.hash("#/officer/cases/SW-01", ".case-head");
    await d.show(page.locator(".summary-strip"), 1500);
    await d.clean("trust");
    d.marks.push({ type: "end", t: d.now() });
    await sleep(500);
    // Closing sync flash (after the end mark, so never in the video): with the opening one it fixes clock drift.
    await page.evaluate(() => {
      const o = document.createElement("div");
      o.id = "sync-flash";
      o.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:#ff0000";
      document.body.appendChild(o);
    });
    await sleep(700);
    endSyncAt = d.now();
    await page.evaluate(() => { document.getElementById("sync-flash").style.background = "#0000ff"; });
    await sleep(600);
  } catch (err) {
    await page.screenshot({ path: join(OUT, "failure.png") }).catch(() => {});
    log(`failed in beat ${d.beat}; screenshot docs/video/failure.png`);
    throw err;
  } finally {
    await context.close();                                   // finishes the video file
    await video.saveAs(join(RUN, "recording.webm")).catch((e) => log(`video not saved: ${e.message}`));
    await browser.close();
    await vite.close();
  }
  // Re-encode to constant 30 fps H.264 with the caption band below the app, then move every mark onto video time.
  ff(["-i", "run/recording.webm", "-vf", `fps=30,pad=1920:1080:0:0:color=${BAND},format=yuv420p`, "-an",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", "raw.mp4"]);
  // Two flashes give a line: video = v0 + (t - syncAt) * rate, so any drift between the clocks is spread evenly.
  const v0 = syncFrame("raw.mp4", 0);
  const tail = Math.floor((probeSeconds(join(OUT, "raw.mp4")) - 8) * 30) / 30;
  const v1 = syncFrame("raw.mp4", tail);
  const rate = (v1 - v0) / (endSyncAt - syncAt);
  const shift = (t) => +(v0 + (t - syncAt) * rate).toFixed(3);
  const marks = d.marks.map((m) => ({ ...m, t: shift(m.t) }));
  const waits = d.waits.map((w) => ({ ...w, a: shift(w.a), b: shift(w.b) }));
  const motion = d.motion.map((w) => ({ ...w, a: shift(w.a), b: shift(w.b) }));
  const sync = { start_offset: +(v0 - syncAt).toFixed(3), end_offset: +(v1 - endSyncAt).toFixed(3), rate: +rate.toFixed(6) };
  log(`raw.mp4: ${probeSeconds(join(OUT, "raw.mp4")).toFixed(1)} s; sync ${JSON.stringify(sync)}`);
  return { marks, waits, motion, warnings: d.warnings, sync };
}

// Time (s) of the first mostly-blue frame of a sync flash at or after `from`, from 8 x 8 thumbnails of 10 s.
function syncFrame(file, from) {
  const r = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-ss", from.toFixed(4), "-t", "10", "-i", file,
    "-vf", "crop=1920:972:0:0,scale=8:8,format=rgb24", "-f", "rawvideo", "-"], { cwd: OUT, maxBuffer: 1 << 26 });
  const buf = r.stdout, size = 8 * 8 * 3;
  for (let i = 0; (i + 1) * size <= buf.length; i++) {
    let R = 0, B = 0;
    for (let p = i * size; p < (i + 1) * size; p += 3) { R += buf[p]; B += buf[p + 2]; }
    if (B / 64 > 180 && R / 64 < 80) return from + i / 30;
  }
  throw new Error(`sync flash not found in the recording after ${from.toFixed(1)} s`);
}

// --- composing --------------------------------------------------------------------------------------------------

const FONT = "C\\:/Windows/Fonts/segoeui.ttf", FONT_B = "C\\:/Windows/Fonts/segoeuib.ttf";
const ENC = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30"];

function card(name, seconds, lines) {
  const filters = lines.map((l, i) => {
    writeFileSync(join(OUT, "parts", `${name}-${i}.txt`), l.text);
    return `drawtext=fontfile='${l.bold ? FONT_B : FONT}':textfile='parts/${name}-${i}.txt':fontsize=${l.size}:fontcolor=${l.color || "white"}:x=(w-text_w)/2:y=${l.y}`;
  }).join(",");
  ff(["-f", "lavfi", "-i", `color=c=0x14304f:s=1920x1080:r=30:d=${seconds}`, "-vf", filters, ...ENC, `parts/${name}.mp4`]);
  return `parts/${name}.mp4`;
}

function compose(rec) {
  const { marks, waits } = rec;
  const dir = join(OUT, "parts");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir);
  const beats = marks.filter((m) => m.type === "beat");
  const end = marks.find((m) => m.type === "end").t;
  // Natural length of each beat after time-lapse, then pad short beats to their target (holding the last frame).
  const plan = beats.map((b, i) => {
    const to = i + 1 < beats.length ? beats[i + 1].t : end;
    const fast = waits.filter((w) => w.a >= b.t && w.b <= to);
    const pieces = [];
    let t = b.t;
    for (const w of fast) {
      if (w.a > t) pieces.push({ a: t, b: w.a, speed: 1 });
      pieces.push({ a: w.a, b: w.b, speed: FAST_SPEED, fast: true });
      t = w.b;
    }
    if (to > t) pieces.push({ a: t, b: to, speed: 1 });
    const natural = pieces.reduce((s, p) => s + (p.b - p.a) / p.speed, 0);
    return { beat: b.beat, pieces, natural, pad: Math.max(0, TARGET[b.beat] - natural) };
  });
  let total = TITLE_S + CLOSING_S + plan.reduce((s, p) => s + p.natural + p.pad, 0);
  if (total > PLAN_CAP) {                                     // first give back padding, never content
    const padding = plan.reduce((s, p) => s + p.pad, 0);
    const cut = Math.min(padding, total - PLAN_CAP);
    for (const p of plan) p.pad -= padding ? (p.pad / padding) * cut : 0;
    total = TITLE_S + CLOSING_S + plan.reduce((s, p) => s + p.natural + p.pad, 0);
  }
  if (total > PLAN_CAP + 0.01) {
    const over = plan.filter((p) => p.natural > TARGET[p.beat]).map((p) => `beat ${p.beat} ${p.natural.toFixed(1)}s > ${TARGET[p.beat]}s`);
    const real = waits.reduce((s, w) => s + w.b - w.a, 0);
    throw new Error(`video would be ${total.toFixed(1)} s (cap ${CAP_TOTAL}); time-lapse ${(real / FAST_SPEED).toFixed(1)} s ` +
      `from ${real.toFixed(1)} s of waits (re-run if the model was slow); shorten pauses in: ${over.join(", ")}`);
  }
  const files = [card("title", TITLE_S, [
    { text: "GovFlow", size: 120, y: 360, bold: true },
    { text: "One AI agent for government case processing", size: 52, y: 530 },
    { text: "An officer always makes the decision", size: 40, y: 620, color: "0xbcd3f0" }])];
  let at = TITLE_S;
  const map = [];                                            // raw interval -> final start time
  const segments = [{ beat: 1, from: 0, to: TITLE_S, card: true }];
  const fastWindows = [];
  for (const p of plan) {
    const beatAt = at;
    p.pieces.forEach((piece, i) => {
      const last = i === p.pieces.length - 1;
      const len = (piece.b - piece.a) / piece.speed;
      const vf = [`setpts=(PTS-STARTPTS)/${piece.speed.toFixed(4)}`, "fps=30", "format=yuv420p"];
      if (last && p.pad > 0.02) vf.push(`tpad=stop_mode=clone:stop_duration=${p.pad.toFixed(3)}`);
      const name = `parts/b${p.beat}-${i}.mp4`;
      // -ss and -t before -i: read exactly this stretch of the recording (after -i, -t would cap the sped-up output
      // instead, and ffmpeg would keep reading far past the stretch).
      ff(["-ss", piece.a.toFixed(3), "-t", (piece.b - piece.a).toFixed(3), "-i", "raw.mp4", "-vf", vf.join(","), ...ENC, name]);
      files.push(name);
      map.push({ beat: p.beat, a: piece.a, b: piece.b, speed: piece.speed, at });
      if (piece.fast) fastWindows.push({ from: at, to: at + len });
      at += len + (last ? p.pad : 0);
    });
    segments.push({ beat: p.beat, from: beatAt, to: at });
  }
  files.push(card("closing", CLOSING_S, [
    { text: "Measured on synthetic test documents (docs/EVAL_RESULTS.md, docs/BENCHMARK.md)", size: 36, y: 170, color: "0xbcd3f0" },
    { text: "Gemini reading: relief 35/35 on every image set", size: 50, y: 270 },
    { text: "Land 25/27 clean, 21/27 hard; 84 reads, 0 provider errors", size: 50, y: 350 },
    { text: "Checks, rules and amounts: median 3.2 ms per land case (software time only)", size: 44, y: 440 },
    { text: "Synthetic data. Values are placeholders until the offices confirm.", size: 46, y: 600, bold: true },
    { text: "Scripted walkthrough of the live prototype", size: 52, y: 760, bold: true }]));
  segments.push({ beat: 9, from: at, to: at + CLOSING_S, card: true });
  writeFileSync(join(dir, "list.txt"), files.map((f) => `file '${f.replace("parts/", "")}'`).join("\n"));
  ff(["-f", "concat", "-safe", "0", "-i", "parts/list.txt", "-c", "copy", "body.mp4"]);

  // Captions on the final timeline: each shows until the next caption of its beat, or the beat's end.
  const toFinal = (t) => { const m = map.find((x) => t >= x.a - 0.001 && t <= x.b + 0.001); return m ? m.at + (t - m.a) / m.speed : null; };
  // A caption maps through its own beat's pieces: a beat's first caption sits exactly on the previous beat's last
  // raw instant, and mapping it there put it before that beat's end padding, over the previous caption.
  const toFinalIn = (t, beat) => {
    const m = map.find((x) => x.beat === beat && t >= x.a - 0.001 && t <= x.b + 0.001);
    return m ? m.at + (t - m.a) / m.speed : null;
  };
  const gray = grayFrames(), byMin = {};
  const changesOver = (min) => (byMin[min] ??= screenChanges(gray, min));
  const caps = marks.filter((m) => m.type === "cap").map((c) => {
    const rule = CAPTION_SCREEN[c.text];
    if (!rule) return { ...c, at: toFinalIn(c.t, c.beat) };
    const { after = 0, before = 0, until = 0, min = 1.5 } = typeof rule === "number" ? { after: rule } : rule;
    const changes = changesOver(min);
    const from = after ? changes.filter((x) => x.b > c.t)[after - 1] : changes.filter((x) => x.a < c.t).at(-before);
    const end = until ? changes.filter((x) => x.a > c.t)[until - 1] : null;
    if (!from || (until && !end)) throw new Error(`screen change not found for caption: ${c.text}`);
    return { ...c, at: toFinalIn(after ? from.b : from.a, c.beat), end: end ? toFinalIn(end.a, c.beat) : null };
  }).filter((c) => c.at !== null);
  const windows = caps.map((c, i) => {
    const seg = segments.find((s) => s.beat === c.beat && !s.card);
    const next = caps[i + 1] && caps[i + 1].beat === c.beat ? caps[i + 1].at : seg.to;
    return { beat: c.beat, text: c.text, from: c.at, to: Math.min(next, seg.to, c.end ?? Infinity) };
  });
  const filters = windows.map((w, i) => {
    writeFileSync(join(dir, `cap-${i}.txt`), w.text);
    return `drawtext=fontfile='${FONT}':textfile='parts/cap-${i}.txt':fontsize=42:fontcolor=white:x=(w-text_w)/2:y=${APP_H}+(${1080 - APP_H}-text_h)/2:enable='between(t,${w.from.toFixed(2)},${w.to.toFixed(2)})'`;
  });
  writeFileSync(join(dir, "fast.txt"), "Sped up");
  for (const f of fastWindows) filters.push(`drawtext=fontfile='${FONT_B}':textfile='parts/fast.txt':fontsize=32:fontcolor=white:box=1:boxcolor=0xb3261e:boxborderw=12:x=36:y=${APP_H}+(${1080 - APP_H}-text_h)/2:enable='between(t,${f.from.toFixed(2)},${f.to.toFixed(2)})'`);
  writeFileSync(join(dir, "captions.txt"), filters.join(",\n"));
  ff(["-i", "body.mp4", "-/vf", "parts/captions.txt", ...ENC, "-movflags", "+faststart", "govflow_demo_captioned.mp4"]);
  // Scripted motion (cursor glides, scrolls) on the final timeline, for measuring smoothness where things move. The
  // director logs when input is sent; it reaches the captured screen RENDER_LAG later (measured on the 2026-11-21
  // recording: in-motion distinct frames peak with the windows 0.10-0.13 s late), so the windows are moved by that much.
  const motion = (rec.motion || []).map((w) => ({ kind: w.kind, from: toFinal(w.a + RENDER_LAG), to: toFinal(w.b + RENDER_LAG) }))
    .filter((w) => w.from !== null && w.to !== null && w.to > w.from);
  const motionAsSent = (rec.motion || []).map((w) => ({ kind: w.kind, from: toFinal(w.a), to: toFinal(w.b) }))
    .filter((w) => w.from !== null && w.to !== null && w.to > w.from);
  return { segments, windows, fastWindows, plan, motion, motionAsSent };
}

const stamp = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;

function writeNarration(segments) {
  const lines = ["GovFlow demo: narration, one line per beat (about 140 words a minute).",
    "Timestamps are the beats of docs/video/govflow_demo_captioned.mp4, written by scripts/make_demo_video.mjs.", ""];
  for (const n of Object.keys(NARRATION).map(Number)) {
    const segs = segments.filter((s) => s.beat === n);
    const from = Math.min(...segs.map((s) => s.from)), to = Math.max(...segs.map((s) => s.to));
    const words = NARRATION[n].split(/\s+/).length;
    lines.push(`[${stamp(from)} - ${stamp(to)}] Beat ${n} (${words} words, ${(words / ((to - from) / 60)).toFixed(1)} words a minute)`,
      NARRATION[n], "");
  }
  writeFileSync(join(OUT, "narration.txt"), lines.join("\n"));
}

function frames(segments, file) {
  const dir = join(OUT, "frames");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir);
  const shots = segments.map((s) => ({ name: `beat${s.beat}${s.card ? "-card" : ""}`, t: s.from + (s.to - s.from) * 0.6 }));
  for (const s of shots) ff(["-ss", s.t.toFixed(2), "-i", file, "-frames:v", "1", `frames/${s.name}.png`]);
  return shots;
}

// --- main ---------------------------------------------------------------------------------------------------------

// --compose-only rebuilds the captioned video from the last recording (raw.mp4 + run/record.json), no app, no model.
let rec;
if (process.argv.includes("--compose-only")) {
  rec = JSON.parse(readFileSync(join(RUN, "record.json"), "utf8"));
} else {
  const pre = preflight();
  log(`Gemini preflight: ${pre.detail}`);
  if (!pre.ok) { log("Stopping: the live model did not answer; the explanation steps would show the fallback."); process.exit(2); }
  const demoDb = prepare();
  const secrets = { citizen: randomBytes(24).toString("hex"), auth: randomBytes(24).toString("hex") };
  const api = startApi(demoDb, secrets);
  try {
    await waitForApi();
    rec = await record(secrets);
  } finally {
    api.kill();
  }
  writeFileSync(join(RUN, "record.json"), JSON.stringify(rec));
}
const composed = compose(rec);
writeNarration(composed.segments);
const duration = probeSeconds(join(OUT, "govflow_demo_captioned.mp4"));
const shots = frames(composed.segments, "govflow_demo_captioned.mp4");
// Smoothness of the app area between the cards (captions and cards excluded), with ffmpeg mpdecimate; also inside the
// scripted motion windows alone (cursor glides and scrolls).
const measureWith = (windows, name) => {
  writeFileSync(join(RUN, name), JSON.stringify(windows));
  const r = spawnSync(process.execPath, [join(ROOT, "scripts", "measure_video.mjs"), "govflow_demo_captioned.mp4",
    "--from", String(TITLE_S), "--to", (duration - CLOSING_S).toFixed(2), "--crop", `1920:${APP_H}:0:0`,
    "--windows", join(RUN, name)], { cwd: OUT, encoding: "utf8" });
  return JSON.parse(r.stdout);
};
const smooth = measureWith(composed.motion, "motion.json");
const asSent = measureWith(composed.motionAsSent, "motion_as_sent.json");
smooth.in_motion_as_sent = { distinct_fps: asSent.distinct_fps_in_motion, gaps_over_0_1: asSent.gaps_over_0_1_in_motion };
log(`smoothness: ${JSON.stringify(smooth)}`);
writeFileSync(join(OUT, "timeline.json"), JSON.stringify({ duration, smooth, warnings: rec.warnings, waits: rec.waits,
  motion: composed.motion,
  segments: composed.segments, captions: composed.windows, fast: composed.fastWindows,
  beats: composed.plan.map((p) => ({ beat: p.beat, natural: p.natural, pad: p.pad })), frames: shots }, null, 2));
log(`final duration ${duration.toFixed(2)} s; warnings: ${rec.warnings.length}; time-lapsed waits: ${rec.waits.length}`);
if (duration > CAP_TOTAL + 0.05) { log("OVER THE CAP"); process.exit(3); }
