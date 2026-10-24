"""Baked Cyrillic->MRZ transliteration table (derived empirically in S1).

Source: scripts/derive_translit.py aligned 2482 train docs (label names vs MRZ
line1 = 'PNRUS'+T(surname)+'<<'+T(first)+'<'+T(middle)+'<'-padding). The scheme
is a 1:1 per-char encoding and deviates from GOST R 52535.1 (e.g. Й->Q, Щ->W),
so the empirical table is authoritative for this dataset.

Per-letter provenance:
  - 'empirical': >=20 train observations, >=99% consistency — except Щ, see
    FLAGGED below (51/52 = 98.08%; the single runner-up '4' is Ш's code, i.e.
    a confident OCR misread of the Щ glyph in doc tr_02195; best achievable
    consistency is 69/70 = 98.6% since train contains only 70 Щ occurrences).
  - 'gost_fallback': <20 train observations, filled from GOST R 52535.1 and
    FLAGGED. Note Ъ's 4 unanimous observations say 'X', not GOST '6' — S2
    matching should treat flagged letters with extra care.

Regenerate with: python scripts/derive_translit.py
"""
import json
import os

# 33 uppercase Cyrillic letters -> MRZ char (empirical unless noted).
TRANSLIT = {
    "А": "A",
    "Б": "B",
    "В": "V",
    "Г": "G",
    "Д": "D",
    "Е": "E",
    "Ё": "E",  # gost_fallback (1 observation)
    "Ж": "J",
    "З": "Z",
    "И": "I",
    "Й": "Q",
    "К": "K",
    "Л": "L",
    "М": "M",
    "Н": "N",
    "О": "O",
    "П": "P",
    "Р": "R",
    "С": "S",
    "Т": "T",
    "У": "U",
    "Ф": "F",
    "Х": "H",
    "Ц": "C",
    "Ч": "3",
    "Ш": "4",
    "Щ": "W",  # 98.08% (51/52); flagged, see module docstring
    "Ъ": "6",  # gost_fallback (4 observations, all 'X' — flagged)
    "Ы": "Y",
    "Ь": "9",
    "Э": "6",
    "Ю": "7",
    "Я": "8",
}

# Non-letter characters occurring in label names.
SPECIAL = {"-": "<"}  # hyphen becomes '<' in the MRZ (55/55 observations)

# Letters whose mapping is NOT backed by >=20 clean observations.
FLAGGED_LETTERS = ("Ё", "Щ", "Ъ")

# Lowercase Cyrillic behaves like uppercase (labels are uppercase after norm).
for _ch in list(TRANSLIT) + list(SPECIAL):
    _low = _ch.lower()
    if _low != _ch:
        TRANSLIT[_low] = TRANSLIT[_ch]
        if _ch in SPECIAL:
            SPECIAL[_low] = SPECIAL[_ch]

_TABLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "analysis_out", "translit.json",
)


def table_matches_analysis():
    """True if the baked table equals analysis_out/translit.json (sanity)."""
    try:
        with open(_TABLE_PATH, encoding="utf-8") as fh:
            ref = json.load(fh)
    except OSError:
        return None
    upper = {k: v for k, v in TRANSLIT.items() if not k.islower()}
    upper.update(SPECIAL)
    return upper == ref


def translit_char(ch):
    """MRZ char for one Cyrillic/special char, or None if unmappable."""
    return TRANSLIT.get(ch, SPECIAL.get(ch))


def encode(name):
    """Transliterate a Cyrillic name to its MRZ form.

    Returns (encoded, unmapped): 'encoded' has '?' placeholders for unmappable
    chars, 'unmapped' lists those chars (deduplicated, in order of first use).
    Spaces encode as '<' (label names are whitespace-collapsed before this).
    """
    out, unmapped = [], []
    for ch in str(name or ""):
        if ch == " ":
            out.append("<")
            continue
        m = translit_char(ch)
        if m is None:
            if ch not in unmapped:
                unmapped.append(ch)
            out.append("?")
        else:
            out.append(m)
    return "".join(out), unmapped


def reverse_map():
    """{mrz_char: [cyrillic chars]} — decoding aid for S2 name matching.

    Ambiguous codes (e.g. '6' <- Э/Ъ, 'E' <- Е/Ё) map to a list; order follows
    TRANSLIT definition order, i.e. the more frequent letter first.
    """
    rev = {}
    for ch, m in TRANSLIT.items():
        if ch.islower():
            continue
        rev.setdefault(m, [])
        if ch not in rev[m]:
            rev[m].append(ch)
    for ch, m in SPECIAL.items():
        if not ch.islower():
            rev.setdefault(m, [])
            if ch not in rev[m]:
                rev[m].append(ch)
    return rev
