# Project Handoff

## מצב הפרויקט הנוכחי

הפרויקט בשלב שלד (scaffolding) בלבד. הוגדרו מטרת הפרויקט, ארכיטקטורת ה-Pipeline, מבנה התיקיות, ותלויות עתידיות ב-CLAUDE.md. טרם נכתב קוד לוגי כלשהו. כל השינויים עדיין untracked/modified ב-git, טרם בוצע commit.

## מה הושלם

- נכתב `CLAUDE.md` בשורש הפרויקט, במבנה תמציתי (מטרה, מבנה קבצים, כללי עבודה, מגבלות, פקודות, החלטות ארכיטקטוניות).
- נוצר מבנה תיקיות מלא: `src/{ingestion,extraction,analysis,reporting,publishing}/`, `data/{raw,processed}/`, `reports/{he,en}/`, `tests/` (כל תיקייה ריקה עם `.gitkeep`).
- נוצר `requirements.txt` עם רשימת ספריות ראשונית (telethon, pdfplumber, anthropic, weasyprint) - טרם הותקנו.
- נוצר `.gitignore` (venv, `__pycache__`, `.env`, `data/raw/*` למעט `.gitkeep`).
- עודכן `README.md` לתיאור עברי קצר עם אזכור התמיכה הדו-לשונית.
- הותקן skill `resume-project` מקומית תחת `.claude/skills/resume-project/SKILL.md`, מופעל ידנית באמצעות `/resume-project` (`disable-model-invocation: true`). קיים גם עותק זהה גלובלי ב-`C:\Users\meir\.claude\skills\resume-project`, לשימוש בפרויקטים אחרים.
- הותקן skill `handoff` מקומית תחת `.claude/skills/handoff/SKILL.md`, לסגירת סשנים ועדכון CLAUDE.md/HANDOFF.md.
- נוצר `HANDOFF.md` (קובץ זה) כיומן מסירה בין סשנים.
- ב-CLAUDE.md נוסף כלל עבודה קבוע: בתחילת סשן חדש יש להפעיל `/resume-project`.

## קבצים מרכזיים

- `CLAUDE.md` - מסמך ההנחיות הקבוע לפרויקט: מטרה, ארכיטקטורה, מוסכמות עבודה.
- `HANDOFF.md` - קובץ זה, יומן מסירה בין סשנים.
- `README.md` - תיאור קצר של הפרויקט לגולשים ב-GitHub.
- `requirements.txt` - רשימת תלויות Python עתידיות.
- `.gitignore` - חריגים ל-git (venv, סודות, PDF-ים גולמיים).
- `src/*/` - חמש תת-תיקיות ריקות, אחת לכל שלב ב-Pipeline.
- `data/raw/`, `data/processed/` - קלט גולמי ונתונים מעובדים.
- `reports/he/`, `reports/en/` - פלט הדוחות לפי שפה.
- `.claude/skills/resume-project/SKILL.md` - skill פרויקטלי להפעלת `/resume-project`.
- `.claude/skills/handoff/SKILL.md` - skill פרויקטלי להפעלת `/handoff`.

## החלטות שהתקבלו

- דו-לשוניות (עברית + אנגלית) היא דרישת ליבה שחייבת להיות מובנית בשלב ה-Reporting מההתחלה, לא תוספת מאוחרת.
- PDF בעברית ידרוש CSS עם `direction: rtl` וגופן תומך עברית ב-WeasyPrint - יש לקחת זאת בחשבון בכל עבודה עתידית על `src/reporting/`.
- מקורות ל-MVP: The Guardian, The Daily Telegraph (אנגלית); Süddeutsche Zeitung, Die Welt (גרמנית).
- מוסכמות טכניות קבועות: Python 3, SQLite, ניהול תלויות באמצעות `venv`.
- תקשורת עם המשתמש בעברית; קוד, שמות משתנים/פונקציות והערות בקוד באנגלית בלבד.
- שחזור מצב בתחילת סשן ייעשה באמצעות `/resume-project` (סקיל ידני, קיים גם גלובלית וגם פרויקטלית - שני העותקים זהים בתוכן).
- **לזכור בעיצוב ה-prompt של שלב ה-Analysis:** לכלול הנחיה מפורשת ל-Claude API שהטקסט הגולמי שהוא מקבל עשוי להכיל קטעים/פסקאות מכתבות שונות בסדר לא-רציף (בגלל פריסת מגזין/גריד ב-PDF, לא טורים פשוטים ברצף אחיד) - כדי שיידע לזהות ולהפריד נכון בין כתבות שונות באותו עמוד, במקום להניח זרימת טקסט רציפה. הסיבה מפורטת ב"בעיות ידועות" למטה.

## עבודה שטרם הושלמה

- לא נכתב שום קוד לוגי בשום שלב מה-Pipeline (Ingestion / Extraction / Analysis / Reporting / Publishing).
- לא הוגדרה סכמת ה-SQLite.
- לא הוגדרו טסטים תחת `tests/`.
- לא בוצע `git add` / `git commit` לשינויי השלד - כל הקבצים עדיין untracked/modified ב-working directory.
- טרם הוגדרה תשתית GitHub Pages (אתר, ניווט, מעבר שפה).
- טרם נבדקה התקנת weasyprint וגופן עברי בפועל.

## בעיות ידועות

- **מגבלה ידועה, נבדקה אמפירית (2026-08-24):** חילוץ הטקסט ב-`src/extraction/extract.py` (pdfplumber) לא שומר על סדר קריאה נכון בעמודים בפריסת מגזין/גריד (למשל עמוד שער, "News in brief") - טקסט מתיבות/כתבות שונות מתערבב זו בזו. נבדק בפועל גם עם `extract_text(layout=True)` על מספר עמודים אמיתיים מ-`data/raw/demagazinesharing/The Guardian UK_2208.pdf` - לא פתר את הבעיה, כי אין טורים ברוחב אחיד לזהות (הבדיקה כללה histogram של מיקומי מילים לרוחב העמוד, שהראה פיזור רציף ולא פערים קבועים בין טורים). תיקון אמיתי ידרוש זיהוי גיאומטרי של גבולות תיבות (rects/lines בקובץ ה-PDF, לא רק מיקומי מילים) - הוחלט במכוון לא להשקיע בזה כרגע, בהמתנה לבדוק אמפירית אם Claude API בשלב ה-Analysis מסתדר סביר עם טקסט מעורבב כזה. אם יתברר שכן פוגע באיכות הניתוח - כאן הנקודה לחזור אליה.

- **כפילות טיזר/כתבה-מלאה בין עמודים, נצפה אמפירית (2026-08-24):** בבדיקת `src/analysis/analyze.py` על קובץ אמיתי (`Süddeutsche Zeitung - 20 August 2026.pdf`, file_id=17) נמצא אותו אירוע ממש (גינוי מרץ את בן-גביר) מתועד כשני מאמרים נפרדים בטבלת `articles` - אחד מעמוד השער (טיזר קצר) ואחד מעמוד פנימי (הכתבה המלאה). זה **כנראה לא הזיית מודל** אלא שיקוף נאמן של מבנה עיתון טיפוסי (שער מפנה לכתבה בפנים). הוחלט במכוון **לא** לתקן את זה ברמת עמוד בודד ב-Analysis - דה-דופליקציה (זיהוי מאמרים שמתארים את אותו אירוע/כתבה, על בסיס דמיון כותרות/תוכן בין כל המאמרים שכבר זוהו יחד) צריכה להתבצע בשלב ה-Reporting, לא כאן.

- **False positive בשלב הסינון (Haiku) על עמודי נקרולוגים/טורי נוסטלגיה היסטורית, נצפה אמפירית (2026-08-25):** עמודים כמו "Court & Social" ב-Telegraph, הכוללים טור "ONE HUNDRED YEARS AGO" (ציטוטים מהעיתון עצמו לפני 100 שנה), סומנו לעיתים `is_relevant=True` בטעות - אזכורי מדינות/אירועים דיפלומטיים היסטוריים (למשל "SPAIN'S DEMAND" מ-1926) יכולים להיראות כמו תוכן גאופוליטי עדכני לסינון הרחב, אף שמדובר בנוסטלגיה היסטורית בלבד. **תופעת לוואי:** כשעמודים כאלה הגיעו לשלב ב' (`analyze.py`), Sonnet סירב לעבד אותם (`stop_reason=refusal`, `category=general_harms`) - ככל הנראה בגלל פרטים אישיים אמיתיים של נפטרים פרטיים בעמוד (שמות, גילאים, פרטי לוויה). זהו **סירוב לגיטימי של המודל, לא באג** שיש לעקוף. שני המקרים הידועים (file_id=2 page=20, file_id=14 page=24) תוקנו ידנית ב-`page_screening` ל-`is_relevant=0`. **לשקול בכיול הפרומפט העתידי:** להוסיף ל-`SYSTEM_PROMPT` ב-`src/analysis/screen.py` הנחיה מפורשת להבחין בין תוכן היסטורי/נוסטלגי (גם אם מזכיר מדינות/דיפלומטיה) לבין תוכן גאופוליטי עדכני, ולסמן את הראשון כלא-רלוונטי.

## הצעד הבא המומלץ

להתחיל בכתיבת שלב ה-Ingestion (`src/ingestion/`): חיבור ל-Telegram (telethon) ומשיכת PDF-ים לתוך `data/raw/`, כולל הגדרת סכמת SQLite ראשונית למעקב אחר קבצים שכבר נמשכו.

## סשן אחרון

**תאריך:** 2026-08-24

**תיאור:** אתחול מלא של הפרויקט - יצירת שלד (scaffolding), CLAUDE.md, README.md, requirements.txt, .gitignore, מבנה תיקיות מלא; התקנת skill `resume-project` (מקומי + גלובלי); יצירת HANDOFF.md; וסגירת סשן עם עדכון סופי לשני המסמכים.

**קבצים ששונו:**
- `CLAUDE.md` (נוצר, נערך מחדש למבנה תמציתי, ולבסוף נוסף כלל עבודה על `/resume-project`)
- `README.md` (עודכן)
- `.gitignore` (נוצר)
- `requirements.txt` (נוצר)
- `src/{ingestion,extraction,analysis,reporting,publishing}/.gitkeep` (נוצרו)
- `data/{raw,processed}/.gitkeep` (נוצרו)
- `reports/{he,en}/.gitkeep` (נוצרו)
- `tests/.gitkeep` (נוצר)
- `.claude/skills/resume-project/SKILL.md` (נוצר בפרויקט זה)
- `.claude/skills/handoff/SKILL.md` (נוצר בפרויקט זה)
- `HANDOFF.md` (נוצר, ואז עודכן בסגירת הסשן - קובץ זה)
