// Sahayak helper: what the page sends and how a reply is shown. English only; no arithmetic, no decisions here.

// The self-check result already on the page, reduced to ids and statuses (the server rejects anything else).
export function selfCheckSummary(result) {
  if (!result) return null;
  return { scheme: result.scheme, outcome: result.outcome,
    rules: (result.rules || []).map(({ rule_id, status }) => ({ rule_id, status })) };
}

export function askBody(message, scheme, result) {
  const body = { message: String(message).trim() };
  if (scheme) body.scheme = scheme;
  const summary = selfCheckSummary(result);
  if (summary) body.self_check = summary;
  return body;
}

// Sources and "verify" tags come straight from the API; a VERIFY url is shown as "source to be confirmed".
export function replyView(reply) {
  return {
    text: reply.answer,
    fallback: !!reply.used_fallback,
    sources: (reply.entries || []).map((e) => ({
      id: e.id, title: e.title, label: e.source.name,
      url: e.source.url === "VERIFY" ? null : e.source.url,
      unconfirmed: e.source.url === "VERIFY",
      tag: e.tag || null,
    })),
  };
}

export function askError(status) {
  return status === 429 ? "Too many questions. Please wait a few minutes, then try again."
    : status === 422 ? "Sahayak could not read that question. Keep it under 500 characters and try again."
      : "Sahayak could not answer just now.";
}
