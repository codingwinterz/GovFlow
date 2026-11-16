import { useEffect, useState } from "react";
import { parseRoute } from "./lib/router.js";
import Landing from "./shells/Landing.jsx";
import CitizenShell from "./shells/CitizenShell.jsx";
import OfficerShell from "./shells/OfficerShell.jsx";

function useRoute() {
  const [route, setRoute] = useState(parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

// The route decides the shell. The citizen shell never renders officer navigation, and vice versa.
export default function App() {
  const route = useRoute();
  if (route.shell === "citizen") return <CitizenShell route={route} />;
  if (route.shell === "officer") return <OfficerShell route={route} />;
  return <Landing notFound={route.page === "notfound"} />;
}
