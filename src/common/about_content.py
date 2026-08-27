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
                        "לתת לקריאה הזו כלי: מערכת שעוקבת אחרי עיתונים מובילים באנגלית ובגרמנית "
                        "- נבחרו במכוון על פני טווח פוליטי רחב - ובונה מהם תמונה יומית של מה "
                        "שתפס את תשומת הלב, ואיך כל מקור בחר למסגר אותו.",
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
                        "לאחר כל שלב עובד. סוכן כתיבת הקוד מציג תוכנית לפני מימוש וממתין "
                        "לאישור - לא פועל על סמך שיקול דעת עצמאי מוחלט. כשמשהו “כמעט עבד” אך "
                        "התברר כלא-מספיק, ההעדפה העקבית הייתה לבנות רשת-ביטחון גנרית ברמת "
                        "הקוד שתופסת כל מקרה חריג מראש, ולא לרדוף אחרי כל מקרה בודד בנפרד.",
                    ),
                ],
            },
            {
                "heading": "מה קיים היום: מהאנליזה לאתר חי",
                "blocks": [
                    (
                        "p",
                        "המערכת בנויה כתהליך עבודה של חמישה שלבים עוקבים - איסוף מהעיתונים, "
                        "חילוץ טקסט, ניתוח וסיווג באמצעות Claude API, הפקת דוחות, ופרסום - "
                        "וכולם פעילים על נתונים אמיתיים. כל דוח יומי מופק בשתי שפות מלאות "
                        "(עברית ואנגלית) ובשני פורמטים (PDF + HTML אינטראקטיבי), עם השוואה "
                        "בין-מקורית שמקבצת מאמרים לפי נושא אמיתי, לא תיוג מכני. האתר עצמו חי "
                        "ונגיש: geopolitics.meirshemesh.com.",
                    ),
                    (
                        "ul_plain",
                        [
                            "7 ימי כיסוי מלאים בארכיון, 4 עיתונים, מעל 300 מאמרי פרשנות שנותחו "
                            "לעומק.",
                            "ארכיטקטורה דו-שלבית לניתוח: סינון רחב וזול, ואחריו ניתוח מעמיק - "
                            "רק על מה שסונן פנימה.",
                            "עלות מצטברת צנועה ביחס להיקף העיבוד - סביב עשרה דולרים בחודש "
                            "בתקופת הפיתוח האינטנסיבית.",
                        ],
                    ),
                ],
            },
            {
                "heading": "המסגרת החדשה: שלושה צירי תפיסה",
                "blocks": [
                    (
                        "p",
                        "גאופוליטיקה היא שילוב של כמה תפיסות חושיות שונות בתכלית: מרחבית, "
                        "זמנית, וטקסטואלית. לכן דף הבית הבא נבנה סביב שלוש “עדשות” "
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
                        "שאר פרטי המאמר, ללא עלות נוספת - וכל 437 המאמרים הקיימים תויגו "
                        "למפרע.",
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
                        "system that follows leading newspapers in English and German - "
                        "deliberately chosen to span a wide political range - and builds "
                        "from them a daily picture of what caught the world's attention, "
                        "and how each source chose to frame it.",
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
                        "at once, with a checkpoint after each working stage. The coding "
                        "agent presents a plan before implementation and waits for "
                        "approval - it doesn't act on fully independent judgment. When "
                        "something \"almost worked\" but turned out insufficient, the "
                        "consistent preference was to build a generic safety net at the "
                        "code level that catches any edge case in advance, rather than "
                        "chasing each individual case separately.",
                    ),
                ],
            },
            {
                "heading": "What exists today: from analysis to a live site",
                "blocks": [
                    (
                        "p",
                        "The system is built as a workflow of five sequential stages - "
                        "collecting from newspapers, extracting text, analyzing and "
                        "classifying via the Claude API, generating reports, and "
                        "publishing - all active on real data. Every daily report is "
                        "produced in two full languages (Hebrew and English) and two "
                        "formats (PDF and interactive HTML), with a cross-source "
                        "comparison that groups articles by real topic, not mechanical "
                        "tagging. The site itself is live and accessible: "
                        "geopolitics.meirshemesh.com.",
                    ),
                    (
                        "ul_plain",
                        [
                            "7 full days of archive coverage, 4 newspapers, over 300 "
                            "opinion pieces analyzed in depth.",
                            "Two-stage analysis architecture: broad, cheap screening, "
                            "followed by deep analysis - only on what passed through.",
                            "Modest cumulative cost relative to processing volume - "
                            "around ten dollars a month during the intensive development "
                            "period.",
                        ],
                    ),
                ],
            },
            {
                "heading": "The new framework: three axes of perception",
                "blocks": [
                    (
                        "p",
                        "Geopolitics combines several fundamentally different senses of "
                        "perception: spatial, temporal, and textual. That's why the next "
                        "homepage is built around three equal-standing \"lenses\" on the "
                        "same data - a geographic axis (where), a time axis (when, and "
                        "where things are heading), and a textual axis (what was written, "
                        "and how each source framed it) - all three reading from one "
                        "source of truth and updating together.",
                    ),
                    (
                        "p",
                        "For the geographic axis to be possible at all, a closed taxonomy "
                        "of 94 countries across 8 geopolitical regions was built, along "
                        "with three actively-tracked conflict zones consistently covered "
                        "in the press: the Israeli-Palestinian conflict, the Iran-West "
                        "confrontation, and the Russia-Ukraine war. The tagging is "
                        "produced in the same model call that already generates the rest "
                        "of each article's details, at no added cost - and all 437 "
                        "existing articles were tagged retroactively.",
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
