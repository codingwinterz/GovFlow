import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { errorMessage, retryable } from "./lib/states.js";

// Load one API resource; `reload` re-fetches after an action.
export function useApi(path) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const load = useCallback(() => {
    if (!path) return;
    setState((s) => ({ ...s, loading: true }));
    api("GET", path)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => setState({ data: null, error, loading: false }));
  }, [path]);
  useEffect(load, [load]);
  return { ...state, reload: load };
}

// Announced to screen readers: loading as a status, failure as an alert with a plain message.
export function Loading({ state, back }) {
  if (state.loading && !state.data) return <p className="muted" role="status">Loading…</p>;
  if (state.error) return (
    <div className="banner warn" role="alert">
      <p>{errorMessage(state.error)}</p>
      {retryable(state.error) && <button type="button" onClick={state.reload}>Retry</button>}
      {state.error.status === 404 && back}
    </div>
  );
  return null;
}
