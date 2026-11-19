import { href } from "../lib/router.js";

// Two entry points, nothing else: citizens and staff never share a navigation bar.
export default function Landing({ notFound = false }) {
  return (
    <div className="shell landing" data-theme="light">
      <main className="content narrow-content">
        <p className="brand big-brand">GovFlow</p>
        <p className="tagline">GovFlow reads the documents in a government case, checks them against the scheme's rules and
          prepares a recommendation. An officer always makes the decision.</p>
        <p className="demo-note"><span className="badge demo">Demo with synthetic data</span>{" "}
          <span className="muted small">Every case, name and document here is made up. No real citizen records.</span></p>
        {notFound && <p className="banner warn">That page does not exist. Choose where to go:</p>}
        <div className="entry-grid">
          <a className="entry card" href={href("citizen-home")}>
            <h2>Citizen services</h2>
            <p>Check before you apply, or track an application you have made. Available in English, Hindi, Marathi
              and Konkani.</p>
            <span className="entry-go">Continue as a citizen →</span>
          </a>
          <a className="entry card" href={href("queue")}>
            <h2>Officer and clerk dashboard</h2>
            <p>Case queue, intake, analytics and the rule simulator. Staff sign-in required (demo mode).</p>
            <span className="entry-go">Continue as staff →</span>
          </a>
        </div>
      </main>
    </div>
  );
}
