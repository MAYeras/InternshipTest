"""2x44 MRZ parsing, field extraction and ICAO 7-3-1 check digits.

Line 2 layout (0-indexed, empirically confirmed on ~2500 clean train docs):
    [0:2]   passport series, part 1 (2 digits)
    [2]     first digit of series part 2
    [3:9]   passport number (6 digits)
    [9]     check digit over [0:9]                      (ICAO 7-3-1, validates)
    [10:13] nationality, normally 'RUS'
    [13:19] birth date YYMMDD
    [19]    check digit over [13:19]                    (ICAO 7-3-1, validates)
    [20]    sex: 'M' / 'F'
    [21:28] '<' filler
    [28]    second digit of series part 2 = the licence digit missing from [0:9]
            (equals label licence digit #4 on 2628/2629 clean train docs; NOT an
            ICAO check digit: no 7-3-1 formula matches, digit distribution uniform)
    [29:35] issue date YYMMDD
    [35:41] subdivision code (6 digits)
    [41]    '<' filler
    [42]    check digit over [28:41]                    (ICAO 7-3-1, validates)
    [43]    composite check over [0:10]+[13:20]+[21:43] (ICAO 7-3-1, validates)

Line 1 layout: 'PNRUS' + translit(surname) + '<<' + translit(first) + '<'
+ translit(patronymic) + '<'-padded to 44 chars. A '-' inside a name also
becomes '<', so splitting on '<' alone cannot always separate given names.

Parsing is tolerant of malformed MRZ (null, 1 line, wrong line lengths):
fields whose offsets no longer fit come out as None, valid_structure=False.
"""
import itertools

WEIGHTS = (7, 3, 1)

# line2 offsets
OFF_LICENCE_A = (0, 3)     # series part1 (2 digits) + 1st digit of series part2
OFF_LICENCE_B = (3, 9)     # 6-digit number
POS_CHECK_9 = 9            # check of [0:9]
OFF_NATIONALITY = (10, 13)
OFF_BIRTH = (13, 19)
POS_CHECK_19 = 19          # check of [13:19]
POS_SEX = 20
OFF_FILLER_21_28 = (21, 28)
POS_28 = 28                # 2nd digit of series part 2 (licence digit #4); NOT a check digit
OFF_ISSUE = (29, 35)
OFF_CODE = (35, 41)
POS_CHECK_42 = 42          # check of [28:41]
POS_COMPOSITE_43 = 43      # check of [0:10]+[13:20]+[21:43]

LINE1_PREFIX_LEN = 5       # 'PNRUS'
LINE_LEN = 44

# check digit positions we validate, with the ranges they cover.
# 9/19/42 cover the data BEFORE the check digit; 43 is the TD3-style composite
# which includes the check digits at 9 and 19 (empirically confirmed on train).
CHECK_SPECS = {
    9: [(0, 9)],
    19: [(13, 19)],
    42: [(28, 41)],
    43: [(0, 10), (13, 20), (21, 43)],
}
# POS 28 excluded on purpose: no ICAO 7-3-1 formula found (see module docstring).


def char_value(ch):
    """ICAO 9303 numeric value: '<'=0, '0'-'9'=0-9, 'A'-'Z'=10-35, else None."""
    if ch == "<":
        return 0
    if "0" <= ch <= "9":
        return int(ch)
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A") + 10
    return None


def check_digit(s):
    """ICAO 7-3-1 check digit of s, or None if s contains a non-MRZ char."""
    total = 0
    for ch, w in zip(s, itertools.cycle(WEIGHTS)):
        v = char_value(ch)
        if v is None:
            return None
        total += v * w
    return total % 10


def _mean(nums):
    nums = [n for n in nums if isinstance(n, (int, float)) and not isinstance(n, bool)]
    return sum(nums) / len(nums) if nums else None


def _slice(line, a, b):
    return line[a:b] if isinstance(line, str) and len(line) >= b else None


def _conf_range(char_conf, a, b):
    if not isinstance(char_conf, (list, tuple)) or len(char_conf) < b:
        return None
    return _mean(char_conf[a:b])


def _parse_yymmdd(raw):
    """YYMMDD -> {'raw','yy','mm','dd'} or None if not 6 digits. Century is
    resolved later (S2 validity logic), raw digits are kept for comparisons."""
    if raw is None or len(raw) != 6 or not raw.isdigit():
        return None
    return {"raw": raw, "yy": int(raw[0:2]), "mm": int(raw[2:4]), "dd": int(raw[4:6])}


def parse_mrz(mrz_obj):
    """Parse the raw mrz object of one prediction into a normalized dict.

    Never raises; malformed structures degrade to Nones / valid_structure=False.
    """
    out = {
        "present": mrz_obj is not None,
        "lines": [],
        "n_lines": 0,
        "valid_structure": False,
        "line1": None,
        "line2": None,
        "line1_confs": [],
        "line2_confs": [],
        "line1_conf": None,
        "line2_conf": None,
        "names_block": None,   # line1[5:] incl. padding
        "surname_translit": None,
        "given_translit": None,  # everything between '<<' and trailing padding
        "licence_digits": None,  # 9 chars: series part1 + 1 digit + number
        "licence_all_digits": False,
        "licence_conf": None,
        "licence_digit10": None,   # l2[28]: series part2 digit 2 (digit #4 of the label layout)
        "licence_digit10_conf": None,
        "licence_digits10": None,  # full 10 digits in label order when all present
        "birth_raw": None,
        "birth": None,          # {'raw','yy','mm','dd'}
        "birth_conf": None,
        "issue_raw": None,
        "issue": None,
        "issue_conf": None,
        "sex": None,            # 'M' / 'F' / whatever char / None
        "sex_conf": None,
        "code_raw": None,
        "code": None,           # formatted 'XXX-XXX' when 6 digits
        "code_conf": None,
        "checks": {},           # {pos: True/False/None} for pos in CHECK_SPECS
        "checks_ok": 0,
        "checks_total": 0,
    }
    if not isinstance(mrz_obj, dict):
        return out
    raw_lines = mrz_obj.get("lines")
    if not isinstance(raw_lines, list):
        raw_lines = []
    texts, confs = [], []
    for ln in raw_lines:
        if not isinstance(ln, dict):
            continue
        texts.append(str(ln.get("text") or ""))
        cc = ln.get("char_conf")
        confs.append(cc if isinstance(cc, list) else [])
    out["lines"] = texts
    out["n_lines"] = len(texts)
    out["valid_structure"] = len(texts) == 2 and all(len(t) == LINE_LEN for t in texts)
    if not texts:
        return out

    l1, c1 = texts[0], confs[0]
    out["line1"] = l1
    out["line1_confs"] = c1
    out["line1_conf"] = _mean(c1)
    nb = _slice(l1, LINE1_PREFIX_LEN, LINE_LEN)
    if nb is not None:
        out["names_block"] = nb
        sep = nb.find("<<")
        if sep >= 0:
            out["surname_translit"] = nb[:sep]
            given = nb[sep + 2:]
            out["given_translit"] = given.rstrip("<") or None
        else:
            # no double filler found: treat everything as surname-ish
            out["surname_translit"] = nb.rstrip("<") or None

    if len(texts) >= 2:
        l2, c2 = texts[1], confs[1]
        out["line2"] = l2
        out["line2_confs"] = c2
        out["line2_conf"] = _mean(c2)
        a = _slice(l2, *OFF_LICENCE_A)
        b = _slice(l2, *OFF_LICENCE_B)
        if a is not None and b is not None:
            lic = a + b
            out["licence_digits"] = lic
            out["licence_all_digits"] = len(lic) == 9 and lic.isdigit()
            out["licence_conf"] = _conf_range(c2, 0, 9)
        d10 = l2[POS_28] if len(l2) > POS_28 else None
        out["licence_digit10"] = d10 if (d10 is not None and d10.isdigit()) else None
        out["licence_digit10_conf"] = _conf_range(c2, POS_28, POS_28 + 1)
        if out["licence_digits"] is not None and out["licence_digit10"] is not None \
                and out["licence_all_digits"]:
            out["licence_digits10"] = (out["licence_digits"][:3] + out["licence_digit10"]
                                       + out["licence_digits"][3:])
        out["birth_raw"] = _slice(l2, *OFF_BIRTH)
        out["birth"] = _parse_yymmdd(out["birth_raw"])
        out["birth_conf"] = _conf_range(c2, *OFF_BIRTH)
        out["issue_raw"] = _slice(l2, *OFF_ISSUE)
        out["issue"] = _parse_yymmdd(out["issue_raw"])
        out["issue_conf"] = _conf_range(c2, *OFF_ISSUE)
        out["sex"] = l2[POS_SEX] if len(l2) > POS_SEX else None
        out["sex_conf"] = _conf_range(c2, POS_SEX, POS_SEX + 1)
        out["code_raw"] = _slice(l2, *OFF_CODE)
        out["code_conf"] = _conf_range(c2, *OFF_CODE)
        if out["code_raw"] is not None and len(out["code_raw"]) == 6 and out["code_raw"].isdigit():
            out["code"] = out["code_raw"][:3] + "-" + out["code_raw"][3:]

        # ICAO 7-3-1 check digits (positions 9, 19, 42, 43)
        for pos, ranges in CHECK_SPECS.items():
            pieces = [_slice(l2, a, b) for a, b in ranges]
            expected = l2[pos] if len(l2) > pos else None
            if None in pieces or expected is None or not expected.isdigit():
                out["checks"][pos] = None
                continue
            want = check_digit("".join(pieces))
            out["checks"][pos] = bool(want is not None and want == int(expected))
        vals = [v for v in out["checks"].values() if v is not None]
        out["checks_ok"] = sum(1 for v in vals if v)
        out["checks_total"] = len(vals)
    return out
