// Citizen pages (and the landing page) are light unless the citizen chooses dark; staff pages follow the system.
const KEY = "govflow-citizen-theme";

export function themeFor(shell, stored) {
  if (shell === "officer") return "system";
  return stored === "dark" ? "dark" : "light";
}

export function nextTheme(theme) {
  return theme === "dark" ? "light" : "dark";
}

export function readStoredTheme() {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function storeTheme(theme) {
  try { localStorage.setItem(KEY, theme); } catch { /* per-visit only */ }
}
