# Project Handoff

## מצב הפרויקט הנוכחי

ה-Pipeline רץ מקצה לקצה בפעם הראשונה על נתונים אמיתיים: Ingestion → Extraction → Analysis (שני שלבים) עובדים ומתועדים. 17 קבצי PDF נמשכו מטלגרם (Guardian, Daily Telegraph, Süddeutsche Zeitung, Die Welt), 795 עמודים חולצו, כל ה-795 עברו סינון (Stage 1), 308 סומנו רלוונטיים (39%), ונותחו לעומק (Stage 2) ל-308 מאמרים בטבלת `articles`. `src/reporting/` ו-`src/publishing/` עדיין לא מומשו. venv מוגדר ומותקן (`telethon`, `python-dotenv`, `pdfplumber`, `anthropic`, `weasyprint`). בנוסף, לאחר סיום ה-Pipeline הורחבו סקילי ההמשכיות עצמם (`resume-project`/`handoff`) - ראו "מה הושלם". קוד ה-Pipeline מ-commit `7bbde2c`; שינויי הסקילים ומסמכי ההמשכיות הנוכחיים ממתינים ל-commit+push בסיום ריצת `/handoff` הזו.

## מה הושלם

- **`src/common/db.py`** - מודול DB משותף לכל השלבים. סכמה מוצהרת פעם אחת ב-`TABLE_COLUMNS`/`TABLE_CONSTRAINTS`; `init_db()` יוצר טבלאות חסרות **וגם** מוסיף עמודות חסרות לטבלה קיימת אוטומטית (נבדק בפועל: DB ישן + עמודות חדשות בקוד → מיגרציה תקינה בלי איבוד נתונים).
- **`src/ingestion/fetch.py`** - מתחבר לערוץ טלגרם `demagazinesharing`, מוריד רק PDF-ים שמזוהים כאחד מ-4 עיתוני ה-MVP (`guess_newspaper`, כולל טיפול מיוחד שלא לתפוס "Welt am Sonntag" בטעות תחת "Die Welt"), עוקב אחרי קבצים שכבר ירדו ב-`downloaded_files`.
- **`src/extraction/extract.py`** - מחלץ טקסט גולמי לעמוד עם pdfplumber ל-`extracted_pages` + עותק `.txt` תחת `data/processed/extracted/`. כשל בפתיחת קובץ שלם = `extraction_status='failed'`; כשל בעמוד בודד בתוך קובץ שנפתח בהצלחה נרשם כטקסט `[EXTRACTION FAILED]` לאותו עמוד בלבד, לא מפיל את הקובץ.
- **`src/analysis/screen.py`** (שלב א', Claude Haiku) - סינון רחב מכוון: בספק מסמן רלוונטי. מדלג על עמודים ריקים (בלי לבזבז קריאת API) אחרי שהתגלה שזה גורם ל-400 מה-API.
- **`src/analysis/analyze.py`** (שלב ב', Claude Sonnet + adaptive thinking) - מזהה מאמרים בעמודים שסומנו רלוונטיים, מחלץ כותרת/מחבר/נושא/עמדה/ציטוט. הפרומפט מכיל הנחיה מפורשת נגד "דליפת" טקסט לשדה `author` (להשאיר ריק בספק), ונגד כלילת תוכן פנים-בלבד ללא זווית בינלאומית.
- הרצה מלאה על כל 17 הקבצים - ראו טבלת תוצאות למטה.
- `.env`/`.env.example` (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `ANTHROPIC_API_KEY`) - `.env` מאומת כלא-נכנס ל-git.
- תוקן באג בשם ה-frontmatter של סקיל `resume-project` (היה `name: Resume Project` עם רווח, לא תואם לשם התיקייה - מנע הפעלה כ-`/resume-project`; תוקן ל-`resume-project`).
- **הורחבו סקילי ההמשכיות:** `resume-project` מבצע כעת `git pull` כצעד ראשון (עוצר אם יש קונפליקט/שינויים לא-committed) וקורא גם את `PROJECT_LOG.md` אם קיים. `handoff` מעדכן כעת גם `PROJECT_LOG.md` (מותנה - רק כשיש החלטה ארכיטקטונית/ממצא מדיד/שינוי אסטרטגי ב-action items), ובסיומו מבצע רצף git חצי-אוטומטי: `git add .` אוטומטי, בדיקת קבצים חשודים (PDF/session/.env), הצעת הודעת commit, ו-commit+push רק אחרי אישור מפורש.

**תוצאות ריצה מלאה (795 עמודים, 4 עיתונים):**

| עיתון | עמודים | רלוונטים | % | מאמרים |
|---|---|---|---|---|
| Süddeutsche Zeitung | 159 | 69 | 43% | 99 |
| Die Welt | 48 | 32 | 67% | 46 |
| Daily Telegraph | 152 | 76 | 50% | 83 |
| Guardian | 436 | 131 | 30% | 80 |
| **סה"כ** | **795** | **308** | **39%** | **308** |

## קבצים שנוצרו או שונו

- `src/common/__init__.py`, `src/common/db.py` (חדשים - db.py הועבר מ-`src/ingestion/`)
- `src/ingestion/__init__.py`, `src/ingestion/fetch.py` (import עודכן אחרי ה-refactor)
- `src/extraction/__init__.py`, `src/extraction/extract.py`
- `src/analysis/__init__.py`, `src/analysis/screen.py`, `src/analysis/analyze.py`
- `.env`, `.env.example`, `.gitignore` (תוספות: `*.session`, `data/processed/tracker.db`, `data/processed/extracted/`), `requirements.txt` (נוסף `python-dotenv`)
- `.claude/skills/resume-project/SKILL.md` (תיקון `name:` ב-frontmatter; בהמשך גם git pull + קריאת PROJECT_LOG.md)
- `.claude/skills/handoff/SKILL.md` (עדכון PROJECT_LOG.md מותנה + רצף git חצי-אוטומטי)
- `CLAUDE.md`, `HANDOFF.md`, `PROJECT_LOG.md` (עדכון סגירת סשן)
- `venv/` (נוצר, לא נכנס ל-git); `data/raw/demagazinesharing/*.pdf` (17 קבצים, לא נכנס ל-git); `data/processed/tracker.db` ו-`data/processed/extracted/*.txt` (לא נכנס ל-git)

## החלטות שהתקבלו

- דו-לשוניות (עברית + אנגלית) היא דרישת ליבה מובנית בשלב ה-Reporting מההתחלה, לא תוספת מאוחרת.
- PDF בעברית ידרוש CSS עם `direction: rtl` וגופן תומך עברית ב-WeasyPrint.
- מקורות ל-MVP: Guardian, Daily Telegraph (אנגלית); Süddeutsche Zeitung, Die Welt (גרמנית).
- מוסכמות טכניות קבועות: Python 3, SQLite, `venv`. תקשורת בעברית; קוד/משתנים/הערות באנגלית.
- שחזור מצב בתחילת סשן באמצעות `/resume-project`.
- **Analysis כשני שלבי-LLM עצמאיים** (Haiku סינון רחב → Sonnet ניתוח מעמיק) - כל שלב ניתן להרצה ולבדיקה בנפרד, כדי לאפשר ביקורת איכות לפני המשך. מכוון להיות over-inclusive בשלב א'.
- **`src/common/db.py` כמקור אמת יחיד לסכמה** - שינויי סכמה עתידיים דרך `TABLE_COLUMNS` בלבד, לא `ALTER TABLE` ידני בקבצים אחרים.
- false-positive בסינון מתוקן ידנית ב-`page_screening.is_relevant` (עם עדכון `screening_reasoning` להסבר), לא נמחק ולא מתעלמים ממנו - שומר מסלול ביקורת.
- כפילות טיזר/כתבה-מלאה בין עמודים לא נפתרת ברמת עמוד ב-Analysis - דה-דופליקציה מתוכננת לשלב ה-Reporting (השוואת דמיון בין כל המאמרים שזוהו).
- **המשכיות דו-שכבתית:** HANDOFF.md נשאר מסמך טכני מדויק (מצב קוד); PROJECT_LOG.md חדש הוא יומן נרטיבי ברמה גבוהה (למה החלטנו ככה, ממצאים מדידים, action items) - לא כפילות של אותו תוכן בשני מקומות.
- **סגירת סשן כוללת רצף git חצי-אוטומטי** (`/handoff`): add אוטומטי, אך commit+push רק אחרי אישור מפורש בכל הרצה - לא פרה-אישור גורף.

## עבודה שטרם הושלמה

- `src/reporting/` - לא נכתב כלל (הפקת דוחות PDF+HTML דו-לשוניים מטבלת `articles`, כולל דה-דופליקציה של כפילויות טיזר/כתבה-מלאה).
- `src/publishing/` - לא נכתב כלל (GitHub Pages, ניווט, מעבר שפה).
- `tests/` - עדיין ריק, אין טסטים.
- טרם נבדקה התקנת weasyprint וגופן עברי בפועל (רלוונטי כש-Reporting יתחיל).
- כיול פרומפט `screen.py` נגד false positive על עמודי נוסטלגיה/היסטוריה (ראו "בעיות ידועות") - שינוי מוצע, טרם בוצע.
- אין עדיין אוטומציה/תזמון (cron) להרצת השלבים - כרגע רק סקריפטים חד-פעמיים ידניים, בכוונה, לא נבחן עדיין.
- מאמר גבולי אחד (`file_id=3`, "Weil es sich lohnt", `region_topic: Medienrecht/Boulevardpresse`) עלה כחשוד ל-false positive בבדיקת מדגם אקראית - לא אומת/תוקן ידנית.

## בעיות ידועות

- **מגבלת סדר-קריאה בחילוץ (2026-08-24):** `pdfplumber` לא שומר סדר קריאה נכון בעמודי מגזין/גריד (כתבות מתערבבות). נבדק גם עם `extract_text(layout=True)` - לא פתר, כי אין טורים ברוחב אחיד. תיקון אמיתי דורש זיהוי גיאומטרי (rects/lines) - נדחה בכוונה; שלב ה-Analysis קיבל הנחיה מפורשת להתמודד עם זה במקום.
- **כפילות טיזר/כתבה-מלאה (2026-08-24):** אותו אירוע מתועד כשני מאמרים נפרדים (עמוד שער + עמוד פנימי) - כנראה שיקוף אמיתי של מבנה עיתון, לא הזיה. דה-דופליקציה מיועדת לשלב ה-Reporting, לא Analysis.
- **False positive בסינון על עמודי נקרולוגים/נוסטלגיה היסטורית (2026-08-25):** עמודים כמו "Court & Social" ב-Telegraph עם טור "ONE HUNDRED YEARS AGO" נתפסים לעיתים כרלוונטיים (אזכורי מדינות היסטוריים נשמעים כמו גאופוליטיקה עדכנית). תופעת לוואי: Sonnet מסרב לעבד אותם (`stop_reason=refusal`, `category=general_harms`) - ככל הנראה בגלל פרטים אישיים אמיתיים של נפטרים; סירוב לגיטימי, לא באג. שני המקרים הידועים (`file_id=2 page=20`, `file_id=14 page=24`) תוקנו ידנית ל-`is_relevant=0`. **לשקול:** הנחיה מפורשת ב-`SYSTEM_PROMPT` של `screen.py` להבחין תוכן היסטורי/נוסטלגי מתוכן גאופוליטי עדכני.
- **כשלי API חולפים בהרצות גדולות:** ברצף של מאות קריאות נצפו `Connection error` (קשור כנראה למחשב שנכנס למצב שינה) ו-`Internal server error` בודדים. הטיפול הקיים (עמוד שנכשל נשאר `pending`, לא נכתב חלקית) מאפשר Retry פשוט ובטוח - לא דורש שינוי קוד.

## הצעד הבא המומלץ

להתחיל את שלב ה-Reporting (`src/reporting/`): הפקת דוח מטבלת `articles` (308 מאמרים קיימים) בשתי שפות (PDF + HTML), כולל טיפול בדה-דופליקציה של כפילויות טיזר/כתבה-מלאה שתועדה ב"בעיות ידועות". שווה לשלב גם את כיול פרומפט `screen.py` המוצע (נוסטלגיה/היסטוריה) לפני ריצת ingestion/analysis הבאה על תוכן חדש.

## סשן אחרון

**תאריך:** 2026-08-25

**תיאור:** נבנה ונבדק מקצה לקצה כל ה-Pipeline עד Analysis: Ingestion (טלגרם→PDF), Extraction (PDF→טקסט), Analysis שלב א' (סינון Haiku) ושלב ב' (ניתוח Sonnet), כולל refactor של ה-DB למודול משותף (`src/common/db.py`) עם מיגרציה אוטומטית. הורצו כל 4 השלבים בפועל על 17 קבצים אמיתיים (795 עמודים), כולל איתור ותיקון מספר בעיות שהתגלו רק בהרצה אמיתית: מיגרציית סכמה לדאטהבייס קיים, עמודים ריקים שגרמו לשגיאת API, פרומפט שדלף טקסט בין שדות, כללי-הכללה רחבים מדי בסינון גאופוליטי, ו-false positive על עמודי נוסטלגיה היסטורית שגרם ל-refusal לגיטימי מהמודל. תוקן גם באג נפרד (לא קשור ל-pipeline): שם ה-frontmatter השגוי בסקיל `resume-project` שמנע ממנו לפעול כ-slash command. בהמשך אותו סשן: נוסף `PROJECT_LOG.md` כיומן נרטיבי משלים ל-HANDOFF.md, וסקילי `resume-project`/`handoff` הורחבו לתמוך בו ובאוטומציית git חצי-אוטומטית (add אוטומטי, commit+push רק אחרי אישור מפורש; `resume-project` מבצע `git pull` תחילה).

**קבצים ששונו:** ראו "קבצים שנוצרו או שונו" למעלה - רשימה מלאה ומעודכנת, לא כפולה כאן.
