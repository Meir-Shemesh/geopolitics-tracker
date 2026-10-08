"""Renders one biweekly narrative-trends report (src/reporting/synthesize_biweekly.py's
output) to HTML, in all three languages - docs/{lang}/biweekly_{start}_{end}_{lang}.html,
no root copy (a deep-link destination, not a primary landing page - same convention as
report_{date}_{lang}.html itself).

Deliberately visually distinct from a daily report (per the spec: the reader should
know immediately they're in a different content type) while reusing the exact same
design-language building blocks (theme tokens, nav, footer, fonts) - no new palette.
The distinguishing device is a period-badge in the masthead and a plainer, non-
accordion vertical list of topics (no category chips - biweekly topics aren't
categorized) with a visible "distinct sources" byline and a row of deep-links to the
daily reports that contributed to each topic.
"""
from src.reporting.render import (
    FONT_FAMILY,
    FONT_FILENAME,
    build_footer_html,
    build_nav_html,
    esc,
    font_face_css,
    footer_hrefs_for,
    head_meta_html,
    nav_chrome_css,
    other_langs,
    print_force_light_css,
    shared_chrome_css,
    theme_tokens_css,
)

PAGE_LABELS = {
    "he": {
        "eyebrow": "גאופוליטיקה יומי",
        "badge": "דוח מגמות דו-שבועי",
        "sources_word": "מקורות",
        "days_word": "מתוך 14 יום",
        "daily_links_label": "ראו בדוחות היומיים:",
        "pdf_download": None,
    },
    "en": {
        "eyebrow": "Daily Geopolitics",
        "badge": "Biweekly Trends Report",
        "sources_word": "sources",
        "days_word": "of 14 days",
        "daily_links_label": "See in the daily reports:",
        "pdf_download": None,
    },
    "de": {
        "eyebrow": "Tägliche Geopolitik",
        "badge": "Zweiwöchentlicher Trendbericht",
        "sources_word": "Quellen",
        "days_word": "von 14 Tagen",
        "daily_links_label": "In den Tagesberichten ansehen:",
        "pdf_download": None,
    },
}

_MONTHS = {
    "en": ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"],
    "de": ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"],
}


def period_filename(start: str, end: str, lang: str) -> str:
    return f"biweekly_{start}_{end}_{lang}.html"


def format_period_range(start_iso: str, end_iso: str, lang: str) -> str:
    import datetime as _dt
    d0 = _dt.date.fromisoformat(start_iso)
    d1 = _dt.date.fromisoformat(end_iso)
    if lang == "he":
        return f"{d0.day}.{d0.month}–{d1.day}.{d1.month}.{d1.year}"
    if lang == "de":
        return f"{d0.day}.–{d1.day}. {_MONTHS['de'][d1.month]} {d1.year}"
    return f"{_MONTHS['en'][d0.month]} {d0.day}–{d1.day}, {d1.year}"


def _short_date(iso: str, lang: str) -> str:
    import datetime as _dt
    d = _dt.date.fromisoformat(iso)
    return f"{d.day}.{d.month}"


def build_biweekly_report_html(
    period: dict,
    topics: list[dict],
    dates_sources_by_topic: dict[int, tuple[list[dict], list[str]]],
    lang: str,
) -> str:
    """`period` is a biweekly_periods row; `topics` is a list of
    biweekly_topics rows (already ordered by sort_order); `dates_sources_by_topic`
    maps topic id -> (list of {section_id, report_date} rows, distinct newspaper
    sources) from db.get_dates_and_sources_for_biweekly_topic()."""
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    L = PAGE_LABELS[lang]
    start, end = period["start_date"], period["end_date"]
    range_label = format_period_range(start, end, lang)
    page_title = f"{L['badge']} - {range_label} - {L['eyebrow']}"

    lang_hrefs = {o: period_filename(start, end, o) for o in other_langs(lang)}
    nav_html = build_nav_html("trends.html", lang_hrefs, lang)

    topic_blocks = []
    for t in topics:
        days_rows, sources = dates_sources_by_topic[t["id"]]
        label = esc(t[f"topic_label_{lang}"])
        text = esc(t[f"comparison_text_{lang}"])
        day_links = "".join(
            f'<a class="daily-link" href="report_{d["report_date"]}_{lang}.html#section-{d["section_id"]}">'
            f'{esc(_short_date(d["report_date"], lang))}</a>'
            for d in days_rows
        )
        byline = (
            f"{t['n_distinct_days']} {esc(L['days_word'])} · {t['n_sources']} {esc(L['sources_word'])}: "
            f"{esc(', '.join(sources))}"
        )
        topic_blocks.append(f"""
    <article class="biweekly-topic">
      <h2 class="biweekly-topic-title">{label}</h2>
      <p class="biweekly-topic-byline">{byline}</p>
      <p class="biweekly-topic-text">{text}</p>
      <div class="biweekly-daily-links">
        <span class="biweekly-daily-links-label">{esc(L['daily_links_label'])}</span>
        {day_links}
      </div>
    </article>""")

    overview = esc(period[f"overview_{lang}"])

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
{head_meta_html(page_title, "../")}
<style>
  {font_face_css(f"../assets/fonts/{FONT_FILENAME}")}

{theme_tokens_css()}

  * {{ box-sizing: border-box; }}
  html, body {{ overflow-x: hidden; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "{FONT_FAMILY}", system-ui, sans-serif;
    line-height: 1.7;
  }}

  {nav_chrome_css()}

  .masthead {{
    background: var(--bg-elevated);
    border-bottom: 3px solid var(--masthead-accent);
    padding: 2.25rem 1.5rem 1.75rem;
  }}
  .masthead-inner {{ max-width: 44rem; margin: 0 auto; }}
  .biweekly-badge {{
    display: inline-block;
    font-size: .78rem;
    font-weight: 700;
    letter-spacing: .03em;
    text-transform: uppercase;
    color: var(--bg);
    background: var(--masthead-accent);
    border-radius: 999px;
    padding: .3rem .9rem;
    margin-bottom: .75rem;
  }}
  /* direction:ltr - the date-range string ("30.9.2026-17.9") is almost
     entirely Latin/numeric with no Hebrew characters of its own; left
     undeclared inside an RTL masthead it bidi-reorders and overflows past
     the viewport edge on narrow screens (same fix already used for
     citation boxes elsewhere in this project, see render.py). */
  .report-title {{ margin: 0; font-size: 1.9rem; font-weight: 800; letter-spacing: -0.01em; direction: ltr; text-align: {"right" if is_he else "left"}; }}
  .biweekly-overview {{
    max-width: 44rem;
    margin: 1.5rem auto 0;
    padding: 0 1.5rem;
    font-size: 1.02rem;
    color: var(--text-muted);
  }}

  main {{ max-width: 44rem; margin: 0 auto; padding: 2rem 1.5rem 3rem; }}

  .biweekly-topic {{
    padding: 1.6rem 0;
    border-bottom: 1px solid var(--border);
  }}
  .biweekly-topic:first-child {{ padding-top: 0; }}
  .biweekly-topic-title {{ margin: 0 0 .4rem; font-size: 1.3rem; font-weight: 700; }}
  /* overflow-wrap: a long comma-separated Latin-script source list mixed
     with a short Hebrew/German prefix can overflow the viewport on narrow
     screens instead of wrapping - same class of bidi-mixing issue the
     citation boxes handle elsewhere in this project, fixed here with a
     blunter, reliably-safe wrap rule rather than isolating direction. */
  .biweekly-topic-byline {{ margin: 0 0 .8rem; font-size: .82rem; color: var(--text-muted); overflow-wrap: break-word; }}
  .biweekly-topic-text {{ margin: 0; font-size: 1rem; }}
  .biweekly-daily-links {{
    margin-top: .9rem;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: .45rem;
    direction: ltr;
  }}
  .biweekly-daily-links-label {{
    font-size: .78rem;
    color: var(--text-muted);
    margin-inline-end: .3rem;
  }}
  .daily-link {{
    font-size: .78rem;
    font-weight: 600;
    color: var(--masthead-accent);
    text-decoration: none;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: .2rem .65rem;
  }}
  .daily-link:hover {{ border-color: var(--masthead-accent); text-decoration: underline; }}

  @media print {{
{print_force_light_css()}
  }}
  {shared_chrome_css()}
</style>
</head>
<body>
{nav_html}
  <header class="masthead">
    <div class="masthead-inner">
      <span class="biweekly-badge">{esc(L['badge'])}</span>
      <h1 class="report-title">{esc(range_label)}</h1>
    </div>
  </header>
  <p class="biweekly-overview">{overview}</p>
  <main>
    {"".join(topic_blocks)}
  </main>
{build_footer_html(lang, *footer_hrefs_for(lang))}
</body>
</html>
"""
