import { t } from "../lib/i18n.js";
import { href } from "../lib/router.js";

export default function CitizenHome({ dict }) {
  return (
    <section>
      <h1>{t(dict, "home.title")}</h1>
      <p>{t(dict, "home.intro")}</p>
      <div className="entry-grid">
        <a className="entry card" href={href("self-check")}>
          <h2>{t(dict, "nav.self_check")}</h2>
          <p>{t(dict, "home.self_check_desc")}</p>
        </a>
        <a className="entry card" href={href("track")}>
          <h2>{t(dict, "nav.track")}</h2>
          <p>{t(dict, "home.track_desc")}</p>
        </a>
      </div>
    </section>
  );
}
