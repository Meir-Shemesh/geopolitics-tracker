"""One-off script: render the geopolitics-tracker background/brand document to PDF+HTML.

Not part of the Ingestion->Extraction->Analysis->Reporting->Publishing pipeline -
this produces a single standalone bilingual-brand document (Hebrew, RTL), reusing
the same rendering approach as src/reporting/render.py (WeasyPrint, locally embedded
Heebo variable font, the site's base light-theme color tokens) so the document reads
as part of the same brand family as the live reports/site. Source content is the
approved text from geopolitics-tracker-v3.pdf, reproduced verbatim; a handful of
embedded Latin/mixed-script phrases (the product name, "Claude API", "PDF + HTML",
the domain) are written in their correct logical reading order rather than copied
from that PDF's own text layer, which is known in this project to scramble embedded
LTR runs inside RTL paragraphs when naively text-extracted (see HANDOFF.md known
issues) - the visual meaning is unchanged, only the extraction artifact is corrected.
"""

import base64
from pathlib import Path

from weasyprint import HTML as WeasyHTML

REPO_ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = REPO_ROOT / "src" / "reporting" / "assets" / "fonts" / "Heebo-Variable.ttf"
LOGO_PATH = REPO_ROOT / "scripts" / "assets" / "MS_Logo.png"
OUTPUT_DIR = REPO_ROOT / "scripts" / "output"

# Same base light-theme tokens as src/reporting/render.py's :root block.
COLORS = {
    "bg": "#f3efe8",
    "bg-elevated": "#fffdfa",
    "text": "#221f1b",
    "text-muted": "#6d675e",
    "border": "#e4ddd0",
    "masthead-accent": "#7a2e2a",
}

BULLETS_1 = [
    (
        "כלי שיחה ותכנון",
        "עוזר לחשוב על הבעיה לפני שנכתבת שורת קוד אחת: בוחן חלופות ארכיטקטוניות, "
        "מזהה סיכונים מראש, ומתרגם החלטות מעורפלות למשימות קונקרטיות. תפקידו קרוב "
        "יותר ליועץ תכנון מאשר לכותב קוד.",
    ),
    (
        "סוכן כתיבת קוד",
        "פועל בפועל בתוך סביבת הפיתוח: כותב קוד, מריץ אותו, בודק תוצאות ומדווח "
        "בחזרה. עוצר ומבקש אישור לפני שינויים משמעותיים, ומדווח על ממצאים "
        "לא-צפויים במקום להסתיר אותם בשקט.",
    ),
    (
        "המפעיל האנושי",
        "לא צד פסיבי שרק מאשר, אלא הגורם היחיד שרואה את שני הכלים בו-זמנית ומעביר "
        "החלטות ביניהם. זו הנקודה שבה נתפסות שוב ושוב תוצאות “כמעט טובות” "
        "שלא באמת נבדקו, הנחות שגויות, או פתרון-יתר לבעיה שלא הייתה קיימת בפועל.",
    ),
]

BULLETS_2 = [
    "7 ימי כיסוי מלאים בארכיון, 4 עיתונים, מעל 300 מאמרי פרשנות שנותחו לעומק.",
    "ארכיטקטורה דו-שלבית לניתוח: סינון רחב וזול, ואחריו ניתוח מעמיק - רק על מה שסונן פנימה.",
    "עלות מצטברת צנועה ביחס להיקף העיבוד - סביב עשרה דולרים בחודש בתקופת הפיתוח האינטנסיבית.",
]


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_html() -> str:
    font_b64 = _b64(FONT_PATH)
    logo_b64 = _b64(LOGO_PATH)

    bullets_1_html = "\n".join(
        f'<li><b>{label}</b> - {text}</li>' for label, text in BULLETS_1
    )
    bullets_2_html = "\n".join(f"<li>{text}</li>" for text in BULLETS_2)

    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<title>geopolitics-tracker - מסמך רקע</title>
<style>
  @font-face {{
    font-family: "Heebo";
    src: url("data:font/ttf;base64,{font_b64}") format("truetype-variations");
    font-weight: 100 900;
  }}

  :root {{
    --bg: {COLORS['bg']};
    --bg-elevated: {COLORS['bg-elevated']};
    --text: {COLORS['text']};
    --text-muted: {COLORS['text-muted']};
    --border: {COLORS['border']};
    --masthead-accent: {COLORS['masthead-accent']};
  }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "Heebo", system-ui, sans-serif;
    line-height: 1.7;
  }}

  .page {{ max-width: 44rem; margin: 0 auto; padding: 2.5rem 1.8rem 3rem; }}

  .header {{ direction: ltr; text-align: left; margin-bottom: 2rem; }}

  .letterhead {{ display: flex; align-items: center; margin-bottom: 1.5rem; }}
  .identity {{ flex: 1; }}
  .identity-name {{ font-size: 1.3rem; font-weight: 800; margin: 0; }}
  .identity-tagline {{ font-size: 0.85rem; color: var(--text-muted); margin: .15rem 0 0; }}
  .logo {{ flex: 0 0 auto; height: 56px; width: auto; margin: 0 1.5rem; }}
  .letterhead-spacer {{ flex: 1; }}

  .header-bottom-rule {{ border-bottom: 3px solid var(--masthead-accent); padding-bottom: 1.6rem; }}

  .doc-meta {{
    margin: 0 0 .6rem;
    font-size: .85rem;
    font-weight: 700;
    color: var(--masthead-accent);
  }}
  .doc-title {{
    margin: 0 0 1rem;
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -0.01em;
  }}
  .doc-subtitle {{
    margin: 0;
    font-size: 1rem;
    font-style: italic;
    color: var(--text-muted);
  }}

  .body {{ direction: rtl; text-align: right; }}

  .body p {{ margin: 0 0 1.1rem; font-size: 1rem; }}

  .body h2 {{
    display: flex;
    align-items: center;
    gap: .9rem;
    margin: 1.9rem 0 1.1rem;
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--masthead-accent);
    white-space: nowrap;
  }}
  .body h2::after {{
    content: "";
    flex: 1;
    height: 1px;
    background: var(--border);
  }}

  .body ul {{ margin: 0 0 1.1rem; padding-inline-start: 1.4rem; }}
  .body ul li {{ margin-bottom: .6rem; font-size: 1rem; }}

  @page {{
    size: A4;
    margin: 2cm 1.8cm;
    @bottom-center {{ content: counter(page); font-size: 9px; color: #888; }}
  }}
</style>
</head>
<body>
  <div class="page">
    <div class="header">
      <div class="header-bottom-rule">
        <div class="letterhead">
          <div class="identity">
            <p class="identity-name">מאיר שמש</p>
            <p class="identity-tagline">ייעוץ וניהול טכנולוגיות</p>
          </div>
          <img class="logo" src="data:image/png;base64,{logo_b64}" alt="">
          <div class="letterhead-spacer"></div>
        </div>
        <p class="doc-meta">מסמך רקע &middot; אוגוסט 2026</p>
        <h1 class="doc-title">GEOPOLITICS-TRACKER</h1>
        <p class="doc-subtitle">
          כיצד עיתונות עולמית רואה אירוע אחד בעיניים שונות - ומה תהליך הבנייה עצמו
          מלמד על עבודה משותפת בין אדם לבינה מלאכותית
        </p>
      </div>
    </div>

    <div class="body">
      <p>
        בכל יום, עשרות עיתונים מובילים מפרסמים מאות מאמרי פרשנות על אותם אירועים
        גאופוליטיים בדיוק. אף אדם אינו יכול לקרוא את כולם - וכל אחד מאיתנו קורא
        זווית אחת או שתיים, לרוב אלה שהוא כבר מכיר, ומחמיץ את השיחה המלאה שמתקיימת
        בין מקורות שונים. geopolitics-tracker הוא ניסיון לתת לקריאה הזו כלי: מערכת
        שעוקבת אחרי עיתונים מובילים באנגלית ובגרמנית - נבחרו במכוון על פני טווח
        פוליטי רחב - ובונה מהם תמונה יומית של מה שתפס את תשומת הלב, ואיך כל מקור
        בחר למסגר אותו.
      </p>

      <h2>שיטת העבודה: שיתוף פעולה בין אדם למכונה</h2>
      <p>
        מעבר למטרה התוכנית, לפרויקט תפקיד נוסף: מקום ללמוד בפועל איך בונים מערכת
        מורכבת עם כלי בינה מלאכותית מתקדמים, מבלי להזמין תוכנית מוכנה כקופסה
        שחורה. זו בחירה מכוונת, לא צורך טכני - להבין כל שלב, כל החלטה, ואיך מזהים
        ומתקנים כשמשהו משתבש.
      </p>
      <p>
        לאורך הדרך התבררה תובנה מרכזית: המודל “אדם מבקש, מכונה מבצעת”
        אינו מדויק. בפועל פועלים שלושה גורמים נפרדים, כל אחד עם תפקיד שונה:
      </p>
      <ul>
        {bullets_1_html}
      </ul>
      <p>
        המתודולוגיה בפועל: בנייה מודול-מודול, לא הכל בבת אחת, עם נקודת עצירה
        לאחר כל שלב עובד. סוכן כתיבת הקוד מציג תוכנית לפני מימוש וממתין לאישור -
        לא פועל על סמך שיקול דעת עצמאי מוחלט. כשמשהו “כמעט עבד” אך
        התברר כלא-מספיק, ההעדפה העקבית הייתה לבנות רשת-ביטחון גנרית ברמת הקוד
        שתופסת כל מקרה חריג מראש, ולא לרדוף אחרי כל מקרה בודד בנפרד.
      </p>

      <h2>מה קיים היום: מהאנליזה לאתר חי</h2>
      <p>
        המערכת בנויה כצינור של חמישה שלבים עוקבים - איסוף מהעיתונים, חילוץ טקסט,
        ניתוח וסיווג באמצעות Claude API, הפקת דוחות, ופרסום - וכולם פעילים על
        נתונים אמיתיים. כל דוח יומי מופק בשתי שפות מלאות (עברית ואנגלית) ובשני
        פורמטים (PDF + HTML אינטראקטיבי), עם השוואה בין-מקורית שמקבצת מאמרים לפי
        נושא אמיתי, לא תיוג מכני. האתר עצמו חי ונגיש: geopolitics.meirshemesh.com.
      </p>
      <ul>
        {bullets_2_html}
      </ul>

      <h2>המסגרת החדשה: שלושה צירי תפיסה</h2>
      <p>
        גאופוליטיקה היא שילוב של כמה תפיסות חושיות שונות בתכלית: מרחבית, זמנית,
        וטקסטואלית. לכן דף הבית הבא נבנה סביב שלוש “עדשות” שוות-מעמד על
        אותם נתונים - ציר גיאוגרפי (איפה), ציר זמן (מתי, ולאן זה נוטה), וציר
        טקסטואלי (מה נכתב, ואיך כל מקור מיסגר אותו) - שלושתן קוראות ממקור אמת
        אחד ומתעדכנות יחד.
      </p>
      <p>
        כדי שהציר הגיאוגרפי יהיה אפשרי בכלל, נבנתה טקסונומיה סגורה של 94 מדינות
        ב-8 אזורים גאופוליטיים, ושלושה אזורי קונפליקט פעילים המסוקרים בעקביות:
        הסכסוך הישראלי-פלסטיני, העימות איראן-מערב, ומלחמת רוסיה-אוקראינה. התיוג
        נכנס לאותה קריאת מודל שכבר מפיקה את שאר פרטי המאמר, ללא עלות נוספת - וכל
        437 המאמרים הקיימים תויגו למפרע.
      </p>

      <h2>מבט קדימה</h2>
      <p>
        התשתית הרחבה כבר יציבה; מה שנותר הוא ליטוש - דיוק בקיבוץ נושאים, חידוד
        הפניות למקורות, ומשוב אנושי על התוכן וההצגה. ככל שיצטברו ימי כיסוי
        נוספים, יתאפשר גם מה שהפרויקט שואף אליו מלכתחילה: לא רק “מה קרה
        היום”, אלא “לאן זה נוטה” - זיהוי מגמות אמיתיות, ודוחות
        בחתכים נוספים, אזוריים ומדינתיים, לא רק יומיים.
      </p>
    </div>
  </div>
</body>
</html>
"""


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_str = build_html()

    html_path = OUTPUT_DIR / "geopolitics-tracker-background-doc.html"
    html_path.write_text(html_str, encoding="utf-8")
    print(f"wrote {html_path}")

    pdf_path = OUTPUT_DIR / "geopolitics-tracker-background-doc.pdf"
    WeasyHTML(string=html_str, base_url=str(html_path)).write_pdf(str(pdf_path))
    print(f"wrote {pdf_path}")


if __name__ == "__main__":
    run()
