"""Language detection, word cleanup, and leading-article removal."""
from __future__ import annotations

import re
import unicodedata

# Leading articles (definite, indefinite, partitive) per language, lowercase.
ARTICLES: dict[str, set[str]] = {
    "en": {"the", "a", "an"},
    "fr": {"le", "la", "les", "un", "une", "des", "du"},
    "es": {"el", "la", "los", "las", "lo", "un", "una", "unos", "unas"},
    "it": {"il", "lo", "la", "i", "gli", "le", "un", "uno", "una"},
    "pt": {"o", "a", "os", "as", "um", "uma", "uns", "umas"},
    "de": {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "eines"},
    "nl": {"de", "het", "een", "'t", "'n"},
    "ca": {"el", "la", "els", "les", "un", "una", "uns", "unes"},
    "sv": {"en", "ett", "den", "det", "de"},
    "da": {"en", "et", "den", "det", "de"},
    "no": {"en", "ei", "et", "den", "det", "de"},
    "ro": {"un", "o", "niște"},
    "hu": {"a", "az", "egy"},
    "el": {"ο", "η", "το", "οι", "τα", "του", "της", "των", "τον", "την", "ένας", "μία", "μια", "ένα"},
    "eo": {"la"},
    "ga": {"an", "na"},
    "cy": {"y", "yr"},
}
# Articles that elide onto the next word with an apostrophe: "L'université".
ELIDED: dict[str, tuple[str, ...]] = {
    "fr": ("l",), "it": ("l", "un", "gl"), "ca": ("l",), "en": (), "cy": (),
}
APOSTROPHES = "'’ʼ`´"

# Common function words used to identify the language of the body text.
STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "and", "of", "to", "in", "is", "for", "that", "with", "on", "will", "was", "at", "by", "has"},
    "fr": {"le", "la", "les", "et", "des", "du", "est", "pour", "dans", "que", "une", "sur", "avec", "au", "qui"},
    "es": {"el", "los", "las", "y", "del", "que", "en", "por", "con", "para", "una", "es", "se", "al"},
    "it": {"il", "gli", "e", "di", "che", "della", "per", "con", "una", "è", "del", "nel", "sono", "alla"},
    "pt": {"o", "os", "e", "do", "da", "que", "em", "para", "com", "uma", "não", "dos", "das", "ao"},
    "de": {"der", "die", "das", "und", "ist", "von", "mit", "für", "den", "ein", "eine", "nicht", "auf", "wird"},
    "nl": {"de", "het", "een", "en", "van", "is", "dat", "op", "voor", "met", "niet", "zijn", "worden"},
    "ca": {"els", "les", "i", "del", "que", "amb", "per", "una", "és", "dels", "als"},
    "sv": {"och", "att", "det", "som", "är", "för", "med", "på", "av", "till", "ett", "inte"},
    "da": {"og", "at", "det", "som", "er", "for", "med", "på", "af", "til", "et", "ikke"},
    "no": {"og", "at", "det", "som", "er", "for", "med", "på", "av", "til", "et", "ikke", "ei"},
    "ro": {"și", "în", "de", "la", "cu", "pe", "care", "este", "din", "pentru", "un", "o"},
    "hu": {"a", "az", "és", "hogy", "nem", "egy", "is", "van", "meg", "volt"},
    "el": {"και", "το", "η", "ο", "της", "του", "να", "με", "για", "την", "σε"},
}

# Tesseract model for each detectable language.
LANG_TO_TESS = {
    "en": "eng", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "de": "deu", "nl": "nld",
    "ca": "cat", "sv": "swe", "da": "dan", "no": "nor", "ro": "ron", "hu": "hun", "el": "ell",
}

ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "inc", "co", "corp", "ltd",
                 "no", "dept", "univ", "gen", "sen", "rep", "gov", "rev", "capt", "lt", "col", "mt"}

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)
_EDGE_LEAD = "\"“”„«»‹›‘’'`([{<¿¡*•·-–—"
_EDGE_TRAIL = "\"“”„«»‹›‘’'`)]}>,;:!?*•·"


def detect_language(text: str) -> tuple[str | None, float]:
    """Return (language code, how many times more stopword hits it has than the runner-up)."""
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    if len(tokens) < 20:
        return None, 0.0
    scores = {lang: sum(t in sw for t in tokens) for lang, sw in STOPWORDS.items()}
    ranked = sorted(scores, key=scores.get, reverse=True)
    best, second = scores[ranked[0]], scores[ranked[1]]
    if best < 5:
        return None, 0.0
    return ranked[0], best / max(second, 1)


def clean_word(token: str) -> str:
    """Strip surrounding quotes/punctuation; keep internal marks and abbreviation periods."""
    t = unicodedata.normalize("NFC", token)
    if t.lower() in {"'t", "'n"}:  # Dutch articles start with an apostrophe
        return t
    t = t.lstrip(_EDGE_LEAD).rstrip(_EDGE_TRAIL)
    if t.endswith("."):
        core = t.rstrip(".")
        initial = len(core) == 1 and core.isalpha()  # "J." in "J. R. Smith"
        if not ("." in core or core.lower() in ABBREVIATIONS or initial):
            t = core
    return t


def is_word(token: str) -> bool:
    return any(ch.isalnum() for ch in token)


def strip_leading_articles(words: list[str], lang: str | None) -> tuple[list[str], list[str]]:
    """Remove every leading article (stacked or elided), keeping words as printed otherwise.
    Punctuation before a removed article moves onto the next word ('"The Show' -> '"Show').
    Returns (remaining words, removed)."""
    langs = [lang] if lang else list(ARTICLES)
    articles = set().union(*(ARTICLES.get(lg, set()) for lg in langs))
    elided = set().union(*(set(ELIDED.get(lg, ())) for lg in langs))
    words, removed = list(words), []
    while words:
        w = words[0]
        if w.lower() in articles:  # covers Dutch "'t", which starts with an apostrophe
            removed.append(words.pop(0))
            continue
        lead = re.match(r"^[^\w]*", w).group(0)
        core = w[len(lead):]
        if core.lower() in articles:
            removed.append(words.pop(0))
            if lead and words:
                words[0] = lead + words[0]
            continue
        m = re.match(rf"^(\w+)[{APOSTROPHES}](\w.*)$", core)
        if m and m.group(1).lower() in elided:
            removed.append(m.group(1) + core[len(m.group(1))])
            words[0] = lead + m.group(2)
            continue
        break
    return words, removed


def capitalize_first(word: str) -> str:
    """Upper-case the first letter, leaving any leading punctuation alone ('"special' -> '"Special')."""
    for i, ch in enumerate(word):
        if ch.isalpha():
            return word[:i] + ch.upper() + word[i + 1:]
    return word
