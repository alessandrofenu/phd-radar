"""Text normalisation, term matching, deadline and country detection."""
import re
import unicodedata
from datetime import date


def norm(s: str) -> str:
    """Lowercase, strip accents, turn punctuation into spaces, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w\s]|_", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


class Terms:
    """Matches a list of phrases as word prefixes in normalised text."""

    def __init__(self, terms):
        self.terms = {}
        for t in terms:
            n = norm(str(t))
            if n:
                self.terms[n] = t
        self.rx = {n: re.compile(r"(?<![a-z0-9])" + re.escape(n)) for n in self.terms}

    def found(self, normed: str):
        return [self.terms[n] for n, rx in self.rx.items() if rx.search(normed)]

    def any(self, normed: str) -> bool:
        return any(rx.search(normed) for rx in self.rx.values())


# ---------------------------------------------------------------- deadlines

MONTHS = {
    1: ["jan", "gen", "tammi"], 2: ["feb", "fev", "fév", "helmi"], 3: ["mar", "mär", "maa"],
    4: ["apr", "avr", "abr", "huhti"], 5: ["may", "mai", "mag", "mei", "maj", "mayo", "touko"],
    6: ["jun", "juin", "giu", "kesä"], 7: ["jul", "juil", "lug", "heinä"],
    8: ["aug", "aoû", "aou", "ago", "elo"], 9: ["sep", "set", "syys"],
    10: ["oct", "okt", "ott", "out", "loka"], 11: ["nov", "marras"],
    12: ["dec", "dez", "déc", "dic", "des", "joulu"],
}


def month_of(word: str):
    w = word.lower().rstrip(".")
    if w.startswith("mars") or w.startswith("marz") or w.startswith("märz"):
        return 3
    if w in ("mai",):
        return 5
    hits = [(len(p), m) for m, prefixes in MONTHS.items() for p in prefixes if w.startswith(p)]
    return max(hits)[1] if hits else None


DEADLINE_KW = re.compile(
    r"(deadline|closing date|closes on|apply by|apply before|applications? (?:must|should|will)?\s*"
    r"(?:be )?(?:received|submitted|accepted|considered)?\s*(?:by|before|until|no later than)|"
    r"bewerbungsschluss|bewerbungsfrist|einsendeschluss|bewerbungen bis|date limite|"
    r"au plus tard|scadenza|entro il|fecha l[ií]mite|plazo|s[øo]knadsfrist|sista ans[öo]kningsdag|"
    r"ans[øo]gningsfrist|sluitingsdatum|reageren kan tot|last day|application period ends|"
    r"application period closes|expires?|valid until)",
    re.I,
)
D_ISO = re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")
D_NUM = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](20\d\d)\b")
D_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th|er)?\.?\s+([A-Za-zÀ-ÿ]{3,10})\.?,?\s+(20\d\d)\b")
D_MDY = re.compile(r"\b([A-Za-zÀ-ÿ]{3,10})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b")


def _mk(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def parse_date(s: str):
    """First date found in s, or None."""
    best = None
    for rx in (D_ISO, D_NUM, D_DMY, D_MDY):
        for mt in rx.finditer(s):
            if rx is D_ISO:
                d = _mk(mt[1], mt[2], mt[3])
            elif rx is D_NUM:
                d = _mk(mt[3], mt[2], mt[1])
            elif rx is D_DMY:
                m = month_of(mt[2])
                d = _mk(mt[3], m, mt[1]) if m else None
            else:
                m = month_of(mt[1])
                d = _mk(mt[3], m, mt[2]) if m else None
            if d and (best is None or mt.start() < best[0]):
                best = (mt.start(), d)
            if d:
                break
    return best[1] if best else None


def find_deadline(text: str):
    """ISO date following a deadline-like phrase, or None."""
    for mt in DEADLINE_KW.finditer(text or ""):
        d = parse_date(text[mt.end(): mt.end() + 140])
        if d and 2000 < d.year < 2100:
            return d.isoformat()
    return None


# ---------------------------------------------------------------- countries

COUNTRIES = {
    "Austria": ["austria", "osterreich", "wien", "vienna", "graz", "innsbruck", "klosterneuburg"],
    "Belgium": ["belgium", "belgique", "belgie", "leuven", "louvain", "brussels", "bruxelles", "ghent", "gent", "antwerp"],
    "Bulgaria": ["bulgaria", "sofia"],
    "Croatia": ["croatia", "zagreb"],
    "Cyprus": ["cyprus", "nicosia"],
    "Czechia": ["czech", "czechia", "prague", "praha", "brno"],
    "Denmark": ["denmark", "danmark", "copenhagen", "kobenhavn", "aarhus", "odense"],
    "Estonia": ["estonia", "tartu", "tallinn"],
    "Finland": ["finland", "suomi", "helsinki", "aalto", "turku", "tampere", "jyvaskyla", "oulu"],
    "France": ["france", "paris", "lyon", "marseille", "toulouse", "bordeaux", "lille", "strasbourg",
               "grenoble", "montpellier", "nantes", "rennes", "nice", "dijon", "orsay", "saclay"],
    "Germany": ["germany", "deutschland", "berlin", "bonn", "munich", "munchen", "hamburg", "heidelberg",
                "munster", "regensburg", "gottingen", "karlsruhe", "leipzig", "freiburg", "frankfurt",
                "cologne", "koln", "dresden", "aachen", "bielefeld", "augsburg", "mainz", "stuttgart"],
    "Greece": ["greece", "athens", "thessaloniki", "crete"],
    "Hungary": ["hungary", "budapest", "renyi"],
    "Iceland": ["iceland", "reykjavik"],
    "Ireland": ["ireland", "dublin", "galway", "cork", "maynooth"],
    "Italy": ["italy", "italia", "roma", "rome", "milano", "milan", "pisa", "torino", "turin", "trieste",
              "sissa", "bologna", "padova", "padua", "napoli", "naples", "firenze", "florence", "genova"],
    "Latvia": ["latvia", "riga"],
    "Lithuania": ["lithuania", "vilnius"],
    "Luxembourg": ["luxembourg"],
    "Malta": ["malta"],
    "Netherlands": ["netherlands", "nederland", "holland", "amsterdam", "utrecht", "leiden", "groningen",
                    "nijmegen", "delft", "eindhoven", "radboud", "tilburg", "twente"],
    "Norway": ["norway", "norge", "oslo", "bergen", "trondheim", "ntnu", "tromso", "stavanger"],
    "Poland": ["poland", "polska", "warsaw", "warszawa", "krakow", "wroclaw", "poznan", "gdansk"],
    "Portugal": ["portugal", "lisbon", "lisboa", "porto", "coimbra", "algarve"],
    "Romania": ["romania", "bucharest", "bucuresti", "cluj"],
    "Serbia": ["serbia", "belgrade"],
    "Slovakia": ["slovakia", "bratislava"],
    "Slovenia": ["slovenia", "ljubljana"],
    "Spain": ["spain", "espana", "madrid", "barcelona", "valencia", "sevilla", "seville", "bilbao", "granada", "icmat"],
    "Sweden": ["sweden", "sverige", "stockholm", "uppsala", "lund", "gothenburg", "goteborg", "chalmers", "linkoping", "umea"],
    "Switzerland": ["switzerland", "schweiz", "suisse", "svizzera", "zurich", "geneva", "geneve", "lausanne",
                    "epfl", "eth", "basel", "bern", "fribourg", "neuchatel", "lugano"],
    "United Kingdom": ["united kingdom", "uk", "england", "scotland", "wales", "london", "oxford", "cambridge",
                       "edinburgh", "glasgow", "manchester", "durham", "warwick", "bristol", "bath", "leeds",
                       "sheffield", "nottingham", "birmingham", "southampton", "aberdeen", "st andrews",
                       "liverpool", "leicester", "exeter", "york", "lancaster", "cardiff", "belfast"],
}
_COUNTRY_RX = [(c, re.compile(r"(?<![a-z0-9])(?:" + "|".join(map(re.escape, names)) + r")(?![a-z0-9])"))
               for c, names in COUNTRIES.items()]


def find_country(text: str):
    """Country whose name (or a main city) appears earliest in text, or None."""
    t = norm(text)
    best = None
    for c, rx in _COUNTRY_RX:
        m = rx.search(t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), c)
    return best[1] if best else None
