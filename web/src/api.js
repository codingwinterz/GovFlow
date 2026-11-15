// API client. DEMO MODE: identity is the X-Role / X-User headers, trusted by the backend as sent.

const KEY = "govflow-demo-login";

export function getLogin() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || null;
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

export async function api(method, path, body) {
  const login = getLogin();
  const headers = { "Content-Type": "application/json" };
  if (login) Object.assign(headers, { "X-Role": login.role, "X-User": login.user });
  const response = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = response.status === 204 ? null : await response.json().catch(() => null);
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
