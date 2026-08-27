# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## מטרת הפרויקט

סקירה יומית של מאמרי פרשנות גאופוליטית מתוך PDF-ים של עיתונים מובילים באנגלית וגרמנית, ניתוח דגש ומגמות לאורך זמן, והפקת דוחות יומיים/שבועיים/חודשיים (PDF + HTML אינטראקטיבי), המתפרסמים באתר ב-GitHub Pages. כל דוח וכן האתר עצמו זמינים בשתי גרסאות שפה מלאות - עברית ואנגלית, עם מעבר שפה באתר. דף הבית (`docs/index.html`) הוא דף בית אינטראקטיבי - מפת עולם, ציר זמן, וכניסה לדוח האחרון, כולם קוראים מ-`docs/assets/data/manifest.json` בזמן ריצה (לא build-time) - הארכיון הכרונולוגי הישן זמין בנפרד ב-`archive.html`.

## מבנה הקבצים המרכזיים

- `src/common/db.py` - מודול ה-DB המשותף לכל שלבי ה-Pipeline (`data/processed/tracker.db`). הסכמה מוצהרת פעם אחת ב-`TABLE_COLUMNS`; `init_db()` יוצר טבלאות חסרות **וגם** מוסיף עמודות חסרות לטבלאות קיימות (`PRAGMA table_info` + `ALTER TABLE`). ראו "החלטות ארכיטקטוניות קבועות".
- `src/ingestion/fetch.py` - משיכת PDF-ים מערוץ הטלגרם `demagazinesharing` (telethon), מסנן רק קבצים שמזוהים כאחד מ-4 העיתונים של ה-MVP.
- `src/extraction/extract.py` - חילוץ טקסט גולמי מה-PDF (pdfplumber) לעמוד, גם ל-DB וגם לעותק טקסט תחת `data/processed/extracted/` (לא נכנס ל-git).
- `src/analysis/` - סיווג וניתוח באמצעות Claude API, בשני שלבים עצמאיים: `screen.py` (סינון רחב) ו-`analyze.py` (ניתוח מעמיק, כולל תיוג country_codes/conflict_zones - ראו "החלטות ארכיטקטוניות קבועות"). `geo_tag_backfill.py` - כלי-עזר קבוע (לא חד-פעמי) שמתייג בדיעבד מאמרים שנותחו לפני שהתיוג הגיאוגרפי נוסף, בקבוצות (batch) עם Haiku זול - לא קורא מחדש את כל שלב ה-Analysis.
- `src/common/geo_taxonomy.py` - שלושה מיפויים קבועים לתיוג גיאוגרפי: `COUNTRY_LIST` (רשימת מדינות סגורה, קוד ISO + שם עברי/אנגלי), `COUNTRY_TO_REGION` (מדינה → אחד מ-8 אזורים קבועים), `CONFLICT_ZONE_LABELS` (3 קונפליקטים סגורים). באותה רוח כמו `NEWSPAPER_DISPLAY_NAMES` - מיפוי קבוע מוזרק לפרומפט, לא ניחוש חופשי.
- `src/reporting/synthesize.py` - שלב א' של Reporting: קריאת Sonnet יחידה ליום, מקבצת את מאמרי היום לפי נושא אמיתי (לא לפי `region_topic` הגולמי) לטבלאות `reports`/`report_sections`/`report_section_articles`, כולל רשת ביטחון כפולה (fallback section דטרמיניסטי + retry מבוסס-יחס) שמבטיחה כיסוי מלא של כל מאמר. ראו "החלטות ארכיטקטוניות קבועות".
- `src/reporting/render.py` - שלב ב' של Reporting: הופך שורות `report_sections` ל-4 קבצים (HTML+PDF × עברית+אנגלית) תחת `reports/{he,en}/`, כולל קידוד צבעוני לפי `category` (`category_css()` - פומבי, משוכפל לשימוש גם בדף הבית ב-`publish.py`), גופן **Assistant** מוטמע מקומית (`src/reporting/assets/fonts/`, מועתק אוטומטית גם ל-`reports/assets/fonts/`; `font_face_css(relative_path)` - פונקציה פומבית משותפת שבונה את בלוק ה-`@font-face`, נקראת מ-4 מקומות: דוח/`about.html`/`archive.html`/דף הבית - ראו "החלטות ארכיטקטוניות קבועות"), ועוגן `id="section-{id}"` על כל section (כולל fallback) - נדרש כדי שקישורי-עומק מהמניפסט יעבדו. `build_nav_html(back_href, other_lang_href, lang)` מקבל hrefs מפורשים (לא גוזר מ-`report_date`) - כדי שגם `about.html` (ב-`publish.py`) יוכל לעשות בו שימוש חוזר; כולל גם לוגו (56px) מקושר ל-`../index.html`, זהה בכל שלוש הצריכות (דוח/about/archive).
- `src/common/about_content.py` - תוכן משותף (עברית+אנגלית: doc_meta/identity/title/subtitle/sections) ל-`scripts/build_background_doc.py` ול-`build_about_html()` ב-`publish.py` - מקור אמת יחיד, לא כפילות. `scripts/` יכול לייבא מ-`common/`; `publish.py` (חלק מה-Pipeline) לעולם לא מייבא מ-`scripts/` (חד-פעמי).
- `src/publishing/publish.py` - שלב Publishing: בונה `docs/` (מקור ה-GitHub Pages) מתוך `reports/` - מעתיק HTML/PDF וגופן Assistant, בונה `archive.html` (ארכיון כרונולוגי, לכל שפה + עותק-שורש, כולל לוגו מקושר ל-`index.html` ב-top-nav) ו-`about.html` (עמוד אתר רגיל, דו-לשוני, אותו לוגו-בנאב + לוגו נוסף גדול יותר - 96px - בכרטיס "אודות הכותב" בתחתית) ו-`manifest.json` סטטי (`assets/data/manifest.json`, גם ב-`docs/` וגם ב-`reports/`), ובונה **דף בית אינטראקטיבי** (`index.html`, לכל שפה + עותק-שורש) - מפת עולם SVG מוטמעת inline (`src/publishing/assets/map/world.svg`, Public Domain, מועתקת גם כנכס עצמאי ל-`assets/map/`) בשורה מלאה של רוחב העמוד, ציר זמן וכרטיס-דוח-אחרון זה-לצד-זה מעליה, וצ'יפים לסינון לפי אזור מתחת למפה, כולם JS+`fetch()` שקוראים מ-`manifest.json` בזמן ריצה, בלי כותרות-מודול מילוליות (העיצוב עצמו מתקשר את התפקיד). תמיד דורס, בלי `--force` (כמו `render.py`).
- `data/raw/` - PDF-ים גולמיים (לא נכנס ל-git).
- `data/processed/` - `tracker.db` (מצב כל ה-Pipeline) ו-`extracted/` (עותקי טקסט) - שניהם לא נכנסים ל-git.
- `reports/he/`, `reports/en/` - דוחות שנוצרים ע"י `render.py` (מקור אמת). `docs/` - נבנה מהם ע"י `publish.py`; זהו המיקום שממנו GitHub Pages מגיש בפועל (כולל `docs/CNAME` לדומיין המותאם `geopolitics.meirshemesh.com`) - **אין לערוך קבצים בתוך `docs/` ידנית**, הם נדרסים בכל הרצת `publish.py`.
- `tests/` - טסטים.
- `scripts/` - סקריפטים חד-פעמיים, מחוץ ל-5 שלבי ה-Pipeline הראשי (כל אחד עומד בפני עצמו, לא מורץ שוטף). למשל `build_background_doc.py` - מפיק מסמך רקע/מותג עצמאי דו-לשוני (PDF+HTML לכל שפה) בגופן Assistant (מסמך זה בחר Assistant לפני שהאתר כולו אימץ אותו - כעת שני הצדדים בגופן זהה במקרה, אך `scripts/` עדיין לא תלוי ב-`src/`: קובץ הגופן שלו תחת `scripts/assets/` הוא עותק נפרד, לא ייבוא מ-`src/reporting/assets/fonts/`) ופלטת הצבעים הבסיסית מ-`render.py`, עם נכסי המקור שלו תחת `scripts/assets/` (למשל `MS_Logo.png`). תוצרי ה-build עצמם (`scripts/output/*.pdf`, `*.html`) לא נכנסים ל-git - נבנים מחדש מהסקריפט, כמו `docs/`/`reports/`.
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
- **כל שינוי במבנה/נתיבי-פלט של `render.py` או `publish.py`** (שמות קבצים, קישורים פנימיים, מבנה HTML) **מחייב regeneration מלא של כל התאריכים הקיימים בארכיון** (לא רק תאריך בדיקה בודד) **+ `git status` מפורש לפני commit** - כדי לוודא שאין קבצים ישנים שנשארו "תקועים" עם המבנה הקודם. הדפוס הזה נתפס שוב ושוב רק ברגע האחרון: תיוג גיאוגרפי (backfill נדרש למאמרים קיימים), עוגני `section-id` (נכתבו בקוד אך לא נאפו לקבצים קיימים), והעברת הארכיון ל-`archive.html` (קישורי "חזרה" בדוחות קיימים המשיכו להצביע על `index.html` הישן). לפני שמכריזים על שינוי כזה "גמור" - להריץ מחדש את `render.py` על כל תאריך קיים ואת `publish.py`, ורק אז לבדוק `git status`.

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

`manifest.json` (נבנה ע"י `build_manifest()` ב-`publish.py`) הוא קובץ סטטי בלבד - נוצר בזמן build, לא API/שרת בזמן ריצה, כמו כל שאר האתר. `sections` הוא מקור האמת המלא (נושא, קטגוריה, מקורות, מדינות/קונפליקטים, קישורים); `countries`/`conflict_zones`/`dates`/`categories`/`regions` הם **רק אינדקסים/תרגומי-תצוגה** מעל `sections` (`countries`/`conflict_zones`/`dates` כוללים אך ורק ערכים עם לפחות section אחד, לעולם לא כל 94 המדינות; `categories` משוכפל מ-`CATEGORY_LABELS` הקיים ב-`render.py` כדי שה-JS לא יצטרך רשימה קשיחה) - לעולם לא כולל את `comparison_text` המלא (כדי שהקובץ יישאר קטן ככל שהארכיון גדל). `regions` נגזר מ-`COUNTRY_TO_REGION` (אותו עיקרון בדיוק כמו `categories`) - `regions[key] = {name_he, name_en, country_codes, section_ids}`, כשה-`section_ids` הוא איחוד (union) של כל המדינות באזור, ורק אזורים עם `section_ids` לא-ריק נכללים (7/8 בפועל - `oceania` עדיין ריק). קישורי `href_he`/`href_en` הם נתיבים יחסיים מתוך `docs/` עצמו (`he/report_<date>_he.html#section-<id>`), **ללא** קידומת `../` מוטמעת מראש - כל צרכן (למשל דף הבית) מוסיף את קידומת-העומק שלו (`asset_prefix`) בזמן ריצה, כי אותו manifest משרת צרכנים בעומקים שונים תחת `docs/` (שורש/`he/`/`en/`).

**דף הבית** (`build_homepage_html()` ב-`publish.py`) הוא הצרכן הראשון של `manifest.json`, ונבנה בשלושה מיקומים בדיוק כמו הארכיון הישן (`docs/index.html` שורש-עברית-ברירת-מחדל, `docs/he/index.html`, `docs/en/index.html`) - כל עותק מקבל קבוע JS `asset_prefix` (`""`/`"../"`) שנקבע בזמן build לפי מיקומו, ומשמש הן לנתיבי-נכס סטטיים (גופן/מפה/`manifest.json` עצמו) והן לתיקון קישורי ה-`href_he`/`href_en` שמגיעים מה-manifest בזמן ריצה. שלושת המודולים (מפה/ציר-זמן/דוח-אחרון) קוראים את `manifest.json` דרך `fetch()` **בזמן טעינת הדף**, לא embedded בזמן build - עיקרון קבוע: שום נתון מה-manifest לא "נאפה" ישירות ל-HTML הסטטי, גם כשזה טכנית אפשרי (כמו כרטיס הדוח האחרון), כדי ששינוי ב-`manifest.json` תמיד ישתקף בלי לבנות מחדש את דף הבית עצמו. מפת העולם (`assets/map/world.svg`, Public Domain, Wikimedia Commons) מוטמעת **inline** בגוף העמוד (לא `<img>`) כדי לאפשר ל-JS לצבוע/להוסיף click handler לכל `<g id="xx">` (קוד ISO 3166-1 alpha-2). הפילטור (קליק על מדינה/תאריך/אזור → פאנל תוצאות משותף) הוא **single-select** - קליק מחליף את הפילטר הפעיל, לא AND משולב (ראו PROJECT_LOG action item ל-v2).

**פריסת דף הבית (v2)**: שתי שורות, לא גריד תלת-טורי אחיד - שורה עליונה = ציר-זמן וכרטיס-דוח-אחרון זה-לצד-זה; שורה תחתונה = מפה ברוחב מלא של העמוד (במקום שליש-טור כמו ב-v1) כדי שקליק על מדינה בודדת מתוך 94 יהיה שימושי בפועל, לא רק אסתטי. אין אף כותרת-מודול מילולית ("מפה"/"ציר זמן" וכו') - עיקרון מכוון: העיצוב עצמו מתקשר את התפקיד של כל מודול, לא טקסט. צ'יפים לסינון לפי אזור (מתוך `regions` שבמניפסט, עד 8) מתחת למפה - קליק על צ'יפ מסנן את פאנל התוצאות **וגם** מדגיש (`is-selected`, אותה מחלקת CSS בדיוק כמו בחירת מדינה בודדת - לא מחלקה נפרדת) את כל מדינות האזור על המפה. כרטיס הדוח האחרון מציג מספר-תאריך גדול ומודגש (באותו פורמט `DD.MM` כמו תאי ציר-הזמן) ותקציר-נושא של ה-section הראשון, בלי מילות "היום"/"דוח" - עקבי עם עיקרון-בלי-כותרות.

**מוסכמה: לוגו מקושר לדף הבית בכל top-nav** - `build_nav_html()` (`render.py`, משמש גם ל-`about.html`) וה-nav הנפרד של `build_index_html()` (`archive.html`) כוללים תמיד תמונת לוגו (56px) עטופה ב-`<a>` שמצביעה על `index.html` (מותאם לעומק-הנתיב של כל עמוד); ה-nav היחיד היוצא מן הכלל הוא top-bar של דף הבית עצמו - הלוגו שם (56px, הוגדל מ-32px) **אינו** מקושר לשום מקום, כי דף הבית כבר "בית". לוגו נוסף וגדול יותר (96px) מופיע בכרטיס "אודות הכותב" בתחתית `about.html` - תפקיד שונה (זיהוי אישי, לא ניווט), מוסכמת גודל נפרדת.

לאימות ויזואלי של עמודים שתלויים ב-JavaScript בזמן ריצה (כמו דף הבית) - WeasyPrint לא מריץ JS בכלל, אז השיטה הרגילה (רינדור ל-PNG) לא מספיקה. אפשר להריץ **Playwright headless Chromium דרך `npx --yes playwright@latest`** (לא תלות קבועה בפרויקט, לא ב-`requirements.txt`) מול שרת HTTP מקומי (`python -m http.server` בתוך `docs/`) - `fetch()` על `file://` נחסם ע"י דפדפנים.
