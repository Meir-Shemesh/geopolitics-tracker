# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## מטרת הפרויקט

סקירה יומית של מאמרי פרשנות גאופוליטית מתוך PDF-ים של עיתונים מובילים באנגלית וגרמנית, ניתוח דגש ומגמות לאורך זמן, והפקת דוחות יומיים/שבועיים/חודשיים (PDF + HTML אינטראקטיבי), המתפרסמים באתר ב-GitHub Pages. כל דוח וכן האתר עצמו זמינים בשתי גרסאות שפה מלאות - עברית ואנגלית, עם מעבר שפה באתר. הרחבה עתידית מתוכננת: תצוגה גיאוגרפית (מפה) וטיימליין, שכבר נתמכת מבחינת נתונים (תיוג מדינה/קונפליקט לכל מאמר - ראו `src/common/geo_taxonomy.py`) גם אם ה-UI עצמו טרם נבנה.

## מבנה הקבצים המרכזיים

- `src/common/db.py` - מודול ה-DB המשותף לכל שלבי ה-Pipeline (`data/processed/tracker.db`). הסכמה מוצהרת פעם אחת ב-`TABLE_COLUMNS`; `init_db()` יוצר טבלאות חסרות **וגם** מוסיף עמודות חסרות לטבלאות קיימות (`PRAGMA table_info` + `ALTER TABLE`). ראו "החלטות ארכיטקטוניות קבועות".
- `src/ingestion/fetch.py` - משיכת PDF-ים מערוץ הטלגרם `demagazinesharing` (telethon), מסנן רק קבצים שמזוהים כאחד מ-4 העיתונים של ה-MVP.
- `src/extraction/extract.py` - חילוץ טקסט גולמי מה-PDF (pdfplumber) לעמוד, גם ל-DB וגם לעותק טקסט תחת `data/processed/extracted/` (לא נכנס ל-git).
- `src/analysis/` - סיווג וניתוח באמצעות Claude API, בשני שלבים עצמאיים: `screen.py` (סינון רחב) ו-`analyze.py` (ניתוח מעמיק, כולל תיוג country_codes/conflict_zones - ראו "החלטות ארכיטקטוניות קבועות"). `geo_tag_backfill.py` - כלי-עזר קבוע (לא חד-פעמי) שמתייג בדיעבד מאמרים שנותחו לפני שהתיוג הגיאוגרפי נוסף, בקבוצות (batch) עם Haiku זול - לא קורא מחדש את כל שלב ה-Analysis.
- `src/common/geo_taxonomy.py` - שלושה מיפויים קבועים לתיוג גיאוגרפי: `COUNTRY_LIST` (רשימת מדינות סגורה, קוד ISO + שם עברי/אנגלי), `COUNTRY_TO_REGION` (מדינה → אחד מ-8 אזורים קבועים), `CONFLICT_ZONE_LABELS` (3 קונפליקטים סגורים). באותה רוח כמו `NEWSPAPER_DISPLAY_NAMES` - מיפוי קבוע מוזרק לפרומפט, לא ניחוש חופשי.
- `src/reporting/synthesize.py` - שלב א' של Reporting: קריאת Sonnet יחידה ליום, מקבצת את מאמרי היום לפי נושא אמיתי (לא לפי `region_topic` הגולמי) לטבלאות `reports`/`report_sections`/`report_section_articles`, כולל רשת ביטחון כפולה (fallback section דטרמיניסטי + retry מבוסס-יחס) שמבטיחה כיסוי מלא של כל מאמר. ראו "החלטות ארכיטקטוניות קבועות".
- `src/reporting/render.py` - שלב ב' של Reporting: הופך שורות `report_sections` ל-4 קבצים (HTML+PDF × עברית+אנגלית) תחת `reports/{he,en}/`, כולל קידוד צבעוני לפי `category` וגופן Heebo מוטמע מקומית (`src/reporting/assets/fonts/`, מועתק אוטומטית גם ל-`reports/assets/fonts/` לשימוש הדפים המתפרסמים).
- `src/publishing/publish.py` - שלב Publishing: בונה `docs/` (מקור ה-GitHub Pages) מתוך `reports/` - מעתיק HTML/PDF וגופן Heebo, יוצר עמוד ארכיון כרונולוגי (`index.html`) לכל שפה + עותק-שורש מותאם-נתיבים בעברית (`docs/index.html`, כברירת מחדל). תמיד דורס, בלי `--force` (כמו `render.py`).
- `data/raw/` - PDF-ים גולמיים (לא נכנס ל-git).
- `data/processed/` - `tracker.db` (מצב כל ה-Pipeline) ו-`extracted/` (עותקי טקסט) - שניהם לא נכנסים ל-git.
- `reports/he/`, `reports/en/` - דוחות שנוצרים ע"י `render.py` (מקור אמת). `docs/` - נבנה מהם ע"י `publish.py`; זהו המיקום שממנו GitHub Pages מגיש בפועל (כולל `docs/CNAME` לדומיין המותאם `geopolitics.meirshemesh.com`) - **אין לערוך קבצים בתוך `docs/` ידנית**, הם נדרסים בכל הרצת `publish.py`.
- `tests/` - טסטים.
- `scripts/` - סקריפטים חד-פעמיים, מחוץ ל-5 שלבי ה-Pipeline הראשי (כל אחד עומד בפני עצמו, לא מורץ שוטף). למשל `build_background_doc.py` - מפיק מסמך רקע/מותג עצמאי (PDF+HTML) בעיצוב תואם לאתר (גופן Heebo, פלטת הצבעים הבסיסית מ-`render.py`), עם נכסי המקור שלו תחת `scripts/assets/` (למשל `MS_Logo.png`). תוצרי ה-build עצמם (`scripts/output/*.pdf`, `*.html`) לא נכנסים ל-git - נבנים מחדש מהסקריפט, כמו `docs/`/`reports/`.
- `requirements.txt` - רשימת תלויות (telethon, python-dotenv, pdfplumber, anthropic, weasyprint) - מותקנות ב-venv מקומי.

## כללי עבודה קבועים

- מקורות ל-MVP: The Guardian, The Daily Telegraph (אנגלית), Süddeutsche Zeitung, Die Welt (גרמנית).
- כל התקשורת וההסברים עם המשתמש בעברית. כל הקוד, שמות המשתנים, הפונקציות וההערות בקוד באנגלית.
- ניהול תלויות באמצעות `venv`.
- בתחילת סשן חדש או לאחר מעבר למחשב אחר, יש להפעיל את `/resume-project` (סקיל ידני בלבד, ללא הפעלה אוטומטית) - מבצע `git pull` תחילה (עוצר אם יש קונפליקט/שינויים לא-committed), ואז משחזר מצב מ-CLAUDE.md, HANDOFF.md, ומ-PROJECT_LOG.md (אם קיים).
- בסיום סשן יש להפעיל את `/handoff` (סקיל ידני בלבד) - מעדכן CLAUDE.md/HANDOFF.md ולעיתים PROJECT_LOG.md, ואז מבצע רצף git חצי-אוטומטי: `git add .` אוטומטי, בדיקת קבצים חשודים, הצעת הודעת commit, ו-commit+push **רק** אחרי אישור מפורש מהמשתמש.
- סודות (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `ANTHROPIC_API_KEY`) נשמרים ב-`.env` בשורש הפרויקט (לא נכנס ל-git) ונטענים באמצעות `python-dotenv`. `.env.example` מתעד את שמות המשתנים הנדרשים בלי ערכים.
- WeasyPrint (הפקת PDF) דורש גם GTK3 Runtime ברמת מערכת ההפעלה, לא רק `pip install weasyprint` - ב-Windows: `winget install tschoonj.GTKForWindows`. בלעדיו `import weasyprint` נכשל; `render.py` מזהה זאת אוטומטית ומדלג רק על שלב ה-PDF (קובצי ה-HTML עדיין נוצרים כרגיל).
- הגדרות GitHub Pages/דומיין (כמו `docs/CNAME`) עלולות להיערך ישירות בממשק ה-Web של GitHub, לא רק דרך git מקומי - לפני `push` אחרי עבודה על `docs/`/הגדרות פרסום, שווה `git pull` מקדים גם באמצע סשן, לא רק בתחילתו (ראו PROJECT_LOG 4.13 למקרה קונפליקט אמיתי שקרה כך).

## מגבלות והעדפות

- דו-לשוניות (עברית + אנגלית) היא דרישת ליבה שחייבת להיות מובנית בשלב ה-Reporting מההתחלה - לא תוספת מאוחרת.
- PDF בעברית דורש CSS עם `direction: rtl` וגופן תומך עברית ב-WeasyPrint - יש לקחת זאת בחשבון בכל עבודה על `src/reporting/` ותיקיית `reports/`.

## פקודות הפעלה ובדיקה

אין build/lint/test מוגדרים - הפעלה היא הרצת סקריפטים חד-פעמיים ישירות (כולם דורשים venv פעיל):

- `python -m src.ingestion.fetch` - משיכת PDF-ים חדשים מטלגרם.
- `python -m src.extraction.extract` - חילוץ טקסט מקבצים שהורדו וטרם חולצו.
- `python -m src.analysis.screen` - שלב א' של Analysis (סינון רחב, Haiku). אופציונלי: `--file <מחרוזת בשם הקובץ>` להגבלה לקובץ יחיד לצורך בדיקה.
- `python -m src.analysis.analyze` - שלב ב' של Analysis (ניתוח מעמיק, Sonnet, כולל תיוג גיאוגרפי). אופציונלי: `--file-id <int>` להגבלה לקובץ יחיד לצורך בדיקה.
- `python -m src.analysis.geo_tag_backfill` - מתייג בדיעבד מאמרים קיימים שחסר להם תיוג גיאוגרפי (בקבוצות, Haiku זול). אופציונלי: `--date <YYYY-MM-DD>` להגבלה לתאריך יחיד לצורך בדיקה. בטוח להרצה חוזרת - מאמר שכבר תויג לא מתעבד שוב.
- `python -m src.reporting.synthesize --date <YYYY-MM-DD>` - שלב א' של Reporting. אופציונלי: `--force` למחיקה ובנייה מחדש של דוח קיים לאותו תאריך.
- `python -m src.reporting.render --date <YYYY-MM-DD>` - שלב ב' של Reporting, מפיק 4 קבצים (HTML+PDF × עברית+אנגלית) מתוך דוח שכבר נבנה ע"י `synthesize.py`.
- `python -m src.publishing.publish` - שלב Publishing, בונה/מעדכן את `docs/` מתוך כל התאריכים הקיימים ב-`reports/`. בלי דגלים, תמיד דורס.

## החלטות ארכיטקטוניות קבועות

Pipeline בן 5 שלבים עוקבים, כל שלב בתת-תיקייה נפרדת תחת `src/`:

Ingestion -> Extraction -> Analysis -> Reporting -> Publishing

שלב ה-Reporting מייצר משתי גרסאות שפה (עברית ואנגלית) לכל דוח, ובשני פורמטים (PDF + HTML) - זהו חלק קבוע מהארכיטקטורה ולא הרחבה עתידית. Python 3 + SQLite הם הבסיס הטכנולוגי הקבוע.

שלב ה-Analysis בנוי כשני תתי-שלבים עצמאיים ונפרדים (כל אחד ניתן להרצה ולבדיקה בלי השני):
1. **סינון רחב** (`screen.py`, Claude Haiku) - שאלה בינארית זולה על כל עמוד: "האם ייתכן שיש כאן תוכן גאופוליטי?". מכוון להיות רשת רחבה מתוך כוונה - במקרה ספק מסמן רלוונטי, כדי לא לפספס תוכן. התוצאה נשמרת ב-`page_screening`.
2. **ניתוח מעמיק** (`analyze.py`, Claude Sonnet) - רק על עמודים שסומנו רלוונטיים בשלב א', מזהה מאמרים בודדים ומחלץ מהם שדות מובנים (כותרת/מחבר/נושא/עמדה/ציטוט) לטבלת `articles`.

`src/common/db.py` הוא מקור האמת היחיד לסכמת ה-DB: הוספת עמודה/טבלה חדשה נעשית **רק** ע"י עריכת `TABLE_COLUMNS`/`TABLE_CONSTRAINTS` שם - `init_db()` מזהה ומוסיף את מה שחסר אוטומטית בכל הרצה, גם על `tracker.db` קיים. אין לכתוב הצהרות `CREATE TABLE`/`ALTER TABLE` ידניות בקבצים אחרים.

שמות עיתונים בכל תוצר (דוחות, פרומפטים ל-Claude) משתמשים תמיד במיפוי קבוע יחיד `NEWSPAPER_DISPLAY_NAMES` (בלי הפרדה ל-HE/EN) בכתיב הלטיני המקורי - "The Guardian", "The Daily Telegraph", "Süddeutsche Zeitung", "Die Welt" - לעולם לא תעתיק/תרגום עברי, גם בתוך טקסט עברי וגם בתוך הנחיות לפרומפט עצמו.

עיקרון מנחה שחזר פעמיים בפרויקט: כשמתגלה כשל חוזר ולא-תלוי-הקשר בהתנהגות מודל (למשל שגיאות רשת חולפות ב-Analysis, השמטת article_id-ים ב-Synthesis) - הפתרון הוא רשת-ביטחון גנרית ברמת הקוד (טיפול שגיאות ברמת-יחידה + retry, fallback דטרמיניסטי), לא רדיפה אחרי כל מקרה בנפרד דרך שינויי פרומפט נקודתיים.

`report_sections.category` הוא מיפוי קבוע של 8 קטגוריות (security_conflict/diplomacy_international/trade_economics/domestic_politics/migration_society/society_culture/technology_media/energy_environment) שהמודל בוחר בעצמו באותה קריאת `synthesize.py`, פלוס ערך שמור `additional_coverage` שלעולם לא מוצע למודל - הוא מסמן section שנוצר ע"י מנגנון ה-fallback ולא ע"י המודל. שינוי ברשימת הקטגוריות דורש עדכון גם ב-`synthesize.py` (ה-enum בסכמת הכלי) וגם ב-`render.py` (`CATEGORY_LABELS`/`CATEGORY_STYLES`).

תיוג גיאוגרפי (`article_countries`/`article_conflict_zones`, many-to-many כי מאמר יכול לגעת ביותר ממדינה/קונפליקט אחד) נכתב ע"י `analyze.py` באותה קריאת API הקיימת שכבר מפיקה headline/region_topic/וכו' - לא קריאה נפרדת. `articles.region_topic` (טקסט חופשי) נשאר כמו שהוא לצדו, לא מוחלף. **חשוב לפרשנות עתידית של הנתונים**: מאמר בלי אף שורה לא ב-`article_countries` ולא ב-`article_conflict_zones` יכול להיות גם מאמר שטרם עבר תיוג וגם מאמר שתויג ונמצא נכון שאין לו מדינה/קונפליקט רלוונטיים (המקרה השני קורה בפועל, לא נדיר) - שני המצבים נראים זהים ב-DB. אין להניח "0 שורות = טרם עובד".

הרחבת רשימת המדינות ב-`geo_taxonomy.py` (`COUNTRY_LIST`/`COUNTRY_TO_REGION`) בעתיד היא ציפייה מובנית, לא חריגה - הרשימה ההתחלתית (94 מדינות) נבנתה מכיסוי אמיתי שכבר נצפה, לא מכסה את כל 195 מדינות העולם בכוונה.
