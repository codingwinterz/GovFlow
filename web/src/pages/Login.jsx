import { useState } from "react";

export default function Login({ onLogin }) {
  const [role, setRole] = useState("officer");
  const [user, setUser] = useState("O-1");
  return (
    <section className="card narrow">
      <h1>Demo sign-in</h1>
      <p className="muted">
        Demo mode: there is no password. The role and user id are sent as headers and trusted by the backend.
        Replace with real authentication before any deployment.
      </p>
      <form onSubmit={(e) => { e.preventDefault(); if (user.trim()) onLogin({ role, user: user.trim() }); }}>
        <label>Role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="officer">officer (decides cases)</option>
            <option value="clerk">clerk (intake, runs the agent)</option>
            <option value="citizen">citizen (status only)</option>
          </select>
        </label>
        <label>User id <input value={user} onChange={(e) => setUser(e.target.value)} /></label>
        <button type="submit">Continue</button>
      </form>
    </section>
  );
}
