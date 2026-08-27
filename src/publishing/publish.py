"""Publishing stage: build docs/ (the GitHub Pages source) from reports/.

Copies every generated report (HTML+PDF, both languages) and the shared Heebo font
from reports/ into docs/, and builds a chronological archive index.html per
language listing every report currently in the DB. The same index content is also
written back into reports/{he,en}/ for local convenience (so navigation links work
when opening report files directly, without going through docs/). docs/index.html
(the site root) is a separate render of the Hebrew index with its relative paths
adjusted for living one level up - not a byte-identical copy, since the normal
he/en index content's links would not resolve correctly from the root.
One-shot run - no --force, always overwrites (read-only from DB, no API cost),
same convention as render.py.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.common.about_content import CONTENT, render_sections_html
from src.common.db import (
    get_all_reports,
    get_connection,
    get_geo_tags_for_section,
    get_report_sections_for_date,
    get_section_articles,
    init_db,
)
from src.common.geo_taxonomy import CONFLICT_ZONE_LABELS, COUNTRY_LIST, COUNTRY_TO_REGION
from src.reporting.render import (
    CATEGORY_LABELS,
    LANG_LABEL,
    NEWSPAPER_DISPLAY_NAMES,
    OTHER_LANG,
    build_nav_html,
    category_css,
    esc,
    format_date_en,
    format_date_he,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
FONT_SOURCE_PATH = REPORTS_DIR / "assets" / "fonts" / "Heebo-Variable.ttf"
LOGO_SOURCE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "assets" / "MS_Logo.png"
MAP_SOURCE_PATH = Path(__file__).resolve().parent / "assets" / "map" / "world.svg"
MANIFEST_RELATIVE_PATH = Path("assets") / "data" / "manifest.json"


def build_index_html(
    entries: list[tuple[str, list[str]]],
    lang: str,
    report_link_prefix: str,
    other_lang_href: str,
    font_relative_path: str,
) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    page_title = "כל הדוחות - גאופוליטיקה יומי" if is_he else "All Reports - Daily Geopolitics"
    eyebrow = "גאופוליטיקה יומי" if is_he else "Daily Geopolitics"
    heading = "כל הדוחות" if is_he else "All Reports"

    cards = []
    for report_date, sources in entries:
        formatted = format_date_he(report_date) if is_he else format_date_en(report_date)
        href = f"{report_link_prefix}report_{report_date}_{lang}.html"
        sources_str = ", ".join(esc(NEWSPAPER_DISPLAY_NAMES.get(s, s)) for s in sources)
        cards.append(f"""
      <a class="archive-card" href="{esc(href)}">
        <span class="archive-date">{esc(formatted)}</span>
        <span class="archive-sources">{sources_str}</span>
      </a>""")
    cards_html = "\n".join(cards)

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
<style>
  @font-face {{
    font-family: "Heebo";
    src: url("{font_relative_path}") format("truetype-variations");
    font-weight: 100 900;
  }}

  :root {{
    --bg: #f3efe8;
    --bg-elevated: #fffdfa;
    --text: #221f1b;
    --text-muted: #6d675e;
    --border: #e4ddd0;
    --masthead-accent: #7a2e2a;
  }}

  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #16140f;
      --bg-elevated: #211e18;
      --text: #ece7dd;
      --text-muted: #a89f91;
      --border: #3a352b;
      --masthead-accent: #d68b86;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #16140f;
    --bg-elevated: #211e18;
    --text: #ece7dd;
    --text-muted: #a89f91;
    --border: #3a352b;
    --masthead-accent: #d68b86;
  }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "Heebo", system-ui, sans-serif;
    line-height: 1.7;
  }}

  .top-nav {{
    max-width: 44rem;
    margin: 0 auto;
    padding: 0.65rem 1.5rem;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    font-size: 0.82rem;
    border-bottom: 1px solid var(--border);
  }}
  .top-nav-link {{
    color: var(--text-muted);
    text-decoration: none;
    font-weight: 500;
  }}
  .top-nav-link:hover {{
    color: var(--masthead-accent);
    text-decoration: underline;
  }}

  .masthead {{
    background: var(--bg-elevated);
    border-bottom: 3px solid var(--masthead-accent);
    padding: 2.75rem 1.5rem 2.25rem;
  }}
  .masthead-inner {{ max-width: 44rem; margin: 0 auto; }}
  .eyebrow {{
    margin: 0 0 .5rem;
    font-size: .85rem;
    font-weight: 600;
    letter-spacing: .04em;
    color: var(--masthead-accent);
    text-transform: uppercase;
  }}
  .report-title {{ margin: 0; font-size: 2.1rem; font-weight: 800; letter-spacing: -0.01em; }}

  .archive-list {{
    max-width: 44rem;
    margin: 0 auto;
    padding: 2.25rem 1.5rem 4rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }}

  .archive-card {{
    display: flex;
    flex-direction: column;
    gap: .35rem;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: .9rem;
    padding: 1.1rem 1.4rem;
    text-decoration: none;
    color: inherit;
  }}
  .archive-card:hover {{ border-color: var(--masthead-accent); }}
  .archive-date {{ font-size: 1.1rem; font-weight: 700; }}
  .archive-sources {{ font-size: .82rem; color: var(--text-muted); }}
</style>
</head>
<body>
  <nav class="top-nav">
    <a class="top-nav-link" href="{esc(other_lang_href)}">{esc(LANG_LABEL[OTHER_LANG[lang]])}</a>
  </nav>
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(eyebrow)}</p>
      <h1 class="report-title">{esc(heading)}</h1>
    </div>
  </header>
  <main class="archive-list">
{cards_html}
  </main>
</body>
</html>
"""


def build_about_html(lang: str) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    other = OTHER_LANG[lang]
    content = CONTENT[lang]

    page_title = "אודות הפרויקט - גאופוליטיקה יומי" if is_he else "About the Project - Daily Geopolitics"
    eyebrow = "גאופוליטיקה יומי" if is_he else "Daily Geopolitics"
    heading = "אודות הפרויקט" if is_he else "About the Project"

    sections_html = render_sections_html(content["sections"])

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
<style>
  @font-face {{
    font-family: "Heebo";
    src: url("../assets/fonts/Heebo-Variable.ttf") format("truetype-variations");
    font-weight: 100 900;
  }}

  :root {{
    --bg: #f3efe8;
    --bg-elevated: #fffdfa;
    --text: #221f1b;
    --text-muted: #6d675e;
    --border: #e4ddd0;
    --masthead-accent: #7a2e2a;
  }}

  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #16140f;
      --bg-elevated: #211e18;
      --text: #ece7dd;
      --text-muted: #a89f91;
      --border: #3a352b;
      --masthead-accent: #d68b86;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #16140f;
    --bg-elevated: #211e18;
    --text: #ece7dd;
    --text-muted: #a89f91;
    --border: #3a352b;
    --masthead-accent: #d68b86;
  }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "Heebo", system-ui, sans-serif;
    line-height: 1.7;
  }}

  .top-nav {{
    max-width: 44rem;
    margin: 0 auto;
    padding: 0.65rem 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.82rem;
    border-bottom: 1px solid var(--border);
  }}
  .top-nav-link {{
    color: var(--text-muted);
    text-decoration: none;
    font-weight: 500;
  }}
  .top-nav-link:hover {{
    color: var(--masthead-accent);
    text-decoration: underline;
  }}

  .masthead {{
    background: var(--bg-elevated);
    border-bottom: 3px solid var(--masthead-accent);
    padding: 2.75rem 1.5rem 2.25rem;
  }}
  .masthead-inner {{ max-width: 44rem; margin: 0 auto; }}
  .eyebrow {{
    margin: 0 0 .5rem;
    font-size: .85rem;
    font-weight: 600;
    letter-spacing: .04em;
    color: var(--masthead-accent);
    text-transform: uppercase;
  }}
  .report-title {{ margin: 0; font-size: 2.1rem; font-weight: 800; letter-spacing: -0.01em; }}

  .about-body {{ max-width: 44rem; margin: 0 auto; padding: 2.25rem 1.5rem 4rem; }}

  .about-intro-title {{ margin: 0 0 .75rem; font-size: 1.6rem; font-weight: 800; letter-spacing: -0.01em; }}
  .about-intro-subtitle {{ margin: 0 0 2rem; font-size: 1rem; font-style: italic; color: var(--text-muted); }}

  .about-content p {{ margin: 0 0 1.1rem; font-size: 1rem; }}
  .about-content h2 {{
    display: flex;
    align-items: center;
    gap: .9rem;
    margin: 1.9rem 0 1.1rem;
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--masthead-accent);
    white-space: nowrap;
  }}
  .about-content h2::after {{
    content: "";
    flex: 1;
    height: 1px;
    background: var(--border);
  }}
  .about-content ul {{ margin: 0 0 1.1rem; padding-inline-start: 1.4rem; }}
  .about-content ul li {{ margin-bottom: .6rem; font-size: 1rem; }}

  .about-author {{
    margin-top: 2.5rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: .9rem;
    padding: 1.1rem 1.4rem;
  }}
  .about-author img {{ height: 56px; width: auto; flex: 0 0 auto; }}
  .about-author-name {{ margin: 0; font-weight: 800; }}
  .about-author-role {{ margin: 0; font-size: .85rem; color: var(--text-muted); }}
</style>
</head>
<body>
{build_nav_html("archive.html", f"../{other}/about.html", lang)}
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(eyebrow)}</p>
      <h1 class="report-title">{esc(heading)}</h1>
    </div>
  </header>
  <main class="about-body">
    <h2 class="about-intro-title">{content['title']}</h2>
    <p class="about-intro-subtitle">{content['subtitle']}</p>
    <div class="about-content">
{sections_html}
    </div>
    <div class="about-author">
      <img src="../assets/images/MS_Logo.png" alt="">
      <div>
        <p class="about-author-name">{esc(content['identity_name'])}</p>
        <p class="about-author-role">{esc(content['identity_role'])}</p>
      </div>
    </div>
  </main>
</body>
</html>
"""


# Plain (non f-string) template so JS/CSS braces don't need doubling - __TOKEN__
# placeholders are substituted with .replace() in build_homepage_html() instead.
_HOMEPAGE_JS_TEMPLATE = """
(function () {
  var LANG = "__LANG__";
  var PREFIX = "__PREFIX__";

  fetch(PREFIX + "assets/data/manifest.json")
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function (err) { console.error("Failed to load manifest.json", err); });

  function init(manifest) {
    renderMap(manifest);
    renderTimeline(manifest);
    renderLatestCard(manifest);
    if (manifest.latest_date) {
      selectDate(manifest, manifest.latest_date);
    }
  }

  function hrefFor(section) {
    var raw = LANG === "he" ? section.href_he : section.href_en;
    return PREFIX + raw;
  }

  function topicFor(section) {
    return LANG === "he" ? section.topic_he : section.topic_en;
  }

  function renderMap(manifest) {
    var svg = document.getElementById("world-map");
    if (!svg) return;
    var candidates = svg.querySelectorAll("[id]");
    candidates.forEach(function (el) {
      if (el.id.length !== 2) return;
      var code = el.id.toUpperCase();
      var country = manifest.countries[code];
      if (!country) return;
      el.classList.add("has-coverage");
      var titleEl = el.querySelector("title");
      if (titleEl) {
        titleEl.textContent = LANG === "he" ? country.name_he : country.name_en;
      }
      el.addEventListener("click", function () {
        selectCountry(manifest, code);
      });
    });
  }

  function renderTimeline(manifest) {
    var track = document.getElementById("timeline-track");
    if (!track) return;
    var dates = Object.keys(manifest.dates).sort();
    var maxCount = 0;
    dates.forEach(function (d) {
      maxCount = Math.max(maxCount, manifest.dates[d].section_ids.length);
    });
    dates.forEach(function (d) {
      var count = manifest.dates[d].section_ids.length;
      var intensity = maxCount ? count / maxCount : 0;
      var cell = document.createElement("div");
      cell.className = "timeline-cell";
      cell.dataset.date = d;
      var pct = Math.round(20 + intensity * 60);
      cell.style.background = "color-mix(in srgb, var(--masthead-accent) " + pct + "%, var(--bg-elevated))";
      cell.textContent = formatShortDate(d);
      cell.addEventListener("click", function () {
        selectDate(manifest, d);
      });
      track.appendChild(cell);
    });
  }

  function renderLatestCard(manifest) {
    var card = document.getElementById("latest-card");
    if (!card || !manifest.latest_date) return;
    var dateInfo = manifest.dates[manifest.latest_date];
    var firstSectionId = dateInfo.section_ids[0];
    var section = firstSectionId !== undefined ? manifest.sections[firstSectionId] : null;

    var link = document.createElement("a");
    link.href = section ? hrefFor(section) : "#";

    var dateEl = document.createElement("p");
    dateEl.className = "latest-card-date";
    dateEl.textContent = formatLongDate(manifest.latest_date);

    var sourcesEl = document.createElement("p");
    sourcesEl.className = "latest-card-sources";
    sourcesEl.textContent = dateInfo.sources.join(", ");

    var cta = document.createElement("p");
    cta.className = "latest-card-cta";
    cta.textContent = LANG === "he" ? "לדוח המלא ←" : "Full report →";

    link.appendChild(dateEl);
    link.appendChild(sourcesEl);
    link.appendChild(cta);
    card.appendChild(link);
  }

  function selectCountry(manifest, code) {
    clearSelection();
    var el = document.getElementById(code.toLowerCase());
    if (el) el.classList.add("is-selected");
    var country = manifest.countries[code];
    var name = LANG === "he" ? country.name_he : country.name_en;
    renderResults(manifest, country.section_ids, name);
  }

  function selectDate(manifest, date) {
    clearSelection();
    var cell = document.querySelector('.timeline-cell[data-date="' + date + '"]');
    if (cell) {
      cell.classList.add("is-selected");
      cell.scrollIntoView({ inline: "center", block: "nearest" });
    }
    renderResults(manifest, manifest.dates[date].section_ids, formatLongDate(date));
  }

  function clearSelection() {
    document.querySelectorAll(".is-selected").forEach(function (el) {
      el.classList.remove("is-selected");
    });
  }

  function renderResults(manifest, sectionIds, headingLabel) {
    var panel = document.getElementById("results-panel");
    if (!panel) return;
    panel.innerHTML = "";

    var heading = document.createElement("p");
    heading.className = "results-heading";
    heading.textContent = (LANG === "he" ? "תוצאות: " : "Results: ") + headingLabel;
    panel.appendChild(heading);

    sectionIds.forEach(function (id) {
      var section = manifest.sections[id];
      if (!section) return;

      var item = document.createElement("a");
      item.className = "result-item";
      item.href = hrefFor(section);
      item.dataset.category = section.category;

      var dot = document.createElement("span");
      dot.className = "category-dot";

      var label = document.createElement("span");
      label.className = "category-label";
      var catInfo = manifest.categories[section.category];
      label.textContent = catInfo ? (LANG === "he" ? catInfo.name_he : catInfo.name_en) : section.category;

      var topic = document.createElement("span");
      topic.className = "result-topic";
      topic.textContent = topicFor(section);

      item.appendChild(dot);
      item.appendChild(label);
      item.appendChild(topic);
      panel.appendChild(item);
    });
  }

  function formatShortDate(iso) {
    var parts = iso.split("-");
    return parts[2] + "." + parts[1];
  }

  var HE_MONTHS = ["ינואר","פברואר","מרץ","אפריל","מאי","יוני","יולי","אוגוסט","ספטמבר","אוקטובר","נובמבר","דצמבר"];
  var EN_MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];

  function formatLongDate(iso) {
    var parts = iso.split("-").map(Number);
    var day = parts[2];
    var month = parts[1] - 1;
    var year = parts[0];
    if (LANG === "he") {
      return day + " ב" + HE_MONTHS[month] + " " + year;
    }
    return EN_MONTHS[month] + " " + day + ", " + year;
  }
})();
"""


def build_homepage_html(lang: str, is_root: bool) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    other = OTHER_LANG[lang]
    content = CONTENT[lang]

    asset_prefix = "" if is_root else "../"
    other_lang_href = "en/index.html" if is_root else f"../{other}/index.html"
    about_href = "he/about.html" if is_root else "about.html"

    page_title = "גאופוליטיקה יומי" if is_he else "Daily Geopolitics"
    eyebrow = "גאופוליטיקה יומי" if is_he else "Daily Geopolitics"

    if is_he:
        story_text = (
            "בכל יום, עשרות עיתונים מספרים סיפור שונה על אותו עולם. רובנו קוראים זווית "
            "אחת - זו שכבר מוכרת לנו - ומחמיצים את השיחה השלמה שמתקיימת, במקביל, בין "
            "מבטים שונים על אותו אירוע. כאן אנו עוקבים אחרי כמה מהעיתונים המובילים "
            "בעולם, וממזגים אותם לתמונה אחת: לא כדי להכריע מי צודק, אלא כדי להאיר את "
            "זוויות המבט השונות."
        )
        story_link_label = "עוד על הפרויקט ←"
        map_title, timeline_title, latest_title = "מפה", "ציר זמן", "לפי טקסט"
        archive_link_label = "לארכיון המלא ←"
    else:
        story_text = (
            "Every day, dozens of newspapers tell a different story about the same "
            "world. Most of us read one angle - the one we already know - and miss "
            "the fuller conversation unfolding, at the same time, between different "
            "viewpoints on the same event. Here, we follow some of the world's "
            "leading newspapers and merge them into a single picture: not to decide "
            "who's right, but to illuminate the different points of view."
        )
        story_link_label = "More about the project →"
        map_title, timeline_title, latest_title = "Map", "Timeline", "By Text"
        archive_link_label = "Full archive →"

    map_svg = _load_map_svg_inline()
    js_code = (
        _HOMEPAGE_JS_TEMPLATE.replace("__LANG__", lang).replace("__PREFIX__", asset_prefix)
    )

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
<style>
  @font-face {{
    font-family: "Heebo";
    src: url("{asset_prefix}assets/fonts/Heebo-Variable.ttf") format("truetype-variations");
    font-weight: 100 900;
  }}

  {category_css()}

  :root {{
    --bg: #f3efe8;
    --bg-elevated: #fffdfa;
    --text: #221f1b;
    --text-muted: #6d675e;
    --border: #e4ddd0;
    --masthead-accent: #7a2e2a;
  }}

  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #16140f;
      --bg-elevated: #211e18;
      --text: #ece7dd;
      --text-muted: #a89f91;
      --border: #3a352b;
      --masthead-accent: #d68b86;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #16140f;
    --bg-elevated: #211e18;
    --text: #ece7dd;
    --text-muted: #a89f91;
    --border: #3a352b;
    --masthead-accent: #d68b86;
  }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "Heebo", system-ui, sans-serif;
    line-height: 1.7;
  }}

  .home-top-bar {{
    max-width: 60rem;
    margin: 0 auto;
    padding: 0.65rem 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border);
  }}
  .home-logo {{ height: 32px; width: auto; display: block; }}
  .home-top-bar a {{
    color: var(--text-muted);
    text-decoration: none;
    font-weight: 500;
    font-size: .82rem;
  }}
  .home-top-bar a:hover {{ color: var(--masthead-accent); text-decoration: underline; }}

  .masthead {{
    background: var(--bg-elevated);
    border-bottom: 3px solid var(--masthead-accent);
    padding: 2.75rem 1.5rem 2.25rem;
  }}
  .masthead-inner {{ max-width: 44rem; margin: 0 auto; }}
  .eyebrow {{
    margin: 0 0 .5rem;
    font-size: .85rem;
    font-weight: 600;
    letter-spacing: .04em;
    color: var(--masthead-accent);
    text-transform: uppercase;
  }}
  .home-title {{ margin: 0 0 1.25rem; font-size: 2.1rem; font-weight: 800; letter-spacing: -0.01em; }}
  .home-story {{ margin: 0; font-size: 1rem; }}
  .home-story-link {{ font-weight: 600; color: var(--masthead-accent); text-decoration: none; white-space: nowrap; }}
  .home-story-link:hover {{ text-decoration: underline; }}

  .home-main {{ max-width: 60rem; margin: 0 auto; padding: 2.25rem 1.5rem 4rem; }}

  .home-grid {{
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1.25rem;
    margin-bottom: 2rem;
  }}
  @media (max-width: 860px) {{
    .home-grid {{ grid-template-columns: minmax(0, 1fr); }}
  }}

  .home-module {{
    min-width: 0;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: .9rem;
    padding: 1.1rem 1.3rem;
    display: flex;
    flex-direction: column;
    min-height: 260px;
  }}
  .module-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: .85rem; }}
  .module-title {{ margin: 0; font-size: 1rem; font-weight: 700; }}
  .module-link {{ font-size: .78rem; color: var(--masthead-accent); text-decoration: none; white-space: nowrap; }}
  .module-link:hover {{ text-decoration: underline; }}

  .map-module svg#world-map {{ width: 100%; height: auto; display: block; }}
  .oceanxx {{ fill: var(--bg); stroke: var(--border); stroke-width: 0.5; }}
  .landxx, .limitxx, .antxx {{ fill: var(--border); stroke: var(--bg-elevated); stroke-width: 0.5; fill-rule: evenodd; }}
  .circlexx, .subxx, .noxx, .unxx {{ opacity: 0; }}
  .landxx.has-coverage {{ fill: var(--masthead-accent); cursor: pointer; }}
  .landxx.has-coverage:hover {{ opacity: .8; }}
  .landxx.is-selected {{ stroke: var(--masthead-accent); stroke-width: 2; }}

  .timeline-track {{
    display: flex;
    gap: .5rem;
    overflow-x: auto;
    padding-bottom: .4rem;
    flex: 1;
    align-items: flex-end;
  }}
  .timeline-cell {{
    flex: 0 0 auto;
    min-width: 52px;
    padding: .6rem .5rem .5rem;
    border-radius: .5rem;
    text-align: center;
    cursor: pointer;
    border: 1px solid var(--border);
    font-size: .72rem;
    color: var(--text);
  }}
  .timeline-cell.is-selected {{ border-color: var(--masthead-accent); border-width: 2px; font-weight: 700; }}

  .latest-card {{ display: flex; flex-direction: column; gap: .5rem; flex: 1; justify-content: center; }}
  .latest-card a {{ text-decoration: none; color: inherit; }}
  .latest-card-date {{ margin: 0; font-size: 1.05rem; font-weight: 700; }}
  .latest-card-sources {{ margin: 0; font-size: .8rem; color: var(--text-muted); }}
  .latest-card-cta {{ margin: .5rem 0 0; font-size: .85rem; font-weight: 600; color: var(--masthead-accent); }}

  .results-heading {{ font-size: 1.05rem; font-weight: 700; margin: 0 0 1rem; }}
  .result-item {{
    display: flex;
    align-items: center;
    gap: .75rem;
    padding: .9rem 1.1rem;
    margin-bottom: .6rem;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-inline-start: 4px solid var(--cat-color, var(--border));
    border-radius: .7rem;
    text-decoration: none;
    color: inherit;
  }}
  .result-item:hover {{ border-color: var(--masthead-accent); }}
  .category-dot {{ width: .5rem; height: .5rem; border-radius: 50%; background: var(--cat-color); flex-shrink: 0; }}
  .category-label {{
    font-size: .72rem;
    font-weight: 600;
    color: var(--cat-color);
    background: var(--cat-bg);
    padding: .15rem .5rem;
    border-radius: 999px;
    white-space: nowrap;
  }}
  .result-topic {{ font-size: .92rem; }}
</style>
</head>
<body>
  <div class="home-top-bar">
    <img class="home-logo" src="{asset_prefix}assets/images/MS_Logo.png" alt="">
    <a href="{esc(other_lang_href)}">{esc(LANG_LABEL[other])}</a>
  </div>
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(eyebrow)}</p>
      <h1 class="home-title">{content['title']}</h1>
      <p class="home-story">{story_text} <a class="home-story-link" href="{esc(about_href)}">{esc(story_link_label)}</a></p>
    </div>
  </header>
  <main class="home-main">
    <div class="home-grid">
      <section class="home-module map-module">
        <div class="module-header">
          <h2 class="module-title">{esc(map_title)}</h2>
        </div>
        {map_svg}
      </section>
      <section class="home-module timeline-module">
        <div class="module-header">
          <h2 class="module-title">{esc(timeline_title)}</h2>
          <a class="module-link" href="archive.html">{esc(archive_link_label)}</a>
        </div>
        <div class="timeline-track" id="timeline-track"></div>
      </section>
      <section class="home-module latest-module">
        <div class="module-header">
          <h2 class="module-title">{esc(latest_title)}</h2>
        </div>
        <div class="latest-card" id="latest-card"></div>
      </section>
    </div>
    <div class="results-panel" id="results-panel"></div>
  </main>
  <script>{js_code}</script>
</body>
</html>
"""


def _copy_reports_to_docs() -> None:
    for lang in ("he", "en"):
        src_dir = REPORTS_DIR / lang
        dst_dir = DOCS_DIR / lang
        dst_dir.mkdir(parents=True, exist_ok=True)
        for pattern in ("report_*.html", "report_*.pdf"):
            for f in src_dir.glob(pattern):
                shutil.copy2(f, dst_dir / f.name)


def _copy_font() -> None:
    dest = DOCS_DIR / "assets" / "fonts" / FONT_SOURCE_PATH.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FONT_SOURCE_PATH, dest)


def _copy_logo() -> None:
    for base_dir in (DOCS_DIR, REPORTS_DIR):
        dest = base_dir / "assets" / "images" / LOGO_SOURCE_PATH.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LOGO_SOURCE_PATH, dest)


def _copy_map() -> None:
    for base_dir in (DOCS_DIR, REPORTS_DIR):
        dest = base_dir / "assets" / "map" / MAP_SOURCE_PATH.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MAP_SOURCE_PATH, dest)


def _load_map_svg_inline() -> str:
    """Load world.svg (see assets/map/NOTICE.txt for source/license) stripped of
    XML prolog and editor-only (Inkscape/Sodipodi) markup, ready to embed directly
    in a page's <body> - required so JS can select/color individual <g id="xx">
    country elements, which an <img>-referenced external SVG would not allow.
    """
    raw = MAP_SOURCE_PATH.read_text(encoding="utf-8")
    if raw.startswith("<?xml"):
        raw = raw.split("\n", 1)[1]
    raw = re.sub(r"\s*<sodipodi:namedview.*?/>\s*\n", "\n", raw, count=1, flags=re.DOTALL)
    raw = re.sub(r'\s*<style\s+id="style_css_sheet".*?</style>\s*\n', "\n", raw, count=1, flags=re.DOTALL)
    raw = re.sub(
        r'<svg\s+version="1\.1"\s+id="svg2985".*?xmlns:svg="http://www\.w3\.org/2000/svg">',
        '<svg id="world-map" viewBox="-35.8 80 2776 1163.1" xmlns="http://www.w3.org/2000/svg">',
        raw,
        count=1,
        flags=re.DOTALL,
    )
    return raw


def build_manifest(conn, entries: list[tuple[str, list[str]]]) -> dict:
    """Build the static geo/timeline manifest consumed by the future homepage.

    `sections` is the source of truth; `countries`/`conflict_zones`/`dates` are
    just section_id indexes over it (only entries that actually have at least
    one section - an index has no use for an empty row), never a copy of the
    full closed taxonomy or of comparison_text.
    """
    sections: dict[int, dict] = {}
    countries_index: dict[str, list[int]] = {}
    conflict_zones_index: dict[str, list[int]] = {}
    dates_index: dict[str, dict] = {}

    for report_date, sources in entries:
        section_ids_for_date = []
        for s in get_report_sections_for_date(conn, report_date):
            section_id = s["id"]
            section_ids_for_date.append(section_id)

            newspapers = [r["newspaper"] for r in get_section_articles(conn, section_id)]
            geo = get_geo_tags_for_section(conn, section_id)

            sections[section_id] = {
                "date": report_date,
                "category": s["category"],
                "topic_he": s["topic_label_he"],
                "topic_en": s["topic_label_en"],
                "sources": newspapers,
                "countries": geo["countries"],
                "conflict_zones": geo["conflict_zones"],
                "href_he": f"he/report_{report_date}_he.html#section-{section_id}",
                "href_en": f"en/report_{report_date}_en.html#section-{section_id}",
            }

            for code in geo["countries"]:
                countries_index.setdefault(code, []).append(section_id)
            for zone in geo["conflict_zones"]:
                conflict_zones_index.setdefault(zone, []).append(section_id)

        dates_index[report_date] = {"sources": sources, "section_ids": section_ids_for_date}

    countries_out = {
        code: {
            "name_he": COUNTRY_LIST[code]["name_he"],
            "name_en": COUNTRY_LIST[code]["name_en"],
            "region": COUNTRY_TO_REGION[code],
            "section_ids": ids,
        }
        for code, ids in countries_index.items()
    }
    conflict_zones_out = {
        zone: {
            "name_he": CONFLICT_ZONE_LABELS[zone]["name_he"],
            "name_en": CONFLICT_ZONE_LABELS[zone]["name_en"],
            "section_ids": ids,
        }
        for zone, ids in conflict_zones_index.items()
    }

    categories_out = {
        code: {"name_he": labels["he"], "name_en": labels["en"]} for code, labels in CATEGORY_LABELS.items()
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_date": entries[0][0] if entries else None,
        "sections": sections,
        "countries": countries_out,
        "conflict_zones": conflict_zones_out,
        "dates": dates_index,
        "categories": categories_out,
    }


def _write_manifest(manifest: dict) -> None:
    manifest_json = json.dumps(manifest, ensure_ascii=False)
    for base_dir in (DOCS_DIR, REPORTS_DIR):
        dest = base_dir / MANIFEST_RELATIVE_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(manifest_json, encoding="utf-8")


def run() -> None:
    conn = get_connection()
    init_db(conn)
    entries = [(r["report_date"], json.loads(r["sources_included"])) for r in get_all_reports(conn)]

    if not entries:
        conn.close()
        print("No reports found in DB - nothing to publish.")
        return

    _copy_font()
    _copy_logo()
    _copy_map()
    _copy_reports_to_docs()

    for lang in ("he", "en"):
        archive_html = build_index_html(
            entries,
            lang,
            report_link_prefix="",
            other_lang_href=f"../{OTHER_LANG[lang]}/archive.html",
            font_relative_path="../assets/fonts/Heebo-Variable.ttf",
        )
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "archive.html").write_text(archive_html, encoding="utf-8")
        print(f"  wrote archive.html for '{lang}' ({len(entries)} report date(s))")

        about_html = build_about_html(lang)
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "about.html").write_text(about_html, encoding="utf-8")
        print(f"  wrote about.html for '{lang}'")

        homepage_html = build_homepage_html(lang, is_root=False)
        (DOCS_DIR / lang / "index.html").write_text(homepage_html, encoding="utf-8")
        print(f"  wrote index.html (homepage) for '{lang}'")

    root_archive_html = build_index_html(
        entries,
        "he",
        report_link_prefix="he/",
        other_lang_href="en/archive.html",
        font_relative_path="assets/fonts/Heebo-Variable.ttf",
    )
    (DOCS_DIR / "archive.html").write_text(root_archive_html, encoding="utf-8")
    print(f"  wrote {DOCS_DIR / 'archive.html'} (root, Hebrew default)")

    root_homepage_html = build_homepage_html("he", is_root=True)
    (DOCS_DIR / "index.html").write_text(root_homepage_html, encoding="utf-8")
    print(f"  wrote {DOCS_DIR / 'index.html'} (root homepage, Hebrew default)")

    manifest = build_manifest(conn, entries)
    conn.close()
    _write_manifest(manifest)
    print(f"  wrote manifest.json ({len(manifest['sections'])} section(s), {len(manifest['countries'])} countrie(s))")

    print(f"\nPublish complete: {len(entries)} report date(s) -> {DOCS_DIR}")


if __name__ == "__main__":
    run()
