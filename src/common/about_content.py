"""Shared background/about content for the project, in Hebrew, English and German.

Single source of truth for text used by two independent renderers:
scripts/build_background_doc.py (standalone branded PDF+HTML, Assistant font)
and src/publishing/publish.py's build_about_html() (a regular site page, also
Assistant font as of the site-wide font unification - part of
docs/{he,en,de}/about.html). Keeping the text here means a wording fix only
has to happen in one place, not two or three.

Each language entry has doc_meta/identity_name/identity_role/title/subtitle,
plus `sections`: an ordered list of {"heading": str | None, "blocks": [...]}
where each block is ("p", text), ("ul_labeled", [(label, text), ...]) for a
bold-lead-in bullet list, or ("ul_plain", [text, ...]) for a plain one.

render_sections_html() turns `sections` into the shared <h2>/<p>/<ul> HTML
shape both renderers use - only the surrounding CSS/fonts differ per caller.

Rewritten 2026-10-08 (full copy pass, see PROJECT_LOG) - covers the biweekly
"Trends" feature that shipped that week. The American-sources sentence was
corrected during this pass: an earlier draft of the new copy listed "The New
York Times International" as the fourth US source, which is wrong - NYT is
permanently suspended from ingestion (structural PDF corruption, confirmed
across multiple editions, see CLAUDE.md/PROJECT_LOG 4.34) and The Washington
Post replaced it as the fourth MVP US source. The text below reflects the
actual current source list, verified directly against NEWSPAPER_DISPLAY_NAMES
and the live DB rather than assumed.
"""


def _render_blocks(blocks) -> str:
    parts = []
    for kind, payload in blocks:
        if kind == "p":
            parts.append(f"      <p>{payload}</p>")
        elif kind == "ul_labeled":
            items = "\n".join(f"        <li><b>{label}</b> - {text}</li>" for label, text in payload)
            parts.append(f"      <ul>\n{items}\n      </ul>")
        elif kind == "ul_plain":
            items = "\n".join(f"        <li>{text}</li>" for text in payload)
            parts.append(f"      <ul>\n{items}\n      </ul>")
    return "\n".join(parts)


def render_sections_html(sections) -> str:
    parts = []
    for section in sections:
        if section["heading"]:
            parts.append(f"      <h2>{section['heading']}</h2>")
        parts.append(_render_blocks(section["blocks"]))
    return "\n".join(parts)


CONTENT = {
    "he": {
        "doc_meta": "מסמך רקע · אוקטובר 2026",
        "identity_name": "מאיר שמש",
        "identity_role": "ייעוץ וניהול טכנולוגיות",
        # Brand title/subtitle - shared by the homepage's own <h1> and the standalone
        # background-doc PDF, NOT about-page-specific (see about_title/about_subtitle
        # below for that). Keep these as the project's brand name/tagline - do not
        # repurpose them for about.html content again (caught and fixed 2026-10-08,
        # see PROJECT_LOG: doing so silently broke the homepage's <h1>).
        "title": "GEOPOLITICS-TRACKER",
        "subtitle": (
            "כיצד עיתונות עולמית רואה אירוע אחד בעיניים שונות - ומה תהליך הבנייה עצמו "
            "מלמד על עבודה משותפת בין אדם לבינה מלאכותית"
        ),
        "about_title": "אודות הפרויקט",
        "about_subtitle": (
            "איך אותו אירוע נראה אחרת מעיתון לעיתון, ומה תהליך הבנייה עצמו מלמד על "
            "עבודה משותפת בין אדם לבינה מלאכותית"
        ),
        "sections": [
            {
                "heading": None,
                "blocks": [
                    (
                        "p",
                        "בכל יום, עשרות עיתונים מובילים בעולם מפרסמים מאות מאמרי דעה "
                        "ופרשנות על אותם אירועים גאופוליטיים בדיוק. אף אדם אינו יכול לקרוא "
                        "את כולם. כל אחד מאיתנו קורא זווית אחת או שתיים, לרוב אלה שהוא כבר "
                        "מכיר, ומחמיץ את השיחה המלאה שמתקיימת בין מקורות שרואים את אותו "
                        "אירוע דרך עדשות שונות.",
                    ),
                    (
                        "p",
                        "geopolitics-tracker מנסה לפתור בעיה ממוקדת: לא להחליף את הקריאה "
                        "האנושית, אלא לתת לה כלי. מערכת שעוקבת אחרי עיתונים מובילים באנגלית "
                        "ובגרמנית, במגוון פוליטי רחב משמאל לימין, מזהה בתוכם מאמרי פרשנות "
                        "גאופוליטית ובונה מהם תמונה יומית: אילו נושאים תפסו את תשומת הלב, "
                        "ואיך כל מקור בחר למסגר אותם. המטרה אינה לקבוע “מי צודק” אלא להנגיש "
                        "את מלוא מרחב הדעות, לא רק את הפינה שהקורא כבר מכיר.",
                    ),
                ],
            },
            {
                "heading": "מתמונת יום למגמה",
                "blocks": [
                    (
                        "p",
                        "התוצר המיידי הוא דוח יומי: מסמך שמקבץ את מאמרי הפרשנות של אותו יום "
                        "לפי נושא ממשי, לא לפי תיוג מכני, ומציג לצד כל נושא השוואה תמציתית "
                        "בין המקורות. אבל דוח יומי בודד, ככל שיהיה מדויק, הוא רק תמונת רגע. "
                        "הערך האמיתי נחשף רק עם הזמן: כשמצטברים שבועות וחודשים של דוחות, "
                        "אפשר לשאול שאלות שאף עיתון בודד לא יכול לענות עליהן. האם עמדה "
                        "מסוימת מתעצבת מחדש? האם נושא שנעלם חוזר בפתאומיות? זו הסיבה שכל "
                        "דוח יומי נבנה מלכתחילה גם כרשומת ארכיון, אבן בניין למבט רחב יותר.",
                    ),
                    (
                        "p",
                        "המבט הרחב הזה כבר אינו רק רעיון. הדוח היומי רץ באופן אוטומטי "
                        "לחלוטין, עם בדיקות תקינות ועצירה אוטומטית בכשלים חוזרים. לצדו פועל "
                        "מדור “מגמות” בשני רכיבים. הראשון הוא דוחות מגמות דו-שבועיים: מדי "
                        "שבוע מתפרסם דוח שמסכם את שני השבועות האחרונים ועוקב אחרי האופן שבו "
                        "הסיקור של נושא משתנה לאורך התקופה. הוא מבוסס על הדוחות היומיים "
                        "עצמם ונכתב כמותם בשלוש השפות. השני הוא מפת מגמות (בטא): מפת אריחים "
                        "של מדינות שמראה איך החלק של כל מדינה בסיקור של העיתונים הנסקרים "
                        "השתנה לעומת השבוע הקודם או לעומת ארבעת השבועות שקדמו לו.",
                    ),
                ],
            },
            {
                "heading": "שיטת העבודה: שלושה תפקידים, לא שניים",
                "blocks": [
                    (
                        "p",
                        "לצד המטרה התוכנית, יש לפרויקט תפקיד נוסף: מקום ללמוד בפועל איך "
                        "בונים מערכת מורכבת עם כלי בינה מלאכותית מתקדמים. התובנה המרכזית: "
                        "המודל הפשטני “אדם מבקש, מכונה מבצעת” אינו מדויק. בפרויקט פועלים "
                        "שלושה גורמים: כלי שיחה ותכנון, שחושב על הבעיה לפני שנכתבת שורת קוד "
                        "ומתרגם החלטה מעורפלת (“אני רוצה שהמערכת תזהה מגמות”) למשימה "
                        "קונקרטית; סוכן כתיבת קוד, שפועל בסביבת הפיתוח: כותב, מריץ, מדווח "
                        "בחזרה; ומעליהם המפעיל האנושי, שרואה את שני הכלים בו-זמנית ובעיקר "
                        "בולם ובודק. לאורך הדרך, זו הייתה שוב ושוב הנקודה שבה נתפסו טעויות: "
                        "תוצאה שנראתה “כמעט טובה” אך לא נבדקה באמת. תוכן ההשוואה בכל דוח "
                        "מופק באמצעות מודל שפה (Claude API של Anthropic), באותה שיטה: בקרה "
                        "אנושית בנקודות קריטיות ובביקורות תקופתיות, ורשת ביטחון קבועה בקוד "
                        "לכל כשל שחוזר על עצמו.",
                    ),
                ],
            },
            {
                "heading": "המקורות",
                "blocks": [
                    (
                        "p",
                        "הפרויקט התחיל עם ארבעה מקורות, שני זוגות מאוזנים פוליטית: Guardian "
                        "מול Telegraph באנגלית, Süddeutsche Zeitung מול Die Welt בגרמנית. "
                        "אחרי כמה ימים התברר פער בולט: הזירה האמריקאית לא הייתה מיוצגת כלל. "
                        "נבחרו ארבעה עיתונים אמריקאים כדי לפרוש טווח פוליטי רחב (The "
                        "Washington Post, Wall Street Journal, Los Angeles Times, USA "
                        "Today), ולצדם שני שבועונים (Economist, Der Spiegel) שמביאים עומק. "
                        "בהמשך התווספו עוד שלושה מקורות (Frankfurter Allgemeine Zeitung, "
                        "Neue Zürcher Zeitung, The Globe and Mail) שמביאים זוויות "
                        "גרמנית-שמרנית, שווייצרית-ליברלית וקנדית, ומקטינים את המשקל היחסי "
                        "של ארה\"ב בתמהיל. לאחרונה הצטרף גם The Observer הבריטי. The Wall "
                        "Street Journal, שנכלל בתחילה, הושעה בסוף ספטמבר ואינו נספר בין "
                        "המקורות הפעילים. היום המערכת עוקבת אחרי 13 מקורות פעילים בשתי שפות "
                        "(שמונה באנגלית, חמישה בגרמנית), בטווח פוליטי רחב בכל זירה.",
                    ),
                ],
            },
            {
                "heading": "המסגרת: שלושה צירי תפיסה",
                "blocks": [
                    (
                        "p",
                        "גאופוליטיקה היא שילוב של תפיסה מרחבית, זמנית וטקסטואלית. דף הבית "
                        "בנוי סביב שלוש “עדשות” שוות מעמד: מפה אינטראקטיבית (כולל אזורי "
                        "קונפליקט פעילים: ישראל-פלסטין, איראן-מערב, רוסיה-אוקראינה), ציר "
                        "זמן וכניסה טקסטואלית. בנוסף אפשר לגלוש בין דוחות לפי נושא, אזור או "
                        "טווח תאריכים.",
                    ),
                ],
            },
            {
                "heading": "השפה השלישית: גרמנית",
                "blocks": [
                    (
                        "p",
                        "האתר פורסם תחילה בעברית ובאנגלית בלבד. ההרחבה לגרמנית נעשתה בשני "
                        "שלבים: כל דוח קיים בארכיון נכתב מחדש לגרמנית, לא תורגם מילולית, "
                        "כדי לשמור על עקביות. מכאן ואילך כל דוח חדש נכתב בגרמנית כטקסט "
                        "מקורי במקביל לעברית ולאנגלית, מאותם מאמרי מקור ולא כתרגום שמתווסף "
                        "אחר כך.",
                    ),
                ],
            },
            {
                "heading": "גבולות הפרויקט",
                "blocks": [
                    (
                        "p",
                        "קורא ביקורתי ראוי שיכיר כמה גבולות. כל המקורות הם עיתונות איכות "
                        "מערבית, ולא מדגם מייצג של הדעות בעולם. נפח הפרסום אינו מדד "
                        "לחשיבות: עיתון שמפרסם הרבה טורי דעה עלול להיראות דומיננטי בלי שזה "
                        "משקף חשיבות אמיתית; מנגנון המיון לפי רוחב המקורות מקל על כך חלקית "
                        "בלבד. אין שכבת אימות עובדתי: המערכת מסכמת מה שכל מקור טוען ואינה "
                        "בודקת אם זה נכון. כל דוח יומי נכתב כיחידה עצמאית; מעקב אחרי "
                        "התפתחות נושא דרש עד כה קריאה ידנית של כמה דוחות, וזה מה שהדוח "
                        "הדו-שבועי בא להקל. שלוש גרסאות השפה נכתבות עצמאית זו מזו ולא "
                        "כתרגום, כך שהבדלי ניסוח קלים ביניהן צפויים.",
                    ),
                ],
            },
            {
                "heading": "מבט קדימה",
                "blocks": [
                    (
                        "p",
                        "הדוח היומי, הדוח הדו-שבועי ומפת המגמות קיימים כעת כולם, אך לא "
                        "באותה בשלות. מפת המגמות היא החוליה הצעירה ביותר: היא נבנתה כדי "
                        "להסביר מה הצבעים אומרים ולא להציג שינוי במקום שאין לו ביסוס, אבל "
                        "היא נשענת על מעט שבועות, ותתייצב רק ככל שיצטברו עוד נתונים. מעבר "
                        "לכך נותרו פתוחות שתי שאלות: חוויית שימוש בהירה יותר לקורא שאינו "
                        "מכיר את הפרויקט, וקהל: האם להרחיב מעבר לחוקרים ואנשי מדיניות, למשל "
                        "לגרסה נגישה לבני נוער.",
                    ),
                ],
            },
        ],
    },
    "en": {
        "doc_meta": "Background Document · October 2026",
        "identity_name": "Meir Shemesh",
        "identity_role": "Technology Consulting and Management",
        "title": "GEOPOLITICS-TRACKER",
        "subtitle": (
            "How world press sees one event through different eyes - and what the "
            "building process itself teaches about human-AI collaboration"
        ),
        "about_title": "About the Project",
        "about_subtitle": (
            "How the same event looks different from newspaper to newspaper - and what "
            "the building process itself teaches about working together with AI"
        ),
        "sections": [
            {
                "heading": None,
                "blocks": [
                    (
                        "p",
                        "Every day, dozens of leading newspapers around the world publish "
                        "hundreds of opinion and analysis pieces about the very same "
                        "geopolitical events. No one can read them all - each of us reads "
                        "one angle or two, usually the ones we already know, and misses "
                        "the fuller conversation taking place between sources that see the "
                        "same event through different lenses.",
                    ),
                    (
                        "p",
                        "geopolitics-tracker tries to solve a focused problem: not to "
                        "replace human reading, but to give it a tool. A system that "
                        "follows leading newspapers in English and German, across a wide "
                        "political range from left to right, identifies the geopolitical "
                        "commentary among them, and builds a daily picture from it: which "
                        "topics drew attention, and how each source chose to frame them. "
                        "The goal isn't to decide \"who's right\" - but to make the full "
                        "range of opinion accessible, not just the corner the reader "
                        "already knows.",
                    ),
                ],
            },
            {
                "heading": "From a Daily Snapshot to a Trend",
                "blocks": [
                    (
                        "p",
                        "The immediate product is a daily report: a document that groups "
                        "that day's commentary by real topic - not by mechanical tagging - "
                        "and sets out a concise comparison between sources for each one. "
                        "But a single daily report, however accurate, is only a snapshot. "
                        "The real value only emerges over time: once weeks and months of "
                        "reports accumulate, you can ask questions no single newspaper can "
                        "answer - is a position being reshaped? Does a topic that "
                        "disappeared suddenly return? That's why every daily report is "
                        "built from the start to double as an archive entry - a building "
                        "block for a wider view.",
                    ),
                    (
                        "p",
                        "That wider view is no longer just an idea. The daily report runs "
                        "fully automatically, with health checks and an automatic stop "
                        "after repeated failures. Alongside it sits a \"Trends\" section with "
                        "two parts. The first is the biweekly trend reports: every week a "
                        "new report covers the previous two weeks and follows how coverage "
                        "of a topic develops over that window. It is built from the daily "
                        "reports themselves and written, like them, in all three languages. "
                        "The second is the Trends Map (beta), a tile map of countries "
                        "showing how each country's share of the surveyed newspapers' "
                        "coverage has changed since the previous week, or since the "
                        "previous four weeks.",
                    ),
                ],
            },
            {
                "heading": "The Method: Three Roles, Not Two",
                "blocks": [
                    (
                        "p",
                        "Alongside its substantive goal, the project has a second role: a "
                        "place to actually learn how to build a complex system with "
                        "advanced AI tools. The central insight: the simplistic model "
                        "\"person asks, machine executes\" isn't accurate. Three parties "
                        "are at work: a conversation-and-planning tool, which thinks "
                        "through the problem before a line of code is written and "
                        "translates a vague decision (\"I want the system to detect "
                        "trends\") into a concrete task; a coding agent, which operates "
                        "inside the development environment - writes, runs, reports back; "
                        "and above both, the human operator, who watches both tools at "
                        "once and, above all, holds the line and checks the work. Again "
                        "and again, this was the point where mistakes got caught - a "
                        "result that looked \"almost good\" but hadn't actually been "
                        "verified. Every report's comparison content is produced using a "
                        "language model (Anthropic's Claude API), by exactly the same "
                        "method: human review at critical points and periodic audits, alongside a standing safety "
                        "net in the code for any failure that repeats.",
                    ),
                ],
            },
            {
                "heading": "The Sources",
                "blocks": [
                    (
                        "p",
                        "The project started with four sources - two politically balanced "
                        "pairs: Guardian vs. Telegraph in English, Süddeutsche Zeitung vs. "
                        "Die Welt in German. After a few days, a clear gap emerged: the "
                        "American arena wasn't represented at all. Four American papers "
                        "were chosen to span a wide political range (The Washington Post, "
                        "Wall Street Journal, Los Angeles Times, USA Today), alongside two "
                        "weeklies (The Economist, Der Spiegel) that bring depth. Three more "
                        "sources were added later (Frankfurter Allgemeine Zeitung, Neue "
                        "Zürcher Zeitung, The Globe and Mail), bringing "
                        "German-conservative, Swiss-liberal and Canadian perspectives - "
                        "and reducing the US's relative weight in the mix. The Observer, a British "
                        "title, joined most recently. The Wall Street Journal, included at the "
                        "start, was suspended at the end of September and is not counted among "
                        "the active sources. Today the system follows 13 active "
                        "sources across two languages (eight in English, five in German), "
                        "spanning a wide political range in every arena.",
                    ),
                ],
            },
            {
                "heading": "The Framework: Three Axes of Perception",
                "blocks": [
                    (
                        "p",
                        "Geopolitics is a combination of spatial, temporal, and textual "
                        "perception. The homepage is built around three equal-standing "
                        "\"lenses\" - an interactive map (including active conflict zones: "
                        "Israel-Palestine, Iran-the West, Russia-Ukraine), a timeline, and "
                        "a textual entry point - along with the ability to browse reports "
                        "by topic, region, or date range.",
                    ),
                ],
            },
            {
                "heading": "The Third Language: German",
                "blocks": [
                    (
                        "p",
                        "The site was first published in Hebrew and English only. The "
                        "expansion to German happened in two stages: every existing report "
                        "in the archive was rewritten into German - not translated "
                        "word-for-word - to keep it consistent; from that point on, every "
                        "new report is written in German as original text, alongside "
                        "Hebrew and English, from the same source articles - not as a "
                        "translation added afterward.",
                    ),
                ],
            },
            {
                "heading": "Limits of the Project",
                "blocks": [
                    (
                        "p",
                        "A critical reader deserves to know a few boundaries. All the "
                        "sources are Western quality press - not a representative sample "
                        "of world opinion. Volume of publication isn't a measure of "
                        "importance: a paper that runs many opinion pieces can look "
                        "dominant without that reflecting real significance; the sorting "
                        "mechanism by source-breadth only partly offsets this. There's no "
                        "fact-checking layer - the system summarizes what each source "
                        "claims, not whether it's true. Every daily report is written as a "
                        "standalone unit; tracking how a topic develops has so far "
                        "required manually reading several reports - which is what the "
                        "biweekly report is meant to ease. The three language versions "
                        "are written independently of each other, not as translations - "
                        "so small differences in wording between them are expected.",
                    ),
                ],
            },
            {
                "heading": "Looking Ahead",
                "blocks": [
                    (
                        "p",
                        "The daily report, the biweekly report and the trends map all exist "
                        "now, but not at the same level of maturity. The map is the "
                        "youngest piece: it was built to explain what its colors mean and "
                        "to show no change where the evidence is too thin, but it rests on "
                        "only a few weeks of data and will settle only as more accumulate. "
                        "Beyond that, two questions remain open: a clearer "
                        "experience for a reader unfamiliar with the project, and audience "
                        "- whether to expand beyond researchers and policy people, for "
                        "instance to a version accessible to teenagers.",
                    ),
                ],
            },
        ],
    },
    "de": {
        "doc_meta": "Hintergrunddokument · Oktober 2026",
        "identity_name": "Meir Shemesh",
        "identity_role": "Technologieberatung und -management",
        "title": "GEOPOLITICS-TRACKER",
        "subtitle": (
            "Wie die Weltpresse ein Ereignis mit unterschiedlichen Augen sieht - und was "
            "der Entstehungsprozess selbst über die Zusammenarbeit von Mensch und "
            "künstlicher Intelligenz lehrt"
        ),
        "about_title": "Über das Projekt",
        "about_subtitle": (
            "Wie dasselbe Ereignis von Zeitung zu Zeitung anders aussieht - und was der "
            "Bauprozess selbst über die Zusammenarbeit zwischen Mensch und KI lehrt"
        ),
        "sections": [
            {
                "heading": None,
                "blocks": [
                    (
                        "p",
                        "Jeden Tag veröffentlichen Dutzende führende Zeitungen weltweit "
                        "Hunderte Meinungs- und Analysebeiträge zu genau denselben "
                        "geopolitischen Ereignissen. Niemand kann sie alle lesen - jeder "
                        "von uns liest ein, zwei Blickwinkel, meist die, die er schon "
                        "kennt, und verpasst das vollständige Gespräch, das zwischen "
                        "Quellen stattfindet, die dasselbe Ereignis durch unterschiedliche "
                        "Linsen sehen.",
                    ),
                    (
                        "p",
                        "geopolitics-tracker versucht, ein konkretes Problem zu lösen: "
                        "nicht die menschliche Lektüre zu ersetzen, sondern ihr ein "
                        "Werkzeug zu geben. Ein System, das führende Zeitungen auf "
                        "Englisch und Deutsch verfolgt, über ein breites politisches "
                        "Spektrum von links bis rechts, darin geopolitische Kommentare "
                        "identifiziert und daraus ein Tagesbild baut: welche Themen "
                        "Aufmerksamkeit bekamen und wie jede Quelle sie einordnete. Das "
                        "Ziel ist nicht zu entscheiden, „wer recht hat“ - sondern das "
                        "gesamte Meinungsspektrum zugänglich zu machen, nicht nur die "
                        "Ecke, die der Leser schon kennt.",
                    ),
                ],
            },
            {
                "heading": "Von der Tagesaufnahme zum Trend",
                "blocks": [
                    (
                        "p",
                        "Das unmittelbare Produkt ist ein Tagesbericht: ein Dokument, das "
                        "die Kommentare eines Tages nach echtem Thema gruppiert - nicht "
                        "nach mechanischer Verschlagwortung - und zu jedem Thema einen "
                        "knappen Vergleich zwischen den Quellen zeigt. Aber ein einzelner "
                        "Tagesbericht, wie genau er auch sein mag, ist nur eine "
                        "Momentaufnahme. Der eigentliche Wert zeigt sich erst mit der "
                        "Zeit: Wenn sich Wochen und Monate von Berichten ansammeln, lassen "
                        "sich Fragen stellen, die keine einzelne Zeitung beantworten kann "
                        "- formt sich eine bestimmte Position neu? Kehrt ein "
                        "verschwundenes Thema plötzlich zurück? Deshalb ist jeder "
                        "Tagesbericht von Anfang an auch als Archiveintrag angelegt - ein "
                        "Baustein für den weiteren Blick.",
                    ),
                    (
                        "p",
                        "Dieser weite Blick ist keine bloße Idee mehr. Der Tagesbericht "
                        "läuft vollautomatisch, mit Funktionsprüfungen und automatischem "
                        "Stopp bei wiederholten Fehlern. Daneben gibt es den Bereich "
                        "„Trends“ mit zwei Teilen. Der erste sind die zweiwöchentlichen "
                        "Trendberichte: Jede Woche erscheint ein neuer Bericht über die "
                        "zurückliegenden zwei Wochen, der verfolgt, wie sich die "
                        "Berichterstattung zu einem Thema in diesem Zeitraum entwickelt. Er "
                        "beruht auf den Tagesberichten selbst und wird wie diese in allen "
                        "drei Sprachen geschrieben. Der zweite ist die Trendkarte (Beta): "
                        "eine Kachelkarte der Länder, die zeigt, wie sich der Anteil jedes "
                        "Landes an der Berichterstattung der ausgewerteten Zeitungen "
                        "gegenüber der Vorwoche oder den vier Vorwochen verändert hat.",
                    ),
                ],
            },
            {
                "heading": "Die Arbeitsweise: Drei Rollen, nicht zwei",
                "blocks": [
                    (
                        "p",
                        "Neben seinem inhaltlichen Ziel hat das Projekt eine zweite "
                        "Rolle: ein Ort, um in der Praxis zu lernen, wie man mit "
                        "fortgeschrittenen KI-Werkzeugen ein komplexes System baut. Die "
                        "zentrale Erkenntnis: Das vereinfachte Modell „Mensch fragt, "
                        "Maschine führt aus“ trifft nicht zu. Drei Parteien sind "
                        "beteiligt: ein Gesprächs- und Planungswerkzeug, das über das "
                        "Problem nachdenkt, bevor eine Codezeile geschrieben wird, und "
                        "eine vage Entscheidung („ich möchte, dass das System Trends "
                        "erkennt“) in eine konkrete Aufgabe übersetzt; ein Code-Agent, der "
                        "in der Entwicklungsumgebung arbeitet - schreibt, führt aus, "
                        "meldet zurück; und über beiden der menschliche Betreiber, der "
                        "beide Werkzeuge gleichzeitig beobachtet und vor allem bremst und "
                        "prüft. Genau an dieser Stelle wurden immer wieder Fehler "
                        "entdeckt - ein Ergebnis, das „fast gut“ aussah, aber nie wirklich "
                        "geprüft worden war. Der Vergleichsinhalt jedes Berichts wird mit "
                        "einem Sprachmodell erzeugt (Anthropics Claude API), nach genau "
                        "derselben Methode: menschliche Prüfung an kritischen Punkten und bei "
                        "regelmäßigen Audits, neben einem fest im Code verankerten "
                        "Sicherheitsnetz für jeden wiederkehrenden Fehler.",
                    ),
                ],
            },
            {
                "heading": "Die Quellen",
                "blocks": [
                    (
                        "p",
                        "Das Projekt begann mit vier Quellen - zwei politisch "
                        "ausgewogenen Paaren: Guardian gegen Telegraph auf Englisch, "
                        "Süddeutsche Zeitung gegen Die Welt auf Deutsch. Nach wenigen "
                        "Tagen zeigte sich eine deutliche Lücke: Der amerikanische Raum "
                        "war gar nicht vertreten. Vier amerikanische Zeitungen wurden "
                        "gewählt, um ein breites politisches Spektrum abzudecken (The "
                        "Washington Post, Wall Street Journal, Los Angeles Times, USA "
                        "Today), dazu zwei Wochenmagazine (The Economist, Der Spiegel), "
                        "die Tiefe bringen. Später kamen drei weitere Quellen hinzu "
                        "(Frankfurter Allgemeine Zeitung, Neue Zürcher Zeitung, "
                        "The Globe and Mail), die deutsch-konservative, "
                        "schweizerisch-liberale und kanadische Perspektiven einbringen - "
                        "und das relative Gewicht der USA im Mix verringern. Zuletzt kam noch "
                        "The Observer aus Großbritannien hinzu. Das Wall Street Journal, das "
                        "anfangs dabei war, wurde Ende September ausgesetzt und zählt nicht zu "
                        "den aktiven Quellen. Heute verfolgt das System "
                        "13 aktive Quellen in zwei Sprachen (acht auf Englisch, fünf auf "
                        "Deutsch), mit breitem politischem Spektrum in jedem Raum.",
                    ),
                ],
            },
            {
                "heading": "Der Rahmen: drei Wahrnehmungsachsen",
                "blocks": [
                    (
                        "p",
                        "Geopolitik ist eine Kombination aus räumlicher, zeitlicher und "
                        "textueller Wahrnehmung. Die Startseite ist um drei gleichrangige "
                        "„Linsen“ aufgebaut - eine interaktive Karte (einschließlich "
                        "aktiver Konfliktzonen: Israel-Palästina, Iran-der Westen, "
                        "Russland-Ukraine), eine Zeitleiste und einen textuellen Einstieg "
                        "- sowie die Möglichkeit, Berichte nach Thema, Region oder "
                        "Zeitraum zu durchsuchen.",
                    ),
                ],
            },
            {
                "heading": "Die dritte Sprache: Deutsch",
                "blocks": [
                    (
                        "p",
                        "Die Website wurde zunächst nur auf Hebräisch und Englisch "
                        "veröffentlicht. Die Erweiterung auf Deutsch geschah in zwei "
                        "Schritten: Jeder bestehende Bericht im Archiv wurde neu auf "
                        "Deutsch geschrieben - nicht wörtlich übersetzt - um Konsistenz "
                        "zu bewahren; von da an wird jeder neue Bericht auf Deutsch als "
                        "eigenständiger Originaltext verfasst, parallel zu Hebräisch und "
                        "Englisch, aus denselben Quellartikeln - nicht als nachträglich "
                        "hinzugefügte Übersetzung.",
                    ),
                ],
            },
            {
                "heading": "Grenzen des Projekts",
                "blocks": [
                    (
                        "p",
                        "Ein kritischer Leser sollte einige Grenzen kennen. Alle Quellen "
                        "sind westliche Qualitätspresse - keine repräsentative "
                        "Stichprobe der Weltmeinung. Veröffentlichungsvolumen ist kein "
                        "Maß für Wichtigkeit: Eine Zeitung, die viele Meinungsbeiträge "
                        "veröffentlicht, kann dominant wirken, ohne dass dies echte "
                        "Bedeutung widerspiegelt; der Sortiermechanismus nach "
                        "Quellenbreite gleicht das nur teilweise aus. Es gibt keine "
                        "Faktenprüfungsebene - das System fasst zusammen, was jede Quelle "
                        "behauptet, nicht ob es stimmt. Jeder Tagesbericht wird als "
                        "eigenständige Einheit geschrieben; die Entwicklung eines Themas "
                        "zu verfolgen erforderte bisher das manuelle Lesen mehrerer "
                        "Berichte - genau das soll der zweiwöchentliche Bericht "
                        "erleichtern. Die drei Sprachversionen werden unabhängig "
                        "voneinander geschrieben, nicht als Übersetzung - kleine "
                        "Unterschiede in der Formulierung zwischen ihnen sind daher zu "
                        "erwarten.",
                    ),
                ],
            },
            {
                "heading": "Ausblick",
                "blocks": [
                    (
                        "p",
                        "Tagesbericht, zweiwöchentlicher Trendbericht und Trendkarte gibt "
                        "es inzwischen alle, aber nicht in gleicher Reife. Die Karte ist "
                        "der jüngste Baustein: Sie wurde so gebaut, dass klar wird, was die "
                        "Farben bedeuten, und dass sie keine Veränderung zeigt, wo die "
                        "Belege zu dünn sind. Sie beruht aber nur auf wenigen Wochen Daten "
                        "und wird sich erst festigen, wenn weitere hinzukommen. "
                        "Darüber hinaus "
                        "bleiben zwei Fragen offen: eine klarere Nutzererfahrung für "
                        "Leser, die das Projekt nicht kennen, und die Zielgruppe - ob man "
                        "über Forscher und Politikexperten hinaus erweitert, etwa zu "
                        "einer für Jugendliche zugänglichen Version.",
                    ),
                ],
            },
        ],
    },
}
