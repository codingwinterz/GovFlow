import { useEffect, useState } from "react";
import { getLogin, setLogin } from "./api.js";
import { href, parseRoute } from "./lib/router.js";
import Login from "./pages/Login.jsx";
import Queue from "./pages/Queue.jsx";
import CasePage from "./pages/CasePage.jsx";
import Audit from "./pages/Audit.jsx";
import Analytics from "./pages/Analytics.jsx";
import Intake from "./pages/Intake.jsx";
import StatusLookup from "./pages/StatusLookup.jsx";
import Track from "./pages/Track.jsx";
import SelfCheck from "./pages/SelfCheck.jsx";
import Simulator from "./pages/Simulator.jsx";

function useRoute() {
  const [route, setRoute] = useState(parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

function Page({ route, login }) {
  if (login.role === "citizen") return <Track />;   // citizens see only the public status page
  if (login.role === "admin") return <Simulator />;  // admins: rule simulator only
  switch (route.page) {
    case "queue": return <Queue />;
    case "case": return <CasePage id={route.id} login={login} />;
    case "audit": return login.role === "officer" ? <Audit id={route.id} /> : <p>Only officers can view the audit trail.</p>;
    case "analytics": return <Analytics />;
    case "intake": return <Intake />;
    case "status": return <StatusLookup />;
    case "simulator": return login.role === "officer" ? <Simulator /> : <p>Only officers and admins can use the simulator.</p>;
    default: return <p>Page not found. <a href={href("queue")}>Back to the queue</a></p>;
  }
}

export default function App() {
  const route = useRoute();
  const [login, setLoginState] = useState(getLogin());
  const signIn = (value) => { setLogin(value); setLoginState(value); };

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href={href("queue")}>GovFlow</a>
        <span className="badge demo" title="Identity comes from X-Role / X-User headers; not real authentication">
          DEMO MODE
        </span>
        {login && !["citizen", "admin"].includes(login.role) && (
          <nav>
            <a href={href("queue")}>Queue</a>
            <a href={href("intake")}>Intake</a>
            <a href={href("analytics")}>Analytics</a>
            <a href={href("status")}>Status lookup</a>
            {login.role === "officer" && <a href={href("simulator")}>Simulator</a>}
          </nav>
        )}
        <a href={href("track")}>Track an application</a>
        <a href={href("self-check")}>Check before you apply</a>
        {login && (
          <span className="who">
            {login.role}: {login.user} <button className="link" onClick={() => signIn(null)}>switch user</button>
          </span>
        )}
      </header>
      <main>
        {route.page === "track" ? <Track /> : route.page === "self-check" ? <SelfCheck />
          : login ? <Page route={route} login={login} /> : <Login onLogin={signIn} />}
      </main>
    </div>
  );
}
