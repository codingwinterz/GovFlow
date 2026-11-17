import { useEffect, useState } from "react";
import { SIGNED_OUT, getLogin, setLogin } from "../api.js";
import { allowed, homePage, officerNav } from "../lib/nav.js";
import { href } from "../lib/router.js";
import Login from "../pages/Login.jsx";
import Queue from "../pages/Queue.jsx";
import CasePage from "../pages/CasePage.jsx";
import Audit from "../pages/Audit.jsx";
import Analytics from "../pages/Analytics.jsx";
import Intake from "../pages/Intake.jsx";
import Simulator from "../pages/Simulator.jsx";
import Award from "../pages/Award.jsx";

const STAFF = ["officer", "clerk", "admin"];
const ROLE_LABEL = { officer: "Officer", clerk: "Clerk", admin: "Administrator" };
const CASE_PAGES = ["case", "audit", "award"];   // reached from the queue, so the queue tab stays active

function Page({ route, login }) {
  switch (route.page) {
    case "queue": return <Queue />;
    // key = the case id: a new case mounts a fresh page (loading state), so nothing of the previous case is shown
    case "case": return <CasePage key={route.id} id={route.id} login={login} />;
    case "audit": return <Audit key={route.id} id={route.id} />;
    case "award": return <Award key={route.id} id={route.id} />;
    case "analytics": return <Analytics />;
    case "intake": return <Intake />;
    case "simulator": return <Simulator />;
    default: return null;
  }
}

export default function OfficerShell({ route }) {
  const [login, setLoginState] = useState(getLogin());
  const signIn = (value) => { setLogin(value); setLoginState(value); };
  useEffect(() => {                                   // the server refused the token (expired): back to sign-in
    const signedOut = () => setLoginState(null);
    window.addEventListener(SIGNED_OUT, signedOut);
    return () => window.removeEventListener(SIGNED_OUT, signedOut);
  }, []);
  const staff = login && STAFF.includes(login.role) ? login : null;
  const active = CASE_PAGES.includes(route.page) ? "queue" : route.page;
  const start = staff && homePage(staff.role);

  return (
    <div className="shell officer" data-theme="system">
      <header className="topbar no-print">
        <div className="topbar-inner">
          <a className="brand" href={href(start || "queue")}>GovFlow <span className="brand-sub">Staff</span></a>
          <span className="badge demo" title="Demo sign-in without a password; a real deployment needs single sign-on">DEMO MODE</span>
          {staff && (
            <nav aria-label="Staff">
              {officerNav(staff.role).map((n) => (
                <a key={n.page} href={href(n.page)} aria-current={active === n.page ? "page" : undefined}>{n.label}</a>
              ))}
            </nav>
          )}
          {staff && (
            <span className="who">{ROLE_LABEL[staff.role]} · {staff.user}{" "}
              <button className="link" onClick={() => signIn(null)}>Switch user</button></span>
          )}
        </div>
      </header>
      <main className="content wide-content">
        {!staff ? <Login onLogin={signIn} />
          : allowed(staff.role, route.page) ? <Page route={route} login={staff} />
            : <p className="banner warn">The {ROLE_LABEL[staff.role].toLowerCase()} role cannot open this page.{" "}
              <a href={href(start)}>Go to your start page</a></p>}
      </main>
    </div>
  );
}
