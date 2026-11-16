// Loading, error and input states shared by pages: plain words for people, never raw status codes.

// What an officer reads when a request fails. The API's own detail is used where it is written for people
// (400 / 404 / 409 explain the case); other failures get a plain sentence.
export function errorMessage(error) {
  const status = error?.status;
  if (!status) return "Cannot reach the server. Check the connection and try again.";
  if (status === 401) return "Your sign-in has expired. Please sign in again.";
  if (status === 403) return "Your role cannot open this.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  if (status >= 500) return "The server had a problem. Please try again.";
  return error.message || "That did not work.";
}

// Retry helps only when the same request may work next time.
export function retryable(error) {
  const status = error?.status;
  return !status || status === 429 || status >= 500;
}

// Citizen tracking: check the format before sending, so a typo neither costs an attempt nor reads as "not found".
const CASE_REF = /^[A-Za-z0-9_-]{1,64}$/;   // the API's case id format
const CODE = /^\d{6}$/;

export function trackProblem(ref, code) {
  if (!CASE_REF.test(String(ref || "").trim())) return "track.invalid_ref";
  if (!CODE.test(String(code || "").trim())) return "track.invalid_code";
  return null;
}

// The self-check list: only a successful response holding a list counts; anything else is a load error.
export async function readList(response) {
  if (!response.ok) throw new Error(`status ${response.status}`);
  const data = await response.json();
  if (!Array.isArray(data)) throw new Error("not a list");
  return data;
}
