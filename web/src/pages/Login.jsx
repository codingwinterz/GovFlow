import { useState } from "react";
import { signIn } from "../api.js";
import { href } from "../lib/router.js";

export default function Login({ onLogin }) {
  const [role, setRole] = useState("officer");
  const [user, setUser] = useState("O-1");
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (!user.trim()) return setError("Enter a user id.");
    try {
      onLogin(await signIn(role, user.trim()));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="card narrow">
      <h1>Demo sign-in</h1>
      <p className="muted">
        Demo mode: there is no password. The server signs your role and user id into a token that lasts 8 hours.
        A real deployment needs the government single sign-on instead.
      </p>
      <form onSubmit={submit}>
        <label>Role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="officer">officer (decides cases)</option>
            <option value="clerk">clerk (intake, runs the agent)</option>
            <option value="admin">admin (rule simulator only)</option>
          </select>
        </label>
        <label>User id <input value={user} onChange={(e) => setUser(e.target.value)} /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit">Continue</button>
      </form>
      <p className="muted">Not staff? <a href={href("citizen-home")}>Citizen services</a></p>
    </section>
  );
}
