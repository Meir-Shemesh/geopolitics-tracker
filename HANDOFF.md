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

## עבודה שטרם הושלמה

- לא נכתב שום קוד לוגי בשום שלב מה-Pipeline (Ingestion / Extraction / Analysis / Reporting / Publishing).
- לא הוגדרה סכמת ה-SQLite.
- לא הוגדרו טסטים תחת `tests/`.
- לא בוצע `git add` / `git commit` לשינויי השלד - כל הקבצים עדיין untracked/modified ב-working directory.
- טרם הוגדרה תשתית GitHub Pages (אתר, ניווט, מעבר שפה).
- טרם נבדקה התקנת weasyprint וגופן עברי בפועל.

## בעיות ידועות

- אין עדיין - הפרויקט בשלב מוקדם מדי לזיהוי תקלות בפועל.

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
