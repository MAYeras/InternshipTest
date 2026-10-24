#!/usr/bin/env python3
"""S1 gate: agreement of MRZ-extracted values with train LABELS + check-digit study.

Scope: train docs whose MRZ is a clean 2x44 (structure-valid). For each metric
the denominator is docs where both MRZ side and label side are computable.

Metrics (gates from plan/stages.md):
  birth    >=98%   MRZ [13:19] YYMMDD vs label Birth_date DD.MM.YYYY
  issue    >=97%   MRZ [29:35]         vs label Issue_date
  sex      >=99%   MRZ [20] M/F        vs label Sex_ru МУЖ./ЖЕН.
  code     >=97%   MRZ [35:41] as XXX-XXX vs label Issue_organisation_code
  licence9 >=96%   MRZ 9 digits [0:3]+[3:9] vs label Licence_number
                  (label digit #4 — series part2 digit 2 — is not in [0:9];
                   it lives at position 28, see pos28 finding below)

Check digits (ICAO 7-3-1, weights 7,3,1, 0-9/A-Z/<): reports which of the
candidate positions 9/19/28/42/43 validate and over what fraction of docs.
Position 28 gets a brute-force sweep over every contiguous 7-3-1 range on
either side of it plus standard composite variants.
Deterministic, stdlib only, writes nothing.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pp.mrz import check_digit  # noqa: E402
from pp.parse import iter_jsonl, parse_doc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "data", "train_predictions.jsonl")
LABELS = os.path.join(ROOT, "data", "train_labels.jsonl")

GATES = [("birth", 0.98), ("issue", 0.97), ("sex", 0.99), ("code", 0.97), ("licence9", 0.96)]


def load_labels():
    lab = {}
    with open(LABELS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                d = json.loads(line)
                lab[d["doc_id"]] = d["fields"]
    return lab


def date_agrees(label_date, raw):
    """label 'DD.MM.YYYY' vs MRZ 'YYMMDD' (century-independent comparison)."""
    if not isinstance(label_date, str) or len(label_date) < 10 or not isinstance(raw, str):
        return None
    return label_date[0:2] == raw[4:6] and label_date[3:5] == raw[2:4] and label_date[8:10] == raw[0:2]


def sex_char(label_sex):
    if not isinstance(label_sex, str) or not label_sex:
        return None
    if label_sex.upper().startswith("М"):
        return "M"
    if label_sex.upper().startswith("Ж"):
        return "F"
    return None


def label_digits(licence):
    return "".join(ch for ch in (licence or "") if ch.isdigit())


def sweep_pos28(lines2):
    """Try every plausible 7-3-1 input for the digit at position 28.

    Candidates: each contiguous range ending at 28 ([a:28]) or starting at 29
    ([29:b]), plus composite concatenations of the major blocks. Returns the
    best (match_fraction, description) over docs where the candidate computes.
    """
    cands = {}
    for a in range(0, 28):
        cands["[%d:28]" % a] = lambda l2, a=a: l2[a:28]
    for b in range(30, 45):
        cands["[29:%d]" % b] = lambda l2, b=b: l2[29:b]
    cands["composite [0:10]+[13:20]+[21:28]"] = lambda l2: l2[0:10] + l2[13:20] + l2[21:28]
    cands["composite [0:9]+[13:19]+[21:28]"] = lambda l2: l2[0:9] + l2[13:19] + l2[21:28]
    cands["composite [21:28]+[29:35]"] = lambda l2: l2[21:28] + l2[29:35]
    best = (0.0, None)
    results = []
    for desc, fn in cands.items():
        ok = n = 0
        for l2 in lines2:
            want = check_digit(fn(l2))
            got = l2[28]
            if want is not None and got.isdigit():
                n += 1
                ok += want == int(got)
        if n:
            frac = ok / n
            results.append((frac, desc, ok, n))
            if frac > best[0]:
                best = (frac, desc)
    results.sort(reverse=True)
    return best, results[:3]


def main():
    labels = load_labels()
    agree = Counter()
    total = Counter()
    check_ok = Counter()
    check_n = Counter()
    pos28_char = Counter()
    lines2 = []
    for doc in iter_jsonl(TRAIN):
        m = parse_doc(doc)["mrz"]
        if not m["valid_structure"]:
            continue
        lf = labels.get(doc["doc_id"])
        if not lf:
            continue
        total["docs"] += 1
        l2 = m["line2"]
        lines2.append(l2)

        a = date_agrees(lf.get("Birth_date"), m["birth_raw"])
        if a is not None:
            total["birth"] += 1
            agree["birth"] += a
        a = date_agrees(lf.get("Issue_date"), m["issue_raw"])
        if a is not None:
            total["issue"] += 1
            agree["issue"] += a
        sc = sex_char(lf.get("Sex_ru"))
        if sc is not None and m["sex"] is not None:
            total["sex"] += 1
            agree["sex"] += sc == m["sex"]
        lc = lf.get("Issue_organisation_code")
        if isinstance(lc, str) and m["code"] is not None:
            total["code"] += 1
            agree["code"] += lc == m["code"]
        ld = label_digits(lf.get("Licence_number"))
        m9 = m["licence_digits"]
        if len(ld) == 10 and m9 is not None and len(m9) == 9 and m9.isdigit():
            total["licence9"] += 1
            agree["licence9"] += (ld[0:3] == m9[0:3] and ld[4:10] == m9[3:9])
        if m["licence_digit10"] is not None:
            pos28_char[m["licence_digit10"]] += 1
            if len(ld) == 10:
                total["licence10"] += 1
                agree["licence10"] += ld[3] == m["licence_digit10"]

        # ICAO 7-3-1 check digits, independently recomputed here.
        specs = {
            9: [(0, 9)],
            19: [(13, 19)],
            42: [(28, 41)],
            43: [(0, 10), (13, 20), (21, 43)],
        }
        for pos, ranges in specs.items():
            s = "".join(l2[a:b] for a, b in ranges)
            want = check_digit(s)
            got = l2[pos]
            if want is not None and got.isdigit():
                check_n[pos] += 1
                check_ok[pos] += want == int(got)
        # pos 42 control variant: check over [29:41] instead of [28:41]
        want = check_digit(l2[29:41])
        if want is not None and l2[42].isdigit():
            check_n["42v"] += 1
            check_ok["42v"] += want == int(l2[42])

    n = total["docs"]
    print("train docs with clean 2x44 MRZ: n=%d" % n)
    print()
    all_pass = True
    for key, gate in GATES:
        rate = agree[key] / total[key] if total[key] else 0.0
        status = "PASS" if rate >= gate else "FAIL"
        all_pass = all_pass and rate >= gate
        print("%-9s %5d/%-5d = %5.1f%%   [gate >=%.0f%%: %s]"
              % (key, agree[key], total[key], rate * 100, gate * 100, status))
    rate = agree["licence10"] / total["licence10"] if total["licence10"] else 0.0
    print("%-9s %5d/%-5d = %5.2f%%  [info: MRZ pos28 == label licence digit #4]"
          % ("licence10", agree["licence10"], total["licence10"], rate * 100))
    print("all agreement gates pass:", "yes" if all_pass else "NO")
    print()

    print("check digits (ICAO 7-3-1, weights 7/3/1):")
    desc = {
        9: "over [0:9]",
        19: "over [13:19]",
        42: "over [28:41]",
        "42v": "over [29:41] (control variant)",
        43: "composite [0:10]+[13:20]+[21:43]",
    }
    for pos in (9, 19, 42, "42v", 43):
        frac = check_ok[pos] / check_n[pos] if check_n[pos] else 0.0
        verdict = "VALIDATES" if frac >= 0.95 else "does not validate"
        print("  pos %-3s %-32s %5d/%-5d = %5.1f%%  %s"
              % (pos, desc[pos], check_ok[pos], check_n[pos], frac * 100, verdict))
    (best_frac, best_desc), top = sweep_pos28(lines2)
    for frac, d, ok, tot in top:
        print("  pos 28 best 7-3-1 candidates: %-34s %5d/%-5d = %5.1f%%" % (d, ok, tot, frac * 100))
    print("  pos 28 verdict: NOT a check digit (best candidate %s at %.1f%%)"
          % (best_desc, best_frac * 100))
    print("  pos 28 digit distribution: " + ", ".join(
        "%s=%d" % kv for kv in sorted(pos28_char.items())))
    print("  pos 28 verdict: NOT a 7-3-1 check digit; carries licence digit #4 "
          "(series part2 digit 2), agrees with labels on %d/%d = %.2f%%"
          % (agree["licence10"], total["licence10"],
             100.0 * agree["licence10"] / max(1, total["licence10"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
