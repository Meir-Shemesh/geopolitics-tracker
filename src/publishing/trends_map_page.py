"""docs/{lang}/trendsmap.html - the tile-map trends page (PROJECT_LOG 4.123).

Alternative 2 of the three chosen sketches ("change map"): a tile per country on an approximate world grid, coloured by
how far the country's share of the coverage differs from its own recent level. Brown rises, blue fades; a tile with too
little evidence is striped, not coloured. It reads assets/data/trends_map.json (src/common/trends_map.py) in the
browser, like every data page here, and sits next to the older trendschart.html without replacing it.

The colour work stays in the page's JavaScript on purpose: it reads the site's theme tokens when it draws, so the light
and dark themes (and the manual toggle) recolour the tiles, and it checks the contrast of the number on every tile.
"""

import json
from pathlib import Path

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
    shared_chrome_css,
    theme_tokens_css,
)

OUTLINE_PATH = Path(__file__).resolve().parent / "assets" / "map" / "tile_outline.txt"

LABELS = {
    "he": {
        "page_title": "מפת שינוי בסיקור (בטא) - מעקב גאופוליטיקה יומי",
        "eyebrow": "מעקב גאופוליטיקה יומי",
        "heading": "מפת שינוי: מה זז בסיקור",
        "beta_badge": "בטא",
        "explainer": "הצבע מראה כמה החלק של המדינה בסיקור שונה מהרגיל, ולא כמה היא גדולה. חום עולה, כחול דועך. מדינות שבשבוע הנוכחי או בתקופת ההשוואה יש עליהן מעט ראיות מסומנות בפסים ואינן נצבעות, כדי שמעבר מכתבה אחת לשתיים לא ייראה כזינוק. מדינה ששתי שיטות החישוב של חלקה נותנות בה כיוון הפוך מסומנת גם היא בפסים, כי אי אפשר לדעת אם היא עולה או דועכת.",
        "callout_title": "גרסת בטא: לקרוא בזהירות",
        "callout_weeks": "מבוסס על {weeks} שבועות בלבד.",
        "callout_lower_bound": "הספירה כוללת רק כתבות שבהן המדינה נזכרת במפורש, ולכן המספרים הם גבול תחתון.",
        "callout_share": "החלק של מדינה הוא הממוצע של חלקה בכל עיתון בנפרד, כך שעיתון שמדפיס יותר אינו שוקל יותר.",
        "callout_caution": "אין להסיק מגמה לגבי מדינה מחלק קטן או משבוע בודד.",
        "callout_scope": "המספרים משקפים את העיתונים הנסקרים בלבד, ולא את הסיקור בעולם.",
        "callout_backlog": "ימי השלמת פרסום אינם מנוטרלים במלואם.",
        "loading": "טוען…",
        "load_error": "טעינת הנתונים נכשלה. אפשר לרענן את הדף.",
        "map_label": "מפת אריחים של מדינות לפי שינוי בחלקן בסיקור",
        "play": "ניגון",
        "pause": "עצירה",
        "week_slider": "שבוע",
        "week_label": "שבוע {n} מתוך {total}, {from} עד {to}",
        "base_label": "בסיס להשוואה:",
        "base_1": "שבוע קודם",
        "base_4": "4 שבועות קודמים",
        "steps": "{n} צעדים",
        "series_label": "סדרה:",
        "series_core": "ליבה: 9 עיתונים",
        "series_all": "כל 14 העיתונים",
        "series_core_note": "תשעה עיתונים שנסרקו לאורך כל התקופה: שלושה מארצות הברית, שלושה מבריטניה ושלושה מגרמניה.",
        "series_all_warning": "סדרה זו מושפעת מגידול המקורות (מ-{from} ל-{to} עיתונים בשבוע), ולכן חלק מהשינויים משקפים הרחבת מקורות ולא שינוי בשיח.",
        "note_partial": "שבוע חלקי: {days} ימים בלבד.",
        "note_backlog": "השבוע כולל ימי השלמת פרסום.",
        "note_break": "ההשוואה חוצה שינוי בנתונים: {label}",
        "legend_change": "שינוי בנקודות אחוז",
        "legend_low": "לא נצבע: ראיות מעטות או כיוון לא ברור",
        "rising": "עולות",
        "fading": "דועכות",
        "none_rising": "אין מדינה שעלתה באופן ברור.",
        "none_fading": "אין מדינה שדעכה באופן ברור.",
        "no_baseline": "לשבוע הזה אין בסיס להשוואה.",
        "selected_hint": "לחצו על מדינה במפה כדי לראות את הפירוט שלה.",
        "selected_low": "אין מספיק ראיות: פחות מ-{min} כתבות בשבוע הנוכחי או בתקופת ההשוואה, ולכן לא מוצג שינוי.",
        "selected_n": "בשבוע הנוכחי: {n} כתבות.",
        "selected_n_both_1": "בשבוע הנוכחי: {n} כתבות; בשבוע הקודם: {base_n} כתבות.",
        "selected_n_both": "בשבוע הנוכחי: {n} כתבות; בתקופת ההשוואה: {base_n} כתבות בשבוע בממוצע.",
        "selected_unclear": "הכיוון לא ברור: חישוב החלק לפי עיתון וחישוב מאוחד של כל הכתבות מצביעים על כיוונים הפוכים, ולכן לא מוצג שינוי.",
        "selected_text": "החלק היה {was}% {base}, ועכשיו {now}%. שינוי של {delta} נקודות אחוז, על סמך {n} כתבות בשבוע הנוכחי.",
        "base_text_1": "בשבוע הקודם",
        "base_text_4": "בממוצע ארבעת השבועות הקודמים",
        "tile_aria": "{country}, שינוי של {delta} נקודות אחוז",
        "tile_aria_low": "{country}, ראיות מעטות",
        "tile_aria_unclear": "{country}, כיוון לא ברור",
        "tile_aria_none": "{country}, אין בסיס להשוואה",
        "table_summary": "הצגה כטבלה",
        "col_country": "מדינה",
        "col_now": "החלק עכשיו",
        "col_base": "החלק בתקופת ההשוואה",
        "col_delta": "שינוי",
        "col_n": "כתבות",
        "low_mark": "ראיות מעטות",
        "unclear_mark": "כיוון לא ברור",
        "reports_link": "דוחות מגמות דו-שבועיים",
    },
    "en": {
        "page_title": "Coverage Change Map (Beta) - Daily Geopolitics",
        "eyebrow": "Daily Geopolitics",
        "heading": "Coverage Change Map: What Moved",
        "beta_badge": "Beta",
        "explainer": "Color shows how far a country's share of the coverage differs from its usual level, not how big the country is. Brown means rising, blue means fading. Countries with little evidence, in the current week or in the comparison period, are striped and left uncolored, so a jump from one article to two never looks like a surge. A country is also striped and left uncolored when the two ways of calculating its share point in opposite directions, because then we cannot tell whether it is rising or fading.",
        "callout_title": "Beta: read with care",
        "callout_weeks": "Based on only {weeks} weeks of data.",
        "callout_lower_bound": "The count includes only articles that explicitly mention the country, so the figures are a lower bound.",
        "callout_share": "A country's share is the average of its share in each newspaper, so a paper that prints more does not weigh more.",
        "callout_caution": "Do not read a trend into a country from a small share or from a single week.",
        "callout_scope": "The figures describe the newspapers surveyed only, not coverage worldwide.",
        "callout_backlog": "Days of catch-up publishing are not fully neutralized.",
        "loading": "Loading…",
        "load_error": "The data could not be loaded. Try reloading the page.",
        "map_label": "Tile map of countries by change in their share of the coverage",
        "play": "Play",
        "pause": "Pause",
        "week_slider": "Week",
        "week_label": "Week {n} of {total}, {from} to {to}",
        "base_label": "Compare with:",
        "base_1": "Previous week",
        "base_4": "Previous 4 weeks",
        "steps": "{n} steps",
        "series_label": "Series:",
        "series_core": "Core: 9 newspapers",
        "series_all": "All 14 newspapers",
        "series_core_note": "Nine newspapers surveyed throughout the period: three from the United States, three from Britain and three from Germany.",
        "series_all_warning": "This series is affected by the growing list of sources (from {from} to {to} newspapers per week), so part of the change reflects broader sourcing, not a shift in the conversation.",
        "note_partial": "Partial week: only {days} days.",
        "note_backlog": "This week includes catch-up publishing days.",
        "note_break": "The comparison crosses a change in the data: {label}",
        "legend_change": "Change in percentage points",
        "legend_low": "Not colored: little evidence or unclear direction",
        "rising": "Rising",
        "fading": "Fading",
        "none_rising": "No country rose clearly.",
        "none_fading": "No country faded clearly.",
        "no_baseline": "There is no baseline to compare this week with.",
        "selected_hint": "Select a country on the map to see its detail.",
        "selected_low": "Not enough evidence: fewer than {min} articles in the current week or in the comparison period, so no change is shown.",
        "selected_n": "This week: {n} articles.",
        "selected_n_both_1": "This week: {n} articles; previous week: {base_n} articles.",
        "selected_n_both": "This week: {n} articles; comparison period: {base_n} articles per week on average.",
        "selected_unclear": "Direction unclear: the share per newspaper and the share pooled across all articles point in opposite directions, so no change is shown.",
        "selected_text": "The share was {was}% {base}, and is now {now}%. A change of {delta} percentage points, based on {n} articles this week.",
        "base_text_1": "in the previous week",
        "base_text_4": "on average over the previous four weeks",
        "tile_aria": "{country}, change of {delta} percentage points",
        "tile_aria_low": "{country}, little evidence",
        "tile_aria_unclear": "{country}, direction unclear",
        "tile_aria_none": "{country}, no baseline to compare with",
        "table_summary": "Show as a table",
        "col_country": "Country",
        "col_now": "Share now",
        "col_base": "Baseline share",
        "col_delta": "Change",
        "col_n": "Articles",
        "low_mark": "little evidence",
        "unclear_mark": "direction unclear",
        "reports_link": "Biweekly Trends Reports",
    },
    "de": {
        "page_title": "Veränderungskarte der Berichterstattung (Beta) - Tägliche Geopolitik",
        "eyebrow": "Tägliche Geopolitik",
        "heading": "Veränderungskarte: Was sich bewegt hat",
        "beta_badge": "Beta",
        "explainer": "Die Farbe zeigt, wie stark der Anteil eines Landes an der Berichterstattung vom üblichen Niveau abweicht, nicht wie groß das Land ist. Braun steht für Zunahme, Blau für Rückgang. Länder mit dünner Datenlage in der aktuellen Woche oder im Vergleichszeitraum sind gestreift und bleiben ungefärbt, damit der Sprung von einem auf zwei Artikel nicht wie ein Anstieg aussieht. Gestreift und ungefärbt bleibt ein Land auch dann, wenn die beiden Berechnungsweisen seines Anteils in entgegengesetzte Richtungen zeigen, weil dann unklar ist, ob es zu- oder abnimmt.",
        "callout_title": "Beta: mit Vorsicht lesen",
        "callout_weeks": "Basiert auf nur {weeks} Wochen an Daten.",
        "callout_lower_bound": "Gezählt werden nur Artikel, in denen das Land ausdrücklich genannt wird; die Zahlen sind daher eine Untergrenze.",
        "callout_share": "Der Anteil eines Landes ist der Durchschnitt seines Anteils in jeder einzelnen Zeitung; eine Zeitung, die mehr druckt, zählt also nicht mehr.",
        "callout_caution": "Aus einem kleinen Anteil oder aus einer einzelnen Woche lässt sich für ein Land kein Trend ablesen.",
        "callout_scope": "Die Zahlen beschreiben nur die ausgewerteten Zeitungen, nicht die Berichterstattung weltweit.",
        "callout_backlog": "Tage mit nachgeholter Veröffentlichung sind nicht vollständig herausgerechnet.",
        "loading": "Wird geladen…",
        "load_error": "Die Daten konnten nicht geladen werden. Bitte die Seite neu laden.",
        "map_label": "Kachelkarte der Länder nach Veränderung ihres Anteils an der Berichterstattung",
        "play": "Abspielen",
        "pause": "Anhalten",
        "week_slider": "Woche",
        "week_label": "Woche {n} von {total}, {from} bis {to}",
        "base_label": "Vergleich mit:",
        "base_1": "Vorwoche",
        "base_4": "Vorherige 4 Wochen",
        "steps": "{n} Schritte",
        "series_label": "Reihe:",
        "series_core": "Kern: 9 Zeitungen",
        "series_all": "Alle 14 Zeitungen",
        "series_core_note": "Neun Zeitungen, die im gesamten Zeitraum ausgewertet wurden: drei aus den USA, drei aus Großbritannien und drei aus Deutschland.",
        "series_all_warning": "Diese Reihe wird durch die wachsende Quellenzahl verzerrt (von {from} auf {to} Zeitungen pro Woche); ein Teil der Veränderungen spiegelt daher die breitere Quellenbasis wider und keinen Wandel im Diskurs.",
        "note_partial": "Unvollständige Woche: nur {days} Tage.",
        "note_backlog": "Diese Woche enthält nachgeholte Veröffentlichungstage.",
        "note_break": "Der Vergleich überschreitet eine Änderung in den Daten: {label}",
        "legend_change": "Veränderung in Prozentpunkten",
        "legend_low": "Nicht gefärbt: dünne Datenlage oder unklare Richtung",
        "rising": "Zunehmend",
        "fading": "Abnehmend",
        "none_rising": "Kein Land hat deutlich zugelegt.",
        "none_fading": "Kein Land hat deutlich nachgelassen.",
        "no_baseline": "Für diese Woche gibt es keinen Vergleichswert.",
        "selected_hint": "Ein Land auf der Karte auswählen, um Einzelheiten zu sehen.",
        "selected_low": "Zu wenig Belege: weniger als {min} Artikel in der aktuellen Woche oder im Vergleichszeitraum, daher wird keine Veränderung angezeigt.",
        "selected_n": "Diese Woche: {n} Artikel.",
        "selected_n_both_1": "Diese Woche: {n} Artikel; Vorwoche: {base_n} Artikel.",
        "selected_n_both": "Diese Woche: {n} Artikel; Vergleichszeitraum: durchschnittlich {base_n} Artikel pro Woche.",
        "selected_unclear": "Richtung unklar: Der Anteil pro Zeitung und der Anteil über alle Artikel zusammen zeigen in entgegengesetzte Richtungen, daher wird keine Veränderung angezeigt.",
        "selected_text": "Der Anteil lag {base} bei {was}% und liegt jetzt bei {now}%. Eine Veränderung von {delta} Prozentpunkten, gestützt auf {n} Artikel in der aktuellen Woche.",
        "base_text_1": "in der Vorwoche",
        "base_text_4": "im Schnitt der vier Vorwochen",
        "tile_aria": "{country}, Veränderung um {delta} Prozentpunkte",
        "tile_aria_low": "{country}, dünne Datenlage",
        "tile_aria_unclear": "{country}, Richtung unklar",
        "tile_aria_none": "{country}, kein Vergleichswert",
        "table_summary": "Als Tabelle anzeigen",
        "col_country": "Land",
        "col_now": "Anteil jetzt",
        "col_base": "Anteil im Vergleich",
        "col_delta": "Veränderung",
        "col_n": "Artikel",
        "low_mark": "dünne Datenlage",
        "unclear_mark": "Richtung unklar",
        "reports_link": "Zweiwöchentliche Trendberichte",
    },
}

_CSS = """
  __FONT__

__TOKENS__

  :root {
    --map-up: var(--masthead-accent);
    --map-down: #1066a3;
    --map-neutral: var(--bg-elevated);
    --hatch-a: var(--border);
    --hatch-b: var(--bg);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { --map-down: #4a93c2; }
  }
  :root[data-theme="dark"] { --map-down: #4a93c2; }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "__FAMILY__", system-ui, sans-serif;
    line-height: 1.6;
  }

  __NAV__

  .masthead {
    background: var(--bg-elevated);
    border-bottom: 3px solid var(--masthead-accent);
    padding: 2rem 1.5rem 1.5rem;
  }
  .masthead-inner { max-width: 72rem; margin: 0 auto; }
  .eyebrow { margin: 0 0 .5rem; font-size: .85rem; font-weight: 600; letter-spacing: .04em; color: var(--masthead-accent); text-transform: uppercase; }
  .heading-row { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
  .report-title { margin: 0; font-size: 2rem; font-weight: 800; letter-spacing: -0.01em; }
  .beta-badge { display: inline-block; font-size: .72rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--chip-selected-text); background: var(--masthead-accent); border-radius: .4rem; padding: .2rem .55rem; }
  .reports-link { margin: .6rem 0 0; font-size: .9rem; }
  .reports-link a { color: var(--masthead-accent); font-weight: 600; }
  .explainer { margin: .8rem 0 0; max-width: 46rem; font-size: .95rem; }
  .beta-callout { margin: .9rem 0 0; max-width: 46rem; padding: .8rem 1rem; border: 1px solid var(--border); background: var(--bg); border-radius: .5rem; font-size: .9rem; }
  .beta-callout-title { margin: 0 0 .4rem; font-weight: 700; }
  .beta-callout-list { margin: 0; padding-inline-start: 1.2rem; display: grid; gap: .3rem; }

  .map-body { max-width: 75rem; margin: 0 auto; padding: 1.5rem 1.5rem 3rem; }
  #map-loading, #map-error { color: var(--text-muted); padding: 2rem 0; }

  .controls { display: flex; flex-wrap: wrap; align-items: center; gap: .75rem 1.25rem; margin-bottom: .75rem; }
  .player { flex: 1 1 22rem; display: flex; align-items: center; gap: .9rem; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: .6rem; padding: .5rem .9rem; direction: ltr; }
  .play-btn { flex: none; width: 2.75rem; height: 2.75rem; border-radius: 50%; border: 0; background: var(--masthead-accent); color: var(--chip-selected-text); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
  .play-btn svg { width: 1rem; height: 1rem; fill: currentColor; }
  .play-btn .icon-pause { display: none; }
  .play-btn[aria-pressed="true"] .icon-pause { display: block; }
  .play-btn[aria-pressed="true"] .icon-play { display: none; }
  #m-range { flex: 1; min-width: 6rem; height: 1.75rem; accent-color: var(--masthead-accent); }
  .week-label { min-width: 11rem; font-size: .95rem; font-weight: 700; font-variant-numeric: tabular-nums; direction: __DIR__; text-align: start; }
  .opt-group { display: flex; align-items: center; flex-wrap: wrap; gap: .4rem; font-size: .85rem; }
  .opt-label { color: var(--text-muted); }
  .opt-btn { min-height: 2.25rem; padding: .3rem .8rem; border: 1px solid var(--pill-border); background: var(--pill-bg); color: var(--pill-text); border-radius: 1rem; font-family: inherit; font-size: .85rem; cursor: pointer; }
  .opt-btn[aria-pressed="true"] { background: var(--masthead-accent); border-color: var(--masthead-accent); color: var(--chip-selected-text); font-weight: 700; }
  .opt-btn .opt-steps { font-size: .78rem; margin-inline-start: .3rem; }

  .notes { margin: 0 0 .5rem; font-size: .85rem; color: var(--text-muted); display: grid; gap: .15rem; }
  .banner { border: 1px solid var(--border); border-inline-start: 4px solid var(--map-down); background: var(--bg-elevated); border-radius: .5rem; padding: .7rem 1rem; font-size: .88rem; margin: 0 0 .9rem; }
  .series-note { margin: 0 0 .9rem; font-size: .85rem; color: var(--text-muted); }

  .map-layout { display: grid; grid-template-columns: minmax(0, 1fr) 18.5rem; gap: 1.5rem; align-items: start; }
  .map { position: relative; width: 100%; aspect-ratio: 798 / 399; container-type: inline-size; direction: ltr; }
  .map-outline { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
  .map-outline path { fill: var(--bg-elevated); fill-opacity: .55; stroke: var(--border); stroke-width: 1; }
  .tile { position: absolute; width: calc(54 / 798 * 100%); height: calc(54 / 399 * 100%); border: 0; border-radius: 7px; padding: 2px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px; font-family: inherit; cursor: pointer; overflow: hidden; line-height: 1.1; }
  .tile-name { font-size: max(8px, 1.25cqw); font-weight: 500; text-align: center; }
  .tile-code { display: none; font-size: max(10px, 2.6cqw); font-weight: 700; }
  .tile-val { font-size: max(8px, 1.5cqw); font-weight: 700; font-variant-numeric: tabular-nums; }
  .tile[aria-pressed="true"] { outline: 2.5px solid var(--text); outline-offset: 1px; z-index: 2; }
  .tile.is-low { background-image: repeating-linear-gradient(45deg, var(--hatch-a), var(--hatch-a) 3px, var(--hatch-b) 3px, var(--hatch-b) 6px); background-color: var(--bg); color: var(--text); }
  @container (max-width: 620px) {
    .tile-name { display: none; }
    .tile-code { display: block; }
    .tile-val { display: none; }
    .tile { border-radius: 4px; padding: 0; }
  }

  .legend { display: flex; flex-wrap: wrap; gap: .6rem 1.5rem; align-items: center; margin-top: .75rem; font-size: .82rem; color: var(--text-muted); }
  .legend-scale { display: flex; align-items: center; gap: .5rem; }
  .legend-bar { display: inline-flex; align-items: center; gap: .5rem; direction: ltr; }
  .legend-ramp { width: 10rem; height: .65rem; border-radius: .35rem; direction: ltr; background: linear-gradient(90deg, var(--map-down), var(--map-neutral), var(--map-up)); border: 1px solid var(--border); }
  .legend-num { direction: ltr; font-variant-numeric: tabular-nums; }
  .legend-low { display: flex; align-items: center; gap: .4rem; }
  .legend-swatch-low { width: 1.1rem; height: .8rem; border-radius: 3px; border: 1px solid var(--border); background-image: repeating-linear-gradient(45deg, var(--hatch-a), var(--hatch-a) 3px, var(--hatch-b) 3px, var(--hatch-b) 6px); }

  .site-footer { flex-wrap: wrap; row-gap: .4rem; }
  .top-nav { flex-wrap: wrap; }
  .top-nav-links { flex-wrap: wrap; row-gap: .25rem; min-width: 0; max-width: 100%; }

  .side { display: grid; gap: .9rem; }
  .card { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: .6rem; padding: .85rem 1rem; }
  .card h2 { margin: 0 0 .4rem; font-size: .8rem; letter-spacing: .05em; text-transform: uppercase; }
  .card h2.rising { color: var(--masthead-accent); }
  .card h2.fading { color: var(--map-down); }
  .rank-list { list-style: none; margin: 0 0 .6rem; padding: 0; display: grid; gap: .35rem; }
  .rank-btn { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: .6rem; align-items: baseline; padding: .3rem .4rem; border: 0; border-radius: .4rem; background: none; color: inherit; font: inherit; font-size: .88rem; text-align: start; cursor: pointer; }
  .rank-btn:hover { background: var(--bg); }
  .rank-btn[aria-pressed="true"] { background: var(--bg); outline: 1.5px solid var(--text); }
  .table-btn { border: 0; background: none; color: inherit; font: inherit; text-align: start; cursor: pointer; padding: .1rem 0; text-decoration: underline; text-decoration-color: var(--border); text-underline-offset: .2em; }
  .table-btn[aria-pressed="true"] { font-weight: 800; }
  .table-wrap tr[aria-current="true"] td { background: var(--bg); }
  .rank-range { direction: ltr; font-size: .78rem; color: var(--text-muted); font-variant-numeric: tabular-nums; }
  .rank-delta { direction: ltr; font-weight: 700; font-variant-numeric: tabular-nums; }
  .rising-delta { color: var(--masthead-accent); }
  .fading-delta { color: var(--map-down); }
  .rank-empty { font-size: .85rem; color: var(--text-muted); margin: 0 0 .6rem; }
  .sel-name { margin: 0 0 .25rem; font-size: 1.05rem; font-weight: 800; }
  .sel-text { margin: 0; font-size: .88rem; }

  .table-view { margin-top: 1.25rem; }
  .table-view summary { cursor: pointer; font-weight: 700; font-size: .9rem; }
  .table-wrap { margin-top: .6rem; overflow-x: auto; }
  .table-wrap table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  .table-wrap th, .table-wrap td { border: 1px solid var(--border); padding: .35rem .6rem; text-align: start; }
  .table-wrap td.num, .table-wrap th.num { text-align: end; direction: ltr; font-variant-numeric: tabular-nums; }

  @media (max-width: 52rem) {
    .map-layout { grid-template-columns: minmax(0, 1fr); }
    .report-title { font-size: 1.6rem; }
    .week-label { min-width: 0; flex: 1 1 100%; }
    .player { flex-wrap: wrap; }
    .table-wrap th, .table-wrap td { padding: .3rem .35rem; font-size: .78rem; }
  }

  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }

  __CHROME__
"""

_JS = r"""
(function () {
  var LABELS = __LABELS__;
  var LANG = "__LANG__";
  var DATA_URL = "__DATA_URL__";
  var FULL_SCALE_PP = 3.5;      // |change| that gets the full colour; about the 97th percentile of weekly changes
  var INK_DARK = [28, 23, 18], INK_LIGHT = [255, 255, 255];
  var MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  var data = null;
  var state = { series: "core", base: 1, week: 0, selected: null, timer: null };
  var tileEls = {};
  var els = {};

  function $(id) { return document.getElementById(id); }
  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, function (m, k) { return values[k] === undefined ? m : values[k]; });
  }
  function fmtDate(iso) {
    var p = iso.split("-"), d = parseInt(p[2], 10), m = parseInt(p[1], 10);
    return LANG === "en" ? MONTHS_EN[m - 1] + " " + d : LANG === "de" ? d + "." + m + "." : d + "." + m;
  }
  // One decimal, with the page language's decimal mark (a comma in German, a point in Hebrew and English).
  var NF1 = new Intl.NumberFormat(LANG === "de" ? "de-DE" : "en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false });
  function num1(v) { return NF1.format(v); }
  // A change that rounds to zero is shown as 0.0, never as +0.0 or −0.0.
  function signed(v) { var t = num1(Math.abs(v)); return t === num1(0) ? t : (v >= 0 ? "+" : "−") + t; }
  // Fills a template into an element as text, keeping the signed numbers in isolated left-to-right runs: inside Hebrew
  // text a bare "−1.2" would otherwise render with the sign on the wrong side.
  function setRich(el, template, values, isolated) {
    el.textContent = "";
    template.split(/(\{\w+\}%?)/).forEach(function (part) {
      var m = /^\{(\w+)\}(%?)$/.exec(part);
      if (m && values[m[1]] !== undefined) {
        if (isolated.indexOf(m[1]) >= 0) { var b = document.createElement("bdi"); b.setAttribute("dir", "ltr"); b.textContent = values[m[1]] + m[2]; el.appendChild(b); }
        else el.appendChild(document.createTextNode(String(values[m[1]]) + m[2]));
      } else if (part) el.appendChild(document.createTextNode(part));
    });
  }
  // A figure as an isolated left-to-right run, for places where it sits among right-to-left text.
  function bdiEl(text) { var b = document.createElement("bdi"); b.setAttribute("dir", "ltr"); b.textContent = text; return b; }
  function countryName(t) { return t["name_" + LANG]; }
  function shortName(t) { return t["short_" + LANG]; }

  // ----- the figures ---------------------------------------------------------------------------------------------
  function series() { return data.series[state.series]; }
  // The last week with seven days of data; the partial week after it stays reachable on the slider.
  function defaultWeek() { return data.default_week !== undefined ? data.default_week : nWeeks() - 1; }
  function nWeeks() { return data.weeks.length; }
  function firstWeek() { return series().first_week; }
  function baselineWeeks(week, base) {
    var out = [];
    if (week - base < firstWeek()) return out;
    for (var w = week - base; w < week; w++) out.push(w);
    return out;
  }
  function stepWeeks(base) {
    var out = [];
    for (var w = firstWeek(); w < nWeeks(); w++) if (baselineWeeks(w, base).length) out.push(w);
    return out;
  }
  // Same arithmetic as trends_map.change_vs_baseline (tests/test_trends_map.py keeps them in step).
  function figures(code, week, base) {
    var s = series().countries[code];
    var prior = baselineWeeks(week, base);
    if (!prior.length || s.share[week] === null) return null;
    var baseShare = 0, baseNamed = 0;
    prior.forEach(function (w) { baseShare += s.share[w] || 0; baseNamed += s.n_named[w]; });
    baseShare /= prior.length; baseNamed /= prior.length;
    var min = data.counting.min_evidence_articles;
    var delta = s.share[week] - baseShare;
    var thin = s.n_named[week] < min || baseNamed < min;
    // The pooled share (all pairs together) has to move the same way; otherwise the direction is not clear.
    var unclear = false;
    if (s.pooled_share && s.pooled_share[week] !== null) {
      var basePooled = 0;
      prior.forEach(function (w) { basePooled += s.pooled_share[w] || 0; });
      var dp = s.pooled_share[week] - basePooled / prior.length;
      unclear = (delta > 0) !== (dp > 0) || (delta < 0) !== (dp < 0);
    }
    return { now: s.share[week], was: baseShare, delta: delta, n: s.n_named[week], baseN: baseNamed, thin: thin, unclear: unclear,
             low: thin || unclear };
  }

  // ----- colour --------------------------------------------------------------------------------------------------
  function parseColor(str) {
    str = (str || "").trim();
    var m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(str);
    if (m) {
      var h = m[1].length === 3 ? m[1].replace(/(.)/g, "$1$1") : m[1];
      return [parseInt(h.substr(0, 2), 16), parseInt(h.substr(2, 2), 16), parseInt(h.substr(4, 2), 16)];
    }
    m = /rgba?\(([^)]+)\)/.exec(str);
    if (m) { var p = m[1].split(/[ ,\/]+/).map(parseFloat); return [p[0], p[1], p[2]]; }
    return [128, 128, 128];
  }
  function token(name) { return parseColor(getComputedStyle(document.documentElement).getPropertyValue(name)); }
  function luminance(c) {
    var l = c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
  }
  function contrast(a, b) {
    var la = luminance(a), lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }
  function mixColor(a, b, t) { return a.map(function (v, i) { return Math.round(v + (b[i] - v) * t); }); }
  function css(c) { return "rgb(" + c.join(",") + ")"; }
  var palette = null;
  function readPalette() {
    palette = { up: token("--map-up"), down: token("--map-down"), neutral: token("--map-neutral") };
  }
  // Fill and ink for a change in percentage points. Between lightness 0.18 and 0.21 neither ink reaches 4.5:1, so the
  // intensity is nudged out of that band (a shift of a few per cent of the scale) instead of accepting weak contrast.
  function tilePaint(delta) {
    var end = delta >= 0 ? palette.up : palette.down;
    var t0 = Math.min(1, Math.sqrt(Math.abs(delta) / FULL_SCALE_PP));
    for (var k = 0; k <= 40; k++) {
      var order = k === 0 ? [0] : [k, -k];
      for (var i = 0; i < order.length; i++) {
        var t = Math.max(0, Math.min(1, t0 + order[i] * 0.01));
        var fillc = mixColor(palette.neutral, end, t);
        var ink = contrast(INK_DARK, fillc) >= contrast(INK_LIGHT, fillc) ? INK_DARK : INK_LIGHT;
        if (contrast(ink, fillc) >= 4.5) return { bg: css(fillc), fg: css(ink) };
      }
    }
    return { bg: css(palette.neutral), fg: css(INK_DARK) };
  }

  // ----- build once ----------------------------------------------------------------------------------------------
  function buildTiles() {
    var map = els.map;
    data.tiles.forEach(function (t) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "tile";
      b.style.left = (t.col * 57 / 798 * 100) + "%";
      b.style.top = (t.row * 57 / 399 * 100) + "%";
      // The drawn text is for the eyes (aria-hidden); the accessible name is the full sentence, so there is no
      // aria-label that could disagree with the visible label (WCAG 2.5.3).
      b.innerHTML = '<span class="tile-name" aria-hidden="true"></span><span class="tile-code" aria-hidden="true" dir="ltr"></span><span class="tile-val" aria-hidden="true"></span><span class="visually-hidden tile-sr"></span>';
      b.querySelector(".tile-name").textContent = shortName(t);
      b.querySelector(".tile-code").textContent = t.code;
      b.addEventListener("click", function () { state.selected = t.code; render(); });
      map.appendChild(b);
      tileEls[t.code] = b;
    });
  }

  // A long name ("Palästinenser", "Deutschland") would otherwise run past the edge of its tile: shrink just that name
  // until it fits, never below 6.5px (the tile code is shown instead below 620px, so the names are secondary).
  function fitNames() {
    data.tiles.forEach(function (t) {
      var tile = tileEls[t.code], name = tile.querySelector(".tile-name");
      name.style.fontSize = "";
      if (!name.getClientRects().length) return;
      var range = document.createRange(); range.selectNodeContents(name);
      var room = tile.clientWidth - 6, need = range.getBoundingClientRect().width;
      if (need > room) name.style.fontSize = Math.max(6.5, parseFloat(getComputedStyle(name).fontSize) * room / need) + "px";
    });
  }

  // ----- render --------------------------------------------------------------------------------------------------
  function breaksFor(key) {
    return data.scope_breaks.filter(function (b) { return key === "all" || b.axis === "analysis_scope"; });
  }
  function crossedBreaks(week, base) {
    var prior = baselineWeeks(week, base);
    if (!prior.length) return [];
    var lo = prior[0];
    return breaksFor(state.series).filter(function (b) { return b.week !== null && b.week >= lo && b.week <= week && b.date > data.weeks[0].start; });
  }

  function renderControls() {
    var steps = stepWeeks(state.base);
    var range = els.range;
    range.min = steps[0]; range.max = steps[steps.length - 1];
    state.week = Math.max(steps[0], Math.min(steps[steps.length - 1], state.week));
    range.value = state.week;
    var w = data.weeks[state.week];
    var label = fill(LABELS.week_label, { n: state.week + 1, total: nWeeks(), from: fmtDate(w.start), to: fmtDate(w.end) });
    els.weekLabel.textContent = label;
    range.setAttribute("aria-valuetext", label);
    [1, 4].forEach(function (b) {
      var btn = els["base" + b];
      btn.setAttribute("aria-pressed", String(state.base === b));
      btn.querySelector(".opt-steps").textContent = "(" + fill(LABELS.steps, { n: stepWeeks(b).length }) + ")";
    });
    ["core", "all"].forEach(function (k) { els["series_" + k].setAttribute("aria-pressed", String(state.series === k)); });

    var notes = [];
    if (w.partial) notes.push(fill(LABELS.note_partial, { days: w.days }));
    if (w.has_backlog) notes.push(LABELS.note_backlog);
    crossedBreaks(state.week, state.base).forEach(function (b) { notes.push(fill(LABELS.note_break, { label: b["label_" + LANG] })); });
    els.notes.innerHTML = "";
    notes.forEach(function (n) { var p = document.createElement("span"); p.textContent = n; els.notes.appendChild(p); });
    els.notes.hidden = !notes.length;

    var s = series();
    var reporting = s.papers_reporting.filter(function (n) { return n > 0; });
    if (state.series === "all") {
      els.seriesNote.hidden = true;
      els.warning.hidden = false;
      els.warning.textContent = fill(LABELS.series_all_warning, { from: reporting[0], to: reporting[reporting.length - 1] });
    } else {
      els.warning.hidden = true;
      els.seriesNote.hidden = false;
      els.seriesNote.textContent = LABELS.series_core_note;
    }
    els.calloutWeeks.textContent = fill(LABELS.callout_weeks, { weeks: nWeeks() - firstWeek() });
  }

  function renderTiles() {
    var rows = [];
    data.tiles.forEach(function (t) {
      var el = tileEls[t.code];
      var f = figures(t.code, state.week, state.base);
      var name = countryName(t);
      el.classList.remove("is-low");
      el.style.backgroundImage = ""; el.style.backgroundColor = ""; el.style.color = "";
      var val = el.querySelector(".tile-val");
      if (!f) {
        el.classList.add("is-low");
        val.textContent = "";
        el.querySelector(".tile-sr").textContent = fill(LABELS.tile_aria_none, { country: name });
      } else if (f.low) {
        el.classList.add("is-low");
        val.textContent = "";
        el.querySelector(".tile-sr").textContent = fill(f.thin ? LABELS.tile_aria_low : LABELS.tile_aria_unclear, { country: name });
      } else {
        var paint = tilePaint(f.delta);
        el.style.backgroundColor = paint.bg; el.style.color = paint.fg;
        val.textContent = signed(f.delta);
        el.querySelector(".tile-sr").textContent = fill(LABELS.tile_aria, { country: name, delta: signed(f.delta) });
      }
      el.setAttribute("aria-pressed", String(state.selected === t.code));
      rows.push({ tile: t, f: f });
    });
    return rows;
  }

  function fillList(listEl, emptyEl, items, cls, emptyText) {
    listEl.innerHTML = "";
    items.forEach(function (r) {
      var li = document.createElement("li");
      var btn = document.createElement("button"); btn.type = "button"; btn.className = "rank-btn";
      btn.setAttribute("data-code", r.tile.code);
      btn.setAttribute("aria-pressed", String(state.selected === r.tile.code));
      btn.addEventListener("click", function () { choose(r.tile.code, listEl.id); });
      var n = document.createElement("span"); n.textContent = countryName(r.tile);
      var range = document.createElement("span"); range.className = "rank-range";
      range.appendChild(bdiEl(num1(r.f.was) + "%")); range.appendChild(document.createTextNode(" → ")); range.appendChild(bdiEl(num1(r.f.now) + "%"));
      var d = document.createElement("span"); d.className = "rank-delta " + cls; d.appendChild(bdiEl(signed(r.f.delta)));
      btn.appendChild(n); btn.appendChild(range); btn.appendChild(d);
      li.appendChild(btn);
      listEl.appendChild(li);
    });
    emptyEl.textContent = emptyText;
    emptyEl.hidden = items.length > 0;
  }

  function renderSide(rows) {
    var valid = rows.filter(function (r) { return r.f && !r.f.low; }).sort(function (a, b) { return b.f.delta - a.f.delta; });
    var rising = valid.filter(function (r) { return r.f.delta > 0; }).slice(0, 4);
    var fading = valid.filter(function (r) { return r.f.delta < 0; }).slice(-4).reverse();
    fillList(els.risingList, els.risingEmpty, rising, "rising-delta", LABELS.none_rising);
    fillList(els.fadingList, els.fadingEmpty, fading, "fading-delta", LABELS.none_fading);

    var sel = state.selected && data.tiles.filter(function (t) { return t.code === state.selected; })[0];
    if (!sel) { els.selName.textContent = ""; els.selText.textContent = LABELS.selected_hint; return; }
    els.selName.textContent = countryName(sel);
    var f = figures(sel.code, state.week, state.base);
    if (!f) { els.selText.textContent = LABELS.no_baseline; return; }
    var min = data.counting.min_evidence_articles;
    if (f.thin || f.unclear) {
      els.selText.textContent = fill(f.thin ? LABELS.selected_low : LABELS.selected_unclear, { min: min }) + " " +
        (f.thin ? fill(state.base === 1 ? LABELS.selected_n_both_1 : LABELS.selected_n_both, { n: f.n, base_n: Math.round(f.baseN) }) : fill(LABELS.selected_n, { n: f.n }));
      return;
    }
    setRich(els.selText, LABELS.selected_text, {
      was: num1(f.was), now: num1(f.now), delta: signed(f.delta), n: f.n,
      base: LABELS["base_text_" + state.base]
    }, ["was", "now", "delta"]);
  }

  function renderTable(rows) {
    var body = els.tableBody;
    body.innerHTML = "";
    rows.slice().sort(function (a, b) {
      var av = a.f && !a.f.low ? a.f.delta : -Infinity, bv = b.f && !b.f.low ? b.f.delta : -Infinity;
      return bv - av || (a.tile.code < b.tile.code ? -1 : 1);
    }).forEach(function (r) {
      var tr = document.createElement("tr");
      function cell(text, num) { var td = document.createElement("td"); if (num) td.className = "num"; if (num) td.appendChild(bdiEl(text)); else td.textContent = text; tr.appendChild(td); }
      var nameTd = document.createElement("td");
      var nameBtn = document.createElement("button"); nameBtn.type = "button"; nameBtn.className = "table-btn";
      nameBtn.setAttribute("data-code", r.tile.code);
      nameBtn.setAttribute("aria-pressed", String(state.selected === r.tile.code));
      nameBtn.textContent = countryName(r.tile);
      nameBtn.addEventListener("click", function () { choose(r.tile.code, "m-tableBody", true); });
      nameTd.appendChild(nameBtn); tr.appendChild(nameTd);
      if (state.selected === r.tile.code) tr.setAttribute("aria-current", "true");
      if (!r.f) { cell("—", true); cell("—", true); cell("—", true); cell("—", true); }
      else if (r.f.low) { cell(num1(r.f.now) + "%", true); cell(num1(r.f.was) + "%", true); cell("— (" + (r.f.thin ? LABELS.low_mark : LABELS.unclear_mark) + ")", true); cell(String(r.f.n), true); }
      else { cell(num1(r.f.now) + "%", true); cell(num1(r.f.was) + "%", true); cell(signed(r.f.delta), true); cell(String(r.f.n), true); }
      body.appendChild(tr);
    });
  }

  // One way to pick a country from a list or the table: select it, keep the keyboard where it was, and (from the
  // table, which sits below the detail card) bring the card into view.
  function choose(code, fromId, scroll) {
    state.selected = code;
    state.refocus = { id: fromId, code: code };
    render();
    if (scroll) {
      var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      els.selCard.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    }
  }

  function render() {
    renderControls();
    var rows = renderTiles();
    renderSide(rows);
    renderTable(rows);
    if (state.refocus) {
      var host = $(state.refocus.id);
      var again = host && host.querySelector('[data-code="' + state.refocus.code + '"]');
      if (again) again.focus({ preventScroll: true });
      state.refocus = null;
    }
  }

  // ----- player and options ---------------------------------------------------------------------------------------
  function setPlaying(on) {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    els.play.setAttribute("aria-pressed", String(on));
    els.play.setAttribute("aria-label", on ? LABELS.pause : LABELS.play);
    if (on) {
      state.timer = setInterval(function () {
        var steps = stepWeeks(state.base);
        var i = steps.indexOf(state.week);
        state.week = steps[(i + 1) % steps.length];
        render();
      }, 1000);
    }
  }

  function bind() {
    els.play.addEventListener("click", function () { setPlaying(els.play.getAttribute("aria-pressed") !== "true"); });
    els.range.addEventListener("input", function () { setPlaying(false); state.week = parseInt(els.range.value, 10); render(); });
    [1, 4].forEach(function (b) {
      els["base" + b].addEventListener("click", function () { state.base = b; render(); });
    });
    ["core", "all"].forEach(function (k) {
      els["series_" + k].addEventListener("click", function () { state.series = k; state.week = defaultWeek(); render(); });
    });
    new MutationObserver(function () { readPalette(); render(); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    if (window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () { readPalette(); render(); };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
    }
  }

  function init(payload) {
    data = payload;
    ["map", "range", "play", "notes", "warning", "seriesNote", "weekLabel", "calloutWeeks", "risingList", "risingEmpty",
     "fadingList", "fadingEmpty", "selCard", "selName", "selText", "tableBody", "base1", "base4", "series_core", "series_all"].forEach(function (k) {
      els[k] = $("m-" + k);
    });
    readPalette();
    buildTiles();
    bind();
    state.week = defaultWeek();
    // start on the tile that moved most in the latest week, so the side card is never empty
    var best = null;
    data.tiles.forEach(function (t) {
      var f = figures(t.code, state.week, state.base);
      if (f && !f.low && (best === null || Math.abs(f.delta) > best.d)) best = { code: t.code, d: Math.abs(f.delta) };
    });
    state.selected = best ? best.code : null;
    $("map-loading").hidden = true;
    $("map-app").hidden = false;
    render();
    fitNames();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitNames);
    if (window.ResizeObserver) new ResizeObserver(fitNames).observe(els.map);
  }

  fetch(DATA_URL).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(init).catch(function () {
    $("map-loading").hidden = true;
    var e = $("map-error"); e.textContent = LABELS.load_error; e.hidden = false;
  });
})();
"""


def _outline_path() -> str:
    return OUTLINE_PATH.read_text(encoding="utf-8").strip()


def build_trends_map_html(lang: str, page_name: str = "trendsmap.html", reports_href: str | None = None) -> str:
    """docs/{lang}/{page_name} - destination page, no root copy (same convention as trendschart.html/topic.html).
    `reports_href`, when given, adds a link to the biweekly reports index (the page that used to be the trends hub)."""
    L = LABELS[lang]
    dir_attr = "rtl" if lang == "he" else "ltr"
    scale = "3,5" if lang == "de" else "3.5"  # legend end values, with the page language decimal mark

    css = (
        _CSS.replace("__FONT__", font_face_css(f"../assets/fonts/{FONT_FILENAME}"))
        .replace("__TOKENS__", theme_tokens_css())
        .replace("__FAMILY__", FONT_FAMILY)
        .replace("__NAV__", nav_chrome_css("72rem"))
        .replace("__CHROME__", shared_chrome_css())
        .replace("__DIR__", dir_attr)
    )
    js = (
        _JS.replace("__LABELS__", json.dumps(L, ensure_ascii=False))
        .replace("__LANG__", lang)
        .replace("__DATA_URL__", "../assets/data/trends_map.json")
    )
    reports_link = (f'\n      <p class="reports-link"><a href="{esc(reports_href)}">{esc(L["reports_link"])}</a></p>' if reports_href else "")
    nav = build_nav_html("trends.html", {o: f"../{o}/{page_name}" for o in other_langs(lang)}, lang)
    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
{head_meta_html(L['page_title'], "../")}
<style>
{css}
</style>
</head>
<body>
{nav}
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">{esc(L['eyebrow'])}</p>
      <div class="heading-row">
        <h1 class="report-title">{esc(L['heading'])}</h1>
        <span class="beta-badge">{esc(L['beta_badge'])}</span>
      </div>
      <p class="explainer">{esc(L['explainer'])}</p>{reports_link}
      <div class="beta-callout" role="note">
        <p class="beta-callout-title">{esc(L['callout_title'])}</p>
        <ul class="beta-callout-list">
          <li id="m-calloutWeeks"></li>
          <li>{esc(L['callout_lower_bound'])}</li>
          <li>{esc(L['callout_share'])}</li>
          <li>{esc(L['callout_caution'])}</li>
          <li>{esc(L['callout_scope'])}</li>
          <li>{esc(L['callout_backlog'])}</li>
        </ul>
      </div>
    </div>
  </header>
  <main class="map-body">
    <p id="map-loading">{esc(L['loading'])}</p>
    <p id="map-error" role="alert" hidden></p>
    <div id="map-app" hidden>
      <div class="controls">
        <div class="player">
          <button type="button" class="play-btn" id="m-play" aria-pressed="false" aria-label="{esc(L['play'])}">
            <svg class="icon-play" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2 L14 8 L4 14 Z"/></svg>
            <svg class="icon-pause" viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="2" width="3.5" height="12"/><rect x="9.5" y="2" width="3.5" height="12"/></svg>
          </button>
          <input type="range" id="m-range" step="1" aria-label="{esc(L['week_slider'])}">
          <output class="week-label" id="m-weekLabel" aria-live="polite"></output>
        </div>
        <div class="opt-group" role="group" aria-labelledby="m-base-label">
          <span class="opt-label" id="m-base-label">{esc(L['base_label'])}</span>
          <button type="button" class="opt-btn" id="m-base1" aria-pressed="true">{esc(L['base_1'])}<span class="opt-steps"></span></button>
          <button type="button" class="opt-btn" id="m-base4" aria-pressed="false">{esc(L['base_4'])}<span class="opt-steps"></span></button>
        </div>
        <div class="opt-group" role="group" aria-labelledby="m-series-label">
          <span class="opt-label" id="m-series-label">{esc(L['series_label'])}</span>
          <button type="button" class="opt-btn" id="m-series_core" aria-pressed="true">{esc(L['series_core'])}</button>
          <button type="button" class="opt-btn" id="m-series_all" aria-pressed="false">{esc(L['series_all'])}</button>
        </div>
      </div>
      <p class="notes" id="m-notes" hidden></p>
      <p class="banner" id="m-warning" role="note" hidden></p>
      <p class="series-note" id="m-seriesNote"></p>
      <div class="map-layout">
        <div>
          <div class="map" id="m-map" role="group" aria-label="{esc(L['map_label'])}">
            <svg class="map-outline" viewBox="0 0 798 399" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path d="{_outline_path()}"/></svg>
          </div>
          <div class="legend">
            <div class="legend-scale"><span>{esc(L['legend_change'])}</span><span class="legend-bar"><span class="legend-num">&minus;{scale}</span><span class="legend-ramp"></span><span class="legend-num">+{scale}</span></span></div>
            <div class="legend-low"><span class="legend-swatch-low"></span><span>{esc(L['legend_low'])}</span></div>
          </div>
        </div>
        <aside class="side">
          <div class="card">
            <h2 class="rising">{esc(L['rising'])}</h2>
            <ul class="rank-list" id="m-risingList"></ul>
            <p class="rank-empty" id="m-risingEmpty" hidden></p>
            <h2 class="fading">{esc(L['fading'])}</h2>
            <ul class="rank-list" id="m-fadingList"></ul>
            <p class="rank-empty" id="m-fadingEmpty" hidden></p>
          </div>
          <div class="card" id="m-selCard" aria-live="polite">
            <p class="sel-name" id="m-selName"></p>
            <p class="sel-text" id="m-selText"></p>
          </div>
        </aside>
      </div>
      <details class="table-view">
        <summary>{esc(L['table_summary'])}</summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th>{esc(L['col_country'])}</th><th class="num">{esc(L['col_now'])}</th><th class="num">{esc(L['col_base'])}</th><th class="num">{esc(L['col_delta'])}</th><th class="num">{esc(L['col_n'])}</th></tr></thead>
            <tbody id="m-tableBody"></tbody>
          </table>
        </div>
      </details>
    </div>
  </main>
{build_footer_html(lang, *footer_hrefs_for(lang))}
  <script>{js}</script>
</body>
</html>
"""
