// Minimal hash router (no dependency). Hash URLs need no server configuration.
// Every route names its shell: the landing page, the citizen shell (#/citizen/...) or the officer shell (#/officer/...).

const CITIZEN = { "": "citizen-home", check: "self-check", track: "track" };
const OFFICER = { "": "queue", intake: "intake", analytics: "analytics", simulator: "simulator" };
const LEGACY = { track: "track", "self-check": "self-check" };   // links printed before the split
const NOT_FOUND = { page: "notfound", shell: "landing" };

export function parseRoute(hash) {
  const path = (hash || "").replace(/^#/, "") || "/";
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const [area, sub = "", id, extra] = parts;
  if (parts.length === 0) return { page: "home", shell: "landing" };
  if (parts.length === 1 && area in LEGACY) return { page: LEGACY[area], shell: "citizen" };
  if (area === "citizen" && parts.length <= 2 && sub in CITIZEN) return { page: CITIZEN[sub], shell: "citizen" };
  if (area !== "officer") return NOT_FOUND;
  if (parts.length <= 2 && sub in OFFICER) return { page: OFFICER[sub], shell: "officer" };
  if (sub === "cases" && id && parts.length === 3) return { page: "case", id, shell: "officer" };
  if (sub === "cases" && id && parts.length === 4 && ["audit", "award"].includes(extra))
    return { page: extra, id, shell: "officer" };
  return NOT_FOUND;
}

const PATHS = {
  home: "#/", "citizen-home": "#/citizen", "self-check": "#/citizen/check", track: "#/citizen/track",
  queue: "#/officer", intake: "#/officer/intake", analytics: "#/officer/analytics", simulator: "#/officer/simulator",
};

export function href(page, id) {
  const caseBase = `#/officer/cases/${encodeURIComponent(id)}`;
  if (page === "case") return caseBase;
  if (page === "audit" || page === "award") return `${caseBase}/${page}`;
  if (!(page in PATHS)) throw new Error(`No route for page ${page}`);
  return PATHS[page];
}
