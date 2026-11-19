// Two shells: citizens never see officer navigation; officer pages are gated by role.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { CITIZEN_NAV, officerNav, allowed } from "./nav.js";
import { href, parseRoute } from "./router.js";

const SRC = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const read = (p) => readFileSync(join(SRC, p), "utf8");
const OFFICER_PAGES = ["Queue", "CasePage", "Intake", "Analytics", "Simulator", "Audit", "Award", "Login"];

test("citizen navigation holds only citizen pages", () => {
  assert.deepEqual(CITIZEN_NAV.map((n) => n.page), ["citizen-home", "self-check", "track"]);
  for (const n of CITIZEN_NAV) assert.equal(parseRoute(href(n.page)).shell, "citizen", n.page);
});

test("officer navigation per role", () => {
  const pages = (role) => officerNav(role).map((n) => n.page);
  assert.deepEqual(pages("officer"), ["queue", "intake", "analytics", "simulator"]);
  assert.deepEqual(pages("clerk"), ["queue", "intake"]);
  assert.deepEqual(pages("admin"), ["analytics", "simulator"]);
  assert.deepEqual(pages("citizen"), []);
  assert.deepEqual(pages(undefined), []);
  for (const role of ["officer", "clerk", "admin"])
    for (const n of officerNav(role)) assert.equal(parseRoute(href(n.page)).shell, "officer", n.page);
});

test("officer pages are allowed by role, never to citizens", () => {
  for (const page of ["queue", "case", "audit", "award", "intake", "analytics", "simulator"]) {
    assert.equal(allowed("officer", page), true, page);
    assert.equal(allowed("citizen", page), false, page);
  }
  assert.deepEqual(["queue", "case", "intake"].map((p) => allowed("clerk", p)), [true, true, true]);
  assert.deepEqual(["audit", "award", "analytics", "simulator"].map((p) => allowed("clerk", p)), [false, false, false, false]);
  assert.deepEqual(["analytics", "simulator", "queue", "case"].map((p) => allowed("admin", p)), [true, true, false, false]);
});


test("the citizen shell and its pages import nothing from the officer side", () => {
  const citizenFiles = ["shells/CitizenShell.jsx", "pages/CitizenHome.jsx", "pages/Track.jsx", "pages/SelfCheck.jsx"];
  for (const file of citizenFiles) {
    const source = read(file);
    for (const page of OFFICER_PAGES) assert.doesNotMatch(source, new RegExp(`/${page}\\.jsx`), `${file} imports ${page}`);
    assert.doesNotMatch(source, /OfficerShell|officerNav|\bapi\.js|getLogin/, file);
  }
});

test("the staff status lookup page is removed (track an application is the only status page)", () => {
  assert.ok(!readdirSync(join(SRC, "pages")).includes("StatusLookup.jsx"));
  assert.doesNotMatch(read("App.jsx") + read("shells/OfficerShell.jsx"), /StatusLookup|Status lookup/);
});

test("the landing page offers exactly the two entry points", () => {
  const source = read("shells/Landing.jsx");
  assert.match(source, /href\("citizen-home"\)/);
  assert.match(source, /href\("queue"\)/);
});
