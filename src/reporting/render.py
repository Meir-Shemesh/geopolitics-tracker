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
        <div class="citations-row">
          <button class="citations-toggle" type="button" aria-expanded="false" aria-controls="{popup_id}">{esc(toggle_label)} ({len(citations)}) ▾</button>
          <div class="citations-popup" id="{popup_id}" hidden>
            <ul>
{items_html}
            </ul>
          </div>
        </div>"""


def _render_section(section: dict, lang: str, show_sources: bool) -> str:
    label = CATEGORY_LABELS.get(section["category"], CATEGORY_LABELS[FALLBACK_CATEGORY])[lang]
    topic = section["topic_label_he"] if lang == "he" else section["topic_label_en"]
    text = section["comparison_text_he"] if lang == "he" else section["comparison_text_en"]

    sources_html = ""
    if show_sources and section["newspapers"]:
        names = ", ".join(esc(NEWSPAPER_DISPLAY_NAMES.get(n, n)) for n in section["newspapers"])
        sources_label = "מקורות" if lang == "he" else "Sources"
        sources_html = f'<p class="section-sources">{sources_label}: <b>{names}</b></p>'

    citations_html = _build_citations_html(section["citations"], lang, section["id"])

    return f"""
      <section class="topic-section" id="section-{section['id']}" data-category="{esc(section['category'])}">
        <div class="topic-meta">
          <span class="category-dot"></span>
          <span class="category-label">{esc(label)}</span>
        </div>
        <h2 class="section-title">{esc(topic)}</h2>
        <p class="comparison-text">{esc(text)}</p>
        {sources_html}
        {citations_html}
      </section>"""


def build_report_html(report_date: str, sources: list[str], sections: list[dict], lang: str) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"

    date_str = format_date_he(report_date) if is_he else format_date_en(report_date)
    page_title = f"דוח יומי - {date_str}" if is_he else f"Daily Geopolitics Report - {date_str}"
    eyebrow = "גאופוליטיקה יומי" if is_he else "Daily Geopolitics"
    sources_label = "עיתונים שנסקרו היום:" if is_he else "Sources covering today:"

    source_pills = "".join(f"<li>{esc(NEWSPAPER_DISPLAY_NAMES.get(s, s))}</li>" for s in sources)

    main_sections = [s for s in sections if s["category"] != FALLBACK_CATEGORY]
    fallback_sections = [s for s in sections if s["category"] == FALLBACK_CATEGORY]

    main_html = "\n".join(_render_section(s, lang, show_sources=True) for s in main_sections)

    fallback_html = ""
    if fallback_sections:
        appendix_title = (
            "כיסוי נוסף (מאמרים בודדים, ללא השוואה בין מקורות)"
            if is_he else "Additional Coverage (single-source items)"
        )
        fallback_items = "\n".join(
            _render_section(s, lang, show_sources=False) for s in fallback_sections
        )
        fallback_html = f"""
      <section class="appendix">
        <h2 class="appendix-title">{esc(appendix_title)}</h2>
        {fallback_items}
      </section>"""

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
  .section-title {{ margin: 0 0 .75rem; font-size: 1.3rem; font-weight: 700; line-height: 1.4; }}
  .comparison-text {{ margin: 0 0 1rem; font-size: 1rem; color: var(--text); line-height: 1.85; }}
  .section-sources {{
    margin: 0;
    font-size: .82rem;
    color: var(--text-muted);
    border-top: 1px solid var(--border);
    padding-top: .75rem;
  }}
  .section-sources b {{ color: var(--text); font-weight: 600; }}

  .citations-row {{ position: relative; margin-top: .6rem; }}
  .citations-toggle {{
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    font: inherit;
    font-size: .78rem;
    color: var(--text-muted);
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 2px;
  }}
  .citations-toggle:hover {{ color: var(--masthead-accent); }}
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

  .appendix {{ display: flex; flex-direction: column; gap: 1rem; }}
  .appendix-title {{ font-size: 1.1rem; font-weight: 700; color: var(--text-muted); margin: .5rem 0 0; }}
  .appendix .topic-section {{ padding: 1.1rem 1.3rem 1.2rem; }}
  .appendix .section-title {{ font-size: 1.05rem; }}

  @media print {{
    @page {{
      size: A4;
      margin: 2cm 1.8cm;
      @bottom-center {{ content: counter(page) " / " counter(pages); font-size: 9px; color: #888; }}
    }}
    body {{ background: #fff; }}
    .top-nav {{ display: none; }}
    .citations-row {{ display: none; }}
  }}
</style>
</head>
<body>
{build_nav_html("archive.html", f"../{OTHER_LANG[lang]}/report_{report_date}_{OTHER_LANG[lang]}.html", lang, f"report_{report_date}_{lang}.pdf")}
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
{main_html}
{fallback_html}
  </main>
  <script>
    document.addEventListener('click', function (e) {{
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

    main_count = sum(1 for s in sections if s["category"] != FALLBACK_CATEGORY)
    fallback_count = len(sections) - main_count

    for lang in ("he", "en"):
        html_str = build_report_html(report_date, sources, sections, lang)

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
