"""Shared background/about content for the project, in Hebrew and English.

Single source of truth for text used by two independent renderers:
scripts/build_background_doc.py (standalone branded PDF+HTML, Assistant font)
and src/publishing/publish.py's build_about_html() (a regular site page,
Heebo font, part of docs/{he,en}/about.html). Keeping the text here means a
wording fix only has to happen in one place, not two.

Each language entry has doc_meta/identity_name/identity_role/title/subtitle,
plus `sections`: an ordered list of {"heading": str | None, "blocks": [...]}
where each block is ("p", text), ("ul_labeled", [(label, text), ...]) for a
bold-lead-in bullet list, or ("ul_plain", [text, ...]) for a plain one.

render_sections_html() turns `sections` into the shared <h2>/<p>/<ul> HTML
shape both renderers use - only the surrounding CSS/fonts differ per caller.
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
        "doc_meta": "מסמך רקע · אוגוסט 2026",
        "identity_name": "מאיר שמש",
        "identity_role": "ייעוץ וניהול טכנולוגיות",
        "title": "GEOPOLITICS-TRACKER",
        "subtitle": (
            "כיצד עיתונות עולמית רואה אירוע אחד בעיניים שונות - ומה תהליך הבנייה עצמו "
            "מלמד על עבודה משותפת בין אדם לבינה מלאכותית"
        ),
        "sections": [
            {
                "heading": None,
                "blocks": [
                    (
                        "p",
                        "בכל יום, עשרות עיתונים מובילים מפרסמים מאות מאמרי פרשנות על אותם "
                        "אירועים גאופוליטיים בדיוק. אף אדם אינו יכול לקרוא את כולם - וכל אחד "
                        "מאיתנו קורא זווית אחת או שתיים, לרוב אלה שהוא כבר מכיר, ומחמיץ את "
                        "השיחה המלאה שמתקיימת בין מקורות שונים. geopolitics-tracker הוא ניסיון "
                        "לתת לקריאה הזו כלי: מערכת שעוקבת אחרי עיתונים מובילים, מזהה בתוכם את "
                        "מאמרי הפרשנות הגאופוליטית, ובונה מהם תמונה יומית של מה שתפס את תשומת "
                        "הלב - ואיך כל מקור בחר למסגר אותו.",
                    ),
                ],
            },
            {
                "heading": "שיטת העבודה: שיתוף פעולה בין אדם למכונה",
                "blocks": [
                    (
                        "p",
                        "מעבר למטרה התוכנית, לפרויקט תפקיד נוסף: מקום ללמוד בפועל איך בונים "
                        "מערכת מורכבת עם כלי בינה מלאכותית מתקדמים, מבלי להזמין תוכנית מוכנה "
                        "כקופסה שחורה. זו בחירה מכוונת, לא צורך טכני - להבין כל שלב, כל החלטה, "
                        "ואיך מזהים ומתקנים כשמשהו משתבש.",
                    ),
                    (
                        "p",
                        "לאורך הדרך התבררה תובנה מרכזית: המודל “אדם מבקש, מכונה מבצעת” אינו "
                        "מדויק. בפועל פועלים שלושה גורמים נפרדים, כל אחד עם תפקיד שונה:",
                    ),
                    (
                        "ul_labeled",
                        [
                            (
                                "כלי שיחה ותכנון",
                                "עוזר לחשוב על הבעיה לפני שנכתבת שורת קוד אחת: בוחן חלופות "
                                "ארכיטקטוניות, מזהה סיכונים מראש, ומתרגם החלטות מעורפלות "
                                "למשימות קונקרטיות. תפקידו קרוב יותר ליועץ תכנון מאשר לכותב "
                                "קוד.",
                            ),
                            (
                                "סוכן כתיבת קוד",
                                "פועל בפועל בתוך סביבת הפיתוח: כותב קוד, מריץ אותו, בודק "
                                "תוצאות ומדווח בחזרה. עוצר ומבקש אישור לפני שינויים "
                                "משמעותיים, ומדווח על ממצאים לא-צפויים במקום להסתיר אותם "
                                "בשקט.",
                            ),
                            (
                                "המפעיל האנושי",
                                "לא צד פסיבי שרק מאשר, אלא הגורם היחיד שרואה את שני הכלים "
                                "בו-זמנית ומעביר החלטות ביניהם. זו הנקודה שבה נתפסות שוב "
                                "ושוב תוצאות “כמעט טובות” שלא באמת נבדקו, הנחות שגויות, או "
                                "פתרון-יתר לבעיה שלא הייתה קיימת בפועל.",
                            ),
                        ],
                    ),
                    (
                        "p",
                        "המתודולוגיה בפועל: בנייה מודול-מודול, לא הכל בבת אחת, עם נקודת עצירה "
                        "לאחר כל שלב עובד. כשמשהו “כמעט עבד” אך התברר כלא-מספיק, ההעדפה "
                        "העקבית הייתה לבנות רשת-ביטחון גנרית ברמת הקוד שתופסת כל מקרה חריג "
                        "מראש, ולא לרדוף אחרי כל מקרה בודד בנפרד - עיקרון שהוכיח את עצמו שוב "
                        "ושוב, מהשלבים הראשונים ועד הרחבות מאוחרות יותר.",
                    ),
                ],
            },
            {
                "heading": "המקורות: מארבעה לעשרה",
                "blocks": [
                    (
                        "p",
                        "הפרויקט התחיל, בימיו הראשונים, עם ארבעה מקורות בלבד - שני זוגות "
                        "מאוזנים פוליטית, אחד בכל שפה: The Guardian מול The Daily Telegraph "
                        "באנגלית, Süddeutsche Zeitung מול Die Welt בגרמנית. הבחירה בזוגות לא "
                        "הייתה מקרית - היא נועדה למנוע מלכתחילה הטיה שיטתית לכיוון פוליטי "
                        "אחד, ולוודא שכל יום מציג לפחות שתי זוויות מנוגדות.",
                    ),
                    (
                        "p",
                        "אחרי כמה ימי עבודה יציבים על הבסיס הזה, התברר פער בולט: הזירה "
                        "העיתונאית העיקרית והמרכזית בעולם - האמריקאית - לא הייתה מיוצגת כלל. "
                        "ההרחבה שבאה בעקבות זאת לא הסתפקה בהוספת זוג נוסף. במקום זאת נבחרו "
                        "ארבעה עיתונים אמריקאים במכוון, כדי לפרוש בתוך הזירה האמריקאית עצמה "
                        "טווח פוליטי רחב יותר משזוג יחיד יכול לתת: The New York Times "
                        "(מהדורה בינלאומית) כקול מרכז-שמאל, The Wall Street Journal כקול "
                        "ימני-ממסדי, Los Angeles Times כקול מרכז-שמאל נוסף בזווית "
                        "חוף-מערבי, ו-USA Today כקול מרכזי-ניטרלי שאינו נושא זהות "
                        "אידיאולוגית מובהקת.",
                    ),
                    (
                        "p",
                        "לצד ההרחבה היומית, נוספו שני שבועונים - The Economist ו-Der "
                        "Spiegel - שמביאים סוג שונה של עומק: לא עוד זווית-יומית, אלא ניתוח "
                        "מרוכז ומעמיק יותר שמשלים את קצב הכיסוי היומי, גם אם אינו זמין בכל "
                        "יום בודד.",
                    ),
                    (
                        "p",
                        "היום המערכת עוקבת אחרי עשרה מקורות: ארבעת המקורות המקוריים, ארבעה "
                        "עיתונים אמריקאים, ושני שבועונים - בשתי שפות (אנגלית וגרמנית) "
                        "ובטווח פוליטי רחב בכל אחת מהזירות שהיא מכסה.",
                    ),
                ],
            },
            {
                "heading": "המסגרת: שלושה צירי תפיסה",
                "blocks": [
                    (
                        "p",
                        "גאופוליטיקה היא שילוב של כמה תפיסות חושיות שונות בתכלית: מרחבית, "
                        "זמנית, וטקסטואלית. לכן דף הבית של הפרויקט נבנה סביב שלוש “עדשות” "
                        "שוות-מעמד על אותם נתונים - ציר גיאוגרפי (איפה), ציר זמן (מתי, ולאן "
                        "זה נוטה), וציר טקסטואלי (מה נכתב, ואיך כל מקור מיסגר אותו) - שלושתן "
                        "קוראות ממקור אמת אחד ומתעדכנות יחד.",
                    ),
                    (
                        "p",
                        "כדי שהציר הגיאוגרפי יהיה אפשרי בכלל, נבנתה טקסונומיה סגורה של 94 "
                        "מדינות ב-8 אזורים גאופוליטיים, ושלושה אזורי קונפליקט פעילים "
                        "המסוקרים בעקביות: הסכסוך הישראלי-פלסטיני, העימות איראן-מערב, "
                        "ומלחמת רוסיה-אוקראינה. התיוג נכנס לאותה קריאת מודל שכבר מפיקה את "
                        "שאר פרטי המאמר.",
                    ),
                ],
            },
            {
                "heading": "מה קיים היום",
                "blocks": [
                    (
                        "p",
                        "המערכת בנויה כתהליך עבודה של חמישה שלבים עוקבים - איסוף מהעיתונים, "
                        "חילוץ טקסט, ניתוח וסיווג באמצעות Claude API, הפקת דוחות, ופרסום - "
                        "וכולם פעילים על נתונים אמיתיים. כל דוח יומי מופק בשתי שפות מלאות "
                        "(עברית ואנגלית) ובשני פורמטים (PDF ואתר אינטראקטיבי), עם השוואה "
                        "בין-מקורית שמקבצת מאמרים לפי נושא אמיתי, לא תיוג מכני. האתר עצמו חי "
                        "ונגיש: geopolitics.meirshemesh.com.",
                    ),
                    (
                        "ul_plain",
                        [
                            "מעל תשעה ימי כיסוי מלאים בארכיון, עשרה מקורות, מאות מאמרי "
                            "פרשנות שנותחו לעומק.",
                            "ארכיטקטורה דו-שלבית לניתוח כל מאמר: סינון רחב וזול, ואחריו "
                            "ניתוח מעמיק - רק על מה שסונן פנימה.",
                            "הפקת ההשוואה היומית עצמה עברה לאחרונה שדרוג דומה: במקום קריאה "
                            "בודדת שמנסה לקבץ ולכתוב את כל מאמרי היום בבת אחת - גישה "
                            "שהתגלתה כלא-יציבה ככל שמספר המקורות גדל - היא מתבצעת כעת "
                            "בשני שלבים נפרדים (קיבוץ לנושאים, ואז כתיבת השוואה לכל נושא "
                            "בנפרד, במקביל), עם שיתוף-הקשר בין הקריאות שמוזיל את העלות "
                            "משמעותית.",
                        ],
                    ),
                ],
            },
            {
                "heading": "מבט קדימה",
                "blocks": [
                    (
                        "p",
                        "התשתית הרחבה כבר יציבה; מה שנותר הוא ליטוש - דיוק בקיבוץ נושאים, "
                        "חידוד הפניות למקורות, ומשוב אנושי על התוכן וההצגה. ככל שיצטברו ימי "
                        "כיסוי נוספים, יתאפשר גם מה שהפרויקט שואף אליו מלכתחילה: לא רק “מה "
                        "קרה היום”, אלא “לאן זה נוטה” - זיהוי מגמות אמיתיות, ודוחות בחתכים "
                        "נוספים, אזוריים ומדינתיים, לא רק יומיים.",
                    ),
                ],
            },
        ],
    },
    "en": {
        "doc_meta": "Background Document · August 2026",
        "identity_name": "Meir Shemesh",
        "identity_role": "Technology Consulting and Management",
        "title": "GEOPOLITICS-TRACKER",
        "subtitle": (
            "How world press sees one event through different eyes - and what the "
            "building process itself teaches about human-AI collaboration"
        ),
        "sections": [
            {
                "heading": None,
                "blocks": [
                    (
                        "p",
                        "Every day, dozens of leading newspapers publish hundreds of opinion "
                        "pieces on the very same geopolitical events. No single person can "
                        "read them all - and each of us tends to read one angle or two, "
                        "usually the ones we already recognize, missing the fuller "
                        "conversation happening between different sources. "
                        "geopolitics-tracker is an attempt to give that reading a tool: a "
                        "system that follows leading newspapers, identifies their "
                        "geopolitical opinion pieces, and builds from them a daily picture "
                        "of what caught the world's attention - and how each source chose "
                        "to frame it.",
                    ),
                ],
            },
            {
                "heading": "Working method: human-machine collaboration",
                "blocks": [
                    (
                        "p",
                        "Beyond its practical goal, the project has another role: a place "
                        "to actually learn how to build a complex system with advanced AI "
                        "coding tools, rather than ordering a finished product as a black "
                        "box. This is a deliberate choice, not a technical necessity - to "
                        "understand every step, every decision, and how to identify and "
                        "fix things when they go wrong.",
                    ),
                    (
                        "p",
                        "Along the way, one insight stood out: the simple model of "
                        "\"human requests, machine executes\" isn't accurate. In practice, "
                        "three separate agents are at work, each with a different role:",
                    ),
                    (
                        "ul_labeled",
                        [
                            (
                                "Planning and conversation tool",
                                "helps think through the problem before a single line of "
                                "code is written: weighing architectural alternatives, "
                                "flagging risks early, and translating vague decisions into "
                                "concrete, buildable tasks. Its role is closer to a "
                                "planning consultant than a coder.",
                            ),
                            (
                                "Coding agent",
                                "works directly inside the development environment: writes "
                                "code, runs it, checks results, and reports back. Stops and "
                                "asks for approval before significant changes, and reports "
                                "unexpected findings instead of quietly hiding them.",
                            ),
                            (
                                "Human operator",
                                "not a passive party who merely approves, but the only one "
                                "who sees both tools at once and relays decisions between "
                                "them. This is where \"almost good\" results that were "
                                "never truly verified, wrong assumptions, or "
                                "over-engineered solutions to non-existent problems get "
                                "caught, again and again.",
                            ),
                        ],
                    ),
                    (
                        "p",
                        "The methodology in practice: building module by module, not all "
                        "at once, with a checkpoint after each working stage. When "
                        "something \"almost worked\" but turned out insufficient, the "
                        "consistent preference was to build a generic safety net at the "
                        "code level that catches any edge case in advance, rather than "
                        "chasing each individual case separately - a principle that proved "
                        "itself repeatedly, from the earliest stages through later "
                        "expansions.",
                    ),
                ],
            },
            {
                "heading": "The sources: from four to ten",
                "blocks": [
                    (
                        "p",
                        "The project began, in its first days, with just four sources - "
                        "two politically balanced pairs, one per language: The Guardian "
                        "versus The Daily Telegraph in English, Süddeutsche Zeitung versus "
                        "Die Welt in German. The choice of pairs was deliberate - meant to "
                        "prevent systematic bias toward one political direction from the "
                        "start, and to ensure every day presented at least two opposing "
                        "angles.",
                    ),
                    (
                        "p",
                        "After a few stable days of work on that foundation, a clear gap "
                        "emerged: the world's primary and central press arena - the "
                        "American one - wasn't represented at all. The expansion that "
                        "followed didn't settle for adding one more pair. Instead, four "
                        "American newspapers were chosen deliberately, to span a wider "
                        "political range within the American arena itself than a single "
                        "pair could offer: The New York Times (International Edition) as a "
                        "center-left voice, The Wall Street Journal as an "
                        "establishment-right voice, Los Angeles Times as an additional "
                        "center-left voice with a West Coast angle, and USA Today as a "
                        "centrist voice without a distinct ideological identity.",
                    ),
                    (
                        "p",
                        "Alongside the daily expansion, two weeklies were added - The "
                        "Economist and Der Spiegel - bringing a different kind of depth: "
                        "not another daily angle, but more concentrated, in-depth analysis "
                        "that complements the pace of daily coverage, even when it isn't "
                        "available every single day.",
                    ),
                    (
                        "p",
                        "Today the system follows ten sources: the four original ones, "
                        "four American newspapers, and two weeklies - in two languages "
                        "(English and German), and with a wide political range within "
                        "each of the arenas it covers.",
                    ),
                ],
            },
            {
                "heading": "The framework: three axes of perception",
                "blocks": [
                    (
                        "p",
                        "Geopolitics combines several fundamentally different senses of "
                        "perception: spatial, temporal, and textual. That's why the "
                        "project's homepage is built around three equal-standing "
                        "\"lenses\" on the same data - a geographic axis (where), a time "
                        "axis (when, and where things are heading), and a textual axis "
                        "(what was written, and how each source framed it) - all three "
                        "reading from one source of truth and updating together.",
                    ),
                    (
                        "p",
                        "For the geographic axis to be possible at all, a closed taxonomy "
                        "of 94 countries across 8 geopolitical regions was built, along "
                        "with three actively-tracked conflict zones consistently covered "
                        "in the press: the Israeli-Palestinian conflict, the Iran-West "
                        "confrontation, and the Russia-Ukraine war. The tagging is "
                        "produced in the same model call that already generates the rest "
                        "of each article's details.",
                    ),
                ],
            },
            {
                "heading": "What exists today",
                "blocks": [
                    (
                        "p",
                        "The system is built as a workflow of five sequential stages - "
                        "collecting from newspapers, extracting text, analyzing and "
                        "classifying via the Claude API, generating reports, and "
                        "publishing - all active on real data. Every daily report is "
                        "produced in two full languages (Hebrew and English) and two "
                        "formats (PDF and an interactive website), with a cross-source "
                        "comparison that groups articles by real topic, not mechanical "
                        "tagging. The site itself is live and accessible: "
                        "geopolitics.meirshemesh.com.",
                    ),
                    (
                        "ul_plain",
                        [
                            "Over nine full days of archive coverage, ten sources, "
                            "hundreds of opinion pieces analyzed in depth.",
                            "A two-stage analysis architecture for every article: broad, "
                            "cheap screening, followed by deep analysis - only on what "
                            "passed through.",
                            "The daily synthesis step itself recently underwent a similar "
                            "upgrade: instead of a single call trying to group and write "
                            "up all of a day's articles at once - an approach that proved "
                            "unstable as the number of sources grew - it now runs in two "
                            "separate stages (grouping into topics, then writing a "
                            "comparison for each topic separately, in parallel), with "
                            "shared context between the calls that significantly reduces "
                            "the cost.",
                        ],
                    ),
                ],
            },
            {
                "heading": "Looking ahead",
                "blocks": [
                    (
                        "p",
                        "The broad infrastructure is already stable; what remains is "
                        "polish - precision in topic grouping, sharper source references, "
                        "and human feedback on content and presentation. As more days of "
                        "coverage accumulate, the project's original ambition becomes "
                        "possible too: not just \"what happened today,\" but \"where is "
                        "this heading\" - identifying real trends, and reports at "
                        "additional scales, regional and per-country, not just daily.",
                    ),
                ],
            },
        ],
    },
}
