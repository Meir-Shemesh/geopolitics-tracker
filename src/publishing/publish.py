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
from datetime import date, datetime, timezone
from pathlib import Path

from src.common.about_content import CONTENT, render_sections_html
from src.common.db import (
    get_all_biweekly_periods,
    get_all_reports,
    get_biweekly_topics_for_period,
    get_connection,
    get_dates_and_sources_for_biweekly_topic,
    get_geo_tags_for_section,
    get_report_sections_for_date,
    get_section_articles,
    init_db,
)
from src.common.geo_taxonomy import CONFLICT_ZONE_LABELS, COUNTRY_LIST, COUNTRY_TO_REGION, REGION_LABELS
from src.common.trends import build_country_week_trends, eligible_countries
from src.reporting.render_biweekly import build_biweekly_report_html, format_period_range, period_filename
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
    THEME_TOGGLE_SCRIPT_HTML,
    TRENDS_LABEL,
    build_footer_html,
    build_nav_html,
    category_css,
    esc,
    favicon_links_html,
    font_face_css,
    footer_hrefs_for,
    other_langs,
    print_force_light_css,
    section_coverage,
    shared_chrome_css,
    theme_toggle_html,
    theme_tokens_css,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
FONT_SOURCE_PATH = REPORTS_DIR / "assets" / "fonts" / FONT_FILENAME
LOGO_SOURCE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "assets" / "MS_Logo.png"
FAVICON_SOURCE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "assets"
MAP_SOURCE_PATH = Path(__file__).resolve().parent / "assets" / "map" / "world.svg"
MANIFEST_RELATIVE_PATH = Path("assets") / "data" / "manifest.json"
TRENDS_RELATIVE_PATH = Path("assets") / "data" / "trends.json"
CONTENT_DIR_RELATIVE = Path("assets") / "data" / "content"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "processed" / "tracker.db"
# Sibling of the repo (established 2026-09-20, PROJECT_LOG 4.44's README) - already
# outside git, already inside the project's own OneDrive-synced folder tree. Not
# moved here - see PROJECT_LOG for why an explicit dated-snapshot mechanism is still
# worth having even though OneDrive already mirrors the live file continuously.
BACKUP_DIR = PROJECT_ROOT.parent / "geopolitics-tracker-backups"
BACKUP_FILENAME_RE = re.compile(r"^tracker_(\d{4}-\d{2}-\d{2})\.db$")
BACKUP_RECENT_DAYS = 14  # keep every daily backup this fresh, in full
BACKUP_MAX_DAYS = 60  # beyond BACKUP_RECENT_DAYS but within this, keep Sundays only


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
    privacy_href: str = "privacy.html",
    trends_href: str = "trends.html",
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
{THEME_TOGGLE_SCRIPT_HTML}
<title>{esc(page_title)}</title>
{favicon_links_html(asset_prefix)}
<style>
  {font_face_css(font_relative_path)}

{theme_tokens_css()}

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
      <a class="top-nav-link" href="{esc(trends_href)}">{esc(TRENDS_LABEL[lang])}</a>
      {"".join(f'<a class="top-nav-link" href="{esc(lang_hrefs[o])}">{esc(LANG_LABEL[o])}</a>' for o in other_langs(lang) if o in lang_hrefs)}
      <a class="top-nav-link" href="mailto:{CONTACT_EMAIL}">{esc(CONTACT_LABEL[lang])}</a>
      {theme_toggle_html(lang)}
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
{build_footer_html(lang, accessibility_href, terms_href, privacy_href)}
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
{THEME_TOGGLE_SCRIPT_HTML}
<title>{esc(page_title)}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

{theme_tokens_css()}

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
    <h2 class="about-intro-title">{esc(content['about_title'])}</h2>
    <p class="about-intro-subtitle">{esc(content['about_subtitle'])}</p>
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
{THEME_TOGGLE_SCRIPT_HTML}
<title>{esc(page_title)}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

{theme_tokens_css()}

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

# Professional/general contact channels (added 2026-10-02, PROJECT_LOG) - shown
# alongside the accessibility-report email in the same "Contact us" section,
# given directly by the site owner, not invented.
PROFESSIONAL_LINKEDIN_URL = "https://www.linkedin.com/in/meir-shemesh-a18633aa/"
PROFESSIONAL_HOMEPAGE_URL = "https://meirshemesh.com"


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
    <p>לפניות מקצועיות, הארות או הערות בנושאי תוכן הדוחות - ניתן לפנות באותה
    כתובת מייל, או דרך:</p>
    <ul>
      <li><a href="{PROFESSIONAL_LINKEDIN_URL}" target="_blank" rel="noopener">לינקדאין</a></li>
      <li><a href="{PROFESSIONAL_HOMEPAGE_URL}" target="_blank" rel="noopener">אתר הבית</a></li>
    </ul>
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
    <p>Für berufliche Anfragen, Anregungen oder Anmerkungen zu den
    Berichtsinhalten erreichen Sie uns unter derselben E-Mail-Adresse oder
    über:</p>
    <ul>
      <li><a href="{PROFESSIONAL_LINKEDIN_URL}" target="_blank" rel="noopener">LinkedIn</a></li>
      <li><a href="{PROFESSIONAL_HOMEPAGE_URL}" target="_blank" rel="noopener">Persönliche Website</a></li>
    </ul>
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
    <p>For professional inquiries, feedback, or comments on the reports'
    content, you can reach us at the same email address, or via:</p>
    <ul>
      <li><a href="{PROFESSIONAL_LINKEDIN_URL}" target="_blank" rel="noopener">LinkedIn</a></li>
      <li><a href="{PROFESSIONAL_HOMEPAGE_URL}" target="_blank" rel="noopener">Personal website</a></li>
    </ul>
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


# Draft privacy policy (added 2026-10-02, PROJECT_LOG) - describes the aggregate-only,
# no-cookie, no-raw-IP-storage analytics approach decided for the site. Explicitly
# marked as an initial draft pending lawyer review in all 3 languages - not to be
# treated as finalized legal advice.
def build_privacy_html(lang: str) -> str:
    if lang == "he":
        page_title = "מדיניות פרטיות - גאופוליטיקה יומי"
        heading = "מדיניות פרטיות"
        body_html = f"""
    <h2>1. אילו נתונים נאספים</h2>
    <p>האתר אוסף נתוני-שימוש מצרפיים בלבד, לצורך סטטיסטיקה כללית על הקוראים שלו:</p>
    <ul>
      <li>מספר צפיות/ביקורים ביום</li>
      <li>שפת הדפדפן (מכותרת ה-Accept-Language)</li>
      <li>מדינת המקור (מזוהה לפי כתובת ה-IP, ברמת מדינה בלבד)</li>
      <li>כתובת-ההפניה (referrer) - מאיזה עמוד או אתר הגעתם</li>
      <li>סוג מכשיר ומשפחת דפדפן, ברמה כללית (למשל נייד/מחשב, Chrome/Safari/Firefox)</li>
    </ul>
    <h2>2. מה לא נאסף</h2>
    <p>האתר אינו משתמש בעוגיות (cookies), ואינו יוצר כל מזהה קבוע או ייחודי
    שמאפשר לשייך ביקורים שונים לאותו אדם - לא באמצעות עוגייה, לא באמצעות
    "טביעת-אצבע" של הדפדפן, ולא באמצעות חישוב קבוע (hash) על כתובת ה-IP. אין
    מעקב אחר משתמשים בין אתרים (cross-site tracking), ואין פרופיל אישי הנבנה
    עבור אף מבקר.</p>
    <h2>3. שימור נתונים</h2>
    <p>הנתונים המצרפיים המתוארים לעיל נשמרים ללא הגבלת זמן. מכיוון שמדובר
    בנתונים אגרגטיביים-אנונימיים בלבד, שאינם מאפשרים זיהוי של משתמש בודד,
    שימור ארוך-טווח אינו יוצר סיכון-פרטיות נוסף לאף משתמש.</p>
    <h2>4. טיפול בכתובת IP</h2>
    <p>כתובת ה-IP של כל בקשה משמשת באופן רגעי בלבד, לצורך זיהוי המדינה שממנה
    מגיעה הבקשה. לאחר השימוש הרגעי הזה כתובת ה-IP עצמה נמחקת ואינה נשמרת -
    במאגר הנתונים נשמר רק קוד-המדינה שחושב ממנה, לעולם לא כתובת ה-IP הגולמית.</p>
    <p>מעבר לכך, ספקי-התשתית של האתר - Cloudflare (המפעיל את שירות האנליטיקס
    המצרפי) ו-GitHub Pages (המארח את האתר עצמו) - מעבדים את כתובת ה-IP באופן
    זמני וברמת ה-edge שלהם, לצורך תפעולי בסיסי של השירות (כגון ניתוב-תעבורה
    והגנה מפני התקפות). עיבוד זה נפרד לחלוטין מקוד האנליטיקס של האתר עצמו
    (cf-analytics), שאינו ניגש לכתובת ה-IP כלל, וכפוף למדיניות-הפרטיות של
    אותם ספקים עצמם.</p>
    <h2>5. מי מפעיל את האתר</h2>
    <p>האתר מופעל ונכתב על ידי מאיר שמש, כפרויקט אישי. לכל שאלה או בקשה
    הקשורה לפרטיות ולנתונים הנאספים, ניתן לפנות ל:
    <a href="mailto:{ACCESSIBILITY_CONTACT_EMAIL}">{ACCESSIBILITY_CONTACT_EMAIL}</a>.</p>
    <p>האתר מופעל כיום כפרויקט אישי, שאינו מסחרי. בעל האתר שומר לעצמו את
    הזכות להפוך את האתר, כולו או חלקו, לפעילות מסחרית בעתיד - ובמקרה כזה,
    מדיניות הפרטיות תעודכן בהתאם לפני כל שינוי כאמור, ותשקף את מעמדו המסחרי
    המעודכן של האתר ואת ההשלכות הנובעות מכך על עיבוד הנתונים.</p>
    <h2>6. חוק הגנת הפרטיות (תיקון 13) ו-GDPR</h2>
    <p>זהו פרויקט אישי קטן ולא-מסחרי, המיועד לקוראים מישראל וממדינות נוספות.
    הנתונים הנאספים מצרפיים ואנונימיים במובהק - אינם מאפשרים זיהוי של מבקר
    ספציפי - ולכן רמת הסיכון לפרטיות נמוכה מאוד. עם זאת, ולמען גילוי נאות:</p>
    <p>בישראל חל חוק הגנת הפרטיות, התשמ"א-1981, לרבות תיקון 13 (בתוקף משנת
    2025), שהחמיר את חובות האבטחה והדיווח על מאגרי מידע. האתר פועל לפי עקרון
    צמצום-הנתונים (data minimization) - נאסף רק המינימום הנדרש לסטטיסטיקה
    כללית, ולא יותר.</p>
    <p>לקוראים מחוץ לישראל, ובפרט באיחוד האירופי: האתר אינו אוסף "נתונים
    אישיים" כהגדרתם בתקנת ה-GDPR (Regulation (EU) 2016/679), שכן הנתונים
    הנאספים מצרפיים ואינם ניתנים לשיוך למבקר מזוהה או ניתן-לזיהוי. לכל שאלה
    בנושא ניתן לפנות לכתובת המייל שלעיל.</p>
    <p>עודכן לאחרונה: אוקטובר 2026.</p>"""
    elif lang == "de":
        page_title = "Datenschutzerklärung - Tägliche Geopolitik"
        heading = "Datenschutzerklärung"
        body_html = f"""
    <h2>1. Welche Daten werden erhoben</h2>
    <p>Diese Website erhebt ausschließlich aggregierte Nutzungsstatistiken, für
    eine allgemeine Leserschaftsanalyse:</p>
    <ul>
      <li>Anzahl der Seitenaufrufe/Besuche pro Tag</li>
      <li>Browsersprache (aus dem Accept-Language-Header)</li>
      <li>Herkunftsland (anhand der IP-Adresse ermittelt, nur auf Länderebene)</li>
      <li>Referrer - von welcher Seite bzw. Website aus Sie gekommen sind</li>
      <li>Grobe Geräte- und Browserfamilie (z. B. mobil/Desktop, Chrome/Safari/Firefox)</li>
    </ul>
    <h2>2. Was nicht erhoben wird</h2>
    <p>Diese Website verwendet keine Cookies und erstellt keine dauerhafte oder
    eindeutige Kennung, die verschiedene Besuche derselben Person zuordnen
    würde - weder über ein Cookie, noch über Browser-Fingerprinting, noch über
    einen festen Hash der IP-Adresse. Es findet kein websiteübergreifendes
    Tracking statt, und es wird kein persönliches Profil für Besucherinnen
    oder Besucher erstellt.</p>
    <h2>3. Aufbewahrung der Daten</h2>
    <p>Die oben beschriebenen aggregierten Daten werden zeitlich unbegrenzt
    aufbewahrt. Da es sich ausschließlich um aggregierte, anonyme Daten
    handelt, die keine Identifizierung einer einzelnen Nutzerin bzw. eines
    einzelnen Nutzers ermöglichen, stellt eine langfristige Aufbewahrung kein
    zusätzliches Datenschutzrisiko dar.</p>
    <h2>4. Umgang mit IP-Adressen</h2>
    <p>Die IP-Adresse jeder Anfrage wird nur für einen Moment verwendet, um
    festzustellen, aus welchem Land die Anfrage stammt. Danach wird die
    IP-Adresse selbst verworfen und nicht gespeichert - in der Datenbank wird
    ausschließlich der daraus ermittelte Ländercode gespeichert, niemals die
    rohe IP-Adresse.</p>
    <p>Darüber hinaus verarbeiten die Infrastrukturanbieter dieser Website -
    Cloudflare (das den aggregierten Analysedienst betreibt) und GitHub Pages
    (das die Website selbst hostet) - IP-Adressen vorübergehend auf ihrer
    eigenen Edge-Ebene, für grundlegende betriebliche Zwecke des Dienstes
    (etwa Traffic-Routing und Schutz vor Angriffen). Diese Verarbeitung ist
    vollständig getrennt vom eigentlichen Analyse-Code der Website
    (cf-analytics), der überhaupt nicht auf die IP-Adresse zugreift, und
    unterliegt den jeweils eigenen Datenschutzerklärungen dieser Anbieter.</p>
    <h2>5. Wer diese Website betreibt</h2>
    <p>Diese Website wird von Meir Shemesh als persönliches Projekt betrieben
    und verfasst. Für Fragen oder Anliegen zum Datenschutz oder zu den
    erhobenen Daten:
    <a href="mailto:{ACCESSIBILITY_CONTACT_EMAIL}">{ACCESSIBILITY_CONTACT_EMAIL}</a>.</p>
    <p>Diese Website wird derzeit als persönliches, nicht-kommerzielles
    Projekt betrieben. Der Betreiber der Website behält sich das Recht vor,
    die Website ganz oder teilweise künftig in eine kommerzielle Tätigkeit
    umzuwandeln - in einem solchen Fall wird diese Datenschutzerklärung vor
    jeder derartigen Änderung entsprechend aktualisiert, um den aktualisierten
    kommerziellen Status der Website und die sich daraus ergebenden
    Auswirkungen auf die Datenverarbeitung widerzuspiegeln.</p>
    <h2>6. Israelisches Datenschutzrecht und DSGVO</h2>
    <p>Dies ist ein kleines, nicht-kommerzielles persönliches Projekt für
    Leserinnen und Leser in Israel und anderswo. Die erhobenen Daten sind
    echt aggregiert und anonym - sie lassen keine Identifizierung einer
    bestimmten besuchenden Person zu -, sodass das Datenschutzrisiko sehr
    gering ist. Der Vollständigkeit halber:</p>
    <p>In Israel gilt das Datenschutzgesetz (Privacy Protection Law),
    5741-1981, einschließlich der Novelle 13 (in Kraft seit 2025), die die
    Sicherheits- und Meldepflichten für Datenbanken verschärft hat. Diese
    Website folgt dem Grundsatz der Datenminimierung - es wird nur erhoben,
    was für allgemeine Statistiken nötig ist, nicht mehr.</p>
    <p>Für Leserinnen und Leser außerhalb Israels, insbesondere in der
    Europäischen Union: Diese Website erhebt keine „personenbezogenen Daten"
    im Sinne der DSGVO (Verordnung (EU) 2016/679), da die erhobenen Daten
    aggregiert sind und keiner identifizierten oder identifizierbaren Person
    zugeordnet werden können. Bei Fragen hierzu können Sie sich gerne an die
    oben genannte E-Mail-Adresse wenden.</p>
    <p>Zuletzt aktualisiert: Oktober 2026.</p>"""
    else:
        page_title = "Privacy Policy - Daily Geopolitics"
        heading = "Privacy Policy"
        body_html = f"""
    <h2>1. What data is collected</h2>
    <p>This site collects aggregate usage statistics only, for general
    readership analytics:</p>
    <ul>
      <li>Number of page views/visits per day</li>
      <li>Browser language (from the Accept-Language header)</li>
      <li>Country of origin (identified from the IP address, at country level only)</li>
      <li>Referrer - which page or site you arrived from</li>
      <li>Broad device and browser family (e.g. mobile/desktop, Chrome/Safari/Firefox)</li>
    </ul>
    <h2>2. What is not collected</h2>
    <p>This site does not use cookies, and does not create any persistent or
    unique identifier that would let different visits be linked to the same
    person - not via a cookie, not via browser fingerprinting, and not via a
    fixed hash of an IP address. There is no cross-site tracking, and no
    personal profile is built for any visitor.</p>
    <h2>3. Data retention</h2>
    <p>The aggregate data described above is kept indefinitely. Because this
    data is genuinely aggregate and anonymous, and does not allow
    identification of an individual user, long-term retention does not
    create any additional privacy risk to any user.</p>
    <h2>4. How IP addresses are handled</h2>
    <p>Each request's IP address is used only momentarily, to determine
    which country the request came from. After this momentary use, the IP
    address itself is discarded and not stored - only the resulting country
    code is kept in the database, never the raw IP address.</p>
    <p>Beyond this, the site's infrastructure providers - Cloudflare (which
    operates the aggregate analytics service) and GitHub Pages (which hosts
    the site itself) - process IP addresses momentarily at their own edge
    level, for basic operational purposes of the service (such as traffic
    routing and protection against attacks). This processing is entirely
    separate from the site's own analytics code (cf-analytics), which does
    not access the IP address at all, and is subject to those providers' own
    privacy policies.</p>
    <h2>5. Who operates this site</h2>
    <p>This site is operated and written by Meir Shemesh, as a personal
    project. For any question or request related to privacy or the data
    collected, contact:
    <a href="mailto:{ACCESSIBILITY_CONTACT_EMAIL}">{ACCESSIBILITY_CONTACT_EMAIL}</a>.</p>
    <p>This site currently operates as a personal, non-commercial project.
    The site owner reserves the right to turn the site, in whole or in part,
    into a commercial activity in the future - and in such a case, this
    privacy policy will be updated accordingly before any such change takes
    effect, to reflect the site's updated commercial status and the
    resulting implications for data processing.</p>
    <h2>6. Israeli privacy law and GDPR</h2>
    <p>This is a small, non-commercial personal project intended for readers
    in Israel and elsewhere. The data collected is genuinely aggregate and
    anonymous - it cannot be used to identify a specific visitor - so the
    privacy risk is very low. For transparency, however:</p>
    <p>In Israel, the Privacy Protection Law, 5741-1981, applies, including
    Amendment 13 (in effect since 2025), which tightened security and
    reporting obligations for databases. This site follows a data-
    minimization principle - collecting only what is needed for general
    statistics, and nothing more.</p>
    <p>For readers outside Israel, in particular in the European Union: this
    site does not collect "personal data" as defined under the GDPR
    (Regulation (EU) 2016/679), since the data collected is aggregate and
    cannot be linked to an identified or identifiable visitor. Any questions
    on this can be directed to the email address above.</p>
    <p>Last updated: October 2026.</p>"""

    return _build_static_page_html(lang, page_title, heading, body_html, "privacy.html")


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
{THEME_TOGGLE_SCRIPT_HTML}
<title>{esc(page_title)}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

  {category_css()}

{theme_tokens_css()}

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


_TRENDS_LABELS = {
    "he": {
        "page_title": "מגמות סיקור (בטא) - גאופוליטיקה יומי",
        "eyebrow": "גאופוליטיקה יומי",
        "heading": "מגמות סיקור לפי מדינה",
        "beta_badge": "בטא",
        "beta_note": "הארכיון כולל כרגע כ-7 שבועות של נתונים - מגמות ארוכות-טווח ייעשו אמינות יותר ככל שהארכיון יגדל.",
        "ranked_intro": "מה זז השבוע",
        "ranked_subtitle": "שינוי במספר המקורות הייחודיים שסיקרו כל מדינה, מול השבוע הקודם",
        "col_country": "מדינה",
        "col_change": "שינוי שבועי",
        "backlog_banner": "השבוע האחרון כולל השלמת-פרסום של ימים שהתעכבו - המספרים לא משקפים שבוע רגיל, והדירוג למטה מושפע מכך.",
        "backlog_point_note": "שבוע זה כולל השלמת ימים שלא פורסמו בזמן - המספר לא משקף שבוע רגיל.",
        "back_to_list": "חזרה לרשימה",
        "legend_selected": "המדינה הנבחרת",
        "legend_others": "מדינות זמינות אחרות",
        "new_label": "חדש",
        "week_of": "שבוע של",
        "sources_label": "מקורות",
        "table_caption": "מקורות ייחודיים שסיקרו את {country}, לפי שבוע",
        "loading": "טוען…",
    },
    "en": {
        "page_title": "Coverage Trends (Beta) - Daily Geopolitics",
        "eyebrow": "Daily Geopolitics",
        "heading": "Coverage Trends by Country",
        "beta_badge": "Beta",
        "beta_note": "The archive currently spans about 7 weeks of data - longer-term trends will become more reliable as it grows.",
        "ranked_intro": "What moved this week",
        "ranked_subtitle": "Change in distinct sources covering each country, vs. the previous week",
        "col_country": "Country",
        "col_change": "Weekly change",
        "backlog_banner": "The most recent week includes catch-up publishing for days that were delayed - the numbers don't reflect a typical week, and the ranking below is affected.",
        "backlog_point_note": "This week includes catch-up publishing for days that were delayed - the number doesn't reflect a typical week.",
        "back_to_list": "Back to list",
        "legend_selected": "Selected country",
        "legend_others": "Other available countries",
        "new_label": "New",
        "week_of": "Week of",
        "sources_label": "sources",
        "table_caption": "Distinct sources covering {country}, by week",
        "loading": "Loading…",
    },
    "de": {
        "page_title": "Berichterstattungstrends (Beta) - Tägliche Geopolitik",
        "eyebrow": "Tägliche Geopolitik",
        "heading": "Berichterstattungstrends nach Land",
        "beta_badge": "Beta",
        "beta_note": "Das Archiv umfasst derzeit etwa 7 Wochen an Daten - längerfristige Trends werden zuverlässiger, je größer das Archiv wird.",
        "ranked_intro": "Was sich diese Woche bewegt hat",
        "ranked_subtitle": "Veränderung der eindeutigen Quellen pro Land im Vergleich zur Vorwoche",
        "col_country": "Land",
        "col_change": "Wöchentliche Veränderung",
        "backlog_banner": "Die letzte Woche enthält nachträglich veröffentlichte, verspätete Tage - die Zahlen entsprechen keiner normalen Woche, und die Rangliste unten ist davon betroffen.",
        "backlog_point_note": "Diese Woche enthält nachträglich veröffentlichte, verspätete Tage - die Zahl entspricht keiner normalen Woche.",
        "back_to_list": "Zurück zur Liste",
        "legend_selected": "Ausgewähltes Land",
        "legend_others": "Andere verfügbare Länder",
        "new_label": "Neu",
        "week_of": "Woche vom",
        "sources_label": "Quellen",
        "table_caption": "Eindeutige Quellen, die {country} abdeckten, nach Woche",
        "loading": "Wird geladen…",
    },
}


_TRENDS_JS_TEMPLATE = """
(function () {
  var LABELS = __LABELS__;
  var LANG = "__LANG__";
  var NAME_KEY = "name_" + LANG;
  var container = document.getElementById("trends-root");

  function fmtWeek(w) {
    return LABELS.week_of + " " + w.start;
  }

  function pctChange(prev, last) {
    if (prev === 0) return last > 0 ? null : 0; // null => "New"
    return ((last - prev) / prev) * 100;
  }

  function renderRanked(data) {
    var weeks = data.weeks;
    var lastIdx = weeks.length - 1;
    var prevIdx = weeks.length - 2;
    var lastWeek = weeks[lastIdx];

    var banner = document.getElementById("backlog-banner");
    if (lastWeek && lastWeek.has_backlog) {
      banner.textContent = LABELS.backlog_banner;
      banner.hidden = false;
    }

    var rows = data.countries.map(function (c) {
      var last = c.n_sources[lastIdx] || 0;
      var prev = prevIdx >= 0 ? (c.n_sources[prevIdx] || 0) : 0;
      var pct = pctChange(prev, last);
      return { code: c.code, name: c[NAME_KEY], last: last, prev: prev, pct: pct };
    });
    rows.sort(function (a, b) {
      var av = a.pct === null ? Infinity : a.pct;
      var bv = b.pct === null ? Infinity : b.pct;
      return bv - av;
    });

    var tbody = document.getElementById("ranked-body");
    tbody.innerHTML = "";
    var maxAbsPct = Math.max.apply(null, rows.map(function (r) { return r.pct === null ? 0 : Math.abs(r.pct); }).concat([1]));

    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.className = "ranked-row";
      tr.tabIndex = 0;
      tr.setAttribute("role", "button");

      var tdName = document.createElement("td");
      tdName.className = "ranked-name";
      tdName.textContent = r.name;
      tr.appendChild(tdName);

      var tdChange = document.createElement("td");
      tdChange.className = "ranked-change";
      var isNew = r.pct === null;
      var isUp = !isNew && r.pct > 0;
      var barWrap = document.createElement("span");
      barWrap.className = "change-bar-wrap";
      var bar = document.createElement("span");
      bar.className = "change-bar " + (isNew || isUp ? "change-up" : "change-down");
      var widthPct = isNew ? 100 : Math.min(100, Math.round((Math.abs(r.pct) / maxAbsPct) * 100));
      bar.style.width = widthPct + "%";
      barWrap.appendChild(bar);
      var label = document.createElement("span");
      label.className = "change-label " + (isNew || isUp ? "change-up-text" : "change-down-text");
      label.textContent = isNew ? LABELS.new_label : (isUp ? "+" : "") + Math.round(r.pct) + "%";
      tdChange.appendChild(barWrap);
      tdChange.appendChild(label);
      tr.appendChild(tdChange);

      tr.addEventListener("click", function () { openExpanded(data, r.code); });
      tr.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openExpanded(data, r.code); }
      });
      tbody.appendChild(tr);
    });
  }

  function openExpanded(data, code) {
    document.getElementById("ranked-view").hidden = true;
    var panel = document.getElementById("expanded-view");
    panel.hidden = false;
    renderChart(data, code);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function closeExpanded() {
    document.getElementById("expanded-view").hidden = true;
    document.getElementById("ranked-view").hidden = false;
  }

  function renderChart(data, selectedCode) {
    var weeks = data.weeks;
    var selected = data.countries.find(function (c) { return c.code === selectedCode; });
    document.getElementById("expanded-title").textContent = selected[NAME_KEY];

    var W = 760, H = 320, padL = 36, padR = 16, padT = 16, padB = 36;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var globalMax = 1;
    data.countries.forEach(function (c) {
      c.n_sources.forEach(function (v) { if (v > globalMax) globalMax = v; });
    });

    function x(i) { return padL + (weeks.length === 1 ? 0 : (i / (weeks.length - 1)) * plotW); }
    function y(v) { return padT + plotH - (v / globalMax) * plotH; }

    var svgParts = [];
    svgParts.push('<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + selected[NAME_KEY] + '" preserveAspectRatio="xMidYMid meet">');

    // gridlines (recessive)
    for (var gy = 0; gy <= 4; gy++) {
      var yy = padT + (gy / 4) * plotH;
      svgParts.push('<line x1="' + padL + '" y1="' + yy + '" x2="' + (W - padR) + '" y2="' + yy + '" class="chart-grid"/>');
    }

    // background (non-selected) lines
    data.countries.forEach(function (c) {
      if (c.code === selectedCode) return;
      var pts = c.n_sources.map(function (v, i) { return x(i) + "," + y(v); }).join(" ");
      svgParts.push('<polyline points="' + pts + '" class="chart-line-muted"/>');
    });

    // selected line - drawn as individual segments so a backlog-adjacent
    // segment can get its own dash-array without affecting the whole line.
    for (var i = 0; i < weeks.length - 1; i++) {
      var segBacklog = weeks[i].has_backlog || weeks[i + 1].has_backlog;
      svgParts.push(
        '<line x1="' + x(i) + '" y1="' + y(selected.n_sources[i]) + '" x2="' + x(i + 1) + '" y2="' + y(selected.n_sources[i + 1]) + '" ' +
        'class="chart-line-selected' + (segBacklog ? ' chart-line-backlog' : '') + '"/>'
      );
    }

    // markers + invisible larger hit-targets for hover/focus
    weeks.forEach(function (w, i) {
      var cx = x(i), cy = y(selected.n_sources[i]);
      var markerClass = w.has_backlog ? "chart-point chart-point-backlog" : "chart-point";
      svgParts.push('<circle cx="' + cx + '" cy="' + cy + '" r="5" class="' + markerClass + '" data-i="' + i + '"/>');
      svgParts.push('<circle cx="' + cx + '" cy="' + cy + '" r="14" class="chart-hit" data-i="' + i + '" tabindex="0" role="img" aria-label="' +
        fmtWeek(w) + ': ' + selected.n_sources[i] + ' ' + LABELS.sources_label + (w.has_backlog ? '. ' + LABELS.backlog_point_note : '') + '"/>');
    });

    svgParts.push('</svg>');
    var chartEl = document.getElementById("chart-svg");
    chartEl.innerHTML = svgParts.join("");

    var tooltip = document.getElementById("chart-tooltip");
    chartEl.querySelectorAll(".chart-hit").forEach(function (hit) {
      var i = parseInt(hit.getAttribute("data-i"), 10);
      var w = weeks[i];
      var text = fmtWeek(w) + ": " + selected.n_sources[i] + " " + LABELS.sources_label +
        (w.has_backlog ? " — " + LABELS.backlog_point_note : "");
      function show(evt) {
        tooltip.textContent = text;
        tooltip.hidden = false;
        var rect = chartEl.getBoundingClientRect();
        var px = (evt.clientX !== undefined ? evt.clientX : rect.left + rect.width / 2) - rect.left;
        tooltip.style.left = Math.min(Math.max(px, 60), rect.width - 60) + "px";
      }
      hit.addEventListener("mouseenter", show);
      hit.addEventListener("focus", show);
      hit.addEventListener("mouseleave", function () { tooltip.hidden = true; });
      hit.addEventListener("blur", function () { tooltip.hidden = true; });
    });

    // Accessible data table alongside the chart (not toggled - always present)
    var thead = document.getElementById("data-table-head");
    var tbody = document.getElementById("data-table-body");
    document.getElementById("data-table-caption").textContent = LABELS.table_caption.replace("{country}", selected[NAME_KEY]);
    thead.innerHTML = "<tr><th></th>" + weeks.map(function (w) { return "<th>" + w.start + "</th>"; }).join("") + "</tr>";
    var rowCells = weeks.map(function (w, i) {
      var v = selected.n_sources[i];
      return "<td>" + v + (w.has_backlog ? " *" : "") + "</td>";
    }).join("");
    tbody.innerHTML = "<tr><th>" + LABELS.sources_label + "</th>" + rowCells + "</tr>";

    var footnote = document.getElementById("data-table-footnote");
    if (weeks.some(function (w) { return w.has_backlog; })) {
      footnote.textContent = "* " + LABELS.backlog_point_note;
      footnote.hidden = false;
    } else {
      footnote.hidden = true;
    }
  }

  document.getElementById("back-to-list").addEventListener("click", closeExpanded);

  fetch("../assets/data/trends.json")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      document.getElementById("trends-loading").hidden = true;
      document.getElementById("ranked-view").hidden = false;
      renderRanked(data);
    })
    .catch(function (err) {
      console.error("Failed to load trends.json", err);
      document.getElementById("trends-loading").textContent = "⚠";
    });
})();
"""


def build_trends_chart_html(lang: str) -> str:
    """Standalone coverage-trends CHART page (src/common/trends.py's groundwork,
    PROJECT_LOG 4.78/4.79) - docs/{lang}/trendschart.html only, no root copy, same
    convention as about.html/topic.html/filter.html (a destination, not a
    primary landing page). Reached from the new trends.html HUB page (PROJECT_LOG
    4.8x) as its "existing graphic view" card, not from the top-nav directly
    anymore - the top-nav "Trends" link now goes to the hub instead (same literal
    href value, "trends.html", unchanged in build_nav_html() - only what's SERVED
    at that path changed, so none of the other ~50 pages that link there needed
    regeneration for this). Content/logic of this page itself is explicitly
    UNCHANGED by that reshuffle (still beta-badged, still not redesigned) - only
    its filename and its own back-link/lang-switch hrefs moved.

    Deliberately NOT a per-country categorical palette: the spec this was
    built against treats the 10 non-selected countries as recessive
    background context, not an identity each reader needs to tell apart from
    the others (see the module's own JS - one highlight color for whichever
    country is selected, one neutral muted tone for the rest). Validated
    with the dataviz skill's palette checker: the one real two-color job on
    this page (the up/down change indicator) passes all checks in both
    themes; an 11-way categorical attempt at reusing CATEGORY_STYLES did not
    (two colors landed near-identical under CVD simulation) - see the
    build session's notes for the rejected intermediate palettes.
    """
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    L = _TRENDS_LABELS[lang]

    js_code = _TRENDS_JS_TEMPLATE.replace("__LABELS__", json.dumps(L, ensure_ascii=False)).replace("__LANG__", lang)

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{THEME_TOGGLE_SCRIPT_HTML}
<title>{esc(L['page_title'])}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

{theme_tokens_css()}

  :root {{ --trend-down: #1066a3; --trend-muted-line: var(--border); }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{ --trend-down: #4a93c2; --trend-muted-line: #6e624a; }}
  }}
  :root[data-theme="dark"] {{ --trend-down: #4a93c2; --trend-muted-line: #6e624a; }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "{FONT_FAMILY}", system-ui, sans-serif;
    line-height: 1.7;
  }}

  .top-nav {{
    max-width: 48rem;
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
    padding: 2.25rem 1.5rem 1.75rem;
  }}
  .masthead-inner {{ max-width: 48rem; margin: 0 auto; }}
  .eyebrow {{
    margin: 0 0 .5rem;
    font-size: .85rem;
    font-weight: 600;
    letter-spacing: .04em;
    color: var(--masthead-accent);
    text-transform: uppercase;
  }}
  .trends-heading-row {{ display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }}
  .report-title {{ margin: 0; font-size: 2rem; font-weight: 800; letter-spacing: -0.01em; }}
  .beta-badge {{
    display: inline-block;
    font-size: .72rem;
    font-weight: 700;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: var(--chip-selected-text);
    background: var(--masthead-accent);
    border-radius: .4rem;
    padding: .2rem .55rem;
  }}
  .beta-note {{ margin: .6rem 0 0; font-size: .88rem; color: var(--text-muted); max-width: 40rem; }}

  .trends-body {{ max-width: 48rem; margin: 0 auto; padding: 2rem 1.5rem 4rem; }}

  .banner {{
    border: 1px solid var(--border);
    border-inline-start: 4px solid var(--trend-down);
    background: var(--bg-elevated);
    border-radius: .5rem;
    padding: .85rem 1rem;
    font-size: .9rem;
    margin-bottom: 1.5rem;
  }}

  .ranked-intro {{ margin: 0 0 .2rem; font-size: 1.3rem; font-weight: 800; }}
  .ranked-subtitle {{ margin: 0 0 1.2rem; font-size: .88rem; color: var(--text-muted); }}

  table {{ width: 100%; border-collapse: collapse; }}
  .ranked-row {{ cursor: pointer; border-bottom: 1px solid var(--border); }}
  .ranked-row:hover, .ranked-row:focus {{ background: var(--bg-elevated); outline: none; }}
  .ranked-row td {{ padding: .75rem .4rem; }}
  .ranked-name {{ font-weight: 700; white-space: nowrap; }}
  .ranked-change {{ width: 60%; direction: ltr; }}
  .change-bar-wrap {{
    display: inline-block;
    width: 55%;
    height: .55rem;
    background: var(--border);
    border-radius: .3rem;
    overflow: hidden;
    vertical-align: middle;
    margin-inline-end: .6rem;
  }}
  .change-bar {{ display: block; height: 100%; }}
  .change-up {{ background: var(--masthead-accent); }}
  .change-down {{ background: var(--trend-down); }}
  .change-label {{ font-weight: 700; font-variant-numeric: tabular-nums; }}
  .change-up-text {{ color: var(--masthead-accent); }}
  .change-down-text {{ color: var(--trend-down); }}

  #trends-loading {{ color: var(--text-muted); padding: 2rem 0; }}

  .expanded-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }}
  #expanded-title {{ margin: 0; font-size: 1.3rem; font-weight: 800; }}
  .back-btn {{
    background: none;
    border: 1px solid var(--border);
    border-radius: .4rem;
    color: var(--text);
    font-family: inherit;
    font-size: .85rem;
    padding: .4rem .8rem;
    cursor: pointer;
  }}
  .back-btn:hover {{ border-color: var(--masthead-accent); color: var(--masthead-accent); }}

  .chart-legend {{ display: flex; gap: 1.2rem; font-size: .82rem; color: var(--text-muted); margin-bottom: .6rem; direction: ltr; }}
  .legend-swatch {{ display: inline-block; width: 1.4rem; height: 2px; vertical-align: middle; margin-inline-end: .4rem; }}
  .legend-selected .legend-swatch {{ background: var(--masthead-accent); height: 3px; }}
  .legend-others .legend-swatch {{ background: var(--trend-muted-line); }}

  .chart-wrap {{ position: relative; direction: ltr; }}
  #chart-svg svg {{ width: 100%; height: auto; display: block; }}
  .chart-grid {{ stroke: var(--border); stroke-width: 1; }}
  .chart-line-muted {{ fill: none; stroke: var(--trend-muted-line); stroke-width: 1.5; opacity: .75; }}
  .chart-line-selected {{ fill: none; stroke: var(--masthead-accent); stroke-width: 3; stroke-linecap: round; }}
  .chart-line-backlog {{ stroke-dasharray: 5 4; }}
  .chart-point {{ fill: var(--masthead-accent); stroke: var(--bg-elevated); stroke-width: 1.5; }}
  .chart-point-backlog {{ fill: var(--bg-elevated); stroke: var(--masthead-accent); stroke-width: 2; stroke-dasharray: 2 2; }}
  .chart-hit {{ fill: transparent; cursor: pointer; }}
  .chart-hit:focus {{ outline: 2px solid var(--masthead-accent); outline-offset: 2px; }}

  #chart-tooltip {{
    position: absolute;
    top: -.5rem;
    transform: translate(-50%, -100%);
    background: var(--text);
    color: var(--bg);
    font-size: .8rem;
    padding: .4rem .6rem;
    border-radius: .35rem;
    white-space: nowrap;
    pointer-events: none;
  }}

  .data-table-wrap {{ margin-top: 1.5rem; overflow-x: auto; direction: ltr; }}
  .data-table-wrap table {{ font-size: .82rem; }}
  .data-table-wrap th, .data-table-wrap td {{ border: 1px solid var(--border); padding: .4rem .5rem; text-align: center; }}
  .data-table-wrap caption {{ caption-side: top; text-align: start; font-size: .82rem; color: var(--text-muted); margin-bottom: .4rem; }}
  .table-footnote {{ font-size: .8rem; color: var(--text-muted); margin: .6rem 0 0; }}

  {shared_chrome_css()}
</style>
</head>
<body>
{build_nav_html("trends.html", {o: f"../{o}/trendschart.html" for o in other_langs(lang)}, lang)}
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(L['eyebrow'])}</p>
      <div class="trends-heading-row">
        <h1 class="report-title">{esc(L['heading'])}</h1>
        <span class="beta-badge">{esc(L['beta_badge'])}</span>
      </div>
      <p class="beta-note">{esc(L['beta_note'])}</p>
    </div>
  </header>
  <main class="trends-body">
    <p id="trends-loading">{esc(L['loading'])}</p>
    <div id="banner-backlog-wrap">
      <p class="banner" id="backlog-banner" hidden></p>
    </div>

    <section id="ranked-view" hidden>
      <h2 class="ranked-intro">{esc(L['ranked_intro'])}</h2>
      <p class="ranked-subtitle">{esc(L['ranked_subtitle'])}</p>
      <table>
        <thead>
          <tr><th>{esc(L['col_country'])}</th><th>{esc(L['col_change'])}</th></tr>
        </thead>
        <tbody id="ranked-body"></tbody>
      </table>
    </section>

    <section id="expanded-view" hidden>
      <div class="expanded-header">
        <h2 id="expanded-title"></h2>
        <button class="back-btn" id="back-to-list" type="button">{esc(L['back_to_list'])}</button>
      </div>
      <div class="chart-legend">
        <span class="legend-selected"><span class="legend-swatch"></span>{esc(L['legend_selected'])}</span>
        <span class="legend-others"><span class="legend-swatch"></span>{esc(L['legend_others'])}</span>
      </div>
      <div class="chart-wrap">
        <div id="chart-svg"></div>
        <div id="chart-tooltip" hidden></div>
      </div>
      <div class="data-table-wrap">
        <table>
          <caption id="data-table-caption"></caption>
          <thead id="data-table-head"></thead>
          <tbody id="data-table-body"></tbody>
        </table>
        <p class="table-footnote" id="data-table-footnote" dir="{dir_attr}" hidden></p>
      </div>
    </section>
  </main>
{build_footer_html(lang, *footer_hrefs_for(lang))}
  <script>{js_code}</script>
</body>
</html>
"""


_TRENDS_HUB_LABELS = {
    "he": {
        "page_title": "מגמות - גאופוליטיקה יומי",
        "eyebrow": "גאופוליטיקה יומי",
        "heading": "מגמות",
        "tagline": "כיסוי גאופוליטי לאורך זמן - דוחות נרטיביים דו-שבועיים, וניתוח-מגמות גיאוגרפי",
        "periods_heading": "דוחות מגמות דו-שבועיים",
        "no_periods": "עדיין לא פורסמו דוחות דו-שבועיים.",
        "topics_word": "נושאים",
        "chart_card_title": "ניתוח-מגמות גיאוגרפי (גרסה ראשונית)",
        "chart_card_body": "תצוגה גרפית של עוצמת-הסיקור לפי מדינה לאורך זמן. גרסה ראשונית - עוברת עיצוב מחדש בהמשך.",
        "chart_card_cta": "לתצוגה ←",
    },
    "en": {
        "page_title": "Trends - Daily Geopolitics",
        "eyebrow": "Daily Geopolitics",
        "heading": "Trends",
        "tagline": "Geopolitical coverage over time - biweekly narrative reports, and geographic trend analysis",
        "periods_heading": "Biweekly Trends Reports",
        "no_periods": "No biweekly reports have been published yet.",
        "topics_word": "topics",
        "chart_card_title": "Geographic Trend Analysis (Initial Version)",
        "chart_card_body": "A chart view of coverage intensity by country over time. Initial version - a redesign is planned.",
        "chart_card_cta": "View ←",
    },
    "de": {
        "page_title": "Trends - Tägliche Geopolitik",
        "eyebrow": "Tägliche Geopolitik",
        "heading": "Trends",
        "tagline": "Geopolitische Berichterstattung im Zeitverlauf - zweiwöchentliche Erzählberichte und geografische Trendanalyse",
        "periods_heading": "Zweiwöchentliche Trendberichte",
        "no_periods": "Es wurden noch keine zweiwöchentlichen Berichte veröffentlicht.",
        "topics_word": "Themen",
        "chart_card_title": "Geografische Trendanalyse (Erste Version)",
        "chart_card_body": "Eine Diagrammansicht der Berichterstattungsintensität nach Land im Zeitverlauf. Erste Version - eine Neugestaltung ist geplant.",
        "chart_card_cta": "Ansehen ←",
    },
}


def build_trends_hub_html(lang: str, periods: list[dict]) -> str:
    """The new primary entry point for all "Trends" content (PROJECT_LOG 4.8x) -
    docs/{lang}/trends.html, same filename/href the top-nav "Trends" link and the
    homepage banner already point to (see build_nav_html()/build_homepage_html()),
    so neither needed to change. Two sections, per the spec: (1) an index of
    biweekly narrative reports, newest first, baked in at build time (same
    precedent as archive.html's own per-date listing - not a runtime fetch,
    since this page is already rebuilt by publish.py every time a new period is
    written); (2) a card linking out to the existing coverage-trends CHART page
    (trendschart.html, see build_trends_chart_html() - explicitly unmodified
    content/logic), clearly labeled as an initial version pending its own future
    redesign. `periods` is a list of biweekly_periods DB rows (dict-like) plus an
    injected "topic_count" key, newest-end_date-first."""
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    L = _TRENDS_HUB_LABELS[lang]

    period_cards = []
    for p in periods:
        range_label = format_period_range(p["start_date"], p["end_date"], lang)
        href = period_filename(p["start_date"], p["end_date"], lang)
        overview = p[f"overview_{lang}"]
        period_cards.append(f"""
      <a class="period-card" href="{esc(href)}">
        <p class="period-card-range">{esc(range_label)}</p>
        <p class="period-card-overview">{esc(overview)}</p>
        <p class="period-card-count">{p['topic_count']} {esc(L['topics_word'])}</p>
      </a>""")
    periods_html = "".join(period_cards) if period_cards else f'<p class="no-periods">{esc(L["no_periods"])}</p>'

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{THEME_TOGGLE_SCRIPT_HTML}
<title>{esc(L['page_title'])}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

{theme_tokens_css()}

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
    padding: 2.25rem 1.5rem 1.75rem;
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
  .report-title {{ margin: 0; font-size: 2rem; font-weight: 800; letter-spacing: -0.01em; }}
  .tagline {{ margin: .6rem 0 0; font-size: 1.02rem; color: var(--text-muted); max-width: 38rem; }}

  main {{ max-width: 44rem; margin: 0 auto; padding: 2rem 1.5rem 3rem; }}
  .section-heading {{ font-size: 1.1rem; font-weight: 700; margin: 0 0 1rem; }}

  .period-card {{
    display: block;
    text-decoration: none;
    color: inherit;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: .9rem;
    padding: 1.1rem 1.3rem;
    margin-bottom: 1rem;
  }}
  .period-card:hover {{ border-color: var(--masthead-accent); }}
  .period-card-range {{ margin: 0 0 .4rem; font-size: 1.1rem; font-weight: 700; color: var(--masthead-accent); }}
  .period-card-overview {{
    margin: 0 0 .5rem;
    font-size: .92rem;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .period-card-count {{ margin: 0; font-size: .78rem; color: var(--text-muted); }}
  .no-periods {{ color: var(--text-muted); font-size: .92rem; }}

  .chart-card {{
    display: block;
    text-decoration: none;
    color: inherit;
    background: var(--bg-elevated);
    border: 1px dashed var(--border);
    border-radius: .9rem;
    padding: 1.1rem 1.3rem;
    margin-top: 1.75rem;
  }}
  .chart-card:hover {{ border-color: var(--masthead-accent); }}
  .chart-card-title {{ margin: 0 0 .4rem; font-size: 1.02rem; font-weight: 700; }}
  .chart-card-body {{ margin: 0 0 .5rem; font-size: .88rem; color: var(--text-muted); }}
  .chart-card-cta {{ margin: 0; font-size: .85rem; font-weight: 600; color: var(--masthead-accent); }}

  {shared_chrome_css()}
</style>
</head>
<body>
{build_nav_html("archive.html", {o: f"../{o}/trends.html" for o in other_langs(lang)}, lang)}
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(L['eyebrow'])}</p>
      <h1 class="report-title">{esc(L['heading'])}</h1>
      <p class="tagline">{esc(L['tagline'])}</p>
    </div>
  </header>
  <main>
    <h2 class="section-heading">{esc(L['periods_heading'])}</h2>
    {periods_html}
    <a class="chart-card" href="trendschart.html">
      <p class="chart-card-title">{esc(L['chart_card_title'])}</p>
      <p class="chart-card-body">{esc(L['chart_card_body'])}</p>
      <p class="chart-card-cta">{esc(L['chart_card_cta'])}</p>
    </a>
  </main>
{build_footer_html(lang, *footer_hrefs_for(lang))}
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
    export_label = {"he": "ייצוא / הדפסה", "en": "Export / Print", "de": "Exportieren / Drucken"}[lang]

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
{THEME_TOGGLE_SCRIPT_HTML}
<title>{esc(page_title)}</title>
{favicon_links_html("../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

  {category_css()}

{theme_tokens_css()}

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

  .export-controls {{ display: flex; align-items: center; gap: .8rem; flex-wrap: wrap; margin: -.4rem 0 1.4rem; }}
  .export-print-btn {{
    font-family: inherit;
    font-size: .85rem;
    font-weight: 600;
    padding: .5rem 1.1rem;
    border: 1px solid var(--border);
    border-radius: .6rem;
    background: var(--bg-elevated);
    color: var(--text);
    cursor: pointer;
  }}
  .export-print-btn:hover, .export-print-btn:focus-visible {{ border-color: var(--masthead-accent); color: var(--masthead-accent); }}
  .export-print-btn:disabled {{ opacity: .5; cursor: default; }}
  .export-note {{ font-size: .8rem; color: var(--text-muted); }}
  .print-compact-line {{ display: none; }}

  {_filter_builder_css()}

  {shared_chrome_css()}

  /* Export/print (2026-09-24, compact threshold raised 2026-09-24 after real
     usage feedback - see PROJECT_LOG) - browser print only, no server-side
     generation. One rule set for every result count: hide interactive-only
     chrome (nav, footer already via shared_chrome_css, filter panel,
     load-more, the export controls themselves) and strip card decoration to
     save ink. A SEPARATE compact mode (body.print-compact-mode, set by JS
     when the filtered count exceeds COMPACT_PRINT_THRESHOLD - see
     _TOPIC_JS_TEMPLATE) swaps each full card for the one-line
     date/source/headline summary already computed at render time
     (.print-compact-line) instead of the full comparison text - printing
     hundreds of full multi-sentence comparisons defeats the point of a
     reference export, so very large sets get a dense list instead.
     Small/medium sets (now up to 500, not 150 - a real 182-result export
     reducing to headline-only lines felt wrong in practice) keep the full
     readable card, matching this page's whole premise (full content inline,
     not just titles). This is now a SEPARATE, higher threshold than the
     export note's size heads-up wording (still ~150) - see PROJECT_LOG for
     why they started as one shared number and were split apart. */
  @media print {{
{print_force_light_css()}
    .top-nav, .filter-panel-wrapper, .load-more-btn, .topic-loading,
    .filter-suggestion-banner, .export-controls, .permalink-icon {{ display: none !important; }}

    /* body/masthead below are still hardcoded to plain black/white rather than
       reading the tokens print_force_light_css() just pinned above - that's
       deliberate, not a leftover: this print layout already intentionally
       strips all color for a plain paper look (see .topic-result below, which
       also drops to plain #999 borders/no background), so it was never
       theme-dependent color to begin with. print_force_light_css() exists
       here specifically to close the *category-badge* gap (--tok-{{key}}-
       color/-bg, read through --cat-color/--cat-bg on .category-badge) - the
       one thing on this page that WAS still theme-dependent in print. */
    body {{ background: #fff; color: #000; }}
    .masthead {{ border-bottom-color: #000; }}
    .topic-result {{
      border: none;
      border-inline-start: none;
      border-bottom: 1px solid #999;
      border-radius: 0;
      background: none;
      padding: .6rem 0;
      margin: 0;
      break-inside: avoid;
    }}
    .topic-result-sources {{ border-top: none; padding-top: 0; }}

    body.print-compact-mode .topic-result {{ padding: .12rem 0; }}
    body.print-compact-mode .topic-result-meta,
    body.print-compact-mode .topic-result-title,
    body.print-compact-mode .topic-result-text,
    body.print-compact-mode .topic-result-sources {{ display: none; }}
    body.print-compact-mode .print-compact-line {{
      display: block;
      font-size: 9pt;
      line-height: 1.4;
    }}
  }}
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
    <div class="export-controls">
      <button type="button" class="export-print-btn" id="export-print-btn" disabled>{esc(export_label)}</button>
      <span class="export-note" id="export-note"></span>
    </div>
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
  // Export/print, two SEPARATE thresholds (split 2026-09-24 after real usage
  // feedback - originally one shared number, 150, for both; see PROJECT_LOG).
  // EXPORT_NOTE_THRESHOLD: above this, the on-screen note switches to the
  // explicit size heads-up wording - unchanged from the original spec (~150).
  var EXPORT_NOTE_THRESHOLD = 150;
  // COMPACT_PRINT_THRESHOLD: above this, @media print swaps full cards for
  // one-line summaries (body.print-compact-mode). Raised 150 -> 500: a
  // 182-result export triggering headline-only printing felt wrong in
  // practice - reducing genuinely browsable-sized result sets (not just
  // whole-archive-sized ones like a common region's 896) to bare headlines
  // defeated the point of a reading-list export. 500 is still well short of
  // the largest real filters seen (e.g. "Europe" ~900), so those still get
  // the compact list they need to stay usable as a reference export.
  var COMPACT_PRINT_THRESHOLD = 500;
  // Rough estimates only, for the heads-up note's "roughly N pages" - which
  // constant applies depends on which print layout will actually be used
  // (see updateExportNote()), never to block or cap anything.
  var LINES_PER_PAGE_ESTIMATE = 45; // compact mode: one line/result at 9pt
  var FULL_CARD_RESULTS_PER_PAGE_ESTIMATE = 4; // full-card mode: much rougher,
                                                 // comparison-text length varies a lot
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
      document.body.classList.toggle("print-compact-mode", allIds.length > COMPACT_PRINT_THRESHOLD);
      wireExportButton();
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

  // Soft warning, never a hard cap: for large result sets the note just says
  // so, in words, before the click - no confirmation dialog, no disabled
  // button past a size limit. Printing itself is unaffected by count; only
  // the wording and the compact-vs-full layout (see the @media print CSS)
  // change.
  function updateExportNote(count) {
    var noteEl = document.getElementById("export-note");
    if (!noteEl) return;
    if (!count) {
      noteEl.textContent = "";
      return;
    }
    if (count <= EXPORT_NOTE_THRESHOLD) {
      noteEl.textContent = LANG === "he" ? "ייצוא " + count + " תוצאות"
        : LANG === "de" ? count + " Ergebnisse exportieren"
        : "Exporting " + count + " result" + (count === 1 ? "" : "s");
      return;
    }
    // Page estimate must match whichever layout will actually print - above
    // COMPACT_PRINT_THRESHOLD that's the dense one-line-per-result mode,
    // below it (but still over EXPORT_NOTE_THRESHOLD) it's still full cards,
    // which fit far fewer per page.
    var perPage = count > COMPACT_PRINT_THRESHOLD ? LINES_PER_PAGE_ESTIMATE : FULL_CARD_RESULTS_PER_PAGE_ESTIMATE;
    var pages = Math.max(1, Math.round(count / perPage));
    noteEl.textContent = LANG === "he" ? "זה יכלול כ-" + count + " תוצאות, בערך " + pages + " עמודים"
      : LANG === "de" ? "Dies umfasst etwa " + count + " Ergebnisse, ungefähr " + pages + " Seiten"
      : "This will include ~" + count + " results across roughly " + pages + " pages";
  }

  function wireExportButton() {
    var btn = document.getElementById("export-print-btn");
    if (!btn) return;
    updateExportNote(allIds.length);
    btn.disabled = !allIds.length;
    if (btn.dataset.wired) return; // filters don't change without a full page load, but guard anyway
    btn.dataset.wired = "1";
    var defaultLabel = btn.textContent;
    var loadingLabel = LANG === "he" ? "מכין…" : LANG === "de" ? "Wird vorbereitet…" : "Preparing…";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      btn.textContent = loadingLabel;
      loadAllRemaining().then(function () {
        btn.textContent = defaultLabel;
        btn.disabled = false;
        window.print();
      });
    });
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
    if (!container) return Promise.resolve();
    var batch = allIds.slice(shownCount, shownCount + PAGE_SIZE);
    if (!batch.length) return Promise.resolve();

    var loading = document.createElement("p");
    loading.className = "topic-loading";
    loading.textContent = LANG === "he" ? "טוען…" : LANG === "de" ? "Wird geladen…" : "Loading…";
    container.appendChild(loading);

    var dates = uniqueDates(batch.map(function (id) { return currentManifest.sections[id].date; }));
    // Returns the promise (not fire-and-forget) so callers - specifically the
    // export/print button's "load everything, then print" sequence below -
    // can chain onto real completion instead of guessing a delay.
    return ensureContentLoaded(dates).then(function () {
      loading.remove();
      batch.forEach(function (id) { renderItem(container, id); });
      shownCount += batch.length;
      updateLoadMoreButton(container);
    });
  }

  // Recursively drains every remaining batch (beyond whatever pagination has
  // already loaded on screen) before the export/print button calls
  // window.print() - printing only ever captures what's actually in the DOM,
  // and pagination deliberately keeps most of a large result set un-rendered
  // until "load more" is clicked. Sequential, not parallel, batches: content
  // fetches are already deduped/cached per date (ensureContentLoaded), so
  // this costs nothing extra beyond normal pagination, just runs it to
  // completion instead of one click at a time.
  function loadAllRemaining() {
    if (shownCount >= allIds.length) return Promise.resolve();
    return loadNextBatch().then(loadAllRemaining);
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
    var sourcesText = section.sources.map(function (s) { return names[s] || s; }).join(", ");
    sources.textContent = sourcesText;

    // Print-only (see @media print / body.print-compact-mode): a single
    // "date · sources · headline" line, precomputed here rather than derived
    // from the full card via CSS, so the print stylesheet just toggles
    // visibility instead of trying to reassemble text across elements.
    var printLine = document.createElement("p");
    printLine.className = "print-compact-line";
    printLine.textContent = formatShortDate(section.date) + " · " + sourcesText + " · " + (content ? content.topic_label : topicFor(section));

    item.appendChild(meta);
    item.appendChild(title);
    item.appendChild(text);
    item.appendChild(sources);
    item.appendChild(printLine);
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
  var TRENDS_HREF = "__TRENDS_HREF__";

  fetch(PREFIX + "assets/data/manifest.json")
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function (err) { console.error("Failed to load manifest.json", err); });

  // Independent fetch/catch from the manifest above - a trends.json hiccup
  // (or an archive still too young to have any eligible country yet) must
  // never take down the rest of the homepage with it.
  fetch(PREFIX + "assets/data/trends.json")
    .then(function (r) { return r.json(); })
    .then(renderTrendsCard)
    .catch(function (err) { console.error("Failed to load trends.json", err); });

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

  // Shared "how much coverage" color scale - one function instead of two
  // near-identical color-mix() calculations (map + timeline), so the same
  // intensity always reads as the same color across both modules. Capped at
  // 55% (not higher) per the 2026-09-16 WCAG audit on the timeline's own
  // text-over-fill contrast - kept here for the map too even though it has
  // no text over the fill, for one consistent scale rather than two.
  function coverageColor(intensity) {
    var pct = Math.round(20 + intensity * 35);
    return "color-mix(in srgb, var(--masthead-accent) " + pct + "%, var(--bg-elevated))";
  }

  function positionTooltip(tooltip, ev) {
    var offset = 14;
    var x = ev.clientX + offset;
    var y = ev.clientY + offset;
    var maxX = window.innerWidth - tooltip.offsetWidth - 8;
    var maxY = window.innerHeight - tooltip.offsetHeight - 8;
    tooltip.style.left = Math.max(0, Math.min(x, maxX)) + "px";
    tooltip.style.top = Math.max(0, Math.min(y, maxY)) + "px";
  }

  function renderMap(manifest) {
    var svg = document.getElementById("world-map");
    if (!svg) return;
    var tooltip = document.getElementById("map-tooltip");
    var maxCount = 0;
    Object.keys(manifest.countries).forEach(function (code) {
      maxCount = Math.max(maxCount, manifest.countries[code].section_ids.length);
    });
    var candidates = svg.querySelectorAll("[id]");
    candidates.forEach(function (el) {
      if (el.id.length !== 2) return;
      var code = el.id.toUpperCase();
      var country = manifest.countries[code];
      if (!country) return;
      el.classList.add("has-coverage");
      var intensity = maxCount ? country.section_ids.length / maxCount : 0;
      el.style.fill = coverageColor(intensity);
      var titleEl = el.querySelector("title");
      if (titleEl) {
        titleEl.textContent = country[LABEL_KEY];
      }
      el.addEventListener("click", function () {
        selectCountry(manifest, code);
      });
      if (tooltip) {
        // Reads the same aria-label text already set at build time (see
        // _load_map_svg_inline/_tag_country_element) instead of duplicating
        // the "N reports" phrasing in JS - one source of truth for both
        // screen-reader and mouse users. pointer-events:none on the tooltip
        // itself (CSS) keeps it from ever intercepting the click/hover that
        // is actually on the country shape underneath it.
        el.addEventListener("mouseenter", function (ev) {
          tooltip.textContent = el.getAttribute("aria-label") || country[LABEL_KEY];
          tooltip.style.display = "block";
          positionTooltip(tooltip, ev);
        });
        el.addEventListener("mousemove", function (ev) {
          positionTooltip(tooltip, ev);
        });
        el.addEventListener("mouseleave", function () {
          tooltip.style.display = "none";
        });
      }
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
      cell.style.background = coverageColor(intensity);
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

  // Redesigned (PROJECT_LOG 4.8x) from a bare, textless sparkline into the
  // site's primary entry point to "Trends" (biweekly narrative reports +
  // the coverage-trends chart) - the previous version relied entirely on
  // "the mini line-chart IS the label," which real feedback found unclear.
  // Now mirrors latest-card's own title/description/CTA structure so it
  // reads at the same glance, with the sparkline kept as a small
  // supporting visual (data-driven, not hardcoded - same country-pick
  // logic as before) rather than the card's only content.
  function buildSparklinePoints(values, w, h, pad) {
    var max = 0;
    for (var i = 0; i < values.length; i++) {
      if (values[i] > max) max = values[i];
    }
    if (max === 0) max = 1;
    var n = values.length;
    var pts = [];
    for (var j = 0; j < n; j++) {
      var x = n > 1 ? (j / (n - 1)) * (w - pad * 2) + pad : w / 2;
      var y = h - pad - (values[j] / max) * (h - pad * 2);
      pts.push(x.toFixed(1) + "," + y.toFixed(1));
    }
    return pts.join(" ");
  }

  function renderTrendsCard(data) {
    var card = document.getElementById("trends-card");
    if (!card) return;

    var title = LANG === "he" ? "מגמות" : LANG === "de" ? "Trends" : "Trends";
    var desc = (
      LANG === "he" ? "דוחות מגמות דו-שבועיים וניתוח סיקור לפי מדינה" :
      LANG === "de" ? "Zweiwöchentliche Trendberichte und Berichterstattungsanalyse nach Land" :
      "Biweekly trend reports and coverage analysis by country"
    );
    var cta = LANG === "he" ? "לצפייה ←" : LANG === "de" ? "Ansehen →" : "View →";

    var link = document.createElement("a");
    link.href = TRENDS_HREF;

    var titleEl = document.createElement("p");
    titleEl.className = "trends-card-title";
    titleEl.textContent = title;
    link.appendChild(titleEl);

    var descEl = document.createElement("p");
    descEl.className = "trends-card-desc";
    descEl.textContent = desc;
    link.appendChild(descEl);

    if (data && data.countries && data.countries.length) {
      var country = data.countries[0];
      var points = buildSparklinePoints(country.n_sources, 100, 24, 3);
      var svgNS = "http://www.w3.org/2000/svg";
      var svg = document.createElementNS(svgNS, "svg");
      svg.setAttribute("class", "trends-card-spark");
      svg.setAttribute("viewBox", "0 0 100 24");
      svg.setAttribute("preserveAspectRatio", "none");
      svg.setAttribute("aria-hidden", "true");
      var polyline = document.createElementNS(svgNS, "polyline");
      polyline.setAttribute("points", points);
      svg.appendChild(polyline);
      link.appendChild(svg);
    }

    var ctaEl = document.createElement("p");
    ctaEl.className = "trends-card-cta";
    ctaEl.textContent = cta;
    link.appendChild(ctaEl);

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
    # accessibility.html/terms.html/privacy.html/filter.html follow the same no-root-copy convention.
    accessibility_href = "he/accessibility.html" if is_root else "accessibility.html"
    terms_href = "he/terms.html" if is_root else "terms.html"
    privacy_href = "he/privacy.html" if is_root else "privacy.html"
    filter_href = "he/filter.html" if is_root else "filter.html"
    trends_href = "he/trends.html" if is_root else "trends.html"

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
    legend_low = {"he": "כיסוי מצומצם", "en": "Light coverage", "de": "Geringe Berichterstattung"}[lang]
    legend_high = {"he": "כיסוי נרחב", "en": "Extensive coverage", "de": "Umfassende Berichterstattung"}[lang]
    js_code = (
        _HOMEPAGE_JS_TEMPLATE.replace("__LANG__", lang)
        .replace("__PREFIX__", asset_prefix)
        .replace("__TOPIC_PREFIX__", topic_prefix)
        .replace("__TRENDS_HREF__", trends_href)
    )

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{THEME_TOGGLE_SCRIPT_HTML}
<title>{esc(page_title)}</title>
{favicon_links_html(asset_prefix)}
<style>
  {font_face_css(f"{asset_prefix}assets/fonts/{FONT_FILENAME}")}

  {category_css()}

{theme_tokens_css()}

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
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
    align-items: start;
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
  /* Shrunk to roughly half its former footprint (was 2fr of 3fr total width,
     now 1fr of 3; min-height likewise ~halved) to make room for the new
     trends-module alongside it in the same row - see "align-items: start"
     above, which lets this card stay short instead of stretching to match
     its taller siblings. */
  .timeline-module {{ min-height: 130px; }}
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
  /* non-scaling-stroke: the embedded map's viewBox is 2776x1163 user units -
     without this, a stroke-width here is in that huge coordinate space and
     renders as a sub-pixel hairline on a normally-sized map regardless of
     the number. With it, stroke-width is read in real output pixels instead,
     independent of viewBox/zoom - measured visually (Playwright) at a few
     widths before settling on 3. */
  .landxx.is-selected {{ stroke: #f4b942; stroke-width: 3; vector-effect: non-scaling-stroke; }}

  .map-legend {{
    direction: ltr; /* a continuous low->high color scale, not text - always
      reads left-to-right regardless of page language, same fix already used
      for citation boxes elsewhere in the site. */
    display: flex;
    align-items: center;
    gap: .5rem;
    margin-top: .75rem;
    font-size: .72rem;
    color: var(--text-muted);
  }}
  .map-legend-bar {{
    width: 110px;
    height: 10px;
    flex: 0 0 auto;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: linear-gradient(
      to right,
      color-mix(in srgb, var(--masthead-accent) 20%, var(--bg-elevated)),
      color-mix(in srgb, var(--masthead-accent) 55%, var(--bg-elevated))
    );
  }}

  .map-tooltip {{
    position: fixed;
    display: none;
    pointer-events: none;
    background: var(--bg-elevated);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: .4rem;
    padding: .35rem .65rem;
    font-size: .78rem;
    box-shadow: 0 2px 10px rgba(0,0,0,.2);
    max-width: 220px;
    z-index: 20;
  }}

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

  /* Redesigned (PROJECT_LOG 4.8x) to match latest-card's own title/
     description/CTA structure - same visual prominence as the other home-
     module cards, per explicit feedback that a bare sparkline alone wasn't
     clear. The module border still brightens on hover (via :has(), same
     affordance archive-card/result-item give their own clickable cards). */
  .trends-module:has(a:hover) {{ border-color: var(--masthead-accent); }}
  .trends-card {{ display: flex; flex: 1; }}
  .trends-card a {{ display: flex; flex-direction: column; gap: .5rem; flex: 1; justify-content: center; text-decoration: none; color: inherit; }}
  .trends-card-title {{ margin: 0; font-size: 1.6rem; font-weight: 800; letter-spacing: -0.01em; color: var(--masthead-accent); }}
  .trends-card-desc {{ margin: 0; font-size: .88rem; color: var(--text); }}
  .trends-card-spark {{ width: 100%; height: 24px; display: block; }}
  .trends-card-spark polyline {{ fill: none; stroke: var(--masthead-accent); stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }}
  .trends-card-cta {{ margin: 0; font-size: .85rem; font-weight: 600; color: var(--masthead-accent); }}

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
      <a href="{esc(trends_href)}">{esc(TRENDS_LABEL[lang])}</a>
      {"".join(f'<a href="{esc(lang_hrefs[o])}">{esc(LANG_LABEL[o])}</a>' for o in other_langs(lang) if o in lang_hrefs)}
      <a href="mailto:{CONTACT_EMAIL}">{esc(CONTACT_LABEL[lang])}</a>
      {theme_toggle_html(lang)}
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
      <section class="home-module trends-module" id="trends-module">
        <div class="trends-card" id="trends-card"></div>
      </section>
    </div>
    <section class="home-module map-module">
      <p class="sr-only" id="map-description">{esc(map_description)}</p>
      {map_svg}
      <div class="map-legend" aria-hidden="true">
        <span>{esc(legend_low)}</span>
        <span class="map-legend-bar"></span>
        <span>{esc(legend_high)}</span>
      </div>
      <div class="map-tooltip" id="map-tooltip" aria-hidden="true"></div>
      <div class="region-chips" id="region-chips"></div>
      <div class="region-chips" id="conflict-chips"></div>
    </section>
    <div class="results-panel" id="results-panel"></div>
  </main>
{build_footer_html(lang, accessibility_href, terms_href, privacy_href)}
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
            # Report count, not just "has coverage" - gives mouse users (via the
            # custom tooltip that reads this same attribute, see renderMap() in
            # _HOMEPAGE_JS_TEMPLATE) the same concrete number screen-reader users
            # already got, instead of the vaguer phrasing this replaces.
            count = len(country["section_ids"])
            if lang == "he":
                word = "דיווח" if count == 1 else "דיווחים"
                label = f"{name} - {count} {word}, לחץ לסינון"
            elif lang == "de":
                word = "Bericht" if count == 1 else "Berichte"
                label = f"{name} - {count} {word}, zum Filtern klicken"
            else:
                word = "report" if count == 1 else "reports"
                label = f"{name} - {count} {word}, click to filter"
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


def build_trends_json(conn) -> dict:
    """Static data file for trends.html (src/common/trends.py's groundwork,
    PROJECT_LOG 4.78/4.79) - built once here, fetched client-side like every
    other data file on this site, never baked into the HTML. Separate from
    manifest.json (different shape/purpose, same reasoning as the per-date
    content/{date}_{lang}.json split: keep each data file lean for what it's
    actually for).

    Week metadata (start/end/has_backlog/backlog_dates) lives ONCE at the top
    level, not duplicated per country - it is identical across every country
    series since detect_backlog_dates() flags a report-date regardless of
    which country it's queried for. Each country's n_sources array is
    index-aligned 1:1 with "weeks" (0 for a week with no data, though that
    should be rare for countries that cleared eligible_countries()'s density
    gate in the first place).
    """
    weeks_trends = build_country_week_trends(conn)
    elig = eligible_countries(conn)

    weeks: list[dict] = []
    if elig:
        any_country = next(iter(elig))
        weeks = [
            {
                "start": w["week_start"],
                "end": w["week_end"],
                "has_backlog": w["has_backlog"],
                "backlog_dates": w["backlog_dates"],
            }
            for w in weeks_trends.get(any_country, [])
        ]

    countries = []
    for code in elig:
        by_week = {w["week_start"]: w["n_sources"] for w in weeks_trends.get(code, [])}
        n_sources = [by_week.get(w["start"], 0) for w in weeks]
        info = COUNTRY_LIST.get(code, {})
        countries.append(
            {
                "code": code,
                "name_he": info.get("name_he", code),
                "name_en": info.get("name_en", code),
                "name_de": info.get("name_de", code),
                "n_sources": n_sources,
            }
        )
    # Most-covered-overall first - a sensible stable default order; the page's
    # own ranked view re-sorts by week-over-week change client-side anyway.
    countries.sort(key=lambda c: -sum(c["n_sources"]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weeks": weeks,
        "countries": countries,
    }


def _write_trends_json(data: dict) -> None:
    trends_json = json.dumps(data, ensure_ascii=False)
    for base_dir in (DOCS_DIR, REPORTS_DIR):
        dest = base_dir / TRENDS_RELATIVE_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(trends_json, encoding="utf-8")


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


def _apply_backup_retention() -> None:
    """Thins BACKUP_DIR's dated tracker_*.db snapshots so the set doesn't grow
    without bound as the live DB itself grows (109MB and rising as of
    2026-09-24 - see PROJECT_LOG). Policy: every daily snapshot from the last
    BACKUP_RECENT_DAYS is kept in full; beyond that and within BACKUP_MAX_DAYS,
    only Sundays survive; beyond BACKUP_MAX_DAYS, none do. The single most
    recent snapshot is never deleted, full stop, regardless of what the policy
    computes for it - a safety invariant, not just the expected outcome of the
    date math, in case of a clock issue or a bug here."""
    if not BACKUP_DIR.exists():
        return
    dated_files: list[tuple[date, Path]] = []
    for p in BACKUP_DIR.iterdir():
        m = BACKUP_FILENAME_RE.match(p.name)
        if not m:
            continue
        try:
            dated_files.append((date.fromisoformat(m.group(1)), p))
        except ValueError:
            continue
    if not dated_files:
        return

    most_recent = max(d for d, _ in dated_files)
    today = date.today()

    for d, p in dated_files:
        if d == most_recent:
            continue
        age_days = (today - d).days
        if age_days <= BACKUP_RECENT_DAYS:
            keep = True
        elif age_days <= BACKUP_MAX_DAYS:
            keep = d.weekday() == 6  # Sunday
        else:
            keep = False
        if not keep:
            try:
                p.unlink()
                print(f"  backup retention: removed {p.name} (age {age_days}d, outside retention policy)")
            except Exception as exc:
                print(f"  *** WARNING: could not remove old backup {p.name}: {exc} ***")


def backup_database() -> None:
    """Copies the live tracker.db to BACKUP_DIR (a sibling of the repo,
    established 2026-09-20 - see that folder's README.txt) with a run-date
    filename, then applies retention. Called once at the very end of a
    successful run() - after publish, never blocking it. A backup failure of
    any kind is logged as a warning and swallowed, not raised: this function
    runs after docs/ has already been written, so failing loudly here would
    make an otherwise-successful publish look broken over what is, at worst,
    one missed backup opportunity - the next run tries again tomorrow.

    Why a dedicated mechanism at all, given the whole project already lives
    inside OneDrive (which mirrors tracker.db's current bytes continuously)?
    OneDrive sync gives redundancy against losing this one machine, but not
    recoverability to a specific earlier point in time (e.g. "put the DB back
    to how it was right after 2026-09-22's run, before some later script
    touched a row") - that needs actual dated, distinct snapshots, which is
    exactly what this provides and OneDrive's own sync does not, by itself.

    Always overwrites today's dated file if one already exists (changed
    2026-09-25 - see PROJECT_LOG action item 53/4.54): a day with more than
    one successful publish run (not rare - 2026-09-24 had several) used to
    keep only the FIRST run's snapshot for that whole day, silently going
    stale relative to every later run the same day. The retention policy
    (BACKUP_RECENT_DAYS/BACKUP_MAX_DAYS, below) is keyed on the file's
    calendar date either way, so overwriting same-day doesn't change how
    many distinct days of history are kept - only which moment within
    "today" the day's single snapshot reflects (the latest, not the first)."""
    try:
        if not DB_PATH.exists():
            print(f"  backup skipped: {DB_PATH} not found")
            return
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dest = BACKUP_DIR / f"tracker_{date.today().isoformat()}.db"
        overwriting = dest.exists()
        shutil.copy2(DB_PATH, dest)
        print(f"  backup: {'overwrote' if overwriting else 'wrote'} {dest} (latest state as of this run)")
        _apply_backup_retention()
    except Exception as exc:
        print(f"  *** WARNING: DB backup failed ({exc}) - pipeline result above is unaffected ***")


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
    trends_data = build_trends_json(conn)
    _write_section_content_files(conn, entries)

    # Biweekly narrative-trends reports (src/reporting/synthesize_biweekly.py) -
    # pre-fetched here, same reason as manifest/trends_data above: conn closes
    # before the per-language loop below, and this data isn't language-specific
    # (only its rendering into HTML is).
    biweekly_periods_data = []
    for p in get_all_biweekly_periods(conn):
        topics = []
        for t in get_biweekly_topics_for_period(conn, p["id"]):
            days, sources = get_dates_and_sources_for_biweekly_topic(conn, t["id"])
            topics.append({**dict(t), "_days": days, "_sources": sources})
        biweekly_periods_data.append({**dict(p), "topics": topics, "topic_count": len(topics)})

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

        trends_chart_html = build_trends_chart_html(lang)
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "trendschart.html").write_text(trends_chart_html, encoding="utf-8")
        print(f"  wrote trendschart.html for '{lang}'")

        trends_hub_html = build_trends_hub_html(lang, biweekly_periods_data)
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "trends.html").write_text(trends_hub_html, encoding="utf-8")
        print(f"  wrote trends.html (hub) for '{lang}'")

        for period in biweekly_periods_data:
            dates_sources_by_topic = {t["id"]: (t["_days"], t["_sources"]) for t in period["topics"]}
            biweekly_html = build_biweekly_report_html(period, period["topics"], dates_sources_by_topic, lang)
            out_name = period_filename(period["start_date"], period["end_date"], lang)
            for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / out_name).write_text(biweekly_html, encoding="utf-8")
        if biweekly_periods_data:
            print(f"  wrote {len(biweekly_periods_data)} biweekly report page(s) for '{lang}'")

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

        privacy_html = build_privacy_html(lang)
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "privacy.html").write_text(privacy_html, encoding="utf-8")
        print(f"  wrote privacy.html for '{lang}'")

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
        privacy_href="he/privacy.html",
        trends_href="he/trends.html",
    )
    (DOCS_DIR / "archive.html").write_text(root_archive_html, encoding="utf-8")
    print(f"  wrote {DOCS_DIR / 'archive.html'} (root, Hebrew default)")

    root_homepage_html = build_homepage_html("he", is_root=True, countries=manifest["countries"])
    (DOCS_DIR / "index.html").write_text(root_homepage_html, encoding="utf-8")
    print(f"  wrote {DOCS_DIR / 'index.html'} (root homepage, Hebrew default)")

    _write_manifest(manifest)
    print(f"  wrote manifest.json ({len(manifest['sections'])} section(s), {len(manifest['countries'])} countrie(s))")
    print(f"  wrote {len(entries) * len(ALL_LANGS)} section-content file(s) under assets/data/content/")

    _write_trends_json(trends_data)
    print(f"  wrote trends.json ({len(trends_data['countries'])} eligible countrie(s), {len(trends_data['weeks'])} week(s))")

    print(f"\nPublish complete: {len(entries)} report date(s) -> {DOCS_DIR}")

    backup_database()


if __name__ == "__main__":
    run()
