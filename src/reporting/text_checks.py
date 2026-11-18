"""Text-quality checks shared by the daily writer (synthesize.py) and the biweekly writer (synthesize_biweekly.py).

One source for everything the two writers used to keep in two diverging copies (PROJECT_LOG: the 2026-11-15 offline
quality audit of the published text). Pure functions on strings, no I/O, no imports from the other reporting modules
(both of them import this one).

  * foreign_script_chars      characters outside Hebrew/Latin/punctuation (the daily whitelist, now used by both writers)
  * NEWSPAPER_NAME_TELLS      newspaper names written in Hebrew letters - the single merged list
  * mixed_script_words        a Hebrew letter touching a Latin letter inside one word ("נתניהu", "Süddeפ")
  * tag_fragments             markup or tool-field names inside the text ("</comparison_text_he>")
  * hebrew_letter_ratio       share of Hebrew letters among all letters of a field that should be Hebrew
  * fix_attached_prefixes     deterministic repair of a Hebrew prefix glued to a Latin name ("בSüddeutsche")
  * latin_name_form_counts    log-only counts of names without "The" and of abbreviations (never a retry)
"""
import re

# --- foreign-script whitelist --------------------------------------------------------------------------------------
# Hebrew block, printable ASCII, Latin-1/Extended-A/B, IPA + spacing modifiers, combining marks, general punctuation,
# currency, arrows, minus, bullet, bidi controls. Calibrated against the full archive (PROJECT_LOG 4.102).
_ALLOWED_TEXT_CHAR = re.compile(
    r"[֐-׿ -~ -ɏɐ-˿̀-ͯ -⁯"
    r"₠-⃏←-⇿−•‎‏‪-‮\n\r\t]"
)


def foreign_script_chars(text: str) -> list[str]:
    """Characters in text that are outside Hebrew/Latin/punctuation/digits (empty list = clean)."""
    return sorted({ch for ch in (text or "") if not _ALLOWED_TEXT_CHAR.match(ch)})


# --- newspaper names in Hebrew letters -------------------------------------------------------------------------------
# Matching is a plain substring test on the text (geresh variants normalised first). A tell is a Hebrew-letter rendering
# of a name that must stay Latin; a name written this way is a leak even when the newspaper is itself the subject of
# the story (decided 2026-11-15). Removed on purpose, after the archive audit: "טיימס" alone (Times Square, "the London
# Times"), "לוס אנג'לס" alone (the city), "וול סטריט" alone (the street / the market) and "שפיגל" alone (surnames):
# only the forms below, which name the newspaper, are kept.
NEWSPAPER_NAME_TELLS = {
    "צייטונג": "Süddeutsche Zeitung",
    "דר שפיגל": "Der Spiegel",
    "השפיגל": "Der Spiegel",
    "בשפיגל": "Der Spiegel",
    "טלגרף": "The Daily Telegraph",
    "הדיילי": "The Daily Telegraph",
    "גארדיין": "The Guardian",
    "גרדיאן": "The Guardian",
    "גארדיאן": "The Guardian",
    "גוארדיאן": "The Guardian",
    "גרדיין": "The Guardian",
    "אקונומיסט": "The Economist",
    "ג'ורנל": "The Wall Street Journal",
    "ג'רנל": "The Wall Street Journal",
    "וול סטריט ג'": "The Wall Street Journal",
    "וושינגטון פוסט": "The Washington Post",
    "לוס אנג'לס טיימס": "Los Angeles Times",
    "טודיי": "USA Today",
    "די וולט": "Die Welt",
    "די ולט": "Die Welt",
    "פרנקפורטר": "Frankfurter Allgemeine Zeitung",
    "אלגמיינ": "Frankfurter Allgemeine Zeitung",
    "נוישה": "Neue Zürcher Zeitung",
    "צירכר": "Neue Zürcher Zeitung",
    "ציריכר": "Neue Zürcher Zeitung",
    "צוריכר": "Neue Zürcher Zeitung",
    "גלוב אנד מייל": "The Globe and Mail",
    "אובזרבר": "The Observer",
    "אובסרבר": "The Observer",
    "רונדשאו": "(a newspaper named Rundschau)",
}


def hebrew_newspaper_name_tells(text: str) -> dict[str, str]:
    normalised = (text or "").replace("׳", "'").replace("’", "'")
    return {tell: name for tell, name in NEWSPAPER_NAME_TELLS.items() if tell in normalised}


# --- mixed-script words ------------------------------------------------------------------------------------------------
_HEB = "א-ת"
_LATIN = "A-Za-zÀ-ÖØ-öø-ɏ"
_LATIN_UPPER = "A-ZÀ-ÖØ-Þ"
_LETTER_RUN = re.compile(f"[{_HEB}{_LATIN}]+")
_HEB_LETTER = re.compile(f"[{_HEB}]")
_LATIN_LETTER = re.compile(f"[{_LATIN}]")
# A one- or two-letter Hebrew prefix glued to a capitalised Latin word ("בSüddeutsche", "הThe"): not a leak, repaired
# deterministically by fix_attached_prefixes() instead of by a retry.
_PREFIX_PLUS_NAME = re.compile(f"([{_HEB}]{{1,2}})([{_LATIN_UPPER}][{_LATIN}]*)")
# Two-letter Hebrew words that are not prefixes: a space, not a hyphen, belongs after them ("של Los Angeles Times").
_TWO_LETTER_WORDS = {"של", "עם", "אל", "על", "את", "אם", "או", "גם", "כי", "לא", "אז", "כל", "פי"}


def mixed_script_words(text: str) -> list[str]:
    """Words in which Hebrew and Latin letters touch ("נתניהu", "Süddeפ", "דנמark"), excluding a Hebrew prefix of one or
    two letters in front of a capitalised Latin word (handled by fix_attached_prefixes)."""
    found = []
    for run in _LETTER_RUN.findall(text or ""):
        if _HEB_LETTER.search(run) and _LATIN_LETTER.search(run) and not _PREFIX_PLUS_NAME.fullmatch(run):
            found.append(run)
    return found


def fix_attached_prefixes(text: str) -> tuple[str, int]:
    """Insert a hyphen between a Hebrew prefix and the Latin name it is glued to ("בSüddeutsche" -> "ב-Süddeutsche");
    after a two-letter Hebrew word like "של" a space instead. Returns (fixed text, number of repairs)."""
    count = 0

    def repair(match: re.Match) -> str:
        nonlocal count
        run = match.group(0)
        m = _PREFIX_PLUS_NAME.fullmatch(run)
        if not m:
            return run
        count += 1
        return m.group(1) + (" " if m.group(1) in _TWO_LETTER_WORDS else "-") + m.group(2)

    return _LETTER_RUN.sub(repair, text or ""), count


# --- markup / field names inside the text ----------------------------------------------------------------------------
_TAG_FRAGMENT = re.compile(
    r"</?[A-Za-z_][A-Za-z0-9_:-]*"                                  # "<tag", "</comparison_text_he"
    r"|\b(?:comparison_text|topic_label|overview)_(?:he|en|de)\b"      # tool-schema field names
    r"|\brecord_(?:biweekly_topic|overview|topic_comparison)\b"
)


def tag_fragments(text: str) -> list[str]:
    return [m.group(0) for m in _TAG_FRAGMENT.finditer(text or "")]


# --- language of a Hebrew field -----------------------------------------------------------------------------------------
HEBREW_RATIO_MIN = 0.35
HEBREW_RATIO_MIN_LETTERS = 40  # shorter fields are not judged: the ratio of a few letters means nothing


def hebrew_letter_ratio(text: str) -> float | None:
    """Hebrew letters / all letters. None when the text has too few letters to judge."""
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if len(letters) < HEBREW_RATIO_MIN_LETTERS:
        return None
    return sum(1 for ch in letters if "א" <= ch <= "ת") / len(letters)


def low_hebrew_ratio(text: str) -> float | None:
    """The ratio when it is below HEBREW_RATIO_MIN, else None."""
    ratio = hebrew_letter_ratio(text)
    return ratio if ratio is not None and ratio < HEBREW_RATIO_MIN else None


# --- one call for a freshly written topic ------------------------------------------------------------------------------
def writer_problems(fields: dict[str, str], hebrew_fields: tuple[str, ...] = ("comparison_text_he", "overview_he")) -> dict[str, dict]:
    """Every retry-worthy defect of the given fields, by kind: {"foreign_chars": {field: [chars]},
    "mixed_script": {field: [words]}, "tag_fragment": {field: [fragments]}, "low_hebrew_ratio": {field: ratio}}.
    Empty dict = clean. Newspaper-name tells and word ceilings are the callers' own checks."""
    out: dict[str, dict] = {}
    for field, text in fields.items():
        chars = foreign_script_chars(text)
        if chars:
            out.setdefault("foreign_chars", {})[field] = chars
        words = mixed_script_words(text)
        if words:
            out.setdefault("mixed_script", {})[field] = words
        frags = tag_fragments(text)
        if frags:
            out.setdefault("tag_fragment", {})[field] = frags
        if field in hebrew_fields:
            ratio = low_hebrew_ratio(text)
            if ratio is not None:
                out.setdefault("low_hebrew_ratio", {})[field] = round(ratio, 2)
    return out


def problems_feedback(problems: dict[str, dict]) -> str:
    """Retry feedback naming exactly what was found (one sentence per kind)."""
    parts = []
    if problems.get("foreign_chars"):
        parts.append("characters from another writing system (not Hebrew or Latin) appeared in "
                     + "; ".join(f"{f}: {''.join(c)}" for f, c in problems["foreign_chars"].items())
                     + " - keep names and words in their normal Latin or Hebrew spelling")
    if problems.get("mixed_script"):
        parts.append("Hebrew and Latin letters were fused inside one word in "
                     + "; ".join(f"{f}: {', '.join(w)}" for f, w in problems["mixed_script"].items())
                     + " - write each word entirely in one script (a foreign name in Latin letters, with a hyphen after any Hebrew prefix)")
    if problems.get("tag_fragment"):
        parts.append("markup or field names leaked into the text in "
                     + "; ".join(f"{f}: {', '.join(t)}" for f, t in problems["tag_fragment"].items())
                     + " - every field must contain only its own plain text, in its own language")
    if problems.get("low_hebrew_ratio"):
        parts.append("a Hebrew field was mostly not Hebrew ("
                     + "; ".join(f"{f}: {int(r * 100)}% Hebrew letters" for f, r in problems["low_hebrew_ratio"].items())
                     + ") - write that field in Hebrew, keeping only proper names in Latin letters")
    return "; ".join(parts)


def problem_kind(problems: dict[str, dict]) -> str:
    """The most specific log reason for a problems dict (priority order)."""
    for kind, label in (("foreign_chars", "foreign_script_chars"), ("mixed_script", "mixed_script"),
                        ("tag_fragment", "tag_fragment"), ("low_hebrew_ratio", "low_hebrew_ratio")):
        if problems.get(kind):
            return label
    return "suspicious"


# --- log-only counts of Latin name forms --------------------------------------------------------------------------------
# Decided 2026-11-15: the missing "The" ("Washington Post") and the abbreviations FAZ/NZZ/SZ are NOT checked and never
# cause a retry; German-inflected forms are not a deviation. They are only counted so a trend is visible in the log.
_NAMES_WITHOUT_THE = re.compile(
    r"(?<!The )(?<!the )(?<![A-Za-z])(?:Washington Post|Globe and Mail|Economist|Daily Telegraph|Guardian|Wall Street Journal|Observer)(?![A-Za-z])"
)
_ABBREVIATIONS = re.compile(r"\b(?:FAZ|F\.A\.Z\.|NZZ|SZ|WSJ|NYT|WaPo|LA Times)\b")


def latin_name_form_counts(text: str) -> dict[str, int]:
    return {"missing_the": len(_NAMES_WITHOUT_THE.findall(text or "")), "abbreviations": len(_ABBREVIATIONS.findall(text or ""))}
