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
                "heading": "גילוי נאות: שימוש בבינה מלאכותית",
                "blocks": [
                    (
                        "p",
                        "תוכן ההשוואה בכל דוח באתר זה מופק באמצעות מודל שפה (Claude API של "
                        "Anthropic) - לא נכתב בידי עיתונאי אנושי. קיימת בקרה אנושית לאורך "
                        "התהליך: בדיקה ויזואלית לפני כל שינוי שיוצא לאוויר, ורשת-ביטחון ברמת-"
                        "קוד לכשלים חוזרים (ראו לעיל, “שיטת העבודה”). למגבלות הנובעות מהשימוש "
                        "בבינה מלאכותית - ראו גם: “מגבלות ידועות” למטה.",
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
                        "יומי: שלוש שפות מלאות, שני פורמטים, השוואה בין-מקורית עם הפניות "
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
                "heading": "השפה השלישית: גרמנית",
                "blocks": [
                    (
                        "p",
                        "האתר פורסם תחילה בעברית ובאנגלית בלבד. ההרחבה לגרמנית נעשתה בשני "
                        "שלבים: ראשית, כל דוח קיים בארכיון נכתב מחדש לגרמנית - לא תורגם "
                        "מילולית - תוך שימוש בטרמינולוגיה ובמשלב שנקבעו במסמך הזה עצמו, כדי "
                        "לשמור על עקביות לאורך הארכיון כולו. מכאן ואילך, כל דוח חדש נכתב "
                        "בגרמנית כטקסט מקורי במקביל לעברית ולאנגלית, באותו שלב הפקה ומאותם "
                        "מאמרי מקור - לא כתרגום שמתווסף אחרי העובדה.",
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
                "heading": "Disclosure: Use of Artificial Intelligence",
                "blocks": [
                    (
                        "p",
                        "The comparison content in every report on this site is generated "
                        "by a language model (Anthropic's Claude API) - not written by a "
                        "human journalist. Human oversight is built into the process "
                        "throughout: visual review before any change goes live, and a "
                        "code-level safety net for recurring failures (see \"Working "
                        "method\" above). For the limitations that come with this - see "
                        "also: \"Known limitations\" below.",
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
                        "publishing - all active on real data. Every daily report: three "
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
                "heading": "The third language: German",
                "blocks": [
                    (
                        "p",
                        "The site was originally published only in Hebrew and English. "
                        "The expansion to German happened in two steps: first, every "
                        "existing report in the archive was rewritten in German - not "
                        "translated literally - using the terminology and register set in "
                        "this very page, to keep the whole archive consistent. From here "
                        "on, every new report is written in German as original text "
                        "alongside Hebrew and English, in the same generation step and "
                        "from the same source articles - not as a translation added after "
                        "the fact.",
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
    "de": {
        "doc_meta": "Hintergrunddokument · September 2026",
        "identity_name": "Meir Shemesh",
        "identity_role": "Technologieberatung und -management",
        "title": "GEOPOLITICS-TRACKER",
        "subtitle": (
            "Wie die Weltpresse ein Ereignis mit unterschiedlichen Augen sieht - und was der "
            "Entstehungsprozess selbst über die Zusammenarbeit von Mensch und künstlicher "
            "Intelligenz lehrt"
        ),
        "sections": [
            {
                "heading": None,
                "blocks": [
                    (
                        "p",
                        "Jeden Tag veröffentlichen Dutzende führende Zeitungen Hunderte "
                        "Meinungsbeiträge zu ein und denselben geopolitischen Ereignissen. "
                        "Niemand kann sie alle lesen - und jeder von uns liest in der Regel "
                        "nur eine oder zwei Perspektiven, meist die bereits vertrauten, und "
                        "verpasst dabei das vollständige Gespräch, das zwischen den "
                        "verschiedenen Quellen stattfindet. geopolitics-tracker ist der "
                        "Versuch, dieser Lektüre ein Werkzeug an die Hand zu geben: ein "
                        "System, das führende Zeitungen beobachtet, ihre geopolitischen "
                        "Meinungsbeiträge identifiziert und daraus ein tägliches Bild dessen "
                        "erstellt, was die Aufmerksamkeit der Welt auf sich gezogen hat - und "
                        "wie jede Quelle es einzuordnen wählte.",
                    ),
                ],
            },
            {
                "heading": "Arbeitsmethode: Zusammenarbeit zwischen Mensch und Maschine",
                "blocks": [
                    (
                        "p",
                        "Über sein praktisches Ziel hinaus hat das Projekt noch eine weitere "
                        "Funktion: Es ist ein Ort, um in der Praxis zu lernen, wie man mit "
                        "fortgeschrittenen KI-Programmierwerkzeugen ein komplexes System "
                        "aufbaut. Dabei hat sich eine zentrale Erkenntnis herauskristallisiert: "
                        "Das einfache Modell „Mensch fordert an, Maschine führt aus“ trifft "
                        "die Realität nicht. Das Projekt kennt drei Partner mit jeweils klar "
                        "unterschiedlicher Rolle - ein Planungswerkzeug, das ein Problem "
                        "durchdenkt, bevor auch nur eine Codezeile geschrieben wird, und ein "
                        "Agent, der den Code tatsächlich schreibt, ausführt und darüber "
                        "berichtet - beide unter der Aufsicht des menschlichen Betreibers, "
                        "der die Vision trägt und die Entscheidungen trifft: Er gibt die "
                        "Richtung vor, synchronisiert zwischen den Partnern und weist ihnen "
                        "Aufgaben gemäß dem von ihm festgelegten Plan zu.",
                    ),
                    (
                        "p",
                        "Die Methodik in der Praxis: Modul für Modul aufgebaut, mit "
                        "menschlicher visueller Prüfung, bevor etwas live geht, und einem "
                        "generischen Sicherheitsnetz auf Code-Ebene, sobald sich ein "
                        "wiederkehrender Fehler zeigt - statt einer punktuellen Korrektur "
                        "für jeden Einzelfall.",
                    ),
                ],
            },
            {
                "heading": "Offenlegung: Einsatz von Künstlicher Intelligenz",
                "blocks": [
                    (
                        "p",
                        "Der Vergleichstext in jedem Bericht auf dieser Website wird von "
                        "einem Sprachmodell erzeugt (Claude API von Anthropic) - nicht von "
                        "einem menschlichen Journalisten verfasst. Menschliche Aufsicht ist "
                        "durchgehend in den Prozess eingebaut: visuelle Prüfung vor jeder "
                        "Änderung, die live geht, und ein Sicherheitsnetz auf Code-Ebene für "
                        "wiederkehrende Fehler (siehe oben, „Arbeitsmethode“). Zu den damit "
                        "verbundenen Einschränkungen siehe auch unten: „Bekannte "
                        "Einschränkungen“.",
                    ),
                ],
            },
            {
                "heading": "Die Quellen: von vier auf zehn",
                "blocks": [
                    (
                        "p",
                        "Das Projekt begann mit vier Quellen - zwei politisch ausgewogenen "
                        "Paaren, eines pro Sprache: The Guardian gegen The Daily Telegraph "
                        "im Englischen, Süddeutsche Zeitung gegen Die Welt im Deutschen.",
                    ),
                    (
                        "p",
                        "Nach einigen stabilen Tagen zeigte sich eine deutliche Lücke: Die "
                        "amerikanische Arena war überhaupt nicht vertreten. Die daraufhin "
                        "folgende Erweiterung begnügte sich nicht mit einem weiteren Paar - "
                        "vier amerikanische Zeitungen wurden bewusst ausgewählt, um "
                        "innerhalb dieser Arena selbst ein breiteres politisches Spektrum "
                        "abzudecken (The Washington Post, The Wall Street Journal, Los "
                        "Angeles Times, USA Today), ergänzt durch zwei Wochenzeitschriften "
                        "(The Economist, Der Spiegel), die eher Tiefe als einen weiteren "
                        "Tagesblickwinkel beitragen.",
                    ),
                    (
                        "p",
                        "Heute verfolgt das System ein vielfältiges Spektrum an Quellen in "
                        "zwei Sprachen, mit einer breiten politischen Bandbreite innerhalb "
                        "jeder der abgedeckten Arenen.",
                    ),
                ],
            },
            {
                "heading": "Der Rahmen: drei Wahrnehmungsachsen",
                "blocks": [
                    (
                        "p",
                        "Geopolitik verbindet räumliche, zeitliche und textuelle "
                        "Wahrnehmung. Die Startseite ist um drei gleichrangige „Linsen“ auf "
                        "dieselben Daten herum aufgebaut - eine interaktive geografische "
                        "Karte (einschließlich aktiv verfolgter Konfliktzonen: des "
                        "israelisch-palästinensischen Konflikts, Iran-Westen, "
                        "Russland-Ukraine), eine Zeitachse und einen textuellen "
                        "Einstiegspunkt - dazu die Möglichkeit, Berichte nach Thema, Region "
                        "oder Zeitraum zu durchsuchen, nicht nur nach einem einzelnen Tag.",
                    ),
                ],
            },
            {
                "heading": "Was heute existiert",
                "blocks": [
                    (
                        "p",
                        "Fünf aufeinanderfolgende Stufen - Sammeln, Textextraktion, Analyse "
                        "und Klassifizierung mittels der Claude API, Erstellung der "
                        "Vergleiche und Veröffentlichung - alle aktiv auf realen Daten. Jeder "
                        "Tagesbericht: drei vollständige Sprachen, zwei Formate, "
                        "quellenübergreifender Vergleich mit präzisen Belegen (Zeitung, "
                        "Datum, Seite) zu jeder Aussage. Die Website ist live: "
                        "geopolitics.meirshemesh.com.",
                    ),
                    (
                        "p",
                        "Die Stufe der Vergleichserstellung selbst durchlief dabei ein "
                        "bedeutendes Upgrade: Ein Ansatz mit einem einzigen Aufruf, der "
                        "versuchte, alle Vergleiche eines Tages auf einmal zu schreiben, "
                        "erwies sich mit wachsender Quellenzahl als instabil - bis hin zum "
                        "vollständigen Scheitern im großen Maßstab. Die Lösung: eine "
                        "Aufteilung in zwei Stufen (Gruppierung nach Themen, danach "
                        "getrennte, parallele Erstellung des Vergleichs für jedes Thema), "
                        "mit gemeinsam genutztem Kontext zwischen den Aufrufen, was zugleich "
                        "die Kosten gegenüber dem alten Ansatz deutlich senkte.",
                    ),
                ],
            },
            {
                "heading": "Die dritte Sprache: Deutsch",
                "blocks": [
                    (
                        "p",
                        "Die Website wurde ursprünglich nur auf Hebräisch und Englisch "
                        "veröffentlicht. Die Erweiterung um Deutsch erfolgte in zwei "
                        "Schritten: Zunächst wurde jeder bestehende Bericht im Archiv neu "
                        "auf Deutsch verfasst - nicht wörtlich übersetzt - unter "
                        "Verwendung der Terminologie und des Sprachregisters, die auf "
                        "genau dieser Seite festgelegt wurden, um das gesamte Archiv "
                        "konsistent zu halten. Von nun an wird jeder neue Bericht als "
                        "eigenständiger deutscher Originaltext parallel zu Hebräisch und "
                        "Englisch erstellt, im selben Erzeugungsschritt und aus denselben "
                        "Quellartikeln - nicht als nachträglich hinzugefügte Übersetzung.",
                    ),
                ],
            },
            {
                "heading": "Bekannte Einschränkungen",
                "blocks": [
                    (
                        "p",
                        "Einige Punkte, die ein kritischer Leser kennen sollte: Sämtliche "
                        "Quellen gehören zur westlichen Qualitätspresse (Englisch und "
                        "Deutsch) - kein repräsentativer Querschnitt „der Welt“, und "
                        "Nachrichtenagenturen oder weitere Sprachen sind nicht enthalten. "
                        "Publikationsvolumen bedeutet nicht Wichtigkeit - ein Blatt, das an "
                        "einem bestimmten Tag viele Meinungsbeiträge veröffentlicht, kann in "
                        "einem Bericht dominant erscheinen, ohne dass dies tatsächliches "
                        "geopolitisches Gewicht widerspiegelt; ein Mechanismus sortiert "
                        "Themen nach Quellen- und Sprachbreite, doch das ist nur eine "
                        "teilweise Abhilfe, keine vollständige Lösung. Es gibt keine "
                        "Faktenprüfungsebene - der Text fasst zusammen, was jede Quelle "
                        "behauptet, nicht ob es zutrifft; Zahlen und Zitate spiegeln die "
                        "Quelle wider, sind aber nicht unabhängig verifiziert. Jeder Bericht "
                        "wird als eigenständige Einheit neu verfasst - es gibt noch kein "
                        "Gedächtnis zwischen den Tagen, sodass die Verfolgung, wie sich ein "
                        "Thema entwickelt, weiterhin das manuelle Lesen mehrerer Berichte "
                        "erfordert.",
                    ),
                ],
            },
            {
                "heading": "Ausblick",
                "blocks": [
                    (
                        "p",
                        "Drei offene Fragen leiten die nächste Phase: Trends - wie sich ein "
                        "wachsendes Archiv in Rohmaterial zur Erkennung von Mustern über die "
                        "Zeit verwandeln lässt, nicht nur in eine Tagesaufnahme; "
                        "Nutzererfahrung - visuelle Klarheit und Navigation für Leser, die "
                        "das Projekt noch nicht kennen; und Zielgruppe - ob über Forschende "
                        "und politische Fachleute hinaus erweitert werden soll, etwa zu "
                        "einer zugänglichen Version für Jugendliche.",
                    ),
                ],
            },
        ],
    },
}
