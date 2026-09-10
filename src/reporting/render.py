"""Reporting stage 2: render synthesized report_sections into bilingual HTML+PDF.

Reads reports/report_sections/report_section_articles for one report date (written
by synthesize.py) and produces 4 files: an HTML page and a PDF per language (Hebrew
RTL, English LTR). Each language gets exactly one HTML+CSS document - @media screen
rules style it for browsing (GitHub Pages), @media print rules (page size/margins/
footer) are the ones WeasyPrint applies when rendering the same string to PDF.
Independent one-shot run - not a long-running daemon.
"""

import argparse
import html
import json
import shutil
import sys
from datetime import date as date_cls
from pathlib import Path

from src.common.db import (
    get_connection,
    get_report,
    get_report_sections_for_date,
    get_section_articles,
    get_section_citations,
    init_db,
)

try:
    from weasyprint import HTML as WeasyHTML
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False

# Windows defaults stdout to the cp1252 console codepage even when redirected
# to a file, which raises UnicodeEncodeError on any print() containing a
# character outside it (e.g. Balkan/Slavic names) - fatal mid-run otherwise.
sys.stdout.reconfigure(encoding="utf-8")

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"

# Single source of truth for the site-wide font (everything under render.py/publish.py -
# NOT scripts/build_background_doc.py, which deliberately uses Assistant too but as its
# own separate, independently-managed asset for a standalone document).
FONT_FAMILY = "Assistant"
FONT_WEIGHT_RANGE = "200 800"
FONT_FILENAME = "Assistant-Variable.ttf"
FONT_SOURCE_PATH = Path(__file__).resolve().parent / "assets" / "fonts" / FONT_FILENAME
FONT_RELATIVE_PATH = f"../assets/fonts/{FONT_FILENAME}"


def font_face_css(relative_path: str) -> str:
    return f"""@font-face {{
    font-family: "{FONT_FAMILY}";
    src: url("{relative_path}") format("truetype-variations");
    font-weight: {FONT_WEIGHT_RANGE};
  }}"""

FALLBACK_CATEGORY = "additional_coverage"

NEWSPAPER_DISPLAY_NAMES = {
    "Guardian": "The Guardian",
    "Daily Telegraph": "The Daily Telegraph",
    "Süddeutsche Zeitung": "Süddeutsche Zeitung",
    "Die Welt": "Die Welt",
    "New York Times International": "The New York Times International",
    "Wall Street Journal": "The Wall Street Journal",
    "Los Angeles Times": "Los Angeles Times",
    "USA Today": "USA Today",
    "Economist": "The Economist",
    "Der Spiegel": "Der Spiegel",
}

# Used only to sort topics by cross-border reach (see section_coverage) - not
# a display value, so no "The"/short-form nuance needed like NEWSPAPER_DISPLAY_NAMES.
NEWSPAPER_LANGUAGES = {
    "Guardian": "en",
    "Daily Telegraph": "en",
    "Wall Street Journal": "en",
    "Los Angeles Times": "en",
    "USA Today": "en",
    "Economist": "en",
    "New York Times International": "en",
    "Süddeutsche Zeitung": "de",
    "Die Welt": "de",
    "Der Spiegel": "de",
}


def section_coverage(newspapers: list[str]) -> tuple[int, int]:
    """(source_count, language_count) for a topic - the wider a topic's
    cross-source/cross-language reach, the more likely it reflects real
    geopolitical significance rather than a single outlet's local angle."""
    source_count = len(newspapers)
    language_count = len({NEWSPAPER_LANGUAGES.get(n, n) for n in newspapers})
    return source_count, language_count


def _coverage_badge_label(source_count: int, language_count: int, lang: str) -> str:
    if lang == "he":
        src_word = "מקור" if source_count == 1 else "מקורות"
        lang_word = "שפה" if language_count == 1 else "שפות"
    else:
        src_word = "source" if source_count == 1 else "sources"
        lang_word = "language" if language_count == 1 else "languages"
    return f"{source_count} {src_word} · {language_count} {lang_word}"

CATEGORY_LABELS = {
    "security_conflict": {"he": "ביטחון וסכסוכים", "en": "Security & Conflict"},
    "diplomacy_international": {"he": "דיפלומטיה ויחסים בינלאומיים", "en": "Diplomacy & International Relations"},
    "trade_economics": {"he": "כלכלה וסחר", "en": "Trade & Economics"},
    "domestic_politics": {"he": "פוליטיקה פנימית", "en": "Domestic Politics"},
    "migration_society": {"he": "הגירה וחברה", "en": "Migration & Society"},
    "society_culture": {"he": "תרבות וזהות", "en": "Society & Culture"},
    "technology_media": {"he": "טכנולוגיה ומדיה", "en": "Technology & Media"},
    "energy_environment": {"he": "אנרגיה וסביבה", "en": "Energy & Environment"},
    FALLBACK_CATEGORY: {"he": "כיסוי נוסף", "en": "Additional Coverage"},
}

# (light color, light bg tint, dark color, dark bg tint) per category - defined once
# here and turned into CSS custom properties by build_report_html, so there is a
# single source of truth for the palette instead of colors hardcoded in two places.
CATEGORY_STYLES = {
    "security_conflict":       ("#8a3324", "#f7e6e2", "#e0a08f", "#3a2019"),
    "diplomacy_international": ("#2a5b8a", "#e3edf5", "#8fb8dd", "#182a38"),
    "trade_economics":         ("#93691a", "#faf1dd", "#e0b859", "#332a13"),
    "domestic_politics":       ("#5c3d82", "#f0e9f6", "#c6a6ea", "#2c2138"),
    "migration_society":       ("#1f6f76", "#e6f3f2", "#6fc9d0", "#12302f"),
    "society_culture":         ("#a5457a", "#f8e8f0", "#e2a0c6", "#381e2c"),
    "technology_media":        ("#3d6b3d", "#e9f2e6", "#8fc98f", "#1c2e1c"),
    "energy_environment":      ("#7a6a1a", "#f5f0dd", "#cdbb5c", "#2e2913"),
    FALLBACK_CATEGORY:         ("#6b6560", "#efece6", "#a89f91", "#2a2620"),
}

OTHER_LANG = {"he": "en", "en": "he"}
LANG_LABEL = {"he": "עברית", "en": "English"}
BACK_LABEL = {"he": "← לכל הדוחות", "en": "← All reports"}

HE_WEEKDAYS = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "יום שבת", "יום ראשון"]
HE_MONTHS = [
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]
EN_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

CITATION_PAGE_LABEL = {"he": "עמ'", "en": "p."}


def format_date_he(report_date: str) -> str:
    d = date_cls.fromisoformat(report_date)
    return f"{HE_WEEKDAYS[d.weekday()]}, {d.day} ב{HE_MONTHS[d.month - 1]} {d.year}"


def format_date_en(report_date: str) -> str:
    d = date_cls.fromisoformat(report_date)
    return d.strftime("%A, %B %d, %Y")


def format_citation_date_he(date_str: str) -> str:
    d = date_cls.fromisoformat(date_str)
    return f"{d.day}.{d.month}.{d.year}"


def format_citation_date_en(date_str: str) -> str:
    d = date_cls.fromisoformat(date_str)
    return f"{EN_MONTHS_ABBR[d.month - 1]} {d.day}, {d.year}"


def _truncate_headline(headline: str, max_words: int = 6) -> str:
    words = headline.split()
    if len(words) <= max_words:
        return headline
    return " ".join(words[:max_words]) + "…"


def category_css() -> str:
    root_light, root_dark = [], []
    selectors = []
    for key, (color, bg, dark_color, dark_bg) in CATEGORY_STYLES.items():
        root_light.append(f"  --tok-{key}-color: {color};\n  --tok-{key}-bg: {bg};")
        root_dark.append(f"  --tok-{key}-color: {dark_color};\n  --tok-{key}-bg: {dark_bg};")
        selectors.append(
            f'[data-category="{key}"] {{ --cat-color: var(--tok-{key}-color); --cat-bg: var(--tok-{key}-bg); }}'
        )
    return (
        ":root {\n" + "\n".join(root_light) + "\n}\n"
        '@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {\n    '
        + "\n    ".join(root_dark) + "\n  }\n}\n"
        ':root[data-theme="dark"] {\n  ' + "\n  ".join(root_dark) + "\n}\n"
        + "\n".join(selectors)
    )


def esc(text: str) -> str:
    return html.escape(text)


def build_nav_html(back_href: str, other_lang_href: str, lang: str, pdf_href: str | None = None) -> str:
    other = OTHER_LANG[lang]
    pdf_link = ""
    if pdf_href is not None:
        pdf_label = "⬇ הורד PDF" if lang == "he" else "⬇ Download PDF"
        pdf_link = f'\n      <a class="top-nav-link" href="{esc(pdf_href)}">{esc(pdf_label)}</a>'
    return f"""
  <nav class="top-nav">
    <a class="top-nav-logo-link" href="../index.html"><img class="top-nav-logo" src="../assets/images/MS_Logo.png" alt=""></a>
    <div class="top-nav-links">
      <a class="top-nav-link" href="{esc(back_href)}">{esc(BACK_LABEL[lang])}</a>
      <a class="top-nav-link" href="{esc(other_lang_href)}">{esc(LANG_LABEL[other])}</a>{pdf_link}
    </div>
  </nav>"""


def _build_citations_html(citations: list, lang: str, section_id: int) -> str:
    if not citations:
        return ""

    format_date = format_citation_date_he if lang == "he" else format_citation_date_en
    page_label = CITATION_PAGE_LABEL[lang]
    quote_marks = ("“", "”") if lang == "he" else ('"', '"')

    # citations arrive pre-sorted by (newspaper, page_number) - group consecutive
    # same-newspaper rows so we know, per group, whether a headline is needed to
    # disambiguate (only when a newspaper contributes more than one article here).
    groups: list[list] = []
    for c in citations:
        if groups and groups[-1][0]["newspaper"] == c["newspaper"]:
            groups[-1].append(c)
        else:
            groups.append([c])

    lines = []
    for group in groups:
        show_headline = len(group) > 1
        for c in group:
            display_name = esc(NEWSPAPER_DISPLAY_NAMES.get(c["newspaper"], c["newspaper"]))
            date_str = esc(format_date(c["published_date"]))
            line = f"{display_name}, {date_str}, {page_label} {c['page_number']}"
            if show_headline:
                snippet = esc(_truncate_headline(c["headline"]))
                line += f" — {quote_marks[0]}{snippet}{quote_marks[1]}"
            lines.append(f"            <li>{line}</li>")

    toggle_label = "מראי מקום" if lang == "he" else "Citations"
    popup_id = f"citations-{section_id}"
    items_html = "\n".join(lines)
    return f"""
          <button class="citations-toggle" type="button" aria-expanded="false" aria-controls="{popup_id}">
            {esc(toggle_label)} ({len(citations)})
            <span class="chevron-circle" aria-hidden="true">⌄</span>
          </button>
          <div class="citations-popup" id="{popup_id}" hidden>
            <ul>
{items_html}
            </ul>
          </div>"""


def _render_section(section: dict, lang: str, show_sources: bool) -> str:
    label = CATEGORY_LABELS.get(section["category"], CATEGORY_LABELS[FALLBACK_CATEGORY])[lang]
    topic = section["topic_label_he"] if lang == "he" else section["topic_label_en"]
    text = section["comparison_text_he"] if lang == "he" else section["comparison_text_en"]

    source_count, language_count = section_coverage(section["newspapers"])
    badge_label = _coverage_badge_label(source_count, language_count, lang)
    # Subtle size/width bump for wide-reach topics only - not a hard cutoff for
    # a single metric, since either a high source_count (many outlets, even if
    # same language) or a high language_count (cross-border by definition,
    # even with few outlets) independently signals real geopolitical weight.
    prominent = source_count >= 3 or language_count >= 2
    section_class = "topic-section topic-section--prominent" if prominent else "topic-section"

    section_id = section["id"]
    anchor = f"section-{section_id}"
    body_id = f"body-{section_id}"

    sources_html = ""
    if show_sources and section["newspapers"]:
        names = ", ".join(esc(NEWSPAPER_DISPLAY_NAMES.get(n, n)) for n in section["newspapers"])
        sources_label = "מקורות" if lang == "he" else "Sources"
        sources_html = f'<p class="section-sources">{sources_label}: <b>{names}</b></p>'

    citations_html = _build_citations_html(section["citations"], lang, section_id)

    share_label = "🔗 העתק קישור" if lang == "he" else "🔗 Copy link"
    copied_label = "הועתק!" if lang == "he" else "Copied!"
    share_html = (
        f'<button class="share-link-btn" type="button" data-anchor="{anchor}" '
        f'data-copied-label="{esc(copied_label)}">{esc(share_label)}</button>'
    )

    return f"""
      <section class="{section_class}" id="{anchor}" data-category="{esc(section['category'])}">
        <div class="section-header" role="button" tabindex="0" aria-expanded="true" aria-controls="{body_id}">
          <div class="topic-meta">
            <span class="category-dot"></span>
            <span class="category-label">{esc(label)}</span>
            <span class="coverage-badge">{esc(badge_label)}</span>
          </div>
          <div class="section-title-row">
            <h2 class="section-title">{esc(topic)}</h2>
            <span class="expand-chevron" aria-hidden="true">⌄</span>
          </div>
        </div>
        <div class="section-body" id="{body_id}">
          <p class="comparison-text">{esc(text)}</p>
          {sources_html}
          <div class="section-actions">
            {share_html}
            {citations_html}
          </div>
        </div>
      </section>"""


def _build_category_nav_html(category_nav: list[tuple[str, int]], lang: str) -> str:
    links = "".join(
        f'<a class="category-nav-link" href="#section-{section_id}">'
        f'{esc(CATEGORY_LABELS.get(cat, CATEGORY_LABELS[FALLBACK_CATEGORY])[lang])}</a>'
        for cat, section_id in category_nav
    )
    toggle_all_label = "הרחב הכל / כווץ הכל" if lang == "he" else "Expand all / Collapse all"
    return f"""
  <nav class="category-nav">
    <div class="category-nav-links">{links}</div>
    <button class="toggle-all-btn" type="button">{esc(toggle_all_label)}</button>
  </nav>"""


def build_report_html(
    report_date: str,
    sources: list[str],
    sections: list[dict],
    lang: str,
    category_nav: list[tuple[str, int]],
) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"

    date_str = format_date_he(report_date) if is_he else format_date_en(report_date)
    page_title = f"דוח יומי - {date_str}" if is_he else f"Daily Geopolitics Report - {date_str}"
    eyebrow = "גאופוליטיקה יומי" if is_he else "Daily Geopolitics"
    sources_label = "עיתונים שנסקרו היום:" if is_he else "Sources covering today:"

    source_pills = "".join(f"<li>{esc(NEWSPAPER_DISPLAY_NAMES.get(s, s))}</li>" for s in sources)

    # Sections arrive pre-sorted by coverage (see run()) - fallback topics
    # (category == FALLBACK_CATEGORY) render inline at their sorted position,
    # not pushed into a separate trailing block: a fallback topic is only a
    # single article by construction (source_count=language_count=1), so it
    # naturally settles near the bottom on its own merit, but it is not
    # structurally forced there - a genuinely wide fallback would rank
    # normally, same as any other topic. Its own category badge ("Additional
    # Coverage") is still what visually marks it as fallback-origin.
    sections_html = "\n".join(_render_section(s, lang, show_sources=True) for s in sections)

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
<style>
  {font_face_css(FONT_RELATIVE_PATH)}

  {category_css()}

  :root {{
    --bg: #f3efe8;
    --bg-elevated: #fffdfa;
    --text: #221f1b;
    --text-muted: #6d675e;
    --border: #e4ddd0;
    --masthead-accent: #7a2e2a;
    --pill-bg: #ffffff;
    --pill-text: #3a352e;
    --pill-border: #ddd3c2;
  }}

  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #16140f;
      --bg-elevated: #211e18;
      --text: #ece7dd;
      --text-muted: #a89f91;
      --border: #3a352b;
      --masthead-accent: #d68b86;
      --pill-bg: #2a2620;
      --pill-text: #ece7dd;
      --pill-border: #453f33;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #16140f;
    --bg-elevated: #211e18;
    --text: #ece7dd;
    --text-muted: #a89f91;
    --border: #3a352b;
    --masthead-accent: #d68b86;
    --pill-bg: #2a2620;
    --pill-text: #ece7dd;
    --pill-border: #453f33;
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

  .category-nav {{
    position: sticky;
    top: 0;
    z-index: 20;
    max-width: 44rem;
    margin: 0 auto;
    padding: .55rem 1.5rem;
    display: flex;
    align-items: center;
    gap: .75rem;
    background: var(--bg-elevated);
    border-bottom: 1px solid var(--border);
  }}
  /* Only the category pills scroll horizontally (flex:1 + min-width:0 lets
     this shrink below its content width inside the flex row, which is what
     actually makes overflow-x kick in) - .toggle-all-btn sits outside this
     scrollable area as a fixed sibling, so it's always visible without
     having to scroll the pill list first, even on a many-category day. */
  .category-nav-links {{
    display: flex;
    gap: .5rem;
    flex-wrap: nowrap;
    overflow-x: auto;
    flex: 1;
    min-width: 0;
  }}
  .category-nav-link {{
    flex-shrink: 0;
    font-size: .78rem;
    font-weight: 500;
    color: var(--text-muted);
    text-decoration: none;
    white-space: nowrap;
    padding: .3rem .7rem;
    border-radius: 999px;
    border: 1px solid var(--pill-border);
  }}
  .category-nav-link:hover {{ color: var(--masthead-accent); border-color: var(--masthead-accent); }}
  .toggle-all-btn {{
    flex-shrink: 0;
    background: none;
    border: 1px solid var(--pill-border);
    border-radius: 999px;
    padding: .3rem .7rem;
    font: inherit;
    font-size: .78rem;
    font-weight: 500;
    color: var(--text-muted);
    cursor: pointer;
    white-space: nowrap;
  }}
  .toggle-all-btn:hover {{ color: var(--masthead-accent); border-color: var(--masthead-accent); }}

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
  .report-title {{ margin: 0 0 1.5rem; font-size: 2.1rem; font-weight: 800; letter-spacing: -0.01em; }}
  .sources-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: .75rem 1rem; }}
  .sources-label {{ font-size: .85rem; color: var(--text-muted); font-weight: 500; white-space: nowrap; }}
  .sources-pills {{ list-style: none; display: flex; flex-wrap: wrap; gap: .5rem; margin: 0; padding: 0; }}
  .sources-pills li {{
    background: var(--pill-bg);
    border: 1px solid var(--pill-border);
    color: var(--pill-text);
    padding: .35rem .85rem;
    border-radius: 999px;
    font-size: .85rem;
    font-weight: 500;
  }}

  .report-body {{
    max-width: 44rem;
    margin: 0 auto;
    padding: 2.25rem 1.5rem 4rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }}

  .topic-section {{
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: .9rem;
    padding: 1.5rem 1.6rem 1.65rem;
    border-inline-start: 5px solid var(--cat-color);
  }}
  /* Subtle featured-item bleed for wide-reach topics (source_count>=3 or
     language_count>=2) - the negative inline margin is symmetric (both
     sides), so a prominent card stays centered under narrower neighbors
     above/below it rather than shifting to one side; padding-inline is
     bumped by the same amount pulled out by the margin, so the actual
     text column still lines up with regular cards, not just the card box. */
  .topic-section--prominent {{
    margin-inline: -.75rem;
    padding-inline: 2.35rem;
  }}
  .topic-section--prominent .section-title {{ font-size: 1.45rem; }}

  .section-header {{ cursor: pointer; }}
  .section-header:hover .section-title {{ color: var(--masthead-accent); }}
  .topic-meta {{ display: flex; align-items: center; gap: .5rem; margin-bottom: .6rem; }}
  .category-dot {{ width: .55rem; height: .55rem; border-radius: 50%; background: var(--cat-color); flex-shrink: 0; }}
  .category-label {{
    font-size: .78rem;
    font-weight: 600;
    letter-spacing: .02em;
    color: var(--cat-color);
    background: var(--cat-bg);
    padding: .2rem .6rem;
    border-radius: 999px;
  }}
  .coverage-badge {{ font-size: .72rem; color: var(--text-muted); }}
  .section-title-row {{ display: flex; align-items: center; justify-content: space-between; gap: .75rem; }}
  .section-title {{ margin: 0; font-size: 1.3rem; font-weight: 700; line-height: 1.4; transition: color .15s ease; }}
  .expand-chevron {{
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 50%;
    border: 1px solid var(--pill-border);
    color: var(--text-muted);
    /* Rotation is purely vertical (180deg <-> 0deg) - never left/right - so
       it reads identically in RTL and LTR, unlike a sideways-pointing chevron. */
    transform: rotate(180deg);
    transition: transform .15s ease, background .15s ease;
  }}
  .section-header:hover .expand-chevron {{ background: var(--pill-bg); }}
  .section-header[aria-expanded="false"] .expand-chevron {{ transform: rotate(0deg); }}
  .section-body {{ margin-top: .75rem; }}
  .comparison-text {{ margin: 0 0 1rem; font-size: 1rem; color: var(--text); line-height: 1.85; }}
  .section-sources {{
    margin: 0;
    font-size: .82rem;
    color: var(--text-muted);
    border-top: 1px solid var(--border);
    padding-top: .75rem;
  }}
  .section-sources b {{ color: var(--text); font-weight: 600; }}

  .section-actions {{ position: relative; margin-top: .6rem; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }}
  .share-link-btn {{
    background: none;
    border: none;
    padding: .2rem .3rem;
    margin: 0;
    font: inherit;
    font-size: .78rem;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: .4rem;
    transition: background .15s ease, color .15s ease;
  }}
  .share-link-btn:hover {{ background: var(--pill-bg); color: var(--masthead-accent); }}
  .citations-toggle {{
    background: none;
    border: none;
    padding: .2rem .3rem;
    margin: 0;
    font: inherit;
    font-size: .78rem;
    color: var(--text-muted);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: .35rem;
    border-radius: .4rem;
    transition: background .15s ease, color .15s ease;
  }}
  .citations-toggle:hover {{ background: var(--pill-bg); color: var(--masthead-accent); }}
  .chevron-circle {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.1rem;
    height: 1.1rem;
    border-radius: 50%;
    border: 1px solid var(--pill-border);
    font-size: .65rem;
    line-height: 1;
    transition: transform .15s ease;
  }}
  .citations-toggle[aria-expanded="true"] .chevron-circle {{ transform: rotate(180deg); }}
  .citations-popup {{
    position: absolute;
    top: 100%;
    inset-inline-start: 0;
    z-index: 10;
    margin-top: .4rem;
    width: max-content;
    min-width: 14rem;
    max-width: min(26rem, 100%);
    max-height: 14rem;
    overflow-y: auto;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: .5rem;
    padding: .6rem .8rem;
    box-shadow: 0 4px 14px rgba(0, 0, 0, .18);
  }}
  .citations-popup ul {{
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: .4rem;
    /* Citation lines are almost entirely Latin/numeric (newspaper name, date,
       page, headline) - only the page-label word is in the page's own script.
       Forcing ltr here keeps each line in one predictable reading order
       instead of letting the surrounding RTL page bidi-reorder the mixed
       script segments (this is applied to the list, not .citations-popup
       itself, so the popup's own inset-inline-start positioning still
       follows the real page direction). */
    direction: ltr;
    text-align: left;
  }}
  .citations-popup li {{ font-size: .8rem; color: var(--text); line-height: 1.5; }}

  @media print {{
    @page {{
      size: A4;
      margin: 2cm 1.8cm;
      @bottom-center {{ content: counter(page) " / " counter(pages); font-size: 9px; color: #888; }}
    }}
    body {{ background: #fff; }}
    .top-nav {{ display: none; }}
    .category-nav {{ display: none; }}
    .section-actions {{ display: none; }}
    /* PDF is generated once from the default (all-expanded) HTML string, so
       this only guards against someone printing the live page in a browser
       after collapsing sections there - the body must never be hidden in print. */
    .section-body[hidden] {{ display: block !important; }}
    .expand-chevron {{ display: none; }}
    .section-header {{ cursor: default; }}
  }}
</style>
</head>
<body>
{build_nav_html("archive.html", f"../{OTHER_LANG[lang]}/report_{report_date}_{OTHER_LANG[lang]}.html", lang, f"report_{report_date}_{lang}.pdf")}
{_build_category_nav_html(category_nav, lang)}
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(eyebrow)}</p>
      <h1 class="report-title">{esc(page_title)}</h1>
      <div class="sources-row">
        <span class="sources-label">{esc(sources_label)}</span>
        <ul class="sources-pills">{source_pills}</ul>
      </div>
    </div>
  </header>
  <main class="report-body">
{sections_html}
  </main>
  <script>
    function toggleSection(header) {{
      var body = document.getElementById(header.getAttribute('aria-controls'));
      var wasExpanded = header.getAttribute('aria-expanded') === 'true';
      header.setAttribute('aria-expanded', String(!wasExpanded));
      body.hidden = wasExpanded;
    }}

    document.addEventListener('click', function (e) {{
      var shareBtn = e.target.closest('.share-link-btn');
      if (shareBtn) {{
        var url = location.origin + location.pathname + '#' + shareBtn.getAttribute('data-anchor');
        navigator.clipboard.writeText(url).then(function () {{
          if (!shareBtn.dataset.original) {{ shareBtn.dataset.original = shareBtn.textContent; }}
          shareBtn.textContent = shareBtn.getAttribute('data-copied-label');
          clearTimeout(shareBtn._copyTimeout);
          shareBtn._copyTimeout = setTimeout(function () {{
            shareBtn.textContent = shareBtn.dataset.original;
          }}, 1600);
        }});
        return;
      }}

      var header = e.target.closest('.section-header');
      if (header) {{
        toggleSection(header);
        return;
      }}

      var toggleAll = e.target.closest('.toggle-all-btn');
      if (toggleAll) {{
        var headers = document.querySelectorAll('.section-header');
        var anyCollapsed = Array.prototype.some.call(headers, function (h) {{
          return h.getAttribute('aria-expanded') === 'false';
        }});
        headers.forEach(function (h) {{
          var body = document.getElementById(h.getAttribute('aria-controls'));
          h.setAttribute('aria-expanded', String(anyCollapsed));
          body.hidden = !anyCollapsed;
        }});
        return;
      }}

      var toggle = e.target.closest('.citations-toggle');
      document.querySelectorAll('.citations-popup:not([hidden])').forEach(function (popup) {{
        if (!toggle || popup.id !== toggle.getAttribute('aria-controls')) {{
          popup.hidden = true;
          var btn = document.querySelector('[aria-controls="' + popup.id + '"]');
          if (btn) btn.setAttribute('aria-expanded', 'false');
        }}
      }});
      if (toggle) {{
        var popup = document.getElementById(toggle.getAttribute('aria-controls'));
        var wasHidden = popup.hidden;
        popup.hidden = !wasHidden;
        toggle.setAttribute('aria-expanded', String(wasHidden));
      }}
    }});
    document.addEventListener('keydown', function (e) {{
      if (e.key === 'Escape') {{
        document.querySelectorAll('.citations-popup:not([hidden])').forEach(function (popup) {{
          popup.hidden = true;
        }});
        return;
      }}
      var header = e.target.closest('.section-header');
      if (header && (e.key === 'Enter' || e.key === ' ')) {{
        e.preventDefault();
        toggleSection(header);
      }}
    }});
  </script>
</body>
</html>
"""


def _ensure_font_asset() -> None:
    dest = REPORTS_DIR / "assets" / "fonts" / FONT_SOURCE_PATH.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copyfile(FONT_SOURCE_PATH, dest)


def render_report(conn, report_date: str) -> None:
    report_row = get_report(conn, report_date)
    if report_row is None:
        print(f"No report found for {report_date} - run synthesize.py for this date first.")
        return

    sources = json.loads(report_row["sources_included"])

    raw_sections = get_report_sections_for_date(conn, report_date)
    if not raw_sections:
        print(f"Report for {report_date} exists but has no sections - nothing to render.")
        return

    sections = []
    for s in raw_sections:
        newspapers = [r["newspaper"] for r in get_section_articles(conn, s["id"])]
        citations = [dict(r) for r in get_section_citations(conn, s["id"])]
        sections.append(
            {
                "id": s["id"],
                "topic_label_he": s["topic_label_he"],
                "topic_label_en": s["topic_label_en"],
                "comparison_text_he": s["comparison_text_he"],
                "comparison_text_en": s["comparison_text_en"],
                "category": s["category"],
                "newspapers": newspapers,
                "citations": citations,
            }
        )

    _ensure_font_asset()

    # Order topics by cross-border reach (language_count desc, source_count
    # desc as tiebreaker) - a zoom-out-to-zoom-in reading order, not the
    # arbitrary order stage-1 grouping happened to return them in. Fallback
    # topics are sorted in on equal footing, not forced to the end (see the
    # comment in build_report_html).
    sections.sort(key=lambda s: tuple(-x for x in section_coverage(s["newspapers"])))

    main_count = sum(1 for s in sections if s["category"] != FALLBACK_CATEGORY)
    fallback_count = len(sections) - main_count

    # Sticky-nav jump targets: one per category actually present that day (not
    # a fixed list of 8), each pointing at that category's first section in
    # the coverage-sorted order above - so jumping there lands on exactly what
    # the reader would scroll to anyway. Nav item order itself follows
    # CATEGORY_LABELS' fixed key order (stable day-to-day), independent of
    # where each category's content happens to land in the sorted report.
    first_id_for_category: dict[str, int] = {}
    for s in sections:
        first_id_for_category.setdefault(s["category"], s["id"])
    category_nav = [
        (cat, first_id_for_category[cat]) for cat in CATEGORY_LABELS if cat in first_id_for_category
    ]

    for lang in ("he", "en"):
        html_str = build_report_html(report_date, sources, sections, lang, category_nav)

        out_dir = REPORTS_DIR / lang
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / f"report_{report_date}_{lang}.html"
        html_path.write_text(html_str, encoding="utf-8")
        print(f"  wrote {html_path}")

        if WEASYPRINT_AVAILABLE:
            pdf_path = out_dir / f"report_{report_date}_{lang}.pdf"
            WeasyHTML(string=html_str, base_url=str(html_path)).write_pdf(str(pdf_path))
            print(f"  wrote {pdf_path}")
        else:
            print("  PDF skipped: WeasyPrint/GTK runtime not available on this machine.")

    print(
        f"\nRender complete for {report_date}: {len(sections)} section(s) "
        f"({main_count} main + {fallback_count} additional-coverage)."
    )


def run(report_date: str) -> None:
    conn = get_connection()
    init_db(conn)
    render_report(conn, report_date)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reporting stage 2: render a synthesized report to bilingual HTML+PDF."
    )
    parser.add_argument("--date", required=True, help="Report date to render, format YYYY-MM-DD.")
    args = parser.parse_args()
    run(report_date=args.date)
