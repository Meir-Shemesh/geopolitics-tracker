"""Fixed geographic taxonomy for geo-tagging articles (country + conflict zone).

Three closed mappings, same convention as NEWSPAPER_DISPLAY_NAMES in src/reporting/
render.py: a fixed dict as the single source of truth, injected into LLM prompts
rather than left to free-form guessing. Starting list is deliberately modest -
built from countries actually observed in real synthesized reports so far, not a
full 195-country enumeration - and meant to be extended over time as new countries
come up in real coverage.
"""

COUNTRY_LIST = {
    # north_america
    "US": {"name_en": "United States", "name_he": "ארצות הברית"},
    "CA": {"name_en": "Canada", "name_he": "קנדה"},
    "MX": {"name_en": "Mexico", "name_he": "מקסיקו"},
    # south_america (includes Central America)
    "BR": {"name_en": "Brazil", "name_he": "ברזיל"},
    "AR": {"name_en": "Argentina", "name_he": "ארגנטינה"},
    "VE": {"name_en": "Venezuela", "name_he": "ונצואלה"},
    "CO": {"name_en": "Colombia", "name_he": "קולומביה"},
    "CL": {"name_en": "Chile", "name_he": "צ'ילה"},
    "PE": {"name_en": "Peru", "name_he": "פרו"},
    "CU": {"name_en": "Cuba", "name_he": "קובה"},
    "SV": {"name_en": "El Salvador", "name_he": "אל סלוודור"},
    "PA": {"name_en": "Panama", "name_he": "פנמה"},
    "GT": {"name_en": "Guatemala", "name_he": "גואטמלה"},
    "HN": {"name_en": "Honduras", "name_he": "הונדורס"},
    "NI": {"name_en": "Nicaragua", "name_he": "ניקרגואה"},
    # europe (excluding Russia)
    "GB": {"name_en": "United Kingdom", "name_he": "בריטניה"},
    "DE": {"name_en": "Germany", "name_he": "גרמניה"},
    "FR": {"name_en": "France", "name_he": "צרפת"},
    "IT": {"name_en": "Italy", "name_he": "איטליה"},
    "ES": {"name_en": "Spain", "name_he": "ספרד"},
    "PT": {"name_en": "Portugal", "name_he": "פורטוגל"},
    "NL": {"name_en": "Netherlands", "name_he": "הולנד"},
    "BE": {"name_en": "Belgium", "name_he": "בלגיה"},
    "CH": {"name_en": "Switzerland", "name_he": "שווייץ"},
    "AT": {"name_en": "Austria", "name_he": "אוסטריה"},
    "SE": {"name_en": "Sweden", "name_he": "שוודיה"},
    "NO": {"name_en": "Norway", "name_he": "נורווגיה"},
    "DK": {"name_en": "Denmark", "name_he": "דנמרק"},
    "FI": {"name_en": "Finland", "name_he": "פינלנד"},
    "IS": {"name_en": "Iceland", "name_he": "איסלנד"},
    "IE": {"name_en": "Ireland", "name_he": "אירלנד"},
    "PL": {"name_en": "Poland", "name_he": "פולין"},
    "CZ": {"name_en": "Czechia", "name_he": "צ'כיה"},
    "SK": {"name_en": "Slovakia", "name_he": "סלובקיה"},
    "HU": {"name_en": "Hungary", "name_he": "הונגריה"},
    "RO": {"name_en": "Romania", "name_he": "רומניה"},
    "BG": {"name_en": "Bulgaria", "name_he": "בולגריה"},
    "GR": {"name_en": "Greece", "name_he": "יוון"},
    "UA": {"name_en": "Ukraine", "name_he": "אוקראינה"},
    "BY": {"name_en": "Belarus", "name_he": "בלארוס"},
    "MD": {"name_en": "Moldova", "name_he": "מולדובה"},
    "RS": {"name_en": "Serbia", "name_he": "סרביה"},
    "HR": {"name_en": "Croatia", "name_he": "קרואטיה"},
    # middle_east (includes Turkey and Egypt)
    "IL": {"name_en": "Israel", "name_he": "ישראל"},
    "PS": {"name_en": "Palestine", "name_he": "פלסטין"},
    "TR": {"name_en": "Turkey", "name_he": "טורקיה"},
    "IR": {"name_en": "Iran", "name_he": "איראן"},
    "IQ": {"name_en": "Iraq", "name_he": "עיראק"},
    "SY": {"name_en": "Syria", "name_he": "סוריה"},
    "LB": {"name_en": "Lebanon", "name_he": "לבנון"},
    "JO": {"name_en": "Jordan", "name_he": "ירדן"},
    "SA": {"name_en": "Saudi Arabia", "name_he": "ערב הסעודית"},
    "AE": {"name_en": "United Arab Emirates", "name_he": "איחוד האמירויות"},
    "QA": {"name_en": "Qatar", "name_he": "קטאר"},
    "KW": {"name_en": "Kuwait", "name_he": "כווית"},
    "YE": {"name_en": "Yemen", "name_he": "תימן"},
    "EG": {"name_en": "Egypt", "name_he": "מצרים"},
    # eurasia (Russia + Central Asia + Caucasus)
    "RU": {"name_en": "Russia", "name_he": "רוסיה"},
    "KZ": {"name_en": "Kazakhstan", "name_he": "קזחסטן"},
    "UZ": {"name_en": "Uzbekistan", "name_he": "אוזבקיסטן"},
    "KG": {"name_en": "Kyrgyzstan", "name_he": "קירגיזסטן"},
    "TJ": {"name_en": "Tajikistan", "name_he": "טג'יקיסטן"},
    "TM": {"name_en": "Turkmenistan", "name_he": "טורקמניסטן"},
    "GE": {"name_en": "Georgia", "name_he": "גאורגיה"},
    "AM": {"name_en": "Armenia", "name_he": "ארמניה"},
    "AZ": {"name_en": "Azerbaijan", "name_he": "אזרבייג'ן"},
    # far_east (includes South Asia, per explicit decision - no separate region for it)
    "CN": {"name_en": "China", "name_he": "סין"},
    "JP": {"name_en": "Japan", "name_he": "יפן"},
    "KR": {"name_en": "South Korea", "name_he": "דרום קוריאה"},
    "KP": {"name_en": "North Korea", "name_he": "צפון קוריאה"},
    "TW": {"name_en": "Taiwan", "name_he": "טייוואן"},
    "HK": {"name_en": "Hong Kong", "name_he": "הונג קונג"},
    "MN": {"name_en": "Mongolia", "name_he": "מונגוליה"},
    "VN": {"name_en": "Vietnam", "name_he": "וייטנאם"},
    "IN": {"name_en": "India", "name_he": "הודו"},
    "PK": {"name_en": "Pakistan", "name_he": "פקיסטן"},
    "AF": {"name_en": "Afghanistan", "name_he": "אפגניסטן"},
    "BD": {"name_en": "Bangladesh", "name_he": "בנגלדש"},
    "LK": {"name_en": "Sri Lanka", "name_he": "סרי לנקה"},
    # oceania
    "AU": {"name_en": "Australia", "name_he": "אוסטרליה"},
    "NZ": {"name_en": "New Zealand", "name_he": "ניו זילנד"},
    # africa (whole continent, no internal split)
    "SD": {"name_en": "Sudan", "name_he": "סודן"},
    "SS": {"name_en": "South Sudan", "name_he": "דרום סודן"},
    "NG": {"name_en": "Nigeria", "name_he": "ניגריה"},
    "ZA": {"name_en": "South Africa", "name_he": "דרום אפריקה"},
    "ET": {"name_en": "Ethiopia", "name_he": "אתיופיה"},
    "KE": {"name_en": "Kenya", "name_he": "קניה"},
    "LY": {"name_en": "Libya", "name_he": "לוב"},
    "MA": {"name_en": "Morocco", "name_he": "מרוקו"},
    "DZ": {"name_en": "Algeria", "name_he": "אלג'יריה"},
    "TN": {"name_en": "Tunisia", "name_he": "תוניסיה"},
    "CD": {"name_en": "DR Congo", "name_he": "קונגו הדמוקרטית"},
    "SO": {"name_en": "Somalia", "name_he": "סומליה"},
    "MU": {"name_en": "Mauritius", "name_he": "מאוריציוס"},
}

COUNTRY_TO_REGION = {
    "US": "north_america", "CA": "north_america", "MX": "north_america",
    "BR": "south_america", "AR": "south_america", "VE": "south_america",
    "CO": "south_america", "CL": "south_america", "PE": "south_america",
    "CU": "south_america", "SV": "south_america", "PA": "south_america",
    "GT": "south_america", "HN": "south_america", "NI": "south_america",
    "GB": "europe", "DE": "europe", "FR": "europe", "IT": "europe",
    "ES": "europe", "PT": "europe", "NL": "europe", "BE": "europe",
    "CH": "europe", "AT": "europe", "SE": "europe", "NO": "europe",
    "DK": "europe", "FI": "europe", "IS": "europe", "IE": "europe",
    "PL": "europe", "CZ": "europe", "SK": "europe", "HU": "europe",
    "RO": "europe", "BG": "europe", "GR": "europe", "UA": "europe",
    "BY": "europe", "MD": "europe", "RS": "europe", "HR": "europe",
    "IL": "middle_east", "PS": "middle_east", "TR": "middle_east",
    "IR": "middle_east", "IQ": "middle_east", "SY": "middle_east",
    "LB": "middle_east", "JO": "middle_east", "SA": "middle_east",
    "AE": "middle_east", "QA": "middle_east", "KW": "middle_east",
    "YE": "middle_east", "EG": "middle_east",
    "RU": "eurasia", "KZ": "eurasia", "UZ": "eurasia", "KG": "eurasia",
    "TJ": "eurasia", "TM": "eurasia", "GE": "eurasia", "AM": "eurasia",
    "AZ": "eurasia",
    "CN": "far_east", "JP": "far_east", "KR": "far_east", "KP": "far_east",
    "TW": "far_east", "HK": "far_east", "MN": "far_east", "VN": "far_east",
    "IN": "far_east", "PK": "far_east", "AF": "far_east", "BD": "far_east",
    "LK": "far_east",
    "AU": "oceania", "NZ": "oceania",
    "SD": "africa", "SS": "africa", "NG": "africa", "ZA": "africa",
    "ET": "africa", "KE": "africa", "LY": "africa", "MA": "africa",
    "DZ": "africa", "TN": "africa", "CD": "africa", "SO": "africa",
    "MU": "africa",
}

CONFLICT_ZONE_LABELS = {
    "israel_palestine_conflict": {
        "name_en": "Israel-Palestine Conflict",
        "name_he": "הסכסוך הישראלי-פלסטיני",
    },
    "iran_west_conflict": {
        "name_en": "Iran-West Conflict",
        "name_he": "העימות איראן-מערב",
    },
    "russia_ukraine_conflict": {
        "name_en": "Russia-Ukraine Conflict",
        "name_he": "מלחמת רוסיה-אוקראינה",
    },
}


def country_codes() -> list[str]:
    return list(COUNTRY_LIST.keys())


def country_list_prompt_text() -> str:
    return ", ".join(f"{code} ({info['name_en']})" for code, info in COUNTRY_LIST.items())
