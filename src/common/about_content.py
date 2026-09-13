"""Shared background/about content for the project, in Hebrew and English.

Single source of truth for text used by two independent renderers:
scripts/build_background_doc.py (standalone branded PDF+HTML, Assistant font)
and src/publishing/publish.py's build_about_html() (a regular site page, also
Assistant font as of the site-wide font unification - part of
docs/{he,en}/about.html). Keeping the text here means a wording fix only has
to happen in one place, not two.

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
        "doc_meta": "מסמך רקע · ספטמבר 2026",
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
                        "מערכת מורכבת עם כלי בינה מלאכותית מתקדמים. לאורך הדרך התבררה תובנה "
                        "מרכזית: המודל “אדם מבקש, מכונה מבצעת” אינו מדויק. בפרויקט שלושה "
                        "שותפים, כל אחד עם תפקיד מובחן - כלי תכנון שחושב על הבעיה לפני "
                        "שנכתבת שורת קוד, וסוכן שכותב ומריץ קוד בפועל ומדווח בחזרה - "
                        "ומעליהם המפעיל האנושי, שהוא בעל החזון ומקבל ההחלטות בפרויקט: מנחה, "
                        "מסנכרן בין השותפים, ומטיל עליהם משימות בהתאם לתכנית שהוא קובע.",
                    ),
                    (
                        "p",
                        "המתודולוגיה בפועל: בנייה מודול-מודול, עם בדיקה ויזואלית אנושית לפני "
                        "כל שינוי שיוצא לאוויר, ורשת-ביטחון גנרית ברמת הקוד בכל פעם שמתגלה "
                        "כשל חוזר - לא תיקון נקודתי לכל מקרה בנפרד.",
                    ),
                ],
            },
            {
                "heading": "המקורות: מארבעה לעשרה",
                "blocks": [
                    (
                        "p",
                        "הפרויקט התחיל עם ארבעה מקורות - שני זוגות מאוזנים פוליטית, אחד בכל "
                        "שפה: Guardian מול Telegraph באנגלית, Süddeutsche Zeitung מול Die "
                        "Welt בגרמנית.",
                    ),
                    (
                        "p",
                        "אחרי כמה ימים יציבים התברר פער בולט: הזירה האמריקאית לא הייתה "
                        "מיוצגת כלל. ההרחבה שבאה בעקבות כך לא הסתפקה בזוג נוסף - נבחרו "
                        "ארבעה עיתונים אמריקאים במכוון כדי לפרוש טווח פוליטי רחב יותר בתוך "
                        "הזירה עצמה (Washington Post, Wall Street Journal, "
                        "Los Angeles Times, USA Today), ולצדם שני שבועונים (Economist, Der "
                        "Spiegel) שמביאים עומק במקום עוד זווית יומית.",
                    ),
                    (
                        "p",
                        "היום המערכת עוקבת אחרי מקורות מגוונים בשתי שפות, עם טווח פוליטי "
                        "רחב בכל אחת מהזירות שהיא מכסה.",
                    ),
                ],
            },
            {
                "heading": "המסגרת: שלושה צירי תפיסה",
                "blocks": [
                    (
                        "p",
                        "גאופוליטיקה היא שילוב של תפיסה מרחבית, זמנית וטקסטואלית. דף הבית "
                        "בנוי סביב שלוש “עדשות” שוות-מעמד על אותם נתונים - מפה גיאוגרפית "
                        "אינטראקטיבית (כולל אזורי קונפליקט פעילים: הסכסוך הישראלי-פלסטיני, "
                        "איראן-מערב, רוסיה-אוקראינה), ציר זמן, וכניסה טקסטואלית - וכן "
                        "אפשרות לגלוש בין דוחות לפי נושא, אזור או טווח תאריכים, לא רק יום "
                        "בודד.",
                    ),
                ],
            },
            {
                "heading": "מה קיים היום",
                "blocks": [
                    (
                        "p",
                        "חמישה שלבים עוקבים - איסוף, חילוץ טקסט, ניתוח וסיווג באמצעות "
                        "Claude API, הפקת השוואה, ופרסום - פעילים על נתונים אמיתיים. כל דוח "
                        "יומי: שתי שפות מלאות, שני פורמטים, השוואה בין-מקורית עם הפניות "
                        "מדויקות (עיתון, תאריך, עמוד) לכל טענה. האתר חי: "
                        "geopolitics.meirshemesh.com.",
                    ),
                    (
                        "p",
                        "שלב הפקת ההשוואה עצמו עבר שדרוג משמעותי בדרך: גישה של קריאה בודדת "
                        "שמנסה לכתוב את כל השוואות היום בבת אחת התבררה כלא-יציבה ככל שמספר "
                        "המקורות גדל - עד כדי כישלון גורף בקנה מידה גדול. הפתרון: פיצול "
                        "לשני שלבים (קיבוץ לנושאים, ואז כתיבת השוואה לכל נושא בנפרד, "
                        "במקביל), עם שיתוף-הקשר בין הקריאות שגם הוזיל את העלות משמעותית "
                        "ביחס לגישה הישנה.",
                    ),
                ],
            },
            {
                "heading": "מגבלות ידועות",
                "blocks": [
                    (
                        "p",
                        "כמה נקודות ששווה שקורא ביקורתי יכיר: המקורות כולם עיתונות-איכות "
                        "מערבית (אנגלית וגרמנית) - לא מדגם מייצג של “העולם”, ולא כולל "
                        "סוכנויות חדשות או שפות נוספות. נפח פרסום אינו חשיבות - עיתון "
                        "שמפרסם הרבה טורי דעה ביום נתון עלול להיראות דומיננטי בדוח בלי שזה "
                        "משקף חשיבות גאופוליטית אמיתית; קיים מנגנון שממיין נושאים לפי "
                        "רוחב-מקורות ושפות, אך זו הקלה חלקית, לא פתרון מלא. אין שכבת "
                        "אימות עובדתי - הטקסט מסכם את מה שכל מקור טוען, לא בודק אם זה נכון; "
                        "מספרים וציטוטים משקפים את המקור, לא אומתו באופן עצמאי. כל דוח "
                        "נכתב מחדש כיחידה עצמאית - אין עדיין זיכרון בין ימים, כך שמעקב אחרי "
                        "איך נושא מתפתח דורש קריאה ידנית של כמה דוחות.",
                    ),
                ],
            },
            {
                "heading": "מבט קדימה",
                "blocks": [
                    (
                        "p",
                        "שלוש שאלות פתוחות מנחות את השלב הבא: מגמות - איך הופכים ארכיון "
                        "שכבר מצטבר לחומר גלם לזיהוי דפוסים לאורך זמן, לא רק תמונת-יום; "
                        "חוויית שימוש - נראות, ניווט ובהירות לקורא שאינו מכיר את הפרויקט; "
                        "וקהל - האם להרחיב מעבר לחוקרים ואנשי מדיניות, למשל לגרסה נגישה "
                        "לבני נוער.",
                    ),
                ],
            },
        ],
    },
    "en": {
        "doc_meta": "Background Document · September 2026",
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
                        "coding tools. Along the way, one insight stood out: the simple "
                        "model of \"human requests, machine executes\" isn't accurate. "
                        "The project has three partners, each with a distinct role - a "
                        "planning tool that thinks through a problem before a single line "
                        "of code is written, and an agent that writes and runs the code "
                        "and reports back - overseen by the human operator, who holds the "
                        "vision and makes the decisions: directing, synchronizing between "
                        "the partners, and assigning them tasks according to the plan he "
                        "sets.",
                    ),
                    (
                        "p",
                        "The methodology in practice: building module by module, with "
                        "human visual review before anything goes live, and a generic "
                        "safety net at the code level whenever a recurring failure "
                        "surfaces - not a one-off patch for each individual case.",
                    ),
                ],
            },
            {
                "heading": "The sources: from four to ten",
                "blocks": [
                    (
                        "p",
                        "The project began with four sources - two politically balanced "
                        "pairs, one per language: The Guardian versus The Daily Telegraph "
                        "in English, Süddeutsche Zeitung versus Die Welt in German.",
                    ),
                    (
                        "p",
                        "After a few stable days, a clear gap emerged: the American arena "
                        "wasn't represented at all. The expansion that followed didn't "
                        "settle for one more pair - four American newspapers were chosen "
                        "deliberately to span a wider political range within that arena "
                        "itself (The Washington Post, The Wall Street "
                        "Journal, Los Angeles Times, USA Today), joined by two weeklies "
                        "(The Economist, Der Spiegel) that bring depth rather than "
                        "another daily angle.",
                    ),
                    (
                        "p",
                        "Today the system follows a diverse set of sources across two "
                        "languages, with a wide political range within each of the arenas "
                        "it covers.",
                    ),
                ],
            },
            {
                "heading": "The framework: three axes of perception",
                "blocks": [
                    (
                        "p",
                        "Geopolitics combines spatial, temporal, and textual perception. "
                        "The homepage is built around three equal-standing \"lenses\" on "
                        "the same data - an interactive geographic map (including "
                        "actively-tracked conflict zones: the Israeli-Palestinian "
                        "conflict, Iran-West, Russia-Ukraine), a time axis, and a textual "
                        "entry point - along with the ability to browse reports by "
                        "topic, region, or date range, not just a single day.",
                    ),
                ],
            },
            {
                "heading": "What exists today",
                "blocks": [
                    (
                        "p",
                        "Five sequential stages - collecting, extracting text, analyzing "
                        "and classifying via the Claude API, generating comparisons, and "
                        "publishing - all active on real data. Every daily report: two "
                        "full languages, two formats, cross-source comparison with "
                        "precise citations (newspaper, date, page) for every claim. The "
                        "site is live: geopolitics.meirshemesh.com.",
                    ),
                    (
                        "p",
                        "The comparison-generation stage itself underwent a significant "
                        "upgrade along the way: a single-call approach trying to write "
                        "all of a day's comparisons at once proved unstable as the number "
                        "of sources grew - to the point of outright failure at scale. The "
                        "fix: splitting into two stages (grouping into topics, then "
                        "writing each topic's comparison separately, in parallel), with "
                        "shared context between the calls that also cut the cost "
                        "significantly compared to the old approach.",
                    ),
                ],
            },
            {
                "heading": "Known limitations",
                "blocks": [
                    (
                        "p",
                        "A few points worth a critical reader knowing: all sources are "
                        "Western quality press (English and German) - not a "
                        "representative sample of \"the world,\" and doesn't include "
                        "wire services or additional languages. Publishing volume isn't "
                        "importance - an outlet that runs many opinion pieces on a given "
                        "day can look dominant in a report without that reflecting real "
                        "geopolitical weight; a mechanism sorts topics by source- and "
                        "language-breadth, but that's a partial mitigation, not a full "
                        "solution. There's no fact-verification layer - the text "
                        "summarizes what each source claims, not whether it's true; "
                        "figures and quotes reflect the source, not independent "
                        "verification. Each report is written from scratch as a "
                        "standalone unit - there's no memory between days yet, so "
                        "tracking how a topic evolves still requires manually reading "
                        "several reports.",
                    ),
                ],
            },
            {
                "heading": "Looking ahead",
                "blocks": [
                    (
                        "p",
                        "Three open questions guide the next stage: trends - how to turn "
                        "an accumulating archive into raw material for identifying "
                        "patterns over time, not just a daily snapshot; usability - "
                        "visual clarity and navigation for a reader unfamiliar with the "
                        "project; and audience - whether to expand beyond researchers "
                        "and policy professionals, for example to an accessible version "
                        "for teenagers.",
                    ),
                ],
            },
        ],
    },
}
