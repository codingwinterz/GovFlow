// Minimal hash router (no dependency). Hash URLs need no server configuration.

export function parseRoute(hash) {
  const path = (hash || "").replace(/^#/, "") || "/";
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts.length === 0) return { page: "queue" };
  if (parts[0] === "cases" && parts.length === 2) return { page: "case", id: parts[1] };
  if (parts[0] === "cases" && parts.length === 3 && parts[2] === "audit") return { page: "audit", id: parts[1] };
  if (parts[0] === "cases" && parts.length === 3 && parts[2] === "award") return { page: "award", id: parts[1] };
  if (parts.length === 1 && ["analytics", "intake", "status", "track", "self-check", "simulator"].includes(parts[0])) return { page: parts[0] };
  return { page: "notfound" };
}

export function href(page, id) {
  if (page === "case") return `#/cases/${encodeURIComponent(id)}`;
  if (page === "audit") return `#/cases/${encodeURIComponent(id)}/audit`;
  if (page === "award") return `#/cases/${encodeURIComponent(id)}/award`;
  return page === "queue" ? "#/" : `#/${page}`;
}
