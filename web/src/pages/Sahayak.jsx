import { useEffect, useState } from "react";
import { askBody, askError, replyView } from "../lib/sahayak.js";

const MAX = 500;

// Text-only, English-only helper on the self-check page. Every reply comes from the server, which answers from a
// fixed knowledge base; nothing is decided or computed here. English whatever the page language.
export default function Sahayak({ scheme, result }) {
  const [open, setOpen] = useState(false);
  const [topics, setTopics] = useState({ state: "idle", list: [] });
  const [message, setMessage] = useState("");
  const [ask, setAsk] = useState({ state: "idle", reply: null, error: "", last: "" });

  const loadTopics = () => {
    setTopics({ state: "loading", list: [] });
    fetch(`/api/public/sahayak${scheme ? `?scheme=${encodeURIComponent(scheme)}` : ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => setTopics({ state: "ready", list: Array.isArray(d.topics) ? d.topics : [] }))
      .catch(() => setTopics({ state: "error", list: [] }));
  };
  useEffect(() => { if (open) loadTopics(); }, [open, scheme]);

  const send = async (text) => {
    const question = String(text).trim();
    if (!question) return;
    setAsk({ state: "loading", reply: null, error: "", last: question });
    try {
      const r = await fetch("/api/public/sahayak", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(askBody(question, scheme, result)) });
      if (!r.ok) return setAsk({ state: "error", reply: null, error: askError(r.status), last: question });
      setAsk({ state: "ready", reply: replyView(await r.json()), error: "", last: question });
    } catch {
      setAsk({ state: "error", reply: null, error: askError(0), last: question });
    }
  };

  return (
    <>
      <button type="button" className="sahayak-open" aria-expanded={open} aria-controls="sahayak"
        onClick={() => setOpen(!open)}>Sahayak</button>
      {open && (
        <aside id="sahayak" className="drawer" role="dialog" aria-label="Sahayak helper" lang="en">
          <div className="drawer-head">
            <h2>Sahayak</h2>
            <button type="button" onClick={() => setOpen(false)}>Close</button>
          </div>
          <p className="muted small">Sahayak answers in English.</p>
          <p className="banner warn"><strong>A guide, not a decision. Only an officer decides.</strong></p>

          {topics.state === "loading" && <p className="muted" role="status">Loading suggested questions…</p>}
          {topics.state === "error" && (
            <div className="banner warn" role="alert">
              <p>Could not load the suggested questions.</p>
              <button type="button" onClick={loadTopics}>Retry</button>
            </div>
          )}
          {topics.state === "ready" && topics.list.length === 0 && <p className="muted">No suggested questions yet.</p>}
          {topics.list.length > 0 && (
            <div className="chips" aria-label="Suggested questions">
              {topics.list.map((t) => (
                <button type="button" key={t.id} className="chip" onClick={() => send(t.title)}>{t.title}</button>
              ))}
            </div>
          )}

          <form onSubmit={(e) => { e.preventDefault(); send(message); }}>
            <label>Your question
              <textarea value={message} maxLength={MAX} rows={3} onChange={(e) => setMessage(e.target.value)} />
            </label>
            <p className="muted small">{message.length} of {MAX} characters</p>
            <button type="submit" disabled={ask.state === "loading" || !message.trim()}>Ask</button>
          </form>

          <div role="status" aria-live="polite" className="sahayak-reply">
            {ask.state === "loading" && <p className="muted">Sahayak is looking…</p>}
            {ask.state === "ready" && (
              <>
                <p className="answer">{ask.reply.text}</p>
                {ask.reply.fallback && <p className="muted small">Answered from the helper's notes.</p>}
                {ask.reply.sources.map((s) => (
                  <p key={s.id} className="small source">
                    Source: {s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.label}</a> : s.label}
                    {s.unconfirmed && " (source to be confirmed)"}
                    {s.tag && <span className="badge warn">{s.tag}</span>}
                  </p>
                ))}
              </>
            )}
          </div>
          {ask.state === "error" && (
            <div className="banner warn" role="alert">
              <p>{ask.error}</p>
              <button type="button" onClick={() => send(ask.last)}>Retry</button>
            </div>
          )}
        </aside>
      )}
    </>
  );
}
