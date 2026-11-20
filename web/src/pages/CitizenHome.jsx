import { t } from "../lib/i18n.js";
import { href } from "../lib/router.js";

// Two large choices, one sentence each, and three steps on how it works.
export default function CitizenHome({ dict }) {
  return (
    <section>
      <h1>{t(dict, "home.title")}</h1>
      <div className="choice-grid">
        <a className="choice" href={href("self-check")}>
          <h2>{t(dict, "nav.self_check")} <span aria-hidden="true">→</span></h2>
          <p>{t(dict, "home.check_short")}</p>
        </a>
        <a className="choice" href={href("track")}>
          <h2>{t(dict, "nav.track")} <span aria-hidden="true">→</span></h2>
          <p>{t(dict, "home.track_short")}</p>
        </a>
      </div>
      <section className="how" aria-labelledby="how-heading">
        <h2 id="how-heading">{t(dict, "home.how_title")}</h2>
        <ol>
          <li>{t(dict, "home.how_1")}</li>
          <li>{t(dict, "home.how_2")}</li>
          <li>{t(dict, "home.how_3")}</li>
        </ol>
      </section>
    </section>
  );
}
