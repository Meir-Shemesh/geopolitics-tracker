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
import shutil
from pathlib import Path

from src.common.db import get_all_reports, get_connection, init_db
from src.reporting.render import (
    LANG_LABEL,
    NEWSPAPER_DISPLAY_NAMES,
    OTHER_LANG,
    esc,
    format_date_en,
    format_date_he,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
FONT_SOURCE_PATH = REPORTS_DIR / "assets" / "fonts" / "Heebo-Variable.ttf"


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


def run() -> None:
    conn = get_connection()
    init_db(conn)
    entries = [(r["report_date"], json.loads(r["sources_included"])) for r in get_all_reports(conn)]
    conn.close()

    if not entries:
        print("No reports found in DB - nothing to publish.")
        return

    _copy_font()
    _copy_reports_to_docs()

    for lang in ("he", "en"):
        html_str = build_index_html(
            entries,
            lang,
            report_link_prefix="",
            other_lang_href=f"../{OTHER_LANG[lang]}/index.html",
            font_relative_path="../assets/fonts/Heebo-Variable.ttf",
        )
        for out_dir in (REPORTS_DIR / lang, DOCS_DIR / lang):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.html").write_text(html_str, encoding="utf-8")
        print(f"  wrote index.html for '{lang}' ({len(entries)} report date(s))")

    root_html = build_index_html(
        entries,
        "he",
        report_link_prefix="he/",
        other_lang_href="en/index.html",
        font_relative_path="assets/fonts/Heebo-Variable.ttf",
    )
    (DOCS_DIR / "index.html").write_text(root_html, encoding="utf-8")
    print(f"  wrote {DOCS_DIR / 'index.html'} (root, Hebrew default)")

    print(f"\nPublish complete: {len(entries)} report date(s) -> {DOCS_DIR}")


if __name__ == "__main__":
    run()
