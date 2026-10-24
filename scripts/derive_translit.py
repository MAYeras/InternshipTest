#!/usr/bin/env python3
"""Derive the Cyrillic->MRZ transliteration table empirically from train data.

Method: for every train doc with a 2-line MRZ whose line1 is 44 chars, align
line1 = 'PNRUS' + T(surname) + '<<' + T(first) + '<' + T(middle) + '<'-padding
against the LABEL names. Transliteration is 1:1 per char (confirmed: Й->Q,
Ч->3, Ш->4, Ь->9, Ю->7, Я->8, Х->H, Ц->C, '-'->'<'), so aligned positions vote
Cyrillic char -> MRZ char. Docs whose '<' separators do not sit at the expected
offsets are skipped (likely OCR shift). Prints per-letter count/consistency,
writes analysis_out/translit.json ({letter: mrz_char}) plus
analysis_out/translit_details.json, and prints a Python literal for pp/translit.py.

Letters with <20 observations fall back to the RF internal-passport MRZ table
(GOST R 52535.1) and are flagged. Deterministic, stdlib only.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pp.parse import iter_jsonl, norm  # noqa: E402

DATA_TRAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "train_predictions.jsonl")
DATA_LABELS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "train_labels.jsonl")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analysis_out")

CYRILLIC = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
PREFIX_LEN = 5  # 'PNRUS'
MIN_OBS = 20
CONSISTENCY_GATE = 0.99

# RF internal-passport MRZ transliteration (GOST R 52535.1) — fallback only,
# used solely for letters the train data cannot pin down (<20 observations).
GOST_FALLBACK = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E",
    "Ж": "J", "З": "Z", "И": "I", "Й": "Q", "К": "K", "Л": "L", "М": "M",
    "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "C", "Ч": "3", "Ш": "4", "Щ": "5", "Ъ": "6",
    "Ы": "Y", "Ь": "9", "Э": "6", "Ю": "7", "Я": "8",
}
# non-letter characters seen in labels: '-' becomes '<' in the MRZ (confirmed)
SPECIAL = {"-": "<"}


def collect_votes():
    votes = {ch: collections.Counter() for ch in CYRILLIC}
    for ch in SPECIAL:
        votes[ch] = collections.Counter()
    used = skipped_sep = skipped_len = no_mrz = skipped_names = 0
    for doc in iter_jsonl(DATA_TRAIN):
        lab = LABELS.get(doc["doc_id"])
        if not lab:
            continue
        mrz = doc.get("mrz")
        if not mrz or not isinstance(mrz.get("lines"), list):
            no_mrz += 1
            continue
        lines = mrz["lines"]
        if len(lines) < 2:
            no_mrz += 1
            continue
        l1 = str(lines[0].get("text") or "")
        if len(l1) != 44:
            skipped_len += 1
            continue
        names = [norm(lab["fields"].get(k)) for k in
                 ("Last_name_ru", "First_name_ru", "Middle_name_ru")]
        if not all(names):
            skipped_names += 1  # e.g. empty Middle_name_ru in labels (~104 docs)
            continue
        nb = l1[PREFIX_LEN:]
        # expected layout: T(sur) '<<' T(first) '<' T(mid) then '<' padding
        n0, n1, n2 = (len(n) for n in names)
        p0 = n0                      # '<<' starts here
        p1 = n0 + 2 + n1             # '<' separator
        p2 = n0 + 2 + n1 + 1 + n2    # trailing '<' padding starts here
        if p2 > len(nb) or nb[p0:p0 + 2] != "<<" or nb[p1] != "<" or nb[p2:] != "<" * (len(nb) - p2):
            skipped_sep += 1
            continue
        pieces = [nb[:p0], nb[p0 + 2:p1], nb[p1 + 1:p2]]
        for name, piece in zip(names, pieces):
            if len(name) != len(piece):
                continue  # cannot happen after the checks above, kept for safety
            for cyr, m in zip(name, piece):
                if cyr in votes:
                    votes[cyr][m] += 1
        used += 1
    stats = {
        "docs_used": used, "skipped_separator": skipped_sep,
        "skipped_line1_len": skipped_len, "no_usable_mrz": no_mrz,
        "skipped_names": skipped_names, "total_docs": sum(
            1 for _ in iter_jsonl(DATA_TRAIN)),
    }
    stats["reconciled"] = (used + skipped_sep + skipped_len + no_mrz
                           + skipped_names == stats["total_docs"])
    return votes, stats


def main():
    votes, stats = collect_votes()
    table = {}
    details = {}
    fallback_letters = []
    print("alignment: {docs_used} docs used; skipped: {skipped_separator} separator "
          "mismatch, {skipped_line1_len} line1 not 44, {no_usable_mrz} no usable "
          "MRZ, {skipped_names} incomplete label names; total {total_docs} train "
          "docs, counters reconcile: {reconciled}".format(**stats))
    print()
    # Explicit fallback DECISION rule (matches the baked pp/translit.py literal):
    #   >=20 observations -> empirical winner (flagged if consistency <99%);
    #   < 20 observations -> GOST R 52535.1 fallback, flagged.
    print(f"{'letter':>7} {'count':>6} {'votes':>18} {'decision':>9} {'consist':>8}  source")
    for ch in list(CYRILLIC) + list(SPECIAL):
        total = sum(votes[ch].values())
        if total == 0:
            if ch in SPECIAL:
                # no hyphen observations at all -> rely on the confirmed mapping
                table[ch] = SPECIAL[ch]
                details[ch] = {"count": 0, "consistency": None, "mrz": table[ch],
                               "source": "confirmed_special"}
                print(f"{ch:>7} {0:>6} {'(no votes)':>18} {table[ch]:>9} {'-':>8}  "
                      "confirmed_special")
                continue
            table[ch] = GOST_FALLBACK[ch]
            details[ch] = {"count": 0, "consistency": None, "mrz": table[ch],
                           "source": "gost_fallback"}
            fallback_letters.append(ch)
            print(f"{ch:>7} {0:>6} {'(no votes)':>18} {table[ch]:>9} {'-':>8}  "
                  "gost_fallback (unseen in train)")
            continue
        top3 = ", ".join(f"{c!r}x{n}" for c, n in votes[ch].most_common(3))
        mrz_char, cnt = votes[ch].most_common(1)[0]
        consistency = cnt / total
        if total >= MIN_OBS:
            # decision: empirical winner regardless of consistency; flag if <99%
            table[ch] = mrz_char
            source = "empirical" if consistency >= CONSISTENCY_GATE else "empirical_flagged"
        else:
            # decision: GOST fallback overrides the (rare) observed votes
            table[ch] = GOST_FALLBACK.get(ch, mrz_char)
            source = "gost_fallback"
            fallback_letters.append(ch)
        details[ch] = {"count": total, "consistency": round(consistency, 6),
                       "mrz": table[ch], "source": source,
                       "votes": dict(votes[ch].most_common(5))}
        print(f"{ch:>7} {total:>6} {top3:>18} {table[ch]:>9} {consistency:>7.2%}  {source}"
              + ("" if table[ch] == mrz_char
                 else f"   [observed winner {mrz_char!r} overridden by GOST]"))

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "translit.json"), "w", encoding="utf-8") as fh:
        json.dump(table, fh, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(OUT_DIR, "translit_details.json"), "w", encoding="utf-8") as fh:
        json.dump(details, fh, ensure_ascii=False, indent=1, sort_keys=True)

    print()
    print("all letters mapped:", all(ch in table for ch in CYRILLIC))
    # Gate (controller-approved revision): every letter with >=20 observations has
    # >=98% consistency AND winner:runner-up margin >= 20:1.
    MARGIN_GATE = 20.0
    CONSISTENCY_GATE_REV = 0.98
    failures = []
    for ch in CYRILLIC:
        d = details[ch]
        if d["count"] >= MIN_OBS:
            c = votes[ch]
            (w_char, w_n), = c.most_common(1)
            runner = c.most_common(2)[1][1] if len(c) > 1 else 0
            margin = w_n / runner if runner else float("inf")
            if (d["consistency"] or 0) < CONSISTENCY_GATE_REV or margin < MARGIN_GATE:
                failures.append(f"{ch} ({d['consistency']:.2%}, margin {margin:.0f}:1)")
    if not failures:
        print(f"consistency gate (>=98% AND margin >=20:1 for >=20 obs): PASS")
    else:
        print("consistency gate (>=98% AND margin >=20:1 for >=20 obs): FAIL " + ", ".join(failures))
    print("fallback (GOST) letters (<20 obs):", " ".join(fallback_letters) or "none")
    print()
    lit = "TRANSLIT = {\n" + "".join(
        f"    {json.dumps(ch, ensure_ascii=False)}: {json.dumps(table[ch])},\n"
        for ch in CYRILLIC) + "}\n"
    print("Python literal for pp/translit.py:")
    print(lit)
    if "SPECIAL" not in table:
        print("SPECIAL = {'-': '<'}  # hyphen in names becomes '<' in MRZ (confirmed)")
    try:
        from pp.translit import TRANSLIT as BAKED, SPECIAL as BAKED_SPECIAL
        upper = {k: v for k, v in BAKED.items() if not k.islower()}
        baked = dict(upper)
        baked.update(BAKED_SPECIAL)
        print("printed literal matches baked pp/translit.py:",
              "yes" if baked == table else "NO -- RE-BAKE pp/translit.py")
    except ImportError:
        print("printed literal matches baked pp/translit.py: unknown (pp not importable)")
    return 0


LABELS = {}


def _load_labels():
    with open(DATA_LABELS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                d = json.loads(line)
                LABELS[d["doc_id"]] = d


if __name__ == "__main__":
    _load_labels()
    sys.exit(main())
