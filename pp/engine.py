"""S2 verification engine: per-field verify/correct + accept/reject decision.

Core policy (plan/stages.md): a field may be CORRECTED only with >=2 independent
corroborating sources (MRZ check digits + format/reference constraint, MRZ +
reference pool, ...). Single-source corrections are forbidden. When viz and MRZ
both look confident and disagree the doc is REJECTED (undecidable) — a false
accept is the only fatal error, a reject is always safe.

Field pipeline order matters:
    dates -> sex -> licence -> code -> names (needs MRZ line1) -> birth place
    -> org (needs the FINAL code) -> validity gate (final birth+issue).
Every verifier returns (status, value, reason) with status in
{"ok", "corrected", "reject"}; value is the final field value or None.

decide(doc, loo_org=None) never raises on odd input (defensive Nones), but the
caller still guards with try/except -> a crashed doc is rejected, not dropped.
"""
import re
from datetime import date

from . import constants as C
from . import orgs
from .parse import norm
from .place import place_anomalies
from .translit import encode, reverse_map, FLAGGED_LETTERS
from .validity import is_valid, age_at

SEX_VALUES = ("МУЖ.", "ЖЕН.")
SEX_TO_MRZ = {"МУЖ.": "M", "ЖЕН.": "F"}
MRZ_TO_SEX = {"M": "МУЖ.", "F": "ЖЕН."}

DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
CODE_RE = re.compile(r"^\d{3}-\d{3}$")
CYR = set("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
NAME_ALLOWED = CYR | set(C.NAME_ALLOWED_EXTRA)
# charset observed across ALL train label birth places (incl. Latin, digits)
PLACE_ALLOWED = CYR | set("Ё") | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-'()/’")


def _min_conf(text, confs):
    """Min char_conf over text. None confs (joined-line spaces, missing data)
    are skipped; REAL space confs count — a low-conf space marks a possibly
    dropped character ('П ' where 'П.' belongs), see tr_01672/tr_02021."""
    worst = 1.0
    for ch, cf in zip(text, confs):
        if cf is None or isinstance(cf, bool) or not isinstance(cf, (int, float)):
            continue
        worst = min(worst, cf)
    return worst if text else 0.0


def _conf_at(text, confs, idx):
    if idx >= len(confs):
        return None
    cf = confs[idx]
    return cf if isinstance(cf, (int, float)) and not isinstance(cf, bool) else None


def _field(doc, name):
    return doc["viz"].get(name)


def _text(doc, name):
    f = _field(doc, name)
    return f["text"] if f else None


def _confs(doc, name):
    f = _field(doc, name)
    return f["char_confs"] if f else []


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------

def _century_yymmdd(raw, kind, hint_year=None, issue=None):
    """YYMMDD -> date, resolving the century unambiguously.

    Candidates = both centuries inside the kind's year range with a valid
    calendar date. Preference: the candidate matching hint_year (the viz
    date's year, when the viz date is calendar-valid); then the unique
    candidate giving a sane age at issue (14..100) against `issue`; a single
    candidate; otherwise None (ambiguous — callers must not guess, they
    reject / fall back to other checks)."""
    if raw is None or len(raw) != 6 or not raw.isdigit():
        return None
    yy, mm, dd = int(raw[0:2]), int(raw[2:4]), int(raw[4:6])
    lo, hi = (C.BIRTH_YEAR_MIN, C.BIRTH_YEAR_MAX) if kind == "birth" \
        else (C.ISSUE_YEAR_MIN, C.ISSUE_YEAR_MAX)
    cands = []
    for century in (1900, 2000):
        y = century + yy
        if lo <= y <= hi:
            try:
                cands.append(date(y, mm, dd))
            except ValueError:
                pass
    if not cands:
        return None
    if hint_year is not None:
        for c in cands:
            if c.year == hint_year:
                return c
    if issue is not None:
        sane = [c for c in cands if 14 <= age_at(c, issue) <= 100]
        if len(sane) == 1:
            return sane[0]
    if len(cands) == 1:
        return cands[0]
    return None


def _mrz_char_conf(doc, pos):
    m = doc["mrz"]
    confs = m.get("line2_confs") or []
    if pos >= len(confs):
        return None
    cf = confs[pos]
    return cf if isinstance(cf, (int, float)) and not isinstance(cf, bool) else None


def verify_date(doc, kind):
    """kind in {'birth','issue'} -> (status, 'DD.MM.YYYY', reason, date|None)."""
    fld = "Birth_date" if kind == "birth" else "Issue_date"
    lo, hi = (C.BIRTH_YEAR_MIN, C.BIRTH_YEAR_MAX) if kind == "birth" \
        else (C.ISSUE_YEAR_MIN, C.ISSUE_YEAR_MAX)
    m = doc["mrz"]
    l2_ok = m.get("line2") is not None and len(m.get("line2") or "") == 44
    check = m.get("checks", {}).get(19 if kind == "birth" else 42)
    mrz_raw = m.get("birth_raw") if kind == "birth" else m.get("issue_raw")
    mrz_positions = range(13, 19) if kind == "birth" else range(29, 35)
    mrz_reliable = l2_ok and check is True
    text = _text(doc, fld)
    vd = None
    if text:
        mt = DATE_RE.match(text)
        if mt:
            d, mo, y = map(int, mt.groups())
            try:
                vd = date(y, mo, d)
            except ValueError:
                vd = None
    # resolve the MRZ date AFTER vd exists: the viz year disambiguates the
    # century (YY 00-12 is ambiguous for birth dates), then the MRZ issue date
    mrz_issue = _century_yymmdd(m.get("issue_raw"), "issue") if l2_ok else None
    md = _century_yymmdd(mrz_raw, kind,
                         hint_year=vd.year if vd is not None else None,
                         issue=mrz_issue if kind == "birth" else None) \
        if mrz_reliable else None
    vd_ok = vd is not None and lo <= vd.year <= hi

    if vd_ok:
        if md is not None and md != vd:
            # digit-level arbitration; mrz digit i maps to text index
            ymrz = {0: 6, 1: 7, 2: 4, 3: 5, 4: 0, 5: 1}  # YYMMDD pos -> DD.MM.YYYY idx
            confs = _confs(doc, fld)
            viz_bad = mrz_bad = False
            for i in range(6):
                v_idx = ymrz[i]
                if text[v_idx] == mrz_raw[i]:
                    continue
                vc = _conf_at(text, confs, v_idx)
                mc = _mrz_char_conf(doc, list(mrz_positions)[i])
                if vc is not None and vc >= C.VIZ_LOSE_CONF and (mc is None or mc < C.MRZ_WIN_CONF):
                    viz_bad = True   # viz confident, MRZ not clearly better
                elif mc is None or mc < C.MRZ_WIN_CONF:
                    viz_bad = True
            if viz_bad:
                return "reject", None, "date_viz_mrz_conflict", None
            return "corrected", md.strftime("%d.%m.%Y"), "corrected_from_mrz", md
        if md is None:
            # no reliable MRZ say: format+range+confidence must carry the field
            confs = _confs(doc, fld)
            if _min_conf(text, confs) < C.DATE_CONF_FLOOR:
                return "reject", None, "date_low_conf_no_mrz", None
        return "ok", text, "ok", vd

    # viz unusable -> MRZ correction (check digit + calendar/range = 2 sources)
    if md is not None:
        return "corrected", md.strftime("%d.%m.%Y"), "corrected_from_mrz", md
    return "reject", None, "date_invalid_no_mrz", None


# --------------------------------------------------------------------------
# sex
# --------------------------------------------------------------------------

def verify_sex(doc):
    text = norm(_text(doc, "Sex_ru"))
    m = doc["mrz"]
    l2_ok = m.get("line2") is not None and len(m.get("line2") or "") == 44
    msex = m.get("sex") if l2_ok else None
    mconf = m.get("sex_conf") if l2_ok else None

    if text in SEX_VALUES:
        if msex in MRZ_TO_SEX:
            if SEX_TO_MRZ[text] == msex:
                return "ok", text, "ok"
            confs = _confs(doc, "Sex_ru")
            vmin = _min_conf(text, confs)
            m_ok = mconf is not None and mconf >= C.SEX_MRZ_WIN_CONF
            if m_ok and vmin < C.VIZ_LOSE_CONF:
                return "corrected", MRZ_TO_SEX[msex], "corrected_from_mrz"
            return "reject", None, "sex_viz_mrz_conflict"
        if _min_conf(text, _confs(doc, "Sex_ru")) < C.SEX_CONF_FLOOR:
            return "reject", None, "sex_low_conf_no_mrz"
        return "ok", text, "ok"

    if msex in MRZ_TO_SEX and mconf is not None and mconf >= C.SEX_MRZ_WIN_CONF:
        return "corrected", MRZ_TO_SEX[msex], "corrected_from_mrz"
    return "reject", None, "sex_invalid"


# --------------------------------------------------------------------------
# licence
# --------------------------------------------------------------------------

# mrz licence_digits10 index -> char index inside the viz 'DD DD DDDDDD' text
_LIC_MAP = (0, 1, 3, 4, 6, 7, 8, 9, 10, 11)


def verify_licence(doc):
    text = _text(doc, "Licence_number") or ""
    confs = _confs(doc, "Licence_number")
    digits = re.sub(r"\D", "", text)
    m = doc["mrz"]
    l2_ok = m.get("line2") is not None and len(m.get("line2") or "") == 44
    checks = m.get("checks", {})
    mrz10 = m.get("licence_digits10") if l2_ok else None
    base_ok = checks.get(9) is True        # covers digits 0-8
    d10_ok = checks.get(42) is True        # covers pos28 (digit 3) + issue + code

    def mrz_digit_conf(i):
        pos = i if i < 3 else (28 if i == 3 else i)  # digits 4-9 live at l2[3:9]
        pos = {0: 0, 1: 1, 2: 2, 3: 28, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8}[i]
        return _mrz_char_conf(doc, pos)

    def canonical(ds):
        return f"{ds[0:2]} {ds[2:4]} {ds[4:10]}"

    if len(digits) == 10:
        final = list(digits)
        if mrz10 is not None and base_ok:
            for i in range(10):
                if digits[i] == mrz10[i]:
                    continue
                covered = i < 9 or d10_ok
                if not covered:
                    continue  # MRZ says nothing authoritative about this digit
                vc = _conf_at(text, confs, _LIC_MAP[i])
                mc = mrz_digit_conf(i)
                need = C.MRZ_POS28_WIN_CONF if i == 3 else C.MRZ_WIN_CONF
                if vc is not None and vc >= C.VIZ_LOSE_CONF and (mc is None or mc < need):
                    return "reject", None, "licence_viz_mrz_conflict"
                if mc is None or mc < need:
                    continue
                final[i] = mrz10[i]
            result = "".join(final)
            status = "ok" if result == digits else "corrected"
            return status, canonical(result), "ok" if status == "ok" else "corrected_from_mrz"
        # no reliable MRZ: confidence floor on all digit chars
        digit_confs = [_conf_at(text, confs, _LIC_MAP[i]) for i in range(10)]
        if any(c is None or c < C.LICENCE_CONF_FLOOR for c in digit_confs):
            return "reject", None, "licence_low_conf_no_mrz"
        return "ok", canonical(digits), "ok"

    if mrz10 is not None and base_ok and d10_ok:
        return "corrected", canonical(mrz10), "corrected_from_mrz"
    if mrz10 is not None and base_ok and m.get("licence_digit10_conf") is not None \
            and m["licence_digit10_conf"] >= C.MRZ_POS28_WIN_CONF:
        return "corrected", canonical(mrz10), "corrected_from_mrz"
    return "reject", None, "licence_invalid_no_mrz"


# --------------------------------------------------------------------------
# subdivision code
# --------------------------------------------------------------------------

def verify_code(doc):
    text = _text(doc, "Issue_organisation_code") or ""
    confs = _confs(doc, "Issue_organisation_code")
    m = doc["mrz"]
    l2_ok = m.get("line2") is not None and len(m.get("line2") or "") == 44
    mrz_code = m.get("code") if l2_ok and m.get("checks", {}).get(42) is True else None
    mrz_code = mrz_code if mrz_code and orgs.known_code(mrz_code) else None

    fmt = bool(CODE_RE.match(text))
    known = fmt and orgs.known_code(text)

    if fmt and known:
        if mrz_code is not None:
            if mrz_code == text:
                return "ok", text, "ok"
            # digit-wise arbitration (positions 0-2,4-6 in text)
            for i in range(7):
                if i == 3:
                    continue
                if text[i] == mrz_code[i]:
                    continue
                vc = _conf_at(text, confs, i)
                mc = _mrz_char_conf(doc, 35 + (i if i < 3 else i - 1))
                if vc is not None and vc >= C.VIZ_LOSE_CONF and (mc is None or mc < C.MRZ_WIN_CONF):
                    return "reject", None, "code_viz_mrz_conflict"
                if mc is None or mc < C.MRZ_WIN_CONF:
                    break
            else:
                return "corrected", mrz_code, "corrected_from_mrz"
            return "reject", None, "code_viz_mrz_conflict"
        if _min_conf(text, confs) < C.CODE_CONF_FLOOR:
            return "reject", None, "code_low_conf_no_mrz"
        return "ok", text, "ok"

    if mrz_code is not None:
        return "corrected", mrz_code, "corrected_from_mrz"
    return "reject", None, "code_invalid_or_unknown"


# --------------------------------------------------------------------------
# names (needs MRZ line1)
# --------------------------------------------------------------------------

def _line1_usable(doc):
    m = doc["mrz"]
    l1 = m.get("line1")
    return l1 is not None and len(l1) == 44 and "<<" in (l1[5:] or "")


def _charset_ok(text):
    return bool(text) and all(ch in NAME_ALLOWED for ch in text)


def _reverse_name(translit_str):
    """MRZ translit -> Cyrillic, or None when any char is ambiguous/flagged."""
    rev = reverse_map()
    out = []
    for ch in transl_str_iter(translit_str):
        options = rev.get(ch)
        if not options or len(options) != 1:
            return None
        letter = options[0]
        if letter in FLAGGED_LETTERS and letter != "Щ":
            return None  # Ё/Ъ fallback mappings are not data-backed
        out.append(letter)
    return "".join(out)


def transl_str_iter(s):
    return list(s)


def _arbitrate_name(doc, field, viz_text, mrz_piece, mrz_confs_slice):
    """Per-char arbitration between one viz name and its MRZ translit piece.

    mrz_confs_slice: list of line1 confs aligned to mrz_piece chars.
    Both channels confident and disagreeing -> undecidable -> reject (the
    line1 channel has NO check digits, and tr_02597 showed a misread '<'
    winning over a perfect viz read)."""
    enc, unmapped = encode(viz_text)
    if unmapped:
        return "reject", None, "name_unmappable"
    if enc == mrz_piece:
        return "ok", viz_text, "ok"
    if len(enc) != len(mrz_piece):
        return "reject", None, "name_len_mismatch"
    if "<" in mrz_piece and " " not in viz_text and "-" not in viz_text:
        # MRZ shows a separator the viz clearly doesn't have: line1 misread
        return "reject", None, "name_line1_misread"
    confs = _confs(doc, field)
    enc_to_text = _enc_index_map(viz_text)
    fixed = list(enc)
    for i, (a, b) in enumerate(zip(enc, mrz_piece)):
        if a == b:
            continue
        vc = _conf_at(viz_text, confs, enc_to_text[i]) if enc_to_text[i] is not None else None
        mc = mrz_confs_slice[i] if i < len(mrz_confs_slice) else None
        mc = mc if isinstance(mc, (int, float)) and not isinstance(mc, bool) else None
        if vc is not None and vc >= C.VIZ_LOSE_CONF and mc is not None and mc >= C.MRZ_WIN_CONF:
            return "reject", None, "name_viz_mrz_conflict"
        if vc is not None and vc >= C.VIZ_LOSE_CONF and (mc is None or mc < C.MRZ_WIN_CONF):
            return "reject", None, "name_viz_mrz_conflict"
        if mc is None or mc < C.MRZ_WIN_CONF:
            return "reject", None, "name_mrz_weak"
        fixed[i] = b
    new_enc = "".join(fixed)
    if new_enc != mrz_piece:
        return "reject", None, "name_unresolvable"
    cyr = _reverse_name(new_enc)
    if cyr is None:
        return "reject", None, "name_reverse_ambiguous"
    return "corrected", cyr, "corrected_from_mrz"


def _enc_index_map(text):
    """Char index in text for each position of its MRZ encoding (1:1 table).

    encode() maps every char to exactly one MRZ char, so index i of the
    encoding corresponds to text index i — spaces excluded (never inside names
    here). Simple identity map with a guard for spaces."""
    out = []
    j = 0
    for ch in text:
        if ch == " ":
            continue
        out.append(j)
        j += 1
    return out


def _name_fallback(doc, field, patronymic=False):
    """No usable MRZ: charset + confidence + patronymic suffix anomaly."""
    text = _text(doc, field)
    if not _charset_ok(text):
        return "reject", None, "name_charset_no_mrz"
    if _min_conf(text, _confs(doc, field)) < C.NAME_CONF_FLOOR:
        return "reject", None, "name_low_conf_no_mrz"
    if patronymic and not any(text.endswith(s) for s in C.PATRONYMIC_SUFFIXES):
        return "reject", None, "patronymic_suffix_anomaly"
    return "ok", text, "ok"


def verify_names(doc):
    """Verify Last/First/Middle together (they share MRZ line1).

    Returns {field: (status, value, reason)}."""
    out = {}
    m = doc["mrz"]
    l1_ok = _line1_usable(doc)
    l1 = m.get("line1") or ""
    l1_confs = m.get("line1_confs") or []

    surname_piece = None
    given_piece = None
    if l1_ok:
        nb = l1[5:]
        sep = nb.find("<<")
        surname_piece = nb[:sep]
        given_piece = nb[sep + 2:].rstrip("<")

    # ---- surname ----
    surname = _text(doc, "Last_name_ru")
    if l1_ok and _charset_ok(surname):
        c1s, c1e = 5, 5 + len(surname_piece)
        out["Last_name_ru"] = _arbitrate_name(doc, "Last_name_ru", surname,
                                              surname_piece, l1_confs[c1s:c1e])
    elif l1_ok and surname_piece and not _charset_ok(surname):
        # viz surname unusable: reconstruct from MRZ only when unambiguous —
        # '<' inside the piece means hyphen/space positions we cannot place
        cyr = _reverse_name(surname_piece) if "<" not in surname_piece else None
        if cyr is not None and _charset_ok(cyr):
            out["Last_name_ru"] = ("corrected", cyr, "corrected_from_mrz")
        else:
            out["Last_name_ru"] = ("reject", None, "name_invalid_no_reverse")
    else:
        out["Last_name_ru"] = _name_fallback(doc, "Last_name_ru")

    # ---- first name ----
    first = _text(doc, "First_name_ru")
    if l1_ok and _charset_ok(first) and given_piece is not None:
        enc_first, _ = encode(first)
        out["First_name_ru"] = _arbitrate_name(doc, "First_name_ru", first,
                                               given_piece[:len(enc_first)],
                                               _given_confs(l1, l1_confs, given_piece)[:len(enc_first)]) \
            if _given_split_ok(given_piece, enc_first) else ("reject", None, "given_block_mismatch")
    elif l1_ok and given_piece:
        # reconstruct first only from a single-piece given block ('<' inside
        # means hyphen/middle boundaries we cannot resolve without viz)
        cyr = _reverse_name(given_piece) if "<" not in given_piece else None
        if cyr is not None and _charset_ok(cyr):
            out["First_name_ru"] = ("corrected", cyr, "corrected_from_mrz")
        else:
            out["First_name_ru"] = ("reject", None, "name_invalid_no_reverse")
    else:
        out["First_name_ru"] = _name_fallback(doc, "First_name_ru")

    # ---- patronymic ----
    middle = _text(doc, "Middle_name_ru")
    if l1_ok and given_piece is not None and out["First_name_ru"][0] != "reject":
        final_first = out["First_name_ru"][1]
        enc_first, _ = encode(final_first)
        if not given_piece.startswith(enc_first):
            out["Middle_name_ru"] = ("reject", None, "given_block_mismatch")
        else:
            rest = given_piece[len(enc_first):]
            if rest == "":
                out["Middle_name_ru"] = ("ok", "", "empty_confirmed_by_mrz") \
                    if not middle else ("reject", None, "middle_extra_vs_mrz")
            elif rest.startswith("<"):
                mid_piece = rest[1:]
                mid_confs = _given_confs(l1, l1_confs, given_piece)[len(enc_first) + 1:]
                if _charset_ok(middle):
                    out["Middle_name_ru"] = _arbitrate_name(
                        doc, "Middle_name_ru", middle, mid_piece, mid_confs)
                elif "<" not in mid_piece:
                    # '<' in the piece would be a space-or-hyphen we cannot
                    # resolve (labels carry BOTH 'САГИБ ОГЛЫ' and 'АДАЛАТ-ОГЛЫ')
                    cyr = _reverse_name(mid_piece)
                    if cyr is not None and _charset_ok(cyr) and \
                            any(cyr.endswith(s) for s in C.PATRONYMIC_SUFFIXES):
                        out["Middle_name_ru"] = ("corrected", cyr, "corrected_from_mrz")
                    else:
                        out["Middle_name_ru"] = ("reject", None, "name_invalid_no_reverse")
                else:
                    out["Middle_name_ru"] = ("reject", None, "name_reverse_ambiguous")
            else:
                out["Middle_name_ru"] = ("reject", None, "given_block_mismatch")
    else:
        if middle is None and not l1_ok:
            out["Middle_name_ru"] = ("reject", None, "middle_missing_no_mrz")
        else:
            out["Middle_name_ru"] = _name_fallback(doc, "Middle_name_ru", patronymic=True)

    # Е/Ё blindness: MRZ 'E' covers both letters, so an 'ok' name containing Ё
    # was NOT actually verified at that char — demand very high conf there
    # (genuine train Ё name: 0.9991; train Ё-errors: 0.2525-0.9759).
    for f in ("Last_name_ru", "First_name_ru", "Middle_name_ru"):
        st, val, _rs = out[f]
        if st == "ok" and val and "Ё" in val:
            if _min_conf(_text(doc, f) or "", _confs(doc, f)) < C.NAME_YO_CONF_FLOOR:
                out[f] = ("reject", None, "name_yo_low_conf")

    return out


def _given_confs(l1, l1_confs, given_piece):
    """line1 confs aligned to the (rstrip'd) given block chars."""
    nb = l1[5:]
    sep = nb.find("<<")
    start = 5 + sep + 2
    n = len(given_piece)
    return l1_confs[start:start + n]


def _given_split_ok(given_piece, enc_first):
    return given_piece.startswith(enc_first) and (
        len(given_piece) == len(enc_first) or given_piece[len(enc_first)] == "<")


# --------------------------------------------------------------------------
# birth place
# --------------------------------------------------------------------------

def verify_place(doc):
    text = _text(doc, "Birth_place_ru")
    if not text or len(text) < C.PLACE_MIN_LEN:
        return "reject", None, "place_too_short"
    bad = [ch for ch in text if ch not in PLACE_ALLOWED]
    if bad:
        return "reject", None, "place_charset"
    if _min_conf(text, _confs(doc, "Birth_place_ru")) < C.PLACE_CONF_FLOOR:
        return "reject", None, "place_low_conf"
    for reason in place_anomalies(text):
        return "reject", None, reason
    return "ok", text, "ok"


# --------------------------------------------------------------------------
# issuing organisation
# --------------------------------------------------------------------------

def verify_org(doc, code_value, loo=None):
    if code_value is None:
        return "reject", None, "org_no_code"
    text = norm(_text(doc, "Issue_organization_ru") or "")
    if not text:
        return "reject", None, "org_missing"
    names = orgs.names_for(code_value, loo=loo)
    if not names:
        return "reject", None, "org_pool_empty"
    if text in names:
        return "ok", text, "ok"
    dist, best, second = orgs.nearest(text, code_value, loo=loo)
    maxd = C.ORG_DIST_MAX_LONG if len(text) > C.ORG_LONG_LEN else C.ORG_DIST_MAX_SHORT
    if dist is not None and dist <= maxd and (second is None or second > dist):
        return "corrected", best, "corrected_from_reference"
    return "reject", None, "org_no_reference_match"


# --------------------------------------------------------------------------
# decision
# --------------------------------------------------------------------------

def decide(doc, loo_org=None):
    """Full pipeline for one parsed doc.

    loo_org=(code, name) drops that single train-label entry from the org pool
    (leave-one-out) so calibration on train is not leak-inflated.
    Returns {"decision", "fields", "log"}; never raises."""
    log = {}

    b_status, b_val, b_reason, b_date = verify_date(doc, "birth")
    log["Birth_date"] = (b_status, b_reason)
    i_status, i_val, i_reason, i_date = verify_date(doc, "issue")
    log["Issue_date"] = (i_status, i_reason)

    s_status, s_val, s_reason = verify_sex(doc)
    log["Sex_ru"] = (s_status, s_reason)

    l_status, l_val, l_reason = verify_licence(doc)
    log["Licence_number"] = (l_status, l_reason)

    c_status, c_val, c_reason = verify_code(doc)
    log["Issue_organisation_code"] = (c_status, c_reason)

    names = verify_names(doc)
    for f, (st, _v, rs) in names.items():
        log[f] = (st, rs)

    p_status, p_val, p_reason = verify_place(doc)
    log["Birth_place_ru"] = (p_status, p_reason)

    o_status, o_val, o_reason = verify_org(doc, c_val, loo=loo_org)
    log["Issue_organization_ru"] = (o_status, o_reason)

    valid, v_reason = (False, "dates_unresolved")
    if b_date is not None and i_date is not None:
        valid, v_reason = is_valid(b_date, i_date)
    log["validity"] = ("ok" if valid else "reject", v_reason)

    fields = {
        "Last_name_ru": names["Last_name_ru"][1],
        "First_name_ru": names["First_name_ru"][1],
        "Middle_name_ru": names["Middle_name_ru"][1],
        "Sex_ru": s_val,
        "Birth_date": b_val,
        "Birth_place_ru": p_val,
        "Issue_date": i_val,
        "Issue_organisation_code": c_val,
        "Licence_number": l_val,
        "Issue_organization_ru": o_val,
    }
    all_ok = all(st in ("ok", "corrected") for st, _ in log.values()) and valid
    return {
        "decision": "accept" if all_ok else "reject",
        "fields": fields if all_ok else None,
        "log": {k: list(v) for k, v in log.items()},
    }
