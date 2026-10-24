"""Baked thresholds for the S2 verification engine (S3 tunes on holdout folds).

Sources: S1/S2 empirical analysis of train (see analysis_out/ and REPORT later).
All values deterministic constants — no runtime tuning.
"""
from datetime import date

# Reference "today": validity is judged against 2026-10-01 (boundary: expiry
# ON that date already counts as invalid, see pp/validity.py).
TARGET_DATE = date(2026, 10, 1)

# --- confidence floors (per-char char_conf) ---------------------------------
# viz field is "clean" only if every char conf >= floor (None conf -> dirty).
PLACE_CONF_FLOOR = 0.97      # Birth_place_ru: wrongs strongly correlate with low conf
NAME_CONF_FLOOR = 0.97       # names when no usable MRZ channel
SEX_CONF_FLOOR = 0.97        # viz sex when MRZ disagrees/absent
# MRZ sex char (line2 pos 20) is covered by NO check digit, so overriding or
# correcting the viz value from it demands near-certain char confidence
# (validated on train: final sex errors = 0 at 0.99).
SEX_MRZ_WIN_CONF = 0.99
DATE_CONF_FLOOR = 0.97       # viz date digits when MRZ disagrees/absent
CODE_CONF_FLOOR = 0.97       # viz code chars when MRZ disagrees/absent
LICENCE_CONF_FLOOR = 0.97    # viz licence digits when MRZ unreliable/absent

# --- viz<->MRZ arbitration ---------------------------------------------------
# MRZ may override a viz char only if MRZ char conf >= MRZ_WIN_CONF and the
# viz char conf at the disagreeing position is < VIZ_LOSE_CONF.
MRZ_WIN_CONF = 0.9
VIZ_LOSE_CONF = 0.9
# When both sides are confident and disagree -> undecidable -> reject (safety).
# MRZ digit #4 of the licence lives at line2 pos 28 with NO check digit cover,
# so demand more from it:
MRZ_POS28_WIN_CONF = 0.995
# MRZ region counts as reliable for a field only if its covering check digit
# validates (9 -> licence [0:9]; 19 -> birth; 42 -> issue+code; 43 composite).

# --- dates -------------------------------------------------------------------
BIRTH_YEAR_MIN, BIRTH_YEAR_MAX = 1900, 2012
ISSUE_YEAR_MIN, ISSUE_YEAR_MAX = 2000, 2026

# --- names -------------------------------------------------------------------
# MRZ pieces containing these chars cannot be reversed unambiguously.
AMBIGUOUS_MRZ_CHARS = {"6"}          # '6' <- Э or Ъ
# 'E' <- Е or Ё treated as unambiguous: Ё is GOST-fallback and ~absent in data.
NAME_ALLOWED_EXTRA = {"-", " "}      # besides Cyrillic letters; labels contain
# both ('САГИБ ОГЛЫ' spaces in patronymics, 'ТЕР-ГЕВОНДЯН' hyphens in others).
# MRZ 'E' is blind to the Е/Ё distinction (both encode 'E'), so an accepted
# name containing Ё is only trustworthy at very high per-char confidence:
# the one genuine train Ё name has conf 0.9991; all three train Ё-errors sit
# at 0.2525-0.9759. Floor chosen between those clusters.
NAME_YO_CONF_FLOOR = 0.999
# Patronymic (Middle_name_ru) must end with one of these (derived from ALL
# train labels: covers every non-empty patronymic in train).
PATRONYMIC_SUFFIXES = (
    "ОВИЧ", "ЕВИЧ", "ИЧ", "ОВНА", "ЕВНА", "ИЧНА", "ВНА", "ОГЛЫ", "КЫЗЫ", "УЛЫ",
)
# Consonant clusters never seen in any train label name (anomaly signal).
NAME_BAD_CLUSTERS = ("ССС", "ММ", "ЙЯ", "ЙЮ", "ЙЁ", "ЩЩ", "ЪЪ", "ЬЬ")

# --- licence -----------------------------------------------------------------
LICENCE_RE = r"\d{2} \d{2} \d{6}"    # emitted format; verification is digit-wise

# --- org fuzzy correction ----------------------------------------------------
# S2 baseline: EXACT match only. dist-1 correction was measured unsafe on
# train (leave-one-out): near-duplicate pool names ('ОБЛ' vs 'ОБЛ.',
# 'ОТДЕЛЕНИЕ' vs 'ОТДЕЛЕНИЕМ') sit at distance 1 and capture corrections.
# S3 may revisit loosening with extra structural constraints.
ORG_DIST_MAX_SHORT = 0              # viz -> candidate Damerau-Levenshtein
ORG_DIST_MAX_LONG = 0               # for strings longer than:
ORG_LONG_LEN = 40
# correction requires unique nearest candidate with a strict margin over the
# 2nd best (2nd_dist > best_dist).

# --- birth place structural checks (all violations -> reject) ----------------
PLACE_MIN_LEN = 8                   # shortest legit train label place
# digit surrounded by Cyrillic letters on both sides is never legit
# (checked as anomaly; standalone/-attached digits like "ЛЬВОВСКОЕ-1" are fine).
