import { useState } from "react";
import { DICTS, htmlLang } from "../i18n/index.js";
import { t } from "../lib/i18n.js";
import { CITIZEN_NAV } from "../lib/nav.js";
import { href } from "../lib/router.js";
import CitizenHome from "../pages/CitizenHome.jsx";
import SelfCheck from "../pages/SelfCheck.jsx";
import Track from "../pages/Track.jsx";

// Public pages only. No sign-in, no role headers, no officer navigation.
function readLang() {
  try { return localStorage.getItem("govflow-lang") || "en"; } catch { return "en"; }
}

export default function CitizenShell({ route }) {
  const [lang, setLang] = useState(readLang());
  const dict = DICTS[lang] || DICTS.en;
  const choose = (value) => {
    setLang(value);
    try { localStorage.setItem("govflow-lang", value); } catch { /* per-visit only */ }
  };
  const Page = { "citizen-home": CitizenHome, "self-check": SelfCheck, track: Track }[route.page];

  return (
    <div className="shell citizen" lang={htmlLang(lang)}>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href={href("citizen-home")}>GovFlow <span className="brand-sub">{t(dict, "nav.citizen_services")}</span></a>
          <nav aria-label={t(dict, "nav.citizen_services")}>
            {CITIZEN_NAV.map((n) => (
              <a key={n.page} href={href(n.page)} aria-current={route.page === n.page ? "page" : undefined}>{t(dict, n.key)}</a>
            ))}
          </nav>
          <label className="lang">{t(dict, "language.label")}
            <select value={lang} onChange={(e) => choose(e.target.value)}>
              {Object.entries(DICTS).map(([k, d]) => <option key={k} value={k}>{d["_meta.language"]}</option>)}
            </select>
          </label>
        </div>
      </header>
      <main className="content narrow-content">
        <Page dict={dict} />
        <footer className="review-note">
          {lang !== "en" && <p>{t(dict, "footer.review")}</p>}
          <p>{t(DICTS.en, "footer.review")}</p>
        </footer>
      </main>
    </div>
  );
}
