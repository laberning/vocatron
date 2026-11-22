"""What the German module is checked against: public-domain words and invented ones."""

from conformance.language_kit import Fixtures

GERMAN = Fixtures(
    normalise={
        "Straße": "strasse",
        "Köpfchen": "köpfchen",
        "Schwänzchen,": "schwänzchen",
        "ÜBER": "über",
        "geht's": "gehts",
        "Bi-Ba-Butzemann": "bibabutzemann",
        "café": "cafe",
        "&": "",
        "—": "",
        "Hallo!": "hallo",
    },
    numbers={
        "0": "null",
        "1": "eins",
        "21": "einundzwanzig",
        "100": "einhundert",
        "1999": "neunzehnhundertneunundneunzig",
        "2005": "zweitausendfünf",
        "1000000": "einemillion",
        "(42)": "(zweiundvierzig)",
        "4ever": "vierever",
    },
    syllables={
        "Entchen": ["Ent", "chen"],
        "aber": ["a", "ber"],
        "Lied": ["Lied"],
        "Wasser,": ["Was", "ser,"],
        "Bi-Ba-Butzemann": ["Bi-", "Ba-", "But", "ze", "mann"],
        "Idee": ["I", "dee"],
        "ja": ["ja"],
    },
    words=["Alle", "meine", "Entchen", "schwimmen", "auf", "dem", "See", "Köpfchen", "Wasser"]
    + ["Schwänzchen", "Höh", "Hänschen", "klein", "Welt", "hinein", "Vogel", "geflogen"],
)
