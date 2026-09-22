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
    "US": {"name_en": "United States", "name_he": "ארצות הברית", "name_de": "Vereinigte Staaten"},
    "CA": {"name_en": "Canada", "name_he": "קנדה", "name_de": "Kanada"},
    "MX": {"name_en": "Mexico", "name_he": "מקסיקו", "name_de": "Mexiko"},
    # south_america (includes Central America)
    "BR": {"name_en": "Brazil", "name_he": "ברזיל", "name_de": "Brasilien"},
    "AR": {"name_en": "Argentina", "name_he": "ארגנטינה", "name_de": "Argentinien"},
    "VE": {"name_en": "Venezuela", "name_he": "ונצואלה", "name_de": "Venezuela"},
    "CO": {"name_en": "Colombia", "name_he": "קולומביה", "name_de": "Kolumbien"},
    "CL": {"name_en": "Chile", "name_he": "צ'ילה", "name_de": "Chile"},
    "PE": {"name_en": "Peru", "name_he": "פרו", "name_de": "Peru"},
    "CU": {"name_en": "Cuba", "name_he": "קובה", "name_de": "Kuba"},
    "SV": {"name_en": "El Salvador", "name_he": "אל סלוודור", "name_de": "El Salvador"},
    "PA": {"name_en": "Panama", "name_he": "פנמה", "name_de": "Panama"},
    "GT": {"name_en": "Guatemala", "name_he": "גואטמלה", "name_de": "Guatemala"},
    "HN": {"name_en": "Honduras", "name_he": "הונדורס", "name_de": "Honduras"},
    "NI": {"name_en": "Nicaragua", "name_he": "ניקרגואה", "name_de": "Nicaragua"},
    # europe (excluding Russia)
    "GB": {"name_en": "United Kingdom", "name_he": "בריטניה", "name_de": "Vereinigtes Königreich"},
    "DE": {"name_en": "Germany", "name_he": "גרמניה", "name_de": "Deutschland"},
    "FR": {"name_en": "France", "name_he": "צרפת", "name_de": "Frankreich"},
    "IT": {"name_en": "Italy", "name_he": "איטליה", "name_de": "Italien"},
    "ES": {"name_en": "Spain", "name_he": "ספרד", "name_de": "Spanien"},
    "PT": {"name_en": "Portugal", "name_he": "פורטוגל", "name_de": "Portugal"},
    "NL": {"name_en": "Netherlands", "name_he": "הולנד", "name_de": "Niederlande"},
    "BE": {"name_en": "Belgium", "name_he": "בלגיה", "name_de": "Belgien"},
    "CH": {"name_en": "Switzerland", "name_he": "שווייץ", "name_de": "Schweiz"},
    "AT": {"name_en": "Austria", "name_he": "אוסטריה", "name_de": "Österreich"},
    "SE": {"name_en": "Sweden", "name_he": "שוודיה", "name_de": "Schweden"},
    "NO": {"name_en": "Norway", "name_he": "נורווגיה", "name_de": "Norwegen"},
    "DK": {"name_en": "Denmark", "name_he": "דנמרק", "name_de": "Dänemark"},
    "FI": {"name_en": "Finland", "name_he": "פינלנד", "name_de": "Finnland"},
    "IS": {"name_en": "Iceland", "name_he": "איסלנד", "name_de": "Island"},
    "IE": {"name_en": "Ireland", "name_he": "אירלנד", "name_de": "Irland"},
    "PL": {"name_en": "Poland", "name_he": "פולין", "name_de": "Polen"},
    "CZ": {"name_en": "Czechia", "name_he": "צ'כיה", "name_de": "Tschechien"},
    "SK": {"name_en": "Slovakia", "name_he": "סלובקיה", "name_de": "Slowakei"},
    "HU": {"name_en": "Hungary", "name_he": "הונגריה", "name_de": "Ungarn"},
    "RO": {"name_en": "Romania", "name_he": "רומניה", "name_de": "Rumänien"},
    "BG": {"name_en": "Bulgaria", "name_he": "בולגריה", "name_de": "Bulgarien"},
    "GR": {"name_en": "Greece", "name_he": "יוון", "name_de": "Griechenland"},
    "UA": {"name_en": "Ukraine", "name_he": "אוקראינה", "name_de": "Ukraine"},
    "BY": {"name_en": "Belarus", "name_he": "בלארוס", "name_de": "Belarus"},
    "MD": {"name_en": "Moldova", "name_he": "מולדובה", "name_de": "Republik Moldau"},
    "RS": {"name_en": "Serbia", "name_he": "סרביה", "name_de": "Serbien"},
    "HR": {"name_en": "Croatia", "name_he": "קרואטיה", "name_de": "Kroatien"},
    # middle_east (includes Turkey and Egypt)
    "IL": {"name_en": "Israel", "name_he": "ישראל", "name_de": "Israel"},
    "PS": {"name_en": "Palestine", "name_he": "פלסטין", "name_de": "Palästina"},
    "TR": {"name_en": "Turkey", "name_he": "טורקיה", "name_de": "Türkei"},
    "IR": {"name_en": "Iran", "name_he": "איראן", "name_de": "Iran"},
    "IQ": {"name_en": "Iraq", "name_he": "עיראק", "name_de": "Irak"},
    "SY": {"name_en": "Syria", "name_he": "סוריה", "name_de": "Syrien"},
    "LB": {"name_en": "Lebanon", "name_he": "לבנון", "name_de": "Libanon"},
    "JO": {"name_en": "Jordan", "name_he": "ירדן", "name_de": "Jordanien"},
    "SA": {"name_en": "Saudi Arabia", "name_he": "ערב הסעודית", "name_de": "Saudi-Arabien"},
    "AE": {"name_en": "United Arab Emirates", "name_he": "איחוד האמירויות", "name_de": "Vereinigte Arabische Emirate"},
    "QA": {"name_en": "Qatar", "name_he": "קטאר", "name_de": "Katar"},
    "KW": {"name_en": "Kuwait", "name_he": "כווית", "name_de": "Kuwait"},
    "YE": {"name_en": "Yemen", "name_he": "תימן", "name_de": "Jemen"},
    "EG": {"name_en": "Egypt", "name_he": "מצרים", "name_de": "Ägypten"},
    # eurasia (Russia + Central Asia + Caucasus)
    "RU": {"name_en": "Russia", "name_he": "רוסיה", "name_de": "Russland"},
    "KZ": {"name_en": "Kazakhstan", "name_he": "קזחסטן", "name_de": "Kasachstan"},
    "UZ": {"name_en": "Uzbekistan", "name_he": "אוזבקיסטן", "name_de": "Usbekistan"},
    "KG": {"name_en": "Kyrgyzstan", "name_he": "קירגיזסטן", "name_de": "Kirgisistan"},
    "TJ": {"name_en": "Tajikistan", "name_he": "טג'יקיסטן", "name_de": "Tadschikistan"},
    "TM": {"name_en": "Turkmenistan", "name_he": "טורקמניסטן", "name_de": "Turkmenistan"},
    "GE": {"name_en": "Georgia", "name_he": "גאורגיה", "name_de": "Georgien"},
    "AM": {"name_en": "Armenia", "name_he": "ארמניה", "name_de": "Armenien"},
    "AZ": {"name_en": "Azerbaijan", "name_he": "אזרבייג'ן", "name_de": "Aserbaidschan"},
    # far_east (includes South Asia, per explicit decision - no separate region for it)
    "CN": {"name_en": "China", "name_he": "סין", "name_de": "China"},
    "JP": {"name_en": "Japan", "name_he": "יפן", "name_de": "Japan"},
    "KR": {"name_en": "South Korea", "name_he": "דרום קוריאה", "name_de": "Südkorea"},
    "KP": {"name_en": "North Korea", "name_he": "צפון קוריאה", "name_de": "Nordkorea"},
    "TW": {"name_en": "Taiwan", "name_he": "טייוואן", "name_de": "Taiwan"},
    "HK": {"name_en": "Hong Kong", "name_he": "הונג קונג", "name_de": "Hongkong"},
    "MN": {"name_en": "Mongolia", "name_he": "מונגוליה", "name_de": "Mongolei"},
    "VN": {"name_en": "Vietnam", "name_he": "וייטנאם", "name_de": "Vietnam"},
    "IN": {"name_en": "India", "name_he": "הודו", "name_de": "Indien"},
    "PK": {"name_en": "Pakistan", "name_he": "פקיסטן", "name_de": "Pakistan"},
    "AF": {"name_en": "Afghanistan", "name_he": "אפגניסטן", "name_de": "Afghanistan"},
    "BD": {"name_en": "Bangladesh", "name_he": "בנגלדש", "name_de": "Bangladesch"},
    "LK": {"name_en": "Sri Lanka", "name_he": "סרי לנקה", "name_de": "Sri Lanka"},
    # oceania
    "AU": {"name_en": "Australia", "name_he": "אוסטרליה", "name_de": "Australien"},
    "NZ": {"name_en": "New Zealand", "name_he": "ניו זילנד", "name_de": "Neuseeland"},
    # africa (whole continent, no internal split)
    "SD": {"name_en": "Sudan", "name_he": "סודן", "name_de": "Sudan"},
    "SS": {"name_en": "South Sudan", "name_he": "דרום סודן", "name_de": "Südsudan"},
    "NG": {"name_en": "Nigeria", "name_he": "ניגריה", "name_de": "Nigeria"},
    "ZA": {"name_en": "South Africa", "name_he": "דרום אפריקה", "name_de": "Südafrika"},
    "ET": {"name_en": "Ethiopia", "name_he": "אתיופיה", "name_de": "Äthiopien"},
    "KE": {"name_en": "Kenya", "name_he": "קניה", "name_de": "Kenia"},
    "LY": {"name_en": "Libya", "name_he": "לוב", "name_de": "Libyen"},
    "MA": {"name_en": "Morocco", "name_he": "מרוקו", "name_de": "Marokko"},
    "DZ": {"name_en": "Algeria", "name_he": "אלג'יריה", "name_de": "Algerien"},
    "TN": {"name_en": "Tunisia", "name_he": "תוניסיה", "name_de": "Tunesien"},
    "CD": {"name_en": "DR Congo", "name_he": "קונגו הדמוקרטית", "name_de": "Demokratische Republik Kongo"},
    "SO": {"name_en": "Somalia", "name_he": "סומליה", "name_de": "Somalia"},
    "MU": {"name_en": "Mauritius", "name_he": "מאוריציוס", "name_de": "Mauritius"},
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

# name_de: added 2026-09-22 for topic.html's trilingual expansion (its result-title
# rendering needs a region/conflict-zone name in whatever language the page is in) -
# COUNTRY_LIST's name_he/name_en are NOT given a name_de alongside these, since no
# in-scope page (only the homepage, which stayed bilingual) displays a country name.
REGION_LABELS = {
    "north_america": {"name_en": "North America", "name_he": "צפון אמריקה", "name_de": "Nordamerika"},
    "south_america": {
        "name_en": "South & Central America", "name_he": "דרום ומרכז אמריקה", "name_de": "Süd- und Mittelamerika",
    },
    "europe": {"name_en": "Europe", "name_he": "אירופה", "name_de": "Europa"},
    "middle_east": {"name_en": "Middle East", "name_he": "המזרח התיכון", "name_de": "Naher Osten"},
    "eurasia": {"name_en": "Eurasia", "name_he": "אירואסיה", "name_de": "Eurasien"},
    "far_east": {"name_en": "Far East", "name_he": "המזרח הרחוק", "name_de": "Ferner Osten"},
    "oceania": {"name_en": "Oceania", "name_he": "אוקיאניה", "name_de": "Ozeanien"},
    "africa": {"name_en": "Africa", "name_he": "אפריקה", "name_de": "Afrika"},
}

CONFLICT_ZONE_LABELS = {
    "israel_palestine_conflict": {
        "name_en": "Israel-Palestine Conflict",
        "name_he": "הסכסוך הישראלי-פלסטיני",
        "name_de": "Israelisch-palästinensischer Konflikt",
    },
    "iran_west_conflict": {
        "name_en": "Iran-West Conflict",
        "name_he": "העימות איראן-מערב",
        "name_de": "Konflikt zwischen Iran und dem Westen",
    },
    "russia_ukraine_conflict": {
        "name_en": "Russia-Ukraine Conflict",
        "name_he": "מלחמת רוסיה-אוקראינה",
        "name_de": "Russland-Ukraine-Krieg",
    },
}


def country_codes() -> list[str]:
    return list(COUNTRY_LIST.keys())


def country_list_prompt_text() -> str:
    return ", ".join(f"{code} ({info['name_en']})" for code, info in COUNTRY_LIST.items())
