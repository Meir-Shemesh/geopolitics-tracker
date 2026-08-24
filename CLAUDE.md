# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## מטרת הפרויקט

סקירה יומית של מאמרי פרשנות גאופוליטית מתוך PDF-ים של עיתונים מובילים באנגלית וגרמנית, ניתוח דגש ומגמות לאורך זמן, והפקת דוחות יומיים/שבועיים/חודשיים (PDF + HTML אינטראקטיבי), המתפרסמים באתר ב-GitHub Pages. כל דוח וכן האתר עצמו זמינים בשתי גרסאות שפה מלאות - עברית ואנגלית, עם מעבר שפה באתר.

## מבנה הקבצים המרכזיים

- `src/ingestion/` - משיכת PDF-ים מטלגרם.
- `src/extraction/` - חילוץ טקסט מה-PDF.
- `src/analysis/` - סיווג וניתוח באמצעות Claude API.
- `src/reporting/` - הפקת דוחות PDF+HTML בשתי שפות.
- `src/publishing/` - פרסום ל-GitHub Pages.
- `data/raw/` - PDF-ים גולמיים (לא נכנס ל-git).
- `data/processed/` - נתונים מעובדים.
- `reports/he/`, `reports/en/` - דוחות מתפרסמים לפי שפה.
- `tests/` - טסטים.
- `requirements.txt` - רשימת תלויות (טרם הותקנו).

## כללי עבודה קבועים

- מקורות ל-MVP: The Guardian, The Daily Telegraph (אנגלית), Süddeutsche Zeitung, Die Welt (גרמנית).
- כל התקשורת וההסברים עם המשתמש בעברית. כל הקוד, שמות המשתנים, הפונקציות וההערות בקוד באנגלית.
- ניהול תלויות באמצעות `venv`.
- בתחילת סשן חדש או לאחר מעבר למחשב אחר, יש להפעיל את `/resume-project` (סקיל ידני בלבד, ללא הפעלה אוטומטית) כדי לשחזר את מצב הפרויקט מ-CLAUDE.md ו-HANDOFF.md.

## מגבלות והעדפות

- דו-לשוניות (עברית + אנגלית) היא דרישת ליבה שחייבת להיות מובנית בשלב ה-Reporting מההתחלה - לא תוספת מאוחרת.
- PDF בעברית דורש CSS עם `direction: rtl` וגופן תומך עברית ב-WeasyPrint - יש לקחת זאת בחשבון בכל עבודה על `src/reporting/` ותיקיית `reports/`.

## פקודות הפעלה ובדיקה

אין עדיין - הפרויקט בשלב שלד בלבד, ללא קוד לוגי, ללא build/lint/test מוגדרים.

## החלטות ארכיטקטוניות קבועות

Pipeline בן 5 שלבים עוקבים, כל שלב בתת-תיקייה נפרדת תחת `src/`:

Ingestion -> Extraction -> Analysis -> Reporting -> Publishing

שלב ה-Reporting מייצר משתי גרסאות שפה (עברית ואנגלית) לכל דוח, ובשני פורמטים (PDF + HTML) - זהו חלק קבוע מהארכיטקטורה ולא הרחבה עתידית. Python 3 + SQLite הם הבסיס הטכנולוגי הקבוע.
