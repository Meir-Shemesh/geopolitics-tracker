"""One-off (2026-09-24, PROJECT_LOG action item 50): retroactively applies the
new Stage-2 author-attribution wording (see src/reporting/synthesize.py's
STAGE2_SYSTEM_PROMPT update, same day) to the two live 2026-09-23 sections
that were identified in an external quality review as misattributing a named
opinion columnist's/letter-writer's claim to the institution instead of the
person:
  - section 2549 ("Antisemitism and terrorism targeting Israel worldwide") -
    Jonah Goldberg's Los Angeles Times column.
  - section 2556 ("Russia: Putin's regime and internal politics") - Mergen
    Mongush's Guardian reader's letter.

Writes the EXACT text that was already generated once, shown to and approved
by the user (via a separate read-only test script + diff review), and saved
verbatim to a scratch file - not a fresh API call, so the approved wording is
what actually lands in the DB (Claude is not deterministic; a second call
would likely reword slightly). Updates topic_label_de, comparison_text_he,
comparison_text_en, and comparison_text_de for both rows.

Not safe to run again blindly - it hardcodes one specific approved rewrite
for these two section ids only, matching the precedent set by
scripts/fix_broken_comparison_text_he.py and scripts/fix_sources_included.py.
"""
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from src.common.db import get_connection, init_db

# Exact approved AFTER text, copied verbatim from
# <scratchpad>/diff_author_attribution_output.txt (the read-only verification
# run reviewed and approved by the user in conversation) - not regenerated.
FIXES = {
    2549: {
        "topic_label_de": "Antisemitismus und Terror gegen Israel weltweit",
        "comparison_text_he": (
            "הכתבות המכונסות בנושא זה נוגעות בזוויות שונות מאוד של הדיון בישראל, "
            "באנטישמיות ובטרור, ומשקפות עמדות שונות באופן חד. בטור דעה ב-Los "
            "Angeles Times, ג'ונה גולדברג טוען שהתקשורת האמריקאית, ובעיקר ערוצי "
            "החדשות בכבלים, מקדישה לישראל תשומת לב חריגה ובלתי פרופורציונלית "
            "בהשוואה לאיראן, רוסיה, אוקראינה וסין, ותוקף זאת כתוצר של הטיה "
            "אנטי-ישראלית והאשמות רצח עם חסרות בסיס, בזמן שהתקשורת מתעלמת "
            "מהתעללויות חמורות יותר של סין. לעומת זאת, Washington Post מדווח "
            "בידיעה חדשותית - מאת ליאור סורוקה - על עימות בין נתניהו לראש עיריית "
            "ניו יורק ממדני בעניין צו בית הדין הפלילי הבינלאומי, שם נתניהו מציג "
            "את קריאת ממדני למעצרו כתמיכה בחמאס, לצד הבהרה שממדני מכחיש זאת - "
            "כתבה שממקדת את הדיון בפוליטיקה המפלגתית סביב ישראל ולא בשאלת "
            "האנטישמיות עצמה. Die Welt, בריאיון שערך ניקולאס פוטר עם אביו של "
            "יארון ליסינסקי - עובד השגרירות הישראלית שנרצח - מציג זווית שונה "
            "בתכלית: קריאה מוסרית ואישית לראות באלימות אנטישמית לא בעיה יהודית "
            "בלבד אלא איום חברתי רחב יותר, תוך דרישה לעונש מוות לרוצח. "
            "ה-Guardian, בכתבתה של נדיה חומאמי, כלל אינו דן באנטישמיות או בטרור "
            "נגד ישראל במובן הישיר, אלא מסקר מחלוקת בעולם המוזיקה שבה שרלוט "
            "צ'רץ' מותחת ביקורת על אד שירן שהעדיף, לטענתה, אינטרסים מסחריים על "
            "פני עמדה מוסרית בנושא עזה - זווית שממקמת את ישראל בהקשר "
            "תרבותי-כלכלי רחוק מהדיון הביטחוני או האנטישמי המרכזי. כך נוצר "
            "פסיפס של התייחסויות שונות בתכלית: מביקורת תקשורתית אידיאולוגית, "
            "דרך פוליטיקה מקומית אמריקאית, ועד עדות אישית וכאב על טרור אנטישמי "
            "ממשי."
        ),
        "comparison_text_en": (
            "The sources grouped under this topic approach the intersection of "
            "Israel, antisemitism and terrorism from strikingly different "
            "angles. In a Los Angeles Times column, Jonah Goldberg argues that "
            "American media, especially cable news, devote disproportionate "
            "attention to Israel compared with Iran, Russia, Ukraine and China, "
            "framing this as evidence of anti-Israel bias and unfounded "
            "genocide accusations while graver abuses by China go ignored. The "
            "Washington Post, in a news report by Lior Soroka, instead covers a "
            "political clash between Netanyahu and New York Mayor Mamdani over "
            "an ICC arrest warrant, presenting Netanyahu's accusation that "
            "Mamdani effectively supports Hamas alongside Mamdani's denial - a "
            "story rooted in partisan American politics rather than a direct "
            "treatment of antisemitism. Die Welt takes a markedly more personal "
            "and moral approach: in an interview conducted by Nicholas Potter, "
            "the father of murdered Israeli embassy worker Yaron Lischinsky "
            "insists that antisemitic violence is not merely a Jewish problem "
            "but a societal one that must be confronted worldwide, while "
            "calling for the death penalty for his son's killer. The "
            "Guardian's contribution, reported by Nadia Khomami, barely "
            "touches antisemitism or terrorism directly at all, instead "
            "covering a celebrity dispute in which Charlotte Church criticizes "
            "Ed Sheeran for prioritizing commercial interests over a moral "
            "stance on Gaza - placing Israel-related controversy in a "
            "cultural-industry context far removed from the security or "
            "antisemitism angle dominant elsewhere. Together, the coverage "
            "ranges from ideological media criticism, through American "
            "domestic politics, to raw personal testimony about real "
            "antisemitic violence."
        ),
        "comparison_text_de": (
            "Die unter diesem Thema zusammengefassten Artikel nähern sich dem "
            "Themenkomplex Israel, Antisemitismus und Terror aus sehr "
            "unterschiedlichen Richtungen. In einem Meinungsbeitrag für die Los "
            "Angeles Times argumentiert Jonah Goldberg, die amerikanischen "
            "Medien, besonders die Nachrichtensender, widmeten Israel eine "
            "unverhältnismäßig große Aufmerksamkeit im Vergleich zu Iran, "
            "Russland, der Ukraine und China, was er als Ausdruck "
            "antiisraelischer Voreingenommenheit und unbegründeter "
            "Völkermordvorwürfe deutet, während schwerere Vergehen Chinas "
            "ignoriert würden. Die Washington Post berichtet dagegen in einer "
            "Nachrichtenmeldung von Lior Soroka über einen politischen "
            "Schlagabtausch zwischen Netanjahu und dem New Yorker "
            "Bürgermeister Mamdani wegen eines Haftbefehls des Internationalen "
            "Strafgerichtshofs, wobei Netanjahus Vorwurf, Mamdani unterstütze "
            "faktisch die Hamas, neben Mamdanis Dementi steht - ein Beitrag, "
            "der eher in der amerikanischen Innenpolitik verortet ist als in "
            "einer direkten Auseinandersetzung mit Antisemitismus. Die Welt "
            "wählt in einem von Nicholas Potter geführten Interview einen "
            "deutlich persönlicheren und moralischen Zugang: Der Vater des "
            "ermordeten israelischen Botschaftsmitarbeiters Yaron Lischinsky "
            "betont, Antisemitismus sei kein rein jüdisches, sondern ein "
            "gesellschaftliches Problem, das weltweit ernst genommen werden "
            "müsse, und fordert zugleich die Todesstrafe für den Mörder seines "
            "Sohnes. Der Beitrag des Guardian, verfasst von Nadia Khomami, "
            "berührt Antisemitismus oder Terror gegen Israel kaum unmittelbar, "
            "sondern behandelt einen Streit aus der Musikbranche, in dem "
            "Charlotte Church Ed Sheeran vorwirft, kommerzielle Interessen "
            "über eine moralische Haltung zu Gaza gestellt zu haben - eine "
            "Einordnung, die Israel-bezogene Kontroversen in einen "
            "kulturindustriellen Kontext rückt, der weit von der "
            "sicherheitspolitischen oder antisemitismuskritischen Dimension "
            "der anderen Beiträge entfernt ist. Insgesamt reicht die "
            "Berichterstattung damit von ideologischer Medienkritik über "
            "amerikanische Innenpolitik bis hin zu unmittelbarem persönlichem "
            "Zeugnis realer antisemitischer Gewalt."
        ),
    },
    2556: {
        "topic_label_de": "Russland: Putins Herrschaft und Innenpolitik",  # unchanged
        "comparison_text_he": (
            "בנושא זה מופיע מקור יחיד: מכתב למערכת The Guardian מאת מרגן "
            "מונגוש. בניגוד לביקורת המערבית הרווחת על משטרו של פוטין, מונגוש "
            "טוען כי ההנהגה הרוסית אימצה בהדרגה רפורמות דמוקרטיות, וכי לרוסים "
            "הפשוטים אין למעשה שום תיאבון למרוד בקרמלין - הם, לדבריו, נוטים "
            "באופן מסורתי לגישה פטליסטית של \"מה שיהיה יהיה\" כלפי הפוליטיקה. "
            "מאחר שזהו הקול היחיד המכסה את הנושא, אין כאן עימות בין מקורות, "
            "אלא עמדה בודדת וחריגה המבקשת להצדיק את המסלול הפוליטי הרוסי מול "
            "הביקורת המקובלת בעיתונות המערבית."
        ),
        "comparison_text_en": (
            "Coverage of this topic consists of a single voice: a letter to "
            "The Guardian from Mergen Mongush. Rather than echoing the "
            "prevailing Western criticism of Putin's rule, Mongush pushes "
            "back, arguing that Russian leaders have gradually embraced "
            "democratic reforms and that ordinary Russians harbor no real "
            "appetite for rebellion against the Kremlin, given what he "
            "describes as their long-standing fatalistic \"que será, será\" "
            "attitude toward politics. With no other source addressing the "
            "topic, there is no cross-source clash here - just a lone, "
            "contrarian defense of Russia's political trajectory set against "
            "the broader critical consensus found elsewhere in the Western "
            "press."
        ),
        "comparison_text_de": (
            "Zu diesem Thema liegt lediglich eine einzelne Stimme vor: ein "
            "Leserbrief von Mergen Mongush an The Guardian. Statt sich der "
            "verbreiteten westlichen Kritik an Putins Herrschaft anzuschließen, "
            "verteidigt Mongush den politischen Kurs Russlands und "
            "argumentiert, die russische Führung habe schrittweise "
            "demokratische Reformen übernommen. Zudem gebe es unter "
            "gewöhnlichen Russen keinerlei echten Wunsch nach Rebellion gegen "
            "den Kreml, da diese traditionell eine fatalistische, nach dem "
            "Motto \"was sein wird, wird sein\" geprägte Haltung zur Politik "
            "pflegten. Da kein weiterer Beitrag dieses Thema aufgreift, "
            "entsteht kein Vergleich zwischen mehreren Quellen - vielmehr "
            "steht hier eine einsame, gegen den kritischen Mainstream der "
            "westlichen Presse gerichtete Verteidigungsposition im Raum."
        ),
    },
}


def main():
    conn = get_connection()
    init_db(conn)

    for section_id, fields in FIXES.items():
        row = conn.execute(
            "SELECT topic_label_de, comparison_text_he, comparison_text_en, comparison_text_de "
            "FROM report_sections WHERE id = ?",
            (section_id,),
        ).fetchone()
        if row is None:
            print(f"section {section_id}: NOT FOUND - skipping")
            continue

        print(f"\n=== section {section_id} ===")
        for field, new_value in fields.items():
            old_value = row[field]
            changed = old_value != new_value
            print(f"  {field}: {'CHANGED' if changed else 'unchanged'} "
                  f"(old {len(old_value)} chars -> new {len(new_value)} chars)")

        conn.execute(
            """
            UPDATE report_sections
            SET topic_label_de = ?, comparison_text_he = ?, comparison_text_en = ?, comparison_text_de = ?
            WHERE id = ?
            """,
            (
                fields["topic_label_de"],
                fields["comparison_text_he"],
                fields["comparison_text_en"],
                fields["comparison_text_de"],
                section_id,
            ),
        )
        conn.commit()
        print(f"  WROTE section {section_id}.")

    conn.close()
    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
