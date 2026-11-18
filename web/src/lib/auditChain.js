// Wording for GET /admin/audit/verify. The server walks the hash chain; the browser only words its answer.
const NO_RESULT = { ok: false, text: "The integrity check gave no result. Try again." };

export function integrityMessage(result) {
  if (!result || typeof result.ok !== "boolean" || !Number.isInteger(result.rows)) return NO_RESULT;
  const { ok, rows, first_broken_id: broken } = result;
  if (ok) {
    if (rows === 0) return { ok, text: "Log intact: the log is empty." };
    return { ok, text: `Log intact: all ${rows} ${rows === 1 ? "row chains" : "rows chain"} correctly.` };
  }
  if (!Number.isInteger(broken)) return NO_RESULT;
  return { ok, text: `Log altered: the chain breaks at row #${broken} (${rows} rows checked). `
    + "That row, or the one before it, was edited, deleted or moved." };
}
