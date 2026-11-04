"""Country aliases for the conservative trends display (PROJECT_LOG 4.122).

A country counts in an article only if its name (English or German), a clear alias (capital, government
metonym such as Kremlin or Beijing) or its adjective/demonym (iranisch, Iranian) appears in the article's
headline, stance summary or key excerpt. Heads of government and parties are deliberately NOT aliases: they
are time-dependent, and in the Haiku pilot (300 articles) they added almost nothing beyond "Trump".

The matching is a lower bound by design (false negative preferred over false positive): it only ever
filters tags the analysis model already assigned, it never adds a country.

Matching is case-sensitive for proper nouns, word-bounded, tolerant of a German genitive "-s" and English
possessive. German adjectives are listed lower-case and also match capitalised at a headline start.
"""

import re

# Names, capitals and government metonyms. Words that are ambiguous in running text are either left out (a bare
# Georgia, Lima, Santiago, Sofia) or accepted knowingly (Paris also matches the Paris Agreement, Washington the state).
NAME_ALIASES = {
    "US": ["United States", r"U\.S\.", "US", "USA", "Vereinigte Staaten", "America", "Amerika", "Washington(?! Post)", "White House", "Weißes Haus", "Pentagon", "Capitol Hill"],
    "CA": ["Canada", "Kanada", "Ottawa"],
    "MX": ["Mexico", "Mexiko", "Mexiko-Stadt"],
    "BR": ["Brazil", "Brasilien", "Brasília", "Brasilia"],
    "AR": ["Argentina", "Argentinien", "Buenos Aires"],
    "VE": ["Venezuela", "Caracas"],
    "CO": ["Colombia", "Kolumbien", "Bogotá", "Bogota"],
    "CL": ["Chile"],
    "PE": ["Peru"],
    "CU": ["Cuba", "Kuba", "Havana", "Havanna"],
    "SV": ["El Salvador", "San Salvador"],
    "PA": ["Panama", "Panamá"],
    "GT": ["Guatemala"],
    "HN": ["Honduras", "Tegucigalpa"],
    "NI": ["Nicaragua", "Managua"],
    "GB": ["United Kingdom", "UK", "Britain", "Great Britain", "Großbritannien", "Vereinigtes Königreich", "London", "Westminster", "Downing Street", "Whitehall"],
    "DE": ["Germany", "Deutschland", "Berlin", "Bundesregierung", "Bundestag"],
    "FR": ["France", "Frankreich", "Paris", "Élysée", "Elysee", "Quai d'Orsay"],
    "IT": ["Italy", "Italien", "Rome", "Palazzo Chigi"],
    "ES": ["Spain", "Spanien", "Madrid"],
    "PT": ["Portugal", "Lisbon", "Lissabon"],
    "NL": ["Netherlands", "Niederlande", "Holland", "Amsterdam"],
    "BE": ["Belgium", "Belgien"],
    "CH": ["Switzerland", "Schweiz", "Bern"],
    "AT": ["Austria", "Österreich", "Vienna", "Wien"],
    "SE": ["Sweden", "Schweden", "Stockholm"],
    "NO": ["Norway", "Norwegen", "Oslo"],
    "DK": ["Denmark", "Dänemark", "Copenhagen", "Kopenhagen"],
    "FI": ["Finland", "Finnland", "Helsinki"],
    "IS": ["Iceland", "Reykjavik", "Island(?!s)"],
    "IE": ["Ireland", "Irland", "Dublin"],
    "PL": ["Poland", "Polen", "Warsaw", "Warschau"],
    "CZ": ["Czechia", "Czech Republic", "Tschechien", "Prague", "Prag"],
    "SK": ["Slovakia", "Slowakei", "Bratislava"],
    "HU": ["Hungary", "Ungarn", "Budapest"],
    "RO": ["Romania", "Rumänien", "Bucharest", "Bukarest"],
    "BG": ["Bulgaria", "Bulgarien"],
    "GR": ["Greece", "Griechenland", "Athens", "Athen"],
    "UA": ["Ukraine", "Kyiv", "Kiev", "Kiew", "Kyjiw"],
    "BY": ["Belarus", "Weißrussland", "Minsk"],
    "MD": ["Moldova", "Republik Moldau", "Chisinau"],
    "RS": ["Serbia", "Serbien", "Belgrade", "Belgrad"],
    "HR": ["Croatia", "Kroatien", "Zagreb"],
    "IL": ["Israel", "Jerusalem", "Tel Aviv", "Knesset", "IDF"],
    "PS": ["Palestine", "Palästina", "Gaza", "West Bank", "Westjordanland", "Ramallah"],
    "TR": ["Turkey", "Türkei", "Türkiye", "Ankara"],
    "IR": ["Iran", "Tehran", "Teheran"],
    "IQ": ["Iraq", "Irak", "Baghdad", "Bagdad"],
    "SY": ["Syria", "Syrien", "Damascus", "Damaskus"],
    "LB": ["Lebanon", "Libanon", "Beirut"],
    "JO": ["Jordan", "Jordanien", "Amman"],
    "SA": ["Saudi Arabia", "Saudi-Arabien", "Riyadh", "Riad"],
    "AE": ["United Arab Emirates", "UAE", "Vereinigte Arabische Emirate", "Abu Dhabi", "Dubai"],
    "QA": ["Qatar", "Katar", "Doha"],
    "KW": ["Kuwait"],
    "YE": ["Yemen", "Jemen", "Sanaa"],
    "EG": ["Egypt", "Ägypten", "Cairo", "Kairo"],
    "RU": ["Russia", "Russland", "Moscow", "Moskau", "Kremlin", "Kreml"],
    "KZ": ["Kazakhstan", "Kasachstan", "Astana"],
    "UZ": ["Uzbekistan", "Usbekistan", "Tashkent"],
    "KG": ["Kyrgyzstan", "Kirgisistan", "Bishkek"],
    "TJ": ["Tajikistan", "Tadschikistan", "Dushanbe"],
    "TM": ["Turkmenistan", "Ashgabat"],
    "GE": ["Tbilisi", "Georgian Dream", "Georgien"],
    "AM": ["Armenia", "Armenien", "Yerevan", "Jerewan"],
    "AZ": ["Azerbaijan", "Aserbaidschan", "Baku"],
    "CN": ["China", "Beijing", "Peking", "PRC"],
    "JP": ["Japan", "Tokyo"],
    "KR": ["South Korea", "Südkorea", "Seoul"],
    "KP": ["North Korea", "Nordkorea", "Pyongyang", "Pjöngjang"],
    "TW": ["Taiwan", "Taipei"],
    "HK": ["Hong Kong", "Hongkong"],
    "MN": ["Mongolia", "Mongolei", "Ulaanbaatar"],
    "VN": ["Vietnam", "Hanoi"],
    "IN": ["India", "Indien", "New Delhi", "Neu-Delhi"],
    "PK": ["Pakistan", "Islamabad"],
    "AF": ["Afghanistan", "Kabul"],
    "BD": ["Bangladesh", "Bangladesch", "Dhaka"],
    "LK": ["Sri Lanka"],
    "AU": ["Australia", "Australien", "Canberra"],
    "NZ": ["New Zealand", "Neuseeland"],
    "SD": [r"(?<!South )(?<!Süd)Sudan", "Khartoum"],
    "SS": ["South Sudan", "Südsudan", "Juba"],
    "NG": ["Nigeria", "Abuja", "Lagos"],
    "ZA": ["South Africa", "Südafrika", "Pretoria"],
    "ET": ["Ethiopia", "Äthiopien", "Addis Ababa"],
    "KE": ["Kenya", "Kenia", "Nairobi"],
    "LY": ["Libya", "Libyen", "Tripoli"],
    "MA": ["Morocco", "Marokko", "Rabat"],
    "DZ": ["Algeria", "Algerien", "Algiers"],
    "TN": ["Tunisia", "Tunesien", "Tunis"],
    "CD": ["DR Congo", "Democratic Republic of Congo", "Democratic Republic of the Congo", "Demokratische Republik Kongo", "Kinshasa", "Congo", "Kongo"],
    "SO": ["Somalia", "Mogadishu", "Mogadischu"],
    "MU": ["Mauritius"],
}

# Adjectives / demonyms, English and German. Matched as a prefix with up to 4 trailing letters (iranischen).
DEMONYMS = {
    "US": ["American", "Amerikaner", "amerikanisch"], "CA": ["Canadian", "kanadisch"], "MX": ["Mexican", "mexikanisch"],
    "BR": ["Brazilian", "brasilianisch"], "AR": ["Argentin", "argentinisch"], "VE": ["Venezuelan", "venezolanisch"],
    "CO": ["Colombian", "kolumbianisch"], "CU": ["Cuban", "kubanisch"], "GB": ["British", "Briten", "britisch"],
    "DE": ["German", "deutsch", "Deutsche"], "FR": ["French", "französisch", "Franzos"], "IT": ["Italian", "italienisch"],
    "ES": ["Spanish", "spanisch"], "PT": ["Portuguese", "portugiesisch"], "NL": ["Dutch", "niederländisch"],
    "BE": ["Belgian", "belgisch"], "CH": ["Swiss", "schweizerisch", "Schweizer"], "AT": ["Austrian", "österreichisch"],
    "SE": ["Swedish", "schwedisch"], "NO": ["Norwegian", "norwegisch"], "DK": ["Danish", "dänisch"], "FI": ["Finnish", "finnisch"],
    "IE": ["Irish", "irisch"], "PL": ["Polish", "polnisch"], "CZ": ["Czech", "tschechisch"], "HU": ["Hungarian", "ungarisch"],
    "RO": ["Romanian", "rumänisch"], "GR": ["Greek", "griechisch"], "UA": ["Ukrainian", "ukrainisch"], "BY": ["Belarusian", "belarussisch"],
    "RS": ["Serbian", "serbisch"], "IL": ["Israeli", "israelisch"], "PS": ["Palestinian", "palästinensisch"],
    "TR": ["Turkish", "türkisch"], "IR": ["Iranian", "iranisch"], "IQ": ["Iraqi", "irakisch"], "SY": ["Syrian", "syrisch"],
    "LB": ["Lebanese", "libanesisch"], "SA": ["Saudi", "saudisch"], "EG": ["Egyptian", "ägyptisch"], "RU": ["Russian", "russisch"],
    "GE": ["Georgian", "georgisch"], "AM": ["Armenian", "armenisch"], "AZ": ["Azerbaijani", "aserbaidschanisch"],
    "CN": ["Chinese", "chinesisch"], "JP": ["Japanese", "japanisch"], "KR": ["South Korean", "südkoreanisch"],
    "KP": ["North Korean", "nordkoreanisch"], "TW": ["Taiwanese", "taiwanisch"], "IN": ["Indian", "indisch"],
    "PK": ["Pakistani", "pakistanisch"], "AF": ["Afghan", "afghanisch"], "AU": ["Australian", "australisch"],
    "NZ": ["New Zealand", "neuseeländisch"], "SD": ["Sudanese", "sudanesisch"], "NG": ["Nigerian", "nigerianisch"],
    "ZA": ["South African", "südafrikanisch"], "ET": ["Ethiopian", "äthiopisch"], "LY": ["Libyan", "libysch"],
    "YE": ["Yemeni", "jemenitisch"],
}


def _word_rx(words: list[str], suffix: str = "") -> "re.Pattern[str]":
    return re.compile(r"(?<![\w-])(?:%s)%s(?![\w])" % ("|".join(words), suffix))


def _cap(word: str) -> str:
    """German adjectives are stored lower-case but appear capitalised at a sentence or headline start."""
    return "[%s%s]%s" % (word[0].upper(), word[0], word[1:]) if word[0].islower() else word


_NAME_RX = {code: _word_rx(words, "s?") for code, words in NAME_ALIASES.items()}
_DEMONYM_RX = {code: re.compile(r"(?<![\w])(?:%s)\w{0,4}" % "|".join(_cap(w) for w in words)) for code, words in DEMONYMS.items()}


def named_countries(text: str) -> set[str]:
    """ISO codes of the countries named in text (name, capital, government alias or demonym)."""
    found = {code for code, rx in _NAME_RX.items() if rx.search(text)}
    found |= {code for code, rx in _DEMONYM_RX.items() if rx.search(text)}
    return found


SEP = " \n "


def article_text(headline: str | None, stance_summary: str | None, key_excerpt: str | None) -> str:
    """The three fields the rule reads - nothing else of the article is consulted."""
    return SEP.join(part or "" for part in (headline, stance_summary, key_excerpt))
