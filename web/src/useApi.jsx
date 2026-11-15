import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";

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

export function Loading({ state }) {
  if (state.loading && !state.data) return <p className="muted">Loading…</p>;
  if (state.error) return <p className="error">Error {state.error.status}: {state.error.message}</p>;
  return null;
}
