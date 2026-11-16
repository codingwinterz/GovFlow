import { useState } from "react";
import { api, readFileAsBase64 } from "../api.js";
import { useApi } from "../useApi.jsx";
import { href } from "../lib/router.js";
import { termLabel } from "../lib/display.js";
import { todayInIndia } from "../lib/format.js";

function CreateCase({ schemes, onCreated }) {
  const [form, setForm] = useState({ case_id: "", scheme: "", reference_date: todayInIndia() });
  const [inputs, setInputs] = useState({});
  const [error, setError] = useState("");
  const scheme = schemes.find((s) => s.scheme === (form.scheme || schemes[0]?.scheme));

  const submit = async (e) => {
    e.preventDefault();
    const typed = Object.fromEntries(Object.entries(inputs).filter(([, v]) => v !== "")
      .map(([k, v]) => [k, /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v]));   // numbers stay numbers; dates stay text
    try {
      await api("POST", "/cases", { ...form, scheme: scheme.scheme, inputs: typed });
      setError("");
      onCreated(form.case_id, scheme);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <form className="card" onSubmit={submit}>
      <h2>1. Create a case</h2>
      <label>Case id <input required pattern="[A-Za-z0-9_\-]{1,64}" value={form.case_id}
        onChange={(e) => setForm({ ...form, case_id: e.target.value })} placeholder="LA-50" /></label>
      <label>Scheme
        <select value={scheme?.scheme || ""} onChange={(e) => setForm({ ...form, scheme: e.target.value })}>
          {schemes.map((s) => <option key={s.scheme} value={s.scheme}>{s.labels.title} (v{s.version})</option>)}
        </select>
      </label>
      <label>Reference date <input type="date" required value={form.reference_date}
        onChange={(e) => setForm({ ...form, reference_date: e.target.value })} /></label>
      {scheme && scheme.officer_inputs.length > 0 && (
        <fieldset>
          <legend>Officer inputs</legend>
          {scheme.officer_inputs.map((name) => (
            <label key={name}>{termLabel(scheme.terms, name)}
              <input value={inputs[name] || ""} onChange={(e) => setInputs({ ...inputs, [name]: e.target.value })}
                placeholder={name.endsWith("_date") ? "YYYY-MM-DD" : ""} />
            </label>
          ))}
        </fieldset>
      )}
      {error && <p className="error">{error}</p>}
      <button type="submit">Create case</button>
    </form>
  );
}

function UploadDocuments({ caseId, scheme }) {
  const [docType, setDocType] = useState(scheme.documents[0]);
  const [file, setFile] = useState(null);
  const [uploaded, setUploaded] = useState([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const base = `/cases/${encodeURIComponent(caseId)}`;

  const upload = async (e) => {
    e.preventDefault();
    if (!file) return setMessage("Choose a file.");
    setBusy(true);
    try {
      const doc = await api("POST", `${base}/documents`, { doc_type: docType, filename: file.name,
        content_base64: await readFileAsBase64(file) });
      let status = "uploaded";
      try {
        const r = await api("POST", `${base}/documents/${doc.id}/extract`);
        status = r.status === "ok" ? `read ${r.fields.length} fields` : "extraction unavailable, retry from the case page";
      } catch (err) {
        status = `uploaded; extraction not run (${err.message})`;
      }
      setUploaded([...uploaded, { ...doc, outcome: status }]);
      setMessage("");
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    setBusy(true);
    try {
      await api("POST", `${base}/run`);
      window.location.hash = href("case", caseId);
    } catch (err) {
      setMessage(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>2. Upload documents for {caseId}</h2>
      <form onSubmit={upload}>
        <label>Document type
          <select value={docType} onChange={(e) => setDocType(e.target.value)}>
            {scheme.documents.map((d) => <option key={d} value={d}>{termLabel(scheme.terms, d)}</option>)}
          </select>
        </label>
        <label>File (.txt, .png, .jpg, .pdf; max 10 MB)
          <input type="file" accept=".txt,.png,.jpg,.jpeg,.pdf" onChange={(e) => setFile(e.target.files[0] || null)} />
        </label>
        <button type="submit" disabled={busy}>Upload</button>
      </form>
      {uploaded.length > 0 && <ul>{uploaded.map((d) => <li key={d.id}>{termLabel(scheme.terms, d.doc_type)} #{d.id}: {d.outcome}</li>)}</ul>}
      {message && <p className="error">{message}</p>}
      <h2>3. Run the agent</h2>
      <p className="muted">Runs extraction checks, verification, eligibility and compensation, then submits to the officer queue.
        If no LLM is available, the same tools run without it and the summary says so.</p>
      <button onClick={run} disabled={busy}>{busy ? "Working…" : "Run agent and open case"}</button>
    </div>
  );
}

export default function Intake() {
  const schemes = useApi("/schemes");
  const [created, setCreated] = useState(null);
  return (
    <section>
      <h1>Case intake</h1>
      {schemes.error && <p className="error">{schemes.error.message}</p>}
      {schemes.data && !created && <CreateCase schemes={schemes.data} onCreated={(id, scheme) => setCreated({ id, scheme })} />}
      {created && <UploadDocuments caseId={created.id} scheme={created.scheme} />}
    </section>
  );
}
