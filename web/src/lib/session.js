// Staff session: the signed token from POST /auth/demo-login. The role and user inside it are signed by the server,
// so editing the saved login cannot change who you are. DEMO sign-in; production uses the government SSO.

export function isCurrent(login, now = new Date()) {
  return Boolean(login && login.token && login.role && login.expires_at && new Date(login.expires_at) > now);
}

export function authHeaders(login, now = new Date()) {
  return isCurrent(login, now) ? { Authorization: `Bearer ${login.token}` } : {};   // never X-Role / X-User
}
