"""Publishing stage: build docs/ (the GitHub Pages source) from reports/.

Copies every generated report (HTML+PDF, both languages) and the shared site font
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
from src.common.geo_taxonomy import CONFLICT_ZONE_LABELS, COUNTRY_LIST, COUNTRY_TO_REGION, REGION_LABELS
from src.reporting.render import (
    ALL_LANGS,
    CATEGORY_LABELS,
    CONTACT_EMAIL,
    CONTACT_LABEL,
    FILTER_LABEL,
    FAVICON_FILENAMES,
    FONT_FAMILY,
    FONT_FILENAME,
    FORMAT_DATE,
    LANG_LABEL,
    LOGO_LINK_LABEL,
    NEWSPAPER_DISPLAY_NAMES,
    OTHER_LANG,
    build_footer_html,
    build_nav_html,
    category_css,
    esc,
    favicon_links_html,
    font_face_css,
    footer_hrefs_for,
    other_langs,
    section_coverage,
    shared_chrome_css,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
FONT_SOURCE_PATH = REPORTS_DIR / "assets" / "fonts" / FONT_FILENAME
LOGO_SOURCE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "assets" / "MS_Logo.png"
FAVICON_SOURCE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "assets"
MAP_SOURCE_PATH = Path(__file__).resolve().parent / "assets" / "map" / "world.svg"
MANIFEST_RELATIVE_PATH = Path("assets") / "data" / "manifest.json"
CONTENT_DIR_RELATIVE = Path("assets") / "data" / "content"


def build_index_html(
    entries: list[tuple[str, list[str]]],
    lang: str,
    report_link_prefix: str,
    lang_hrefs: dict[str, str],
    font_relative_path: str,
    asset_prefix: str,
    accessibility_href: str = "accessibility.html",
    terms_href: str = "terms.html",
    filter_href: str = "filter.html",
) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    page_title = {
        "he": "כל הדוחות - גאופוליטיקה יומי", "en": "All Reports - Daily Geopolitics",
        "de": "Alle Berichte - Tägliche Geopolitik",
    }[lang]
    eyebrow = {"he": "גאופוליטיקה יומי", "en": "Daily Geopolitics", "de": "Tägliche Geopolitik"}[lang]
    heading = {"he": "כל הדוחות", "en": "All Reports", "de": "Alle Berichte"}[lang]

    cards = []
    for report_date, sources in entries:
        formatted = FORMAT_DATE[lang](report_date)
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
{favicon_links_html(asset_prefix)}
<style>
  {font_face_css(font_relative_path)}

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
    font-family: "{FONT_FAMILY}", system-ui, sans-serif;
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
  .top-nav-logo-link {{ display: flex; align-items: center; }}
  .top-nav-logo {{ height: 56px; width: auto; display: block; }}
  .top-nav-links {{ display: flex; align-items: center; gap: 1.1rem; }}
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

  {shared_chrome_css()}
</style>
</head>
<body>
  <nav class="top-nav">
    <a class="top-nav-logo-link" href="{esc(asset_prefix)}index.html" aria-label="{esc(LOGO_LINK_LABEL[lang])}"><img class="top-nav-logo" src="{esc(asset_prefix)}assets/images/MS_Logo.png" alt=""></a>
    <div class="top-nav-links">
      <a class="top-nav-link" href="{esc(filter_href)}">{esc(FILTER_LABEL[lang])}</a>
      {"".join(f'<a class="top-nav-link" href="{esc(lang_hrefs[o])}">{esc(LANG_LABEL[o])}</a>' for o in other_langs(lang) if o in lang_hrefs)}
      <a class="top-nav-link" href="mailto:{CONTACT_EMAIL}">{esc(CONTACT_LABEL[lang])}</a>
    </div>
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
{build_footer_html(lang, accessibility_href, terms_href)}
</body>
</html>
"""


def build_about_html(lang: str) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    content = CONTENT[lang]

    page_title = {
        "he": "אודות הפרויקט - גאופוליטיקה יומי", "en": "About the Project - Daily Geopolitics",
        "de": "Über das Projekt - Tägliche Geopolitik",
    }[lang]
    eyebrow = {"he": "גאופוליטיקה יומי", "en": "Daily Geopolitics", "de": "Tägliche Geopolitik"}[lang]
    heading = {"he": "אודות הפרויקט", "en": "About the Project", "de": "Über das Projekt"}[lang]

    sections_html = render_sections_html(content["sections"])

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

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
    font-family: "{FONT_FAMILY}", system-ui, sans-serif;
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
  .top-nav-logo-link {{ display: flex; align-items: center; }}
  .top-nav-logo {{ height: 56px; width: auto; display: block; }}
  .top-nav-links {{ display: flex; align-items: center; gap: 1.1rem; }}
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
  .about-author img {{ height: 96px; width: auto; flex: 0 0 auto; }}
  .about-author-name {{ margin: 0; font-weight: 800; }}
  .about-author-role {{ margin: 0; font-size: .85rem; color: var(--text-muted); }}

  {shared_chrome_css()}
</style>
</head>
<body>
{build_nav_html("archive.html", {o: f"../{o}/about.html" for o in other_langs(lang)}, lang)}
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
{build_footer_html(lang, *footer_hrefs_for(lang))}
</body>
</html>
"""


# Shared by build_accessibility_html and build_terms_html - both are simple,
# static, single-column prose pages using the same masthead/body/footer shell
# as about.html, just without about.html's heading-per-section DSL (a single
# flat set of <h2>/<p> blocks doesn't need that machinery). Trilingual as of
# 2026-09-22 (de/accessibility.html and de/terms.html now exist for real).
def _build_static_page_html(
    lang: str, page_title: str, heading: str, body_html: str, other_lang_filename: str
) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    eyebrow = {"he": "גאופוליטיקה יומי", "en": "Daily Geopolitics", "de": "Tägliche Geopolitik"}[lang]

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

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
    font-family: "{FONT_FAMILY}", system-ui, sans-serif;
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
  .top-nav-logo-link {{ display: flex; align-items: center; }}
  .top-nav-logo {{ height: 56px; width: auto; display: block; }}
  .top-nav-links {{ display: flex; align-items: center; gap: 1.1rem; }}
  .top-nav-link {{ color: var(--text-muted); text-decoration: none; font-weight: 500; }}
  .top-nav-link:hover {{ color: var(--masthead-accent); text-decoration: underline; }}

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

  .static-body {{ max-width: 44rem; margin: 0 auto; padding: 2.25rem 1.5rem 4rem; }}
  .static-body h2 {{ margin: 1.9rem 0 1.1rem; font-size: 1.2rem; font-weight: 700; color: var(--masthead-accent); }}
  .static-body h2:first-child {{ margin-top: 0; }}
  .static-body p {{ margin: 0 0 1.1rem; font-size: 1rem; }}
  .static-body a {{ color: var(--masthead-accent); }}

  {shared_chrome_css()}
</style>
</head>
<body>
{build_nav_html("archive.html", {o: f"../{o}/{other_lang_filename}" for o in other_langs(lang)}, lang)}
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(eyebrow)}</p>
      <h1 class="report-title">{esc(heading)}</h1>
    </div>
  </header>
  <main class="static-body">
{body_html}
  </main>
{build_footer_html(lang)}
</body>
</html>
"""


# Contact address for accessibility issue reports - given directly by the site
# owner (2026-09-16), not invented; change here only at his explicit request.
ACCESSIBILITY_CONTACT_EMAIL = "meir@meirshemesh.com"


def build_accessibility_html(lang: str) -> str:
    if lang == "he":
        page_title = "הצהרת נגישות - גאופוליטיקה יומי"
        heading = "הצהרת נגישות"
        body_html = f"""
    <p>אתר זה שואף לעמוד בדרישות תקן ישראלי (ת"י) 5568 חלק 1, המבוסס על הנחיות
    WCAG 2.0 ברמת AA.</p>
    <h2>התאמות שבוצעו</h2>
    <p>טקסט חלופי לתמונות ולסמלים משמעותיים; ניגודיות צבעים נבדקה ותוקנה מול
    דרישת 4.5:1 עבור טקסט רגיל; ניווט מקלדת מלא לרוב הרכיבים האינטראקטיביים
    באתר (הרחבת/כיווץ נושאים, כפתור שיתוף, ניווט-קטגוריות דביק); מבנה כותרות
    היררכי תקין בכל עמודי האתר; תיוג SVG למפת העולם האינטראקטיבית (שם
    וסטטוס-כיסוי לכל מדינה).</p>
    <h2>מגבלה ידועה</h2>
    <p>ניווט מקלדת למפת העולם האינטראקטיבית (בחירת מדינה בלחיצה) טרם מומש
    במלואו - זוהי הרחבה עתידית.</p>
    <h2>יצירת קשר</h2>
    <p>נתקלתם בבעיית נגישות באתר? אנא כתבו אלינו:
    <a href="mailto:{ACCESSIBILITY_CONTACT_EMAIL}">{ACCESSIBILITY_CONTACT_EMAIL}</a></p>
    <p>עודכן לאחרונה: ספטמבר 2026.</p>"""
    elif lang == "de":
        page_title = "Barrierefreiheitserklärung - Tägliche Geopolitik"
        heading = "Barrierefreiheitserklärung"
        body_html = f"""
    <p>Diese Website strebt an, den israelischen Standard (IS) 5568 Teil 1 zu
    erfüllen, der auf den WCAG-2.0-Richtlinien der Stufe AA basiert.</p>
    <h2>Umgesetzte Maßnahmen</h2>
    <p>Alternativtext für bedeutungstragende Bilder und Symbole; Farbkontraste
    wurden geprüft und gegen die Anforderung von 4,5:1 für normalen Text
    korrigiert; vollständige Tastaturnavigation für die meisten interaktiven
    Elemente der Website (Ein-/Ausklappen von Themen, Teilen-Schaltfläche,
    fixierte Kategorienavigation); durchgehend korrekte, hierarchische
    Überschriftenstruktur auf jeder Seite; SVG-Auszeichnung der interaktiven
    Weltkarte (Name und Berichterstattungsstatus für jedes Land).</p>
    <h2>Bekannte Einschränkung</h2>
    <p>Die Tastaturnavigation für die interaktive Weltkarte (Länderauswahl per
    Klick) ist noch nicht vollständig umgesetzt - das ist eine geplante
    künftige Verbesserung.</p>
    <h2>Kontakt</h2>
    <p>Ein Barrierefreiheitsproblem auf dieser Website festgestellt? Bitte
    schreiben Sie uns:
    <a href="mailto:{ACCESSIBILITY_CONTACT_EMAIL}">{ACCESSIBILITY_CONTACT_EMAIL}</a></p>
    <p>Zuletzt aktualisiert: September 2026.</p>"""
    else:
        page_title = "Accessibility Statement - Daily Geopolitics"
        heading = "Accessibility Statement"
        body_html = f"""
    <p>This site aims to comply with Israeli Standard (IS) 5568 Part 1, based
    on WCAG 2.0 Level AA guidelines.</p>
    <h2>Accommodations made</h2>
    <p>Alternative text for meaningful images and icons; color contrast checked
    and corrected against the 4.5:1 requirement for normal text; full keyboard
    navigation for most of the site's interactive elements (expanding/
    collapsing topics, the share button, the sticky category nav); a properly
    hierarchical heading structure across every page; SVG tagging on the
    interactive world map (name and coverage status for each country).</p>
    <h2>Known limitation</h2>
    <p>Keyboard navigation for the interactive world map (selecting a country
    by click) is not yet fully implemented - this is a planned future
    improvement.</p>
    <h2>Contact us</h2>
    <p>Encountered an accessibility issue on this site? Please write to us:
    <a href="mailto:{ACCESSIBILITY_CONTACT_EMAIL}">{ACCESSIBILITY_CONTACT_EMAIL}</a></p>
    <p>Last updated: September 2026.</p>"""

    return _build_static_page_html(lang, page_title, heading, body_html, "accessibility.html")


def build_terms_html(lang: str) -> str:
    if lang == "he":
        page_title = "תנאי שימוש - גאופוליטיקה יומי"
        heading = "תנאי שימוש"
        body_html = """
    <h2>1. אופי התוכן</h2>
    <p>התוכן המוצג באתר, לרבות ניתוחים, השוואות בין מקורות, וסיכומים, מופק
    באמצעות מודל בינה מלאכותית, ואינו עובר אימות עובדתי עצמאי. אין להסתמך
    עליו כמקור בלעדי למידע מדויק, מלא, או עדכני.</p>
    <h2>2. אחריות</h2>
    <p>האתר ותכניו מסופקים כמות-שהם ("as-is"), ללא כל אחריות, מפורשת או
    משתמעת, לדיוק, שלמות, עדכניות, או התאמה למטרה מסוימת.</p>
    <h2>3. אחריות המשתמש</h2>
    <p>כל שימוש בתוכן האתר, לרבות הסתמכות על מסקנה, ציטוט, או נתון המופיעים
    בו, הוא באחריותו הבלעדית של המשתמש.</p>
    <h2>4. שינויים</h2>
    <p>בעל האתר רשאי לעדכן תנאים אלה מעת לעת ללא הודעה מוקדמת.</p>"""
    elif lang == "de":
        page_title = "Nutzungsbedingungen - Tägliche Geopolitik"
        heading = "Nutzungsbedingungen"
        body_html = """
    <h2>1. Art des Inhalts</h2>
    <p>Die auf dieser Website dargestellten Inhalte, einschließlich Analysen,
    quellenübergreifender Vergleiche und Zusammenfassungen, werden mittels
    eines Sprachmodells der künstlichen Intelligenz erzeugt und durchlaufen
    keine unabhängige Faktenprüfung. Sie sollten nicht als alleinige Quelle
    für genaue, vollständige oder aktuelle Informationen herangezogen
    werden.</p>
    <h2>2. Gewährleistungsausschluss</h2>
    <p>Die Website und ihre Inhalte werden „wie besehen" bereitgestellt, ohne
    jegliche ausdrückliche oder stillschweigende Gewährleistung hinsichtlich
    Genauigkeit, Vollständigkeit, Aktualität oder Eignung für einen
    bestimmten Zweck.</p>
    <h2>3. Verantwortung der Nutzerin bzw. des Nutzers</h2>
    <p>Jede Nutzung der Inhalte dieser Website, einschließlich des
    Vertrauens auf eine darin enthaltene Schlussfolgerung, ein Zitat oder
    eine Zahlenangabe, erfolgt in alleiniger Verantwortung der Nutzerin
    bzw. des Nutzers.</p>
    <h2>4. Änderungen</h2>
    <p>Der Betreiber der Website kann diese Bedingungen von Zeit zu Zeit
    ohne vorherige Ankündigung aktualisieren.</p>"""
    else:
        page_title = "Terms of Use - Daily Geopolitics"
        heading = "Terms of Use"
        body_html = """
    <h2>1. Nature of the content</h2>
    <p>The content on this site, including analyses, cross-source comparisons,
    and summaries, is generated using an artificial intelligence model and has
    not undergone independent fact-checking. It should not be relied upon as a
    sole source of accurate, complete, or current information.</p>
    <h2>2. No warranty</h2>
    <p>The site and its content are provided "as-is," without any warranty,
    express or implied, as to accuracy, completeness, currency, or fitness for
    a particular purpose.</p>
    <h2>3. User responsibility</h2>
    <p>Any use of the site's content, including reliance on any conclusion,
    quotation, or figure it presents, is the user's sole responsibility.</p>
    <h2>4. Changes</h2>
    <p>The site owner may update these terms from time to time without prior
    notice.</p>"""

    return _build_static_page_html(lang, page_title, heading, body_html, "terms.html")


FILTER_FORM_LABELS = {
    "category": {"he": "קטגוריה", "en": "Category", "de": "Kategorie"},
    "region": {"he": "אזור גיאוגרפי", "en": "Region", "de": "Region"},
    "conflict": {"he": "סכסוך פעיל", "en": "Active conflict", "de": "Aktiver Konflikt"},
    "daterange": {"he": "טווח תאריכים", "en": "Date range", "de": "Zeitraum"},
    "any": {"he": "הכל", "en": "Any", "de": "Alle"},
    "apply": {"he": "החל סינון", "en": "Apply filter", "de": "Filter anwenden"},
    "reset": {"he": "נקה הכל", "en": "Clear all", "de": "Alles zurücksetzen"},
    "close": {"he": "סגור", "en": "Close", "de": "Schließen"},
    "last7": {"he": "7 ימים אחרונים", "en": "Last 7 days", "de": "Letzte 7 Tage"},
    "last30": {"he": "30 יום אחרונים", "en": "Last 30 days", "de": "Letzte 30 Tage"},
    "thismonth": {"he": "החודש הנוכחי", "en": "This month", "de": "Dieser Monat"},
    "from": {"he": "מ-", "en": "From", "de": "Von"},
    "to": {"he": "עד", "en": "To", "de": "Bis"},
}


def _filter_builder_css() -> str:
    """Shared by build_filter_html() (the standalone page) and build_topic_html()
    (the embedded panel opened via "Edit filter") - one definition, so the two
    entry points can never visually drift apart. See _filter_builder_form_html()
    and _FILTER_BUILDER_JS_TEMPLATE for the rest of the shared component."""
    return """
  .filter-builder {
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
    max-width: 32rem;
  }
  .filter-field { display: flex; flex-direction: column; gap: .4rem; }
  .filter-field label { font-size: .85rem; font-weight: 600; color: var(--text-muted); }
  .filter-field select, .filter-field input[type="date"] {
    font-family: inherit;
    font-size: .95rem;
    padding: .55rem .7rem;
    border: 1px solid var(--border);
    border-radius: .5rem;
    background: var(--bg-elevated);
    color: var(--text);
  }
  .filter-presets { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .5rem; }
  .filter-preset-btn {
    font-family: inherit;
    font-size: .8rem;
    font-weight: 600;
    padding: .35rem .8rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg-elevated);
    color: var(--text-muted);
    cursor: pointer;
  }
  .filter-preset-btn:hover, .filter-preset-btn:focus-visible { border-color: var(--masthead-accent); color: var(--masthead-accent); }
  .filter-date-inputs { display: flex; align-items: center; gap: .6rem; }
  .filter-date-inputs span { color: var(--text-muted); font-size: .85rem; }
  .filter-actions { display: flex; align-items: center; gap: .8rem; margin-top: .3rem; }
  .filter-submit-btn {
    font-family: inherit;
    font-size: .92rem;
    font-weight: 700;
    padding: .65rem 1.5rem;
    border: none;
    border-radius: .6rem;
    background: var(--masthead-accent);
    color: #fff;
    cursor: pointer;
  }
  .filter-reset-btn, .filter-close-btn {
    font-family: inherit;
    font-size: .85rem;
    font-weight: 600;
    padding: .55rem 1rem;
    border: 1px solid var(--border);
    border-radius: .6rem;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
  }
  .filter-reset-btn:hover, .filter-close-btn:hover { border-color: var(--masthead-accent); color: var(--masthead-accent); }

  .filter-panel-wrapper { max-width: 44rem; margin: 0 auto; padding: 1.2rem 1.5rem 0; }
  .edit-filter-btn {
    font-family: inherit;
    font-size: .85rem;
    font-weight: 600;
    padding: .5rem 1rem;
    border: 1px solid var(--border);
    border-radius: .6rem;
    background: var(--bg-elevated);
    color: var(--text);
    cursor: pointer;
  }
  .edit-filter-btn:hover, .edit-filter-btn:focus-visible { border-color: var(--masthead-accent); color: var(--masthead-accent); }
  .filter-builder-panel {
    margin-top: 1rem;
    padding: 1.3rem 1.4rem;
    border: 1px solid var(--border);
    border-radius: .9rem;
    background: var(--bg-elevated);
  }

  .filter-suggestion-banner {
    border: 1px dashed var(--border);
    border-radius: .8rem;
    padding: 1rem 1.2rem;
    margin-bottom: 1.1rem;
  }
  .filter-suggestion-banner p { margin: 0 0 .5rem; }
  .filter-suggestion-banner p:last-child { margin-bottom: 0; }
  .filter-suggestion-hint { font-size: .85rem; color: var(--text-muted); }
  .filter-suggestion-chips { display: flex; flex-wrap: wrap; gap: .5rem; }
  .filter-suggestion-chip {
    font-size: .8rem;
    font-weight: 600;
    padding: .3rem .75rem;
    border-radius: 999px;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    text-decoration: none;
  }
  .filter-suggestion-chip:hover, .filter-suggestion-chip:focus-visible { border-color: var(--masthead-accent); color: var(--masthead-accent); }
"""


def _filter_builder_form_html(lang: str, show_close: bool) -> str:
    """The filter-builder's form markup - shared verbatim by build_filter_html()
    (fresh/blank, no close button) and build_topic_html()'s embedded panel
    (pre-filled from the current URL by _FILTER_BUILDER_JS_TEMPLATE, with a
    close button to dismiss the panel without navigating). category/region/
    conflict <select> options are populated client-side from manifest.json
    (same JS handles both host pages), not baked in here - see
    _FILTER_BUILDER_JS_TEMPLATE's populateSelect().
    """
    t = FILTER_FORM_LABELS
    any_label = esc(t["any"][lang])
    close_btn = (
        f'<button type="button" class="filter-close-btn" id="filter-close-btn">{esc(t["close"][lang])}</button>'
        if show_close else ""
    )
    return f"""
    <div class="filter-field">
      <label for="filter-category">{esc(t['category'][lang])}</label>
      <select id="filter-category"><option value="">{any_label}</option></select>
    </div>
    <div class="filter-field">
      <label for="filter-region">{esc(t['region'][lang])}</label>
      <select id="filter-region"><option value="">{any_label}</option></select>
    </div>
    <div class="filter-field">
      <label for="filter-conflict">{esc(t['conflict'][lang])}</label>
      <select id="filter-conflict"><option value="">{any_label}</option></select>
    </div>
    <div class="filter-field">
      <label>{esc(t['daterange'][lang])}</label>
      <div class="filter-presets">
        <button type="button" class="filter-preset-btn" data-preset="7">{esc(t['last7'][lang])}</button>
        <button type="button" class="filter-preset-btn" data-preset="30">{esc(t['last30'][lang])}</button>
        <button type="button" class="filter-preset-btn" data-preset="month">{esc(t['thismonth'][lang])}</button>
      </div>
      <div class="filter-date-inputs">
        <span>{esc(t['from'][lang])}</span>
        <input type="date" id="filter-from">
        <span>{esc(t['to'][lang])}</span>
        <input type="date" id="filter-to">
      </div>
    </div>
    <div class="filter-actions">
      <button type="button" class="filter-submit-btn" id="filter-submit-btn">{esc(t['apply'][lang])}</button>
      <button type="button" class="filter-reset-btn" id="filter-reset-btn">{esc(t['reset'][lang])}</button>
      {close_btn}
    </div>"""


# Plain (non f-string) template so JS/CSS braces don't need doubling - __TOKEN__
# placeholders are substituted with .replace() in build_filter_html() and
# build_topic_html(). Defines window.initFilterBuilder(manifest) but does not
# call fetch() itself - each host page already has (or is about to make) its
# own manifest.json fetch, and handing this component the parsed manifest
# object (rather than having it fetch a second, ~900KB copy of its own) is
# the whole reason it's a plain function instead of a self-starting IIFE like
# the other page templates. build_topic_html() calls it with the manifest its
# own script already fetched; build_filter_html() does one small fetch of its
# own (it has no other reason to load manifest.json) and calls it from there.
_FILTER_BUILDER_JS_TEMPLATE = """
(function () {
  var LANG = "__LANG__";
  var TARGET = "__TARGET__"; // "" = reload the current page; otherwise a bare filename to navigate to

  var LABEL_KEY = { he: "name_he", en: "name_en", de: "name_de" }[LANG] || "name_en";

  function populateSelect(id, dict) {
    var select = document.getElementById(id);
    if (!select || !dict) return;
    Object.keys(dict).forEach(function (key) {
      var option = document.createElement("option");
      option.value = key;
      option.textContent = dict[key][LABEL_KEY] || key;
      select.appendChild(option);
    });
  }

  function prefillFromQuery() {
    var params = new URLSearchParams(window.location.search);
    ["category", "region", "conflict"].forEach(function (name) {
      var raw = params.get(name);
      var first = raw ? raw.split(",")[0].trim() : "";
      var el = document.getElementById("filter-" + name);
      if (el && first) el.value = first;
    });
    var fromEl = document.getElementById("filter-from");
    var toEl = document.getElementById("filter-to");
    if (fromEl && params.get("from")) fromEl.value = params.get("from");
    if (toEl && params.get("to")) toEl.value = params.get("to");
  }

  function isoFromUTC(y, m, d) {
    var dt = new Date(Date.UTC(y, m, d));
    return dt.getUTCFullYear() + "-" + String(dt.getUTCMonth() + 1).padStart(2, "0") + "-" + String(dt.getUTCDate()).padStart(2, "0");
  }
  function addDaysIso(iso, delta) {
    var p = iso.split("-").map(Number);
    return isoFromUTC(p[0], p[1] - 1, p[2] + delta);
  }
  function monthStartIso(iso) {
    var p = iso.split("-").map(Number);
    return isoFromUTC(p[0], p[1] - 1, 1);
  }
  function monthEndIso(iso) {
    var p = iso.split("-").map(Number);
    return isoFromUTC(p[0], p[1], 0); // day 0 of next month = last day of this month
  }

  function wirePresets(anchorDate) {
    document.querySelectorAll(".filter-preset-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var fromEl = document.getElementById("filter-from");
        var toEl = document.getElementById("filter-to");
        if (!fromEl || !toEl || !anchorDate) return;
        var preset = btn.dataset.preset;
        if (preset === "7") { fromEl.value = addDaysIso(anchorDate, -6); toEl.value = anchorDate; }
        else if (preset === "30") { fromEl.value = addDaysIso(anchorDate, -29); toEl.value = anchorDate; }
        else if (preset === "month") { fromEl.value = monthStartIso(anchorDate); toEl.value = monthEndIso(anchorDate); }
      });
    });
  }

  function targetUrl(qs) {
    var path;
    if (TARGET) {
      path = window.location.pathname.replace(/[^\\/]*$/, "") + TARGET;
    } else {
      path = window.location.pathname;
    }
    return path + (qs ? "?" + qs : "");
  }

  function wireSubmit() {
    var btn = document.getElementById("filter-submit-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var params = new URLSearchParams();
      ["category", "region", "conflict"].forEach(function (name) {
        var el = document.getElementById("filter-" + name);
        if (el && el.value) params.set(name, el.value);
      });
      var fromEl = document.getElementById("filter-from");
      var toEl = document.getElementById("filter-to");
      var from = fromEl ? fromEl.value : "";
      var to = toEl ? toEl.value : "";
      if (from && to && from > to) { var tmp = from; from = to; to = tmp; }
      if (from) params.set("from", from);
      if (to) params.set("to", to);
      window.location.href = targetUrl(params.toString());
    });
  }

  function wireReset() {
    var btn = document.getElementById("filter-reset-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      ["filter-category", "filter-region", "filter-conflict", "filter-from", "filter-to"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.value = "";
      });
    });
  }

  function wireClose() {
    var btn = document.getElementById("filter-close-btn");
    var panel = document.getElementById("filter-builder-panel");
    if (!btn || !panel) return;
    btn.addEventListener("click", function () { panel.hidden = true; });
  }

  window.initFilterBuilder = function (manifest) {
    populateSelect("filter-category", manifest.categories);
    populateSelect("filter-region", manifest.regions);
    populateSelect("filter-conflict", manifest.conflict_zones);
    prefillFromQuery();
    wirePresets(manifest.latest_date);
    wireSubmit();
    wireReset();
    wireClose();
  };
})();
"""


def build_filter_html(lang: str) -> str:
    """Standalone "Advanced filter" page - docs/{lang}/filter.html only, no root
    copy (same convention as topic.html and about.html: a destination reached
    via the nav or a deep link, not a primary landing page). Opened blank
    (nothing pre-filled) via the "Advanced filter" nav link added to
    build_nav_html(); submitting navigates to topic.html?... with whatever was
    selected. This is the SAME component (_filter_builder_form_html() +
    _FILTER_BUILDER_JS_TEMPLATE) that topic.html embeds inline behind its
    "Edit filter" button - not a second implementation of the builder.
    """
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"

    page_title = {
        "he": "סינון מתקדם - גאופוליטיקה יומי", "en": "Advanced Filter - Daily Geopolitics",
        "de": "Erweiterte Filterung - Tägliche Geopolitik",
    }[lang]
    eyebrow = {"he": "גאופוליטיקה יומי", "en": "Daily Geopolitics", "de": "Tägliche Geopolitik"}[lang]
    heading = {"he": "סינון מתקדם", "en": "Advanced filter", "de": "Erweiterte Filterung"}[lang]

    form_html = _filter_builder_form_html(lang, show_close=False)
    builder_js = _FILTER_BUILDER_JS_TEMPLATE.replace("__LANG__", lang).replace("__TARGET__", "topic.html")
    bootstrap_js = (
        'fetch("../assets/data/manifest.json").then(function(r){return r.json();})'
        '.then(function(manifest){ if (window.initFilterBuilder) window.initFilterBuilder(manifest); })'
        '.catch(function(err){ console.error("Failed to load manifest.json", err); });'
    )

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

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
    font-family: "{FONT_FAMILY}", system-ui, sans-serif;
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
  .top-nav-logo-link {{ display: flex; align-items: center; }}
  .top-nav-logo {{ height: 56px; width: auto; display: block; }}
  .top-nav-links {{ display: flex; align-items: center; gap: 1.1rem; }}
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

  .filter-body {{ max-width: 44rem; margin: 0 auto; padding: 2.25rem 1.5rem 4rem; }}

  {_filter_builder_css()}

  {shared_chrome_css()}
</style>
</head>
<body>
{build_nav_html("archive.html", {o: f"../{o}/filter.html" for o in other_langs(lang)}, lang)}
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(eyebrow)}</p>
      <h1 class="report-title">{esc(heading)}</h1>
    </div>
  </header>
  <main class="filter-body">
    <div class="filter-builder">{form_html}</div>
  </main>
{build_footer_html(lang, *footer_hrefs_for(lang))}
  <script>{builder_js}</script>
  <script>{bootstrap_js}</script>
</body>
</html>
"""


def build_topic_html(lang: str) -> str:
    """A dynamic, filtered view over manifest.json's sections - not a synthesis:
    every result links straight to its real section anchor in the actual report
    (href_he/href_en#section-{id}), never re-rendering comparison_text. Reads
    ?category=&region=&conflict=&from=&to= (all optional, combinable) at load
    time client-side - same manifest.json already used by the homepage, no new
    endpoint/index. Lives only at docs/{he,en}/topic.html (no root copy),
    matching about.html's convention, since it's a deep-link target reached via
    query params rather than a primary nav destination.
    """
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"

    page_title = {
        "he": "תוצאות לפי סינון - גאופוליטיקה יומי", "en": "Filtered Results - Daily Geopolitics",
        "de": "Gefilterte Ergebnisse - Tägliche Geopolitik",
    }[lang]
    eyebrow = {"he": "גאופוליטיקה יומי", "en": "Daily Geopolitics", "de": "Tägliche Geopolitik"}[lang]
    loading_label = {"he": "טוען…", "en": "Loading…", "de": "Wird geladen…"}[lang]
    edit_filter_label = {"he": "ערוך סינון", "en": "Edit filter", "de": "Filter bearbeiten"}[lang]

    # The panel embeds the exact same builder component as the standalone
    # filter.html page (_filter_builder_form_html() + _FILTER_BUILDER_JS_TEMPLATE)
    # - with a close button (it's a dismissible panel, not a full page) and
    # TARGET="" so submitting reloads topic.html itself with the new query
    # string instead of navigating to a separate page.
    panel_form_html = _filter_builder_form_html(lang, show_close=True)
    filter_builder_js = _FILTER_BUILDER_JS_TEMPLATE.replace("__LANG__", lang).replace("__TARGET__", "")
    js_code = _TOPIC_JS_TEMPLATE.replace("__LANG__", lang)

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

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
    font-family: "{FONT_FAMILY}", system-ui, sans-serif;
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
  .top-nav-logo-link {{ display: flex; align-items: center; }}
  .top-nav-logo {{ height: 56px; width: auto; display: block; }}
  .top-nav-links {{ display: flex; align-items: center; gap: 1.1rem; }}
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

  .topic-body {{ max-width: 44rem; margin: 0 auto; padding: 2.25rem 1.5rem 4rem; }}
  .topic-count {{ margin: 0 0 1.2rem; font-size: .85rem; color: var(--text-muted); }}

  .topic-result {{
    display: flex;
    flex-direction: column;
    gap: .4rem;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-inline-start: 4px solid var(--cat-color, var(--border));
    border-radius: .8rem;
    padding: 1.1rem 1.3rem 1.3rem;
    margin-bottom: 1.1rem;
  }}
  .topic-result-meta {{ display: flex; align-items: center; gap: .6rem; }}
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
  .topic-result-date {{ font-size: .78rem; color: var(--text-muted); font-weight: 600; margin-inline-start: auto; }}
  .permalink-icon {{
    font-size: .82rem;
    text-decoration: none;
    opacity: .5;
    line-height: 1;
  }}
  .permalink-icon:hover, .permalink-icon:focus-visible {{ opacity: 1; }}
  .topic-result-title {{ margin: .2rem 0 0; font-size: 1.2rem; font-weight: 700; line-height: 1.4; }}
  .topic-result-text {{ margin: 0; font-size: 1rem; line-height: 1.85; color: var(--text); }}
  .topic-result-sources {{
    margin: .3rem 0 0;
    font-size: .82rem;
    color: var(--text-muted);
    padding-top: .6rem;
    border-top: 1px solid var(--border);
  }}
  .topic-empty, .topic-loading {{ color: var(--text-muted); font-size: .95rem; text-align: center; padding: 1rem 0; }}
  .load-more-btn {{
    display: block;
    margin: .5rem auto 0;
    padding: .65rem 1.6rem;
    border: 1px solid var(--border);
    border-radius: .6rem;
    background: var(--bg-elevated);
    color: var(--text);
    font-family: inherit;
    font-size: .9rem;
    font-weight: 600;
    cursor: pointer;
  }}
  .load-more-btn:hover, .load-more-btn:focus-visible {{ border-color: var(--masthead-accent); color: var(--masthead-accent); }}

  {_filter_builder_css()}

  {shared_chrome_css()}
</style>
</head>
<body>
{build_nav_html("archive.html", {o: f"../{o}/topic.html" for o in other_langs(lang)}, lang)}
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(eyebrow)}</p>
      <h1 class="report-title" id="topic-title">{esc(loading_label)}</h1>
    </div>
  </header>
  <div class="filter-panel-wrapper">
    <button type="button" class="edit-filter-btn" id="edit-filter-btn">{esc(edit_filter_label)}</button>
    <div class="filter-builder-panel" id="filter-builder-panel" hidden>
      <div class="filter-builder">{panel_form_html}</div>
    </div>
  </div>
  <main class="topic-body">
    <p class="topic-count" id="topic-count"></p>
    <div id="topic-results"></div>
  </main>
{build_footer_html(lang, *footer_hrefs_for(lang))}
  <script>{filter_builder_js}</script>
  <script>{js_code}</script>
</body>
</html>
"""


# Plain (non f-string) template so JS/CSS braces don't need doubling - __TOKEN__
# placeholders are substituted with .replace() in build_topic_html().
_TOPIC_JS_TEMPLATE = """
(function () {
  var LANG = "__LANG__";
  var PREFIX = "../";

  // topic.html only ever lives at docs/{lang}/topic.html (no root copy), so
  // each language-switch link built by build_nav_html (one per other
  // language - two now, trilingual) always points at a bare
  // "../{other}/topic.html" - append the current query string to each one so
  // an active filter survives switching language, since query params are
  // only known at runtime, not at build time. build_nav_html marks these
  // specifically with .top-nav-lang-link, so this doesn't have to assume a
  // fixed count/position among .top-nav-link (which also includes the
  // "back to archive" link).
  if (window.location.search) {
    document.querySelectorAll(".top-nav-lang-link").forEach(function (link) {
      link.href = link.getAttribute("href") + window.location.search;
    });
  }

  // Every enum-like dimension (category/region/conflict) is parsed as a
  // comma-separated list, even though the UI only ever writes a single value
  // today - this is the forward-compatible URL scheme: "?category=security"
  // and "?category=security,economy" both parse the same way, so a future
  // multi-select UI needs no scheme change and breaks no existing link.
  // from/to stay plain scalars - a date range is one interval, not a set of
  // enum values, so a comma-list doesn't apply to it the same way.
  function parseList(raw) {
    return raw ? raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [];
  }

  var params = new URLSearchParams(window.location.search);
  var filters = {
    category: parseList(params.get("category")),
    region: parseList(params.get("region")),
    conflict: parseList(params.get("conflict")),
    from: params.get("from"),
    to: params.get("to"),
  };

  // Pagination: a filter can match dozens of sections, and each is now shown
  // with full content (not just a title), so rendering everything matched in
  // one pass would both bloat the DOM and force fetching every content file
  // up front. PAGE_SIZE items are rendered per batch instead - full content
  // stays inline and the user still reads straight down the page without
  // leaving it (per the brief), they just click "load more" every 15 items
  // instead of the page loading 100+ full posts at once. A click-to-expand
  // per item was considered and rejected: it would hide content that's
  // supposed to already be visible while scrolling, which is the opposite of
  // what was asked for here.
  var PAGE_SIZE = 15;
  // Below this many total matches, a suggestion banner (with per-filter
  // "remove this" chips) appears above the results, not just when there are
  // literally zero - a 4-dimension AND filter can easily land on 1-2 results
  // even though each dimension alone has plenty.
  var FEW_RESULTS_THRESHOLD = 5;
  var allIds = [];
  var shownCount = 0;
  var contentCache = {}; // section id (string) -> {topic_label, comparison_text}
  var contentFetches = {}; // date -> Promise, so a date already loaded (or in
                            // flight) for an earlier batch is never re-fetched
  var loadMoreBtn = null;
  var currentManifest = null;

  fetch(PREFIX + "assets/data/manifest.json")
    .then(function (r) { return r.json(); })
    .then(function (manifest) {
      currentManifest = manifest;
      // Same already-fetched manifest object hands off to the embedded
      // filter-builder panel - it never fetches manifest.json a second time
      // (see _FILTER_BUILDER_JS_TEMPLATE's comment on why that matters at
      // ~900KB).
      if (window.initFilterBuilder) window.initFilterBuilder(manifest);
      wireEditFilterButton();

      allIds = filterSections(manifest, filters);
      renderTitle(manifest, filters, allIds.length);
      var container = document.getElementById("topic-results");
      if (!allIds.length) {
        renderFilterBanner(container, filters, manifest, "empty");
        return;
      }
      if (allIds.length < FEW_RESULTS_THRESHOLD) {
        renderFilterBanner(container, filters, manifest, "few");
      }
      loadNextBatch();
    })
    .catch(function (err) { console.error("Failed to load manifest.json", err); });

  function wireEditFilterButton() {
    var btn = document.getElementById("edit-filter-btn");
    var panel = document.getElementById("filter-builder-panel");
    if (!btn || !panel) return;
    btn.addEventListener("click", function () { panel.hidden = !panel.hidden; });
  }

  function contentUrlFor(date) {
    return PREFIX + "assets/data/content/" + date + "_" + LANG + ".json";
  }

  // Fetches only the content files a given batch actually needs (grouped by
  // date, deduplicated against files already fetched for a previous batch) -
  // never the whole filtered set's dates up front. The same function would
  // serve a future "export matched results to PDF" feature just as well: it
  // takes any list of dates and guarantees their content is in contentCache
  // when it resolves, regardless of how the caller assembled that list.
  function ensureContentLoaded(dates) {
    var promises = dates.map(function (date) {
      if (!contentFetches[date]) {
        contentFetches[date] = fetch(contentUrlFor(date))
          .then(function (r) { return r.json(); })
          .then(function (data) {
            Object.keys(data).forEach(function (sid) { contentCache[sid] = data[sid]; });
          })
          .catch(function (err) { console.error("Failed to load content for " + date, err); });
      }
      return contentFetches[date];
    });
    return Promise.all(promises);
  }

  function uniqueDates(list) {
    var seen = {};
    var out = [];
    list.forEach(function (d) {
      if (!seen[d]) { seen[d] = true; out.push(d); }
    });
    return out;
  }

  function loadNextBatch() {
    var container = document.getElementById("topic-results");
    if (!container) return;
    var batch = allIds.slice(shownCount, shownCount + PAGE_SIZE);
    if (!batch.length) return;

    var loading = document.createElement("p");
    loading.className = "topic-loading";
    loading.textContent = LANG === "he" ? "טוען…" : LANG === "de" ? "Wird geladen…" : "Loading…";
    container.appendChild(loading);

    var dates = uniqueDates(batch.map(function (id) { return currentManifest.sections[id].date; }));
    ensureContentLoaded(dates).then(function () {
      loading.remove();
      batch.forEach(function (id) { renderItem(container, id); });
      shownCount += batch.length;
      updateLoadMoreButton(container);
    });
  }

  function updateLoadMoreButton(container) {
    var remaining = allIds.length - shownCount;
    if (remaining <= 0) {
      if (loadMoreBtn) loadMoreBtn.style.display = "none";
      return;
    }
    if (!loadMoreBtn) {
      loadMoreBtn = document.createElement("button");
      loadMoreBtn.type = "button";
      loadMoreBtn.className = "load-more-btn";
      loadMoreBtn.addEventListener("click", loadNextBatch);
    }
    var label = LANG === "he" ? "טען עוד" : LANG === "de" ? "Mehr laden" : "Load more";
    loadMoreBtn.textContent = label + " (" + remaining + ")";
    loadMoreBtn.style.display = "";
    container.appendChild(loadMoreBtn); // re-appending an existing node moves it to the end
  }

  // Shown both when a filter combination matches nothing (kind="empty") and
  // when it matches very few sections (kind="few", see FEW_RESULTS_THRESHOLD)
  // - same banner either way, just a different headline message. Each active
  // filter dimension gets its own "remove this" chip (an <a> to the current
  // URL with just that one param stripped), so the suggestion is concrete,
  // not just "try something else." A date range counts as one dimension for
  // this purpose (removing it clears both from and to together).
  function renderFilterBanner(container, f, manifest, kind) {
    if (!container) return;
    var banner = document.createElement("div");
    banner.className = "filter-suggestion-banner";

    var msg = document.createElement("p");
    msg.textContent = kind === "empty"
      ? (LANG === "he" ? "לא נמצאו תוצאות התואמות את הסינון."
        : LANG === "de" ? "Keine Ergebnisse entsprechen diesem Filter."
        : "No results match this filter.")
      : (LANG === "he" ? "מעט מאוד תוצאות עבור השילוב הזה."
        : LANG === "de" ? "Sehr wenige Ergebnisse für diese Kombination."
        : "Very few results for this combination.");
    banner.appendChild(msg);

    var chips = activeFilterChips(f, manifest);
    if (chips.length) {
      var hint = document.createElement("p");
      hint.className = "filter-suggestion-hint";
      hint.textContent = LANG === "he" ? "נסו להסיר או להרחיב אחד מהסינונים:"
        : LANG === "de" ? "Entfernen oder erweitern Sie einen der Filter:"
        : "Try removing or broadening one of these filters:";
      banner.appendChild(hint);

      var chipRow = document.createElement("div");
      chipRow.className = "filter-suggestion-chips";
      chips.forEach(function (chip) {
        var a = document.createElement("a");
        a.className = "filter-suggestion-chip";
        a.href = urlWithoutParam(chip.removeParam);
        a.textContent = "✕ " + chip.label;
        chipRow.appendChild(a);
      });
      banner.appendChild(chipRow);
    }
    container.appendChild(banner);
  }

  function activeFilterChips(f, manifest) {
    var chips = [];
    f.category.forEach(function (key) {
      chips.push({ label: (manifest.categories[key] || {})[LABEL_KEY] || key, removeParam: "category" });
    });
    f.region.forEach(function (key) {
      chips.push({ label: (manifest.regions[key] || {})[LABEL_KEY] || key, removeParam: "region" });
    });
    f.conflict.forEach(function (key) {
      chips.push({ label: (manifest.conflict_zones[key] || {})[LABEL_KEY] || key, removeParam: "conflict" });
    });
    if (f.from || f.to) {
      chips.push({ label: formatRange(f.from, f.to), removeParam: "daterange" });
    }
    return chips;
  }

  function urlWithoutParam(param) {
    var p = new URLSearchParams(window.location.search);
    if (param === "daterange") { p.delete("from"); p.delete("to"); }
    else { p.delete(param); }
    var qs = p.toString();
    return window.location.pathname + (qs ? "?" + qs : "");
  }

  function filterSections(manifest, f) {
    var ids = Object.keys(manifest.sections).map(Number);
    if (f.region.length) {
      var regionSet = new Set();
      f.region.forEach(function (key) {
        var region = manifest.regions[key];
        if (region) region.section_ids.forEach(function (id) { regionSet.add(id); });
      });
      ids = ids.filter(function (id) { return regionSet.has(id); });
    }
    if (f.conflict.length) {
      ids = ids.filter(function (id) {
        return f.conflict.some(function (key) {
          return manifest.sections[id].conflict_zones.indexOf(key) !== -1;
        });
      });
    }
    if (f.category.length) {
      ids = ids.filter(function (id) { return f.category.indexOf(manifest.sections[id].category) !== -1; });
    }
    if (f.from) {
      ids = ids.filter(function (id) { return manifest.sections[id].date >= f.from; });
    }
    if (f.to) {
      ids = ids.filter(function (id) { return manifest.sections[id].date <= f.to; });
    }
    ids.sort(function (a, b) {
      var da = manifest.sections[a].date, db = manifest.sections[b].date;
      if (da !== db) return da < db ? 1 : -1;
      return a - b;
    });
    return ids;
  }

  var LABEL_KEY = { he: "name_he", en: "name_en", de: "name_de" }[LANG] || "name_en";
  var TOPIC_KEY = { he: "topic_he", en: "topic_en", de: "topic_de" }[LANG] || "topic_en";
  var HREF_KEY = { he: "href_he", en: "href_en", de: "href_de" }[LANG] || "href_en";

  function hrefFor(section) {
    return PREFIX + section[HREF_KEY];
  }

  function topicFor(section) {
    return section[TOPIC_KEY];
  }

  var HE_MONTHS = ["ינואר","פברואר","מרץ","אפריל","מאי","יוני","יולי","אוגוסט","ספטמבר","אוקטובר","נובמבר","דצמבר"];
  var EN_MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  var DE_MONTHS = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];

  function formatLongDate(iso) {
    var parts = iso.split("-").map(Number);
    var day = parts[2], month = parts[1] - 1, year = parts[0];
    if (LANG === "he") return day + " ב" + HE_MONTHS[month] + " " + year;
    if (LANG === "de") return day + ". " + DE_MONTHS[month] + " " + year;
    return EN_MONTHS[month] + " " + day + ", " + year;
  }

  function formatShortDate(iso) {
    var p = iso.split("-");
    return p[2] + "." + p[1] + "." + p[0];
  }

  function formatRange(from, to) {
    if (!from && !to) return "";
    if (from && to) {
      var f = from.split("-").map(Number), t = to.split("-").map(Number);
      if (f[0] === t[0] && f[1] === t[1]) {
        if (LANG === "he") return f[2] + "-" + t[2] + " ב" + HE_MONTHS[f[1] - 1] + " " + f[0];
        if (LANG === "de") return f[2] + ".-" + t[2] + ". " + DE_MONTHS[f[1] - 1] + " " + f[0];
        return EN_MONTHS[f[1] - 1] + " " + f[2] + "-" + t[2] + ", " + f[0];
      }
      return formatLongDate(from) + " – " + formatLongDate(to);
    }
    if (from) return (LANG === "he" ? "מ-" : LANG === "de" ? "Ab " : "From ") + formatLongDate(from);
    return (LANG === "he" ? "עד " : LANG === "de" ? "Bis " : "Until ") + formatLongDate(to);
  }

  function labelsFor(keys, dict) {
    return keys.map(function (key) { return (dict[key] || {})[LABEL_KEY] || key; });
  }

  function renderTitle(manifest, f, count) {
    var parts = [];
    parts = parts.concat(labelsFor(f.category, manifest.categories));
    parts = parts.concat(labelsFor(f.region, manifest.regions));
    parts = parts.concat(labelsFor(f.conflict, manifest.conflict_zones));
    var rangeLabel = formatRange(f.from, f.to);
    if (rangeLabel) parts.push(rangeLabel);

    var allResultsLabel = LANG === "he" ? "כל התוצאות" : LANG === "de" ? "Alle Ergebnisse" : "All Results";
    var title = parts.length ? parts.join(" · ") : allResultsLabel;
    var titleEl = document.getElementById("topic-title");
    if (titleEl) titleEl.textContent = title;
    var suffix = LANG === "he" ? " - גאופוליטיקה יומי" : LANG === "de" ? " - Tägliche Geopolitik" : " - Daily Geopolitics";
    document.title = title + suffix;

    var countEl = document.getElementById("topic-count");
    if (countEl) {
      countEl.textContent = LANG === "he" ? count + " תוצאות"
        : LANG === "de" ? count + " Ergebnisse"
        : count + " result" + (count === 1 ? "" : "s");
    }
  }

  function renderItem(container, id) {
    var section = currentManifest.sections[id];
    if (!section) return;
    var content = contentCache[id];

    var item = document.createElement("article");
    item.className = "topic-result";
    item.dataset.category = section.category;

    var meta = document.createElement("div");
    meta.className = "topic-result-meta";

    var dot = document.createElement("span");
    dot.className = "category-dot";

    var label = document.createElement("span");
    label.className = "category-label";
    var catInfo = currentManifest.categories[section.category];
    label.textContent = catInfo ? catInfo[LABEL_KEY] : section.category;

    var dateBadge = document.createElement("span");
    dateBadge.className = "topic-result-date";
    dateBadge.textContent = formatShortDate(section.date);

    var permalink = document.createElement("a");
    permalink.className = "permalink-icon";
    permalink.href = hrefFor(section);
    var permalinkLabel = LANG === "he" ? "קישור ישיר לממצא זה בדוח המקורי"
      : LANG === "de" ? "Permalink zu diesem Eintrag im Originalbericht"
      : "Permalink to this item in the original report";
    permalink.title = permalinkLabel;
    permalink.setAttribute("aria-label", permalinkLabel);
    permalink.textContent = "🔗";

    meta.appendChild(dot);
    meta.appendChild(label);
    meta.appendChild(dateBadge);
    meta.appendChild(permalink);

    var title = document.createElement("h2");
    title.className = "topic-result-title";
    title.textContent = content ? content.topic_label : topicFor(section);

    var text = document.createElement("p");
    text.className = "topic-result-text";
    text.textContent = content ? content.comparison_text : "";

    var sources = document.createElement("p");
    sources.className = "topic-result-sources";
    var names = currentManifest.newspaper_display_names || {};
    sources.textContent = section.sources.map(function (s) { return names[s] || s; }).join(", ");

    item.appendChild(meta);
    item.appendChild(title);
    item.appendChild(text);
    item.appendChild(sources);
    container.appendChild(item);
  }
})();
"""


# Plain (non f-string) template so JS/CSS braces don't need doubling - __TOKEN__
# placeholders are substituted with .replace() in build_homepage_html() instead.
_HOMEPAGE_JS_TEMPLATE = """
(function () {
  var LANG = "__LANG__";
  var PREFIX = "__PREFIX__";
  var TOPIC_PREFIX = "__TOPIC_PREFIX__";

  fetch(PREFIX + "assets/data/manifest.json")
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function (err) { console.error("Failed to load manifest.json", err); });

  function init(manifest) {
    renderMap(manifest);
    renderTimeline(manifest);
    renderLatestCard(manifest);
    renderRegionChips(manifest);
    renderConflictChips(manifest);
    if (manifest.latest_date) {
      selectDate(manifest, manifest.latest_date);
    }
  }

  var LABEL_KEY = { he: "name_he", en: "name_en", de: "name_de" }[LANG] || "name_en";
  var TOPIC_KEY = { he: "topic_he", en: "topic_en", de: "topic_de" }[LANG] || "topic_en";
  var HREF_KEY = { he: "href_he", en: "href_en", de: "href_de" }[LANG] || "href_en";

  function hrefFor(section) {
    return PREFIX + section[HREF_KEY];
  }

  function topicFor(section) {
    return section[TOPIC_KEY];
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
        titleEl.textContent = country[LABEL_KEY];
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
      // Capped at 55 (not 80) since a 2026-09-16 WCAG audit measured --text
      // against this color-mix at the old max and found it fell to ~3:1 in
      // both themes on the highest-coverage days - below the 4.5:1 minimum,
      // and ironically on the most-important cells to actually read. 55 keeps
      // every intensity level at or above 4.75:1 in both themes.
      var pct = Math.round(20 + intensity * 35);
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

    var numberEl = document.createElement("p");
    numberEl.className = "latest-card-number";
    numberEl.textContent = formatShortDate(manifest.latest_date);

    var previewEl = document.createElement("p");
    previewEl.className = "latest-card-preview";
    previewEl.textContent = section ? topicFor(section) : "";

    var cta = document.createElement("p");
    cta.className = "latest-card-cta";
    cta.textContent = LANG === "he" ? "לדוח המלא ←" : LANG === "de" ? "Zum vollständigen Bericht →" : "Full report →";

    link.appendChild(numberEl);
    link.appendChild(previewEl);
    link.appendChild(cta);
    card.appendChild(link);
  }

  function renderRegionChips(manifest) {
    var container = document.getElementById("region-chips");
    if (!container || !manifest.regions) return;
    Object.keys(manifest.regions).forEach(function (key) {
      var region = manifest.regions[key];
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "region-chip";
      chip.dataset.region = key;
      chip.textContent = region[LABEL_KEY];
      chip.addEventListener("click", function () {
        selectRegion(manifest, key);
      });
      container.appendChild(chip);
    });
  }

  function renderConflictChips(manifest) {
    var container = document.getElementById("conflict-chips");
    if (!container || !manifest.conflict_zones) return;
    Object.keys(manifest.conflict_zones).forEach(function (key) {
      var zone = manifest.conflict_zones[key];
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "region-chip";
      chip.dataset.conflict = key;
      chip.textContent = zone[LABEL_KEY];
      chip.addEventListener("click", function () {
        window.location.href = TOPIC_PREFIX + "topic.html?conflict=" + encodeURIComponent(key);
      });
      container.appendChild(chip);
    });
  }

  function selectCountry(manifest, code) {
    clearSelection();
    var el = document.getElementById(code.toLowerCase());
    if (el) el.classList.add("is-selected");
    var country = manifest.countries[code];
    var name = country[LABEL_KEY];
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

  function selectRegion(manifest, regionKey) {
    clearSelection();
    var region = manifest.regions[regionKey];
    if (!region) return;
    var chip = document.querySelector('.region-chip[data-region="' + regionKey + '"]');
    if (chip) chip.classList.add("is-selected");
    region.country_codes.forEach(function (code) {
      var el = document.getElementById(code.toLowerCase());
      if (el) el.classList.add("is-selected");
    });
    var name = region[LABEL_KEY];
    var fullReportHref = TOPIC_PREFIX + "topic.html?region=" + encodeURIComponent(regionKey);
    renderResults(manifest, region.section_ids, name, fullReportHref);
  }

  function clearSelection() {
    document.querySelectorAll(".is-selected").forEach(function (el) {
      el.classList.remove("is-selected");
    });
  }

  function renderResults(manifest, sectionIds, headingLabel, fullReportHref) {
    var panel = document.getElementById("results-panel");
    if (!panel) return;
    panel.innerHTML = "";

    var heading = document.createElement("p");
    heading.className = "results-heading";
    var resultsPrefix = LANG === "he" ? "תוצאות: " : LANG === "de" ? "Ergebnisse: " : "Results: ";
    heading.textContent = resultsPrefix + headingLabel;
    panel.appendChild(heading);

    if (fullReportHref) {
      var fullLink = document.createElement("a");
      fullLink.className = "results-full-link";
      fullLink.href = fullReportHref;
      fullLink.textContent = LANG === "he" ? "פתח כדוח מלא ←" : LANG === "de" ? "Als vollständigen Bericht öffnen →" : "View as full report →";
      panel.appendChild(fullLink);
    }

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
      label.textContent = catInfo ? catInfo[LABEL_KEY] : section.category;

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
  var DE_MONTHS = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];

  function formatLongDate(iso) {
    var parts = iso.split("-").map(Number);
    var day = parts[2];
    var month = parts[1] - 1;
    var year = parts[0];
    if (LANG === "he") {
      return day + " ב" + HE_MONTHS[month] + " " + year;
    }
    if (LANG === "de") {
      return day + ". " + DE_MONTHS[month] + " " + year;
    }
    return EN_MONTHS[month] + " " + day + ", " + year;
  }
})();
"""


def build_homepage_html(lang: str, is_root: bool, countries: dict) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    content = CONTENT[lang]

    asset_prefix = "" if is_root else "../"
    # Only "he" ever has is_root=True (the root copy stays Hebrew-default, unchanged
    # convention) - so the other-language hrefs from a root page are root-relative
    # ("en/index.html"), while every non-root copy points "up and over" ("../en/index.html").
    lang_hrefs = (
        {o: f"{o}/index.html" for o in other_langs(lang)} if is_root
        else {o: f"../{o}/index.html" for o in other_langs(lang)}
    )
    about_href = "he/about.html" if is_root else "about.html"
    # topic.html has the same root-copy quirk as about.html (lives only under
    # docs/{lang}/, never at the site root) - same fix as about_href above.
    topic_prefix = "he/" if is_root else ""
    # accessibility.html/terms.html/filter.html follow the same no-root-copy convention.
    accessibility_href = "he/accessibility.html" if is_root else "accessibility.html"
    terms_href = "he/terms.html" if is_root else "terms.html"
    filter_href = "he/filter.html" if is_root else "filter.html"

    page_title = {"he": "גאופוליטיקה יומי", "en": "Daily Geopolitics", "de": "Tägliche Geopolitik"}[lang]
    eyebrow = page_title

    story_text = {
        "he": (
            "בכל יום, עשרות עיתונים מספרים סיפור שונה על אותו עולם. רובנו קוראים זווית "
            "אחת - זו שכבר מוכרת לנו - ומחמיצים את השיחה השלמה שמתקיימת, במקביל, בין "
            "מבטים שונים על אותו אירוע. כאן אנו עוקבים אחרי כמה מהעיתונים המובילים "
            "בעולם, וממזגים אותם לתמונה אחת: לא כדי להכריע מי צודק, אלא כדי להאיר את "
            "זוויות המבט השונות."
        ),
        "en": (
            "Every day, dozens of newspapers tell a different story about the same "
            "world. Most of us read one angle - the one we already know - and miss "
            "the fuller conversation unfolding, at the same time, between different "
            "viewpoints on the same event. Here, we follow some of the world's "
            "leading newspapers and merge them into a single picture: not to decide "
            "who's right, but to illuminate the different points of view."
        ),
        "de": (
            "Jeden Tag erzählen Dutzende Zeitungen eine andere Geschichte über "
            "dieselbe Welt. Die meisten von uns lesen nur eine Perspektive - die "
            "bereits vertraute - und verpassen dabei das vollständige Gespräch, das "
            "zur gleichen Zeit zwischen verschiedenen Sichtweisen auf dasselbe "
            "Ereignis stattfindet. Hier verfolgen wir einige der weltweit führenden "
            "Zeitungen und fügen sie zu einem einzigen Bild zusammen: nicht um zu "
            "entscheiden, wer recht hat, sondern um die unterschiedlichen "
            "Blickwinkel sichtbar zu machen."
        ),
    }[lang]
    story_link_label = {"he": "עוד על הפרויקט ←", "en": "More about the project →", "de": "Mehr über das Projekt →"}[lang]
    archive_link_label = {"he": "לארכיון המלא ←", "en": "Full archive →", "de": "Zum vollständigen Archiv →"}[lang]

    map_svg = _load_map_svg_inline(lang, countries)
    map_description = {
        "he": (
            "מפת עולם אינטראקטיבית. מדינות עם כיסוי חדשותי מודגשות בצבע; לחיצה על מדינה "
            "מסננת את פאנל התוצאות למטה. רשימת המדינות המכוסות מפורטת בהמשך העמוד."
        ),
        "en": (
            "Interactive world map. Countries with news coverage are highlighted in "
            "color; clicking a country filters the results panel below. The list of "
            "covered countries is detailed further down the page."
        ),
        "de": (
            "Interaktive Weltkarte. Länder mit Nachrichtenberichterstattung sind "
            "farblich hervorgehoben; ein Klick auf ein Land filtert das "
            "Ergebnisfeld weiter unten. Die Liste der abgedeckten Länder ist "
            "weiter unten auf der Seite aufgeführt."
        ),
    }[lang]
    js_code = (
        _HOMEPAGE_JS_TEMPLATE.replace("__LANG__", lang)
        .replace("__PREFIX__", asset_prefix)
        .replace("__TOPIC_PREFIX__", topic_prefix)
    )

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
{favicon_links_html(asset_prefix)}
<style>
  {font_face_css(f"{asset_prefix}assets/fonts/{FONT_FILENAME}")}

  {category_css()}

  :root {{
    --bg: #f3efe8;
    --bg-elevated: #fffdfa;
    --text: #221f1b;
    --text-muted: #6d675e;
    --border: #e4ddd0;
    --masthead-accent: #7a2e2a;
    --chip-selected-text: #ffffff;
  }}

  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #16140f;
      --bg-elevated: #211e18;
      --text: #ece7dd;
      --text-muted: #a89f91;
      --border: #3a352b;
      --masthead-accent: #d68b86;
      /* --masthead-accent flips to a light dusty pink in dark mode, so the
         selected-chip text (previously hardcoded white) needs its own
         theme-aware token too - white-on-light-pink measured at 2.66:1 in a
         2026-09-16 WCAG audit, well under the 4.5:1 minimum; this dark value
         measures 6.62:1 against the dark-mode accent. */
      --chip-selected-text: #2a1210;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #16140f;
    --bg-elevated: #211e18;
    --text: #ece7dd;
    --text-muted: #a89f91;
    --border: #3a352b;
    --masthead-accent: #d68b86;
    --chip-selected-text: #2a1210;
  }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "{FONT_FAMILY}", system-ui, sans-serif;
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
  .home-logo {{ height: 56px; width: auto; display: block; }}
  .home-top-bar a {{
    color: var(--text-muted);
    text-decoration: none;
    font-weight: 500;
    font-size: .82rem;
  }}
  .home-top-bar a:hover {{ color: var(--masthead-accent); text-decoration: underline; }}
  .home-top-bar-links {{ display: flex; align-items: center; gap: 1.1rem; }}

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

  .home-top-row {{
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
    gap: 1.25rem;
    margin-bottom: 1.25rem;
  }}
  @media (max-width: 860px) {{
    .home-top-row {{ grid-template-columns: minmax(0, 1fr); }}
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
  .module-link {{ font-size: .78rem; color: var(--masthead-accent); text-decoration: none; white-space: nowrap; }}
  .module-link:hover {{ text-decoration: underline; }}

  .map-module {{ margin-bottom: 1.25rem; }}
  .map-module svg#world-map {{ width: 100%; height: auto; display: block; }}
  /* Visually hidden but present for screen readers/search engines - the
     standard clip-based pattern (not display:none, which removes it from
     the accessibility tree too). */
  .sr-only {{
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }}
  .oceanxx {{ fill: var(--bg); stroke: var(--border); stroke-width: 0.5; }}
  .landxx, .limitxx, .antxx {{ fill: var(--border); stroke: var(--bg-elevated); stroke-width: 0.5; fill-rule: evenodd; }}
  .circlexx, .subxx, .noxx, .unxx {{ opacity: 0; }}
  .landxx.has-coverage {{ fill: var(--masthead-accent); cursor: pointer; }}
  .landxx.has-coverage:hover {{ opacity: .8; }}
  .landxx.is-selected {{ stroke: #f4b942; stroke-width: 2.5; }}

  .region-chips {{
    display: flex;
    flex-wrap: wrap;
    gap: .5rem;
    margin-top: 1.1rem;
  }}
  .region-chip {{
    font-family: inherit;
    font-size: .78rem;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: .35rem .9rem;
    cursor: pointer;
  }}
  .region-chip:hover {{ border-color: var(--masthead-accent); color: var(--masthead-accent); }}
  .region-chip.is-selected {{ background: var(--masthead-accent); border-color: var(--masthead-accent); color: var(--chip-selected-text); }}

  .timeline-top {{ display: flex; justify-content: flex-end; margin-bottom: .6rem; }}
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

  .latest-card {{ display: flex; flex-direction: column; gap: .6rem; flex: 1; justify-content: center; }}
  .latest-card a {{ text-decoration: none; color: inherit; }}
  .latest-card-number {{ margin: 0; font-size: 2.6rem; font-weight: 800; letter-spacing: -0.02em; color: var(--masthead-accent); }}
  .latest-card-preview {{
    margin: 0;
    font-size: .95rem;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .latest-card-cta {{ margin: .25rem 0 0; font-size: .85rem; font-weight: 600; color: var(--masthead-accent); }}

  .results-heading {{ font-size: 1.05rem; font-weight: 700; margin: 0 0 1rem; }}
  .results-full-link {{
    display: inline-block;
    font-size: .85rem;
    color: var(--masthead-accent);
    text-decoration: none;
    margin: -0.6rem 0 1rem;
  }}
  .results-full-link:hover {{ text-decoration: underline; }}
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

  {shared_chrome_css()}
</style>
</head>
<body>
  <div class="home-top-bar">
    <img class="home-logo" src="{asset_prefix}assets/images/MS_Logo.png" alt="">
    <div class="home-top-bar-links">
      <a href="{esc(filter_href)}">{esc(FILTER_LABEL[lang])}</a>
      {"".join(f'<a href="{esc(lang_hrefs[o])}">{esc(LANG_LABEL[o])}</a>' for o in other_langs(lang) if o in lang_hrefs)}
      <a href="mailto:{CONTACT_EMAIL}">{esc(CONTACT_LABEL[lang])}</a>
    </div>
  </div>
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(eyebrow)}</p>
      <h1 class="home-title">{content['title']}</h1>
      <p class="home-story">{story_text} <a class="home-story-link" href="{esc(about_href)}">{esc(story_link_label)}</a></p>
    </div>
  </header>
  <main class="home-main">
    <div class="home-top-row">
      <section class="home-module timeline-module">
        <div class="timeline-top">
          <a class="module-link" href="archive.html">{esc(archive_link_label)}</a>
        </div>
        <div class="timeline-track" id="timeline-track"></div>
      </section>
      <section class="home-module latest-module">
        <div class="latest-card" id="latest-card"></div>
      </section>
    </div>
    <section class="home-module map-module">
      <p class="sr-only" id="map-description">{esc(map_description)}</p>
      {map_svg}
      <div class="region-chips" id="region-chips"></div>
      <div class="region-chips" id="conflict-chips"></div>
    </section>
    <div class="results-panel" id="results-panel"></div>
  </main>
{build_footer_html(lang, accessibility_href, terms_href)}
  <script>{js_code}</script>
</body>
</html>
"""


def _copy_reports_to_docs() -> None:
    for lang in ("he", "en", "de"):
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


def _copy_favicons() -> None:
    for base_dir in (DOCS_DIR, REPORTS_DIR):
        dest_dir = base_dir / "assets" / "images"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for filename in FAVICON_FILENAMES:
            shutil.copy2(FAVICON_SOURCE_DIR / filename, dest_dir / filename)


def _copy_map() -> None:
    for base_dir in (DOCS_DIR, REPORTS_DIR):
        dest = base_dir / "assets" / "map" / MAP_SOURCE_PATH.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MAP_SOURCE_PATH, dest)


def _load_map_svg_inline(lang: str, countries: dict) -> str:
    """Load world.svg (see assets/map/NOTICE.txt for source/license) stripped of
    XML prolog and editor-only (Inkscape/Sodipodi) markup, ready to embed directly
    in a page's <body> - required so JS can select/color individual country
    elements by id, which an <img>-referenced external SVG would not allow.
    getElementById(code) is what JS elsewhere already uses, and it doesn't care
    which of two shapes the element actually is: a multi-piece country (islands/
    exclaves) is a <g id="xx"> wrapping several <path> children (each child's own
    id carries a distinguishing suffix, e.g. "il-", never the bare code); a
    single-piece country is just one bare <path id="xx"> with no wrapping <g> at
    all. Confirmed empirically against this specific file - neither pattern alone
    covers every one of the ~90 covered countries, only their union does.

    Also tags every one of the ~250 total country elements (both shapes) for
    accessibility (a screen reader/search engine otherwise sees a flat,
    context-free list of every country's raw name, real content or not): a
    country absent from `countries` (no coverage today) gets aria-hidden="true" -
    it contributes only background color, no information; a covered country gets
    a real aria-label instead of relying on the SVG's original bare-name <title>
    child. This is a one-time build-time snapshot of `countries` - a deliberate,
    narrow exception to the homepage's usual everything-fetched-at-runtime rule
    (see build_homepage_html), since static accessibility markup doesn't need to
    be "live" the way the interactive coloring/click behavior does.
    """
    raw = MAP_SOURCE_PATH.read_text(encoding="utf-8")
    if raw.startswith("<?xml"):
        raw = raw.split("\n", 1)[1]
    raw = re.sub(r"\s*<sodipodi:namedview.*?/>\s*\n", "\n", raw, count=1, flags=re.DOTALL)
    raw = re.sub(r'\s*<style\s+id="style_css_sheet".*?</style>\s*\n', "\n", raw, count=1, flags=re.DOTALL)
    # role="img" + aria-labelledby give the map itself an accessible name before
    # a screen reader descends into individual countries - previously the only
    # accessible-text on the page was the sr-only <p id="map-description"> sitting
    # next to the <svg> in the DOM, with no programmatic link between them
    # (a WCAG audit, 2026-09-16, flagged this: DOM adjacency isn't a formal name).
    raw = re.sub(
        r'<svg\s+version="1\.1"\s+id="svg2985".*?xmlns:svg="http://www\.w3\.org/2000/svg">',
        '<svg id="world-map" role="img" aria-labelledby="map-description" '
        'viewBox="-35.8 80 2776 1163.1" xmlns="http://www.w3.org/2000/svg">',
        raw,
        count=1,
        flags=re.DOTALL,
    )

    def _tag_country_element(tag: str):
        def _replace(match: re.Match) -> str:
            code = match.group(1)
            country = countries.get(code.upper())
            if country is None:
                return f'<{tag} id="{code}" aria-hidden="true"'
            name = country[{"he": "name_he", "en": "name_en", "de": "name_de"}[lang]]
            label = {
                "he": f"{name} - יש כיסוי חדשותי, לחץ לסינון",
                "en": f"{name} - has news coverage, click to filter",
                "de": f"{name} - hat Nachrichtenberichterstattung, zum Filtern klicken",
            }[lang]
            # role="img" - not "button" - because aria-label is only reliably
            # exposed on an element that has *some* valid role (axe flags
            # aria-label on a bare path/g with none), and these aren't
            # actually keyboard-operable yet (mouse click only, no tabindex) -
            # role="button" without that would be a false accessibility claim.
            # Making the map itself keyboard-navigable is a separate, larger
            # feature, not part of this fix.
            return f'<{tag} id="{code}" role="img" aria-label="{esc(label)}"'
        return _replace

    # Two distinct shapes in this SVG, both selected identically by
    # getElementById() elsewhere so both need tagging here: a multi-piece
    # country (islands/exclaves) is a <g id="xx"> wrapping several <path>
    # children (each child's own id carries a distinguishing suffix, e.g.
    # "il-", never the bare code, so this can't double-match those); a
    # single-piece country is just one bare <path id="xx"> with no wrapping
    # <g> at all. Confirmed empirically: neither pattern alone covers every
    # manifest country - only their union does.
    raw = re.sub(r'<g\s+id="([a-zA-Z]{2,3})"', _tag_country_element("g"), raw)
    raw = re.sub(r'<path\s+id="([a-zA-Z]{2,3})"', _tag_country_element("path"), raw)
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
                "topic_de": s["topic_label_de"],
                "sources": newspapers,
                "countries": geo["countries"],
                "conflict_zones": geo["conflict_zones"],
                "href_he": f"he/report_{report_date}_he.html#section-{section_id}",
                "href_en": f"en/report_{report_date}_en.html#section-{section_id}",
                "href_de": f"de/report_{report_date}_de.html#section-{section_id}",
            }

            for code in geo["countries"]:
                countries_index.setdefault(code, []).append(section_id)
            for zone in geo["conflict_zones"]:
                conflict_zones_index.setdefault(zone, []).append(section_id)

        # Same coverage-based order as the rendered report (see render.py) - so
        # the homepage's "first section" teaser (section_ids[0]) matches what
        # actually appears first in the report itself, not raw insertion order.
        section_ids_for_date.sort(
            key=lambda sid: tuple(-x for x in section_coverage(sections[sid]["sources"]))
        )
        dates_index[report_date] = {"sources": sources, "section_ids": section_ids_for_date}

    countries_out = {
        code: {
            "name_he": COUNTRY_LIST[code]["name_he"],
            "name_en": COUNTRY_LIST[code]["name_en"],
            "name_de": COUNTRY_LIST[code]["name_de"],
            "region": COUNTRY_TO_REGION[code],
            "section_ids": ids,
        }
        for code, ids in countries_index.items()
    }
    conflict_zones_out = {
        zone: {
            "name_he": CONFLICT_ZONE_LABELS[zone]["name_he"],
            "name_en": CONFLICT_ZONE_LABELS[zone]["name_en"],
            "name_de": CONFLICT_ZONE_LABELS[zone]["name_de"],
            "section_ids": ids,
        }
        for zone, ids in conflict_zones_index.items()
    }

    categories_out = {
        code: {"name_he": labels["he"], "name_en": labels["en"], "name_de": labels["de"]}
        for code, labels in CATEGORY_LABELS.items()
    }

    region_country_codes: dict[str, list[str]] = {}
    for code, region_key in COUNTRY_TO_REGION.items():
        region_country_codes.setdefault(region_key, []).append(code)

    regions_out = {}
    for region_key, codes in region_country_codes.items():
        ids: set[int] = set()
        for code in codes:
            ids.update(countries_index.get(code, []))
        if ids:
            regions_out[region_key] = {
                "name_he": REGION_LABELS[region_key]["name_he"],
                "name_en": REGION_LABELS[region_key]["name_en"],
                "name_de": REGION_LABELS[region_key]["name_de"],
                "country_codes": sorted(codes),
                "section_ids": sorted(ids),
            }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_date": entries[0][0] if entries else None,
        "sections": sections,
        "countries": countries_out,
        "conflict_zones": conflict_zones_out,
        "dates": dates_index,
        "categories": categories_out,
        "regions": regions_out,
        "newspaper_display_names": NEWSPAPER_DISPLAY_NAMES,
    }


def _write_manifest(manifest: dict) -> None:
    manifest_json = json.dumps(manifest, ensure_ascii=False)
    for base_dir in (DOCS_DIR, REPORTS_DIR):
        dest = base_dir / MANIFEST_RELATIVE_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(manifest_json, encoding="utf-8")


def _write_section_content_files(conn, entries: list[tuple[str, list[str]]]) -> None:
    """The raw-text sibling of build_manifest()'s `sections` index.

    manifest.json's `sections` deliberately never carries comparison_text (see
    build_manifest()'s docstring) so it stays small as the archive grows -
    that invariant doesn't change here. Full trilingual content (topic_label +
    comparison_text) instead lands in one small JSON file per report date per
    language, assets/data/content/{date}_{lang}.json, keyed by section id.
    This is what topic.html's filtered results list fetches lazily, one file
    per distinct date actually needed for the page/batch currently on screen -
    never all dates at once, and never embedded in manifest.json.

    Splitting by BOTH date and language (not one combined file per date, or
    one giant all-dates file) keeps each fetch small regardless of how large
    the archive grows or how many languages exist: measured on the 2026-09-22
    archive (31 dates, 1538 sections), a single date's content in one language
    is 5-180KB (median ~35-50KB) of raw text, vs. 586KB for all 3 languages
    combined in the worst-case date - and a monolithic all-dates file would
    already be several MB and only grow. Same per-date grouping the pipeline
    already uses elsewhere (render_report(conn, date), get_report_sections_for_date)
    - not a new unit of work, just a new (smaller, text-only) output format for
    an existing one. A future consumer needing this same "everything about X
    between date A and B" query server-side (e.g. weekly-digest synthesis)
    would query report_sections directly via SQL, not read these JSON files -
    these exist purely as a browser-fetchable cache of the same underlying
    rows, generated at publish time like every other docs/ artifact.
    """
    for report_date, _sources in entries:
        by_lang: dict[str, dict[str, dict]] = {lang: {} for lang in ALL_LANGS}
        for s in get_report_sections_for_date(conn, report_date):
            section_id = str(s["id"])
            for lang in ALL_LANGS:
                by_lang[lang][section_id] = {
                    "topic_label": s[f"topic_label_{lang}"],
                    "comparison_text": s[f"comparison_text_{lang}"],
                }
        for lang, content in by_lang.items():
            payload = json.dumps(content, ensure_ascii=False)
            for base_dir in (DOCS_DIR, REPORTS_DIR):
                dest = base_dir / CONTENT_DIR_RELATIVE / f"{report_date}_{lang}.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(payload, encoding="utf-8")


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
    _copy_favicons()
    _copy_map()
    _copy_reports_to_docs()

    # Computed here (rather than at the very end, as before) because
    # build_homepage_html() now needs manifest["countries"] to statically
    # tag the map's accessibility markup - see _load_map_svg_inline().
    manifest = build_manifest(conn, entries)
    _write_section_content_files(conn, entries)
    conn.close()

    # All three languages build every page type below - German joined
    # archive/about/topic/accessibility/terms/homepage together on 2026-09-22
    # (see CLAUDE.md); no per-page-type language guard remains.
    for lang in ALL_LANGS:
        archive_html = build_index_html(
            entries,
            lang,
            report_link_prefix="",
            lang_hrefs={o: f"../{o}/archive.html" for o in other_langs(lang)},
            font_relative_path=f"../assets/fonts/{FONT_FILENAME}",
            asset_prefix="../",
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

        topic_html = build_topic_html(lang)
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "topic.html").write_text(topic_html, encoding="utf-8")
        print(f"  wrote topic.html for '{lang}'")

        filter_html = build_filter_html(lang)
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "filter.html").write_text(filter_html, encoding="utf-8")
        print(f"  wrote filter.html for '{lang}'")

        # German joined the trilingual set on 2026-09-22 (previously accessibility.html/
        # terms.html/the homepage stayed he/en-only) - all three now build for every
        # language in ALL_LANGS, same as archive/about/topic above.
        accessibility_html = build_accessibility_html(lang)
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "accessibility.html").write_text(accessibility_html, encoding="utf-8")
        print(f"  wrote accessibility.html for '{lang}'")

        terms_html = build_terms_html(lang)
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "terms.html").write_text(terms_html, encoding="utf-8")
        print(f"  wrote terms.html for '{lang}'")

        homepage_html = build_homepage_html(lang, is_root=False, countries=manifest["countries"])
        (DOCS_DIR / lang / "index.html").write_text(homepage_html, encoding="utf-8")
        print(f"  wrote index.html (homepage) for '{lang}'")

    root_archive_html = build_index_html(
        entries,
        "he",
        report_link_prefix="he/",
        lang_hrefs={o: f"{o}/archive.html" for o in other_langs("he")},
        font_relative_path=f"assets/fonts/{FONT_FILENAME}",
        asset_prefix="",
        accessibility_href="he/accessibility.html",
        terms_href="he/terms.html",
        filter_href="he/filter.html",
    )
    (DOCS_DIR / "archive.html").write_text(root_archive_html, encoding="utf-8")
    print(f"  wrote {DOCS_DIR / 'archive.html'} (root, Hebrew default)")

    root_homepage_html = build_homepage_html("he", is_root=True, countries=manifest["countries"])
    (DOCS_DIR / "index.html").write_text(root_homepage_html, encoding="utf-8")
    print(f"  wrote {DOCS_DIR / 'index.html'} (root homepage, Hebrew default)")

    _write_manifest(manifest)
    print(f"  wrote manifest.json ({len(manifest['sections'])} section(s), {len(manifest['countries'])} countrie(s))")
    print(f"  wrote {len(entries) * len(ALL_LANGS)} section-content file(s) under assets/data/content/")

    print(f"\nPublish complete: {len(entries)} report date(s) -> {DOCS_DIR}")


if __name__ == "__main__":
    run()
