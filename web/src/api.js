// API client. Staff identity is the signed token from the demo sign-in (lib/session.js). DEMO sign-in, no password.
import { authHeaders, isCurrent } from "./lib/session.js";

const KEY = "govflow-demo-login";
export const SIGNED_OUT = "govflow-signed-out";   // window event: the server refused the token; show sign-in

export function getLogin() {
  try {
    const login = JSON.parse(localStorage.getItem(KEY)) || null;
    return isCurrent(login) ? login : null;   // expired, or saved before tokens: sign in again
  } catch {
    return null;
  }
}

export function setLogin(login) {
  try {
    if (login) localStorage.setItem(KEY, JSON.stringify(login));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: the login lasts for this page only */
  }
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
  }
}

export async function signIn(role, user) {
  const response = await fetch("/api/auth/demo-login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, user }) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, response.status === 422 ? "Use letters, digits, dot, dash or underscore for the user id." : data?.detail ?? response.statusText);
  return data;   // { token, role, user, expires_at }
}

export async function api(method, path, body) {
  const headers = { "Content-Type": "application/json", ...authHeaders(getLogin()) };
  const response = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (response.status === 401) {
    setLogin(null);
    window.dispatchEvent(new Event(SIGNED_OUT));
  }
  if (!response.ok) throw new ApiError(response.status, data?.detail ?? response.statusText);
  return data;
}

export function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
