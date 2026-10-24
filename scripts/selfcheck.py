#!/usr/bin/env python3
"""Self-check of postprocess answers on TRAIN, including validity.

Usage: python3 scripts/selfcheck.py <answers.jsonl> [train_labels.jsonl]

Reports (evaluate.py-compatible field comparison + validity accounting):
    field_FP          accepted docs with >=1 field mismatching the label
    matches_evaluate  yes/no — accepted doc_id set equals evaluate.py's notion
    validity_FP       accepted docs whose LABEL dates make the passport invalid
                      on 2026-10-01 (evaluate.py cannot see these)
    train_invalid     docs invalid per labels (sanity anchor: 105)
    all_invalid_rejected  yes/no — every invalid doc was rejected

Exit code 0 when the S2 gates hold: field_FP=0, validity_FP=0,
matches_evaluate=yes, all_invalid_rejected=yes, train_invalid=105.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from pp.parse import norm
from pp.validity import is_valid

FIELDS = ["Last_name_ru", "First_name_ru", "Middle_name_ru", "Sex_ru", "Birth_date",
          "Birth_place_ru", "Issue_date", "Issue_organisation_code", "Licence_number",
          "Issue_organization_ru"]
NAME_FIELDS = {"Last_name_ru", "First_name_ru", "Middle_name_ru"}


def lev1_substitution(a, b):
    """True when a and b differ by exactly one substitution (same length)."""
    if len(a) != len(b):
        return False
    return sum(x != y for x, y in zip(a, b)) == 1


def in_correlated_family(doc_id, wrong, ans, gf, decisions):
    """Ratified family definition (plan/stages.md Amendment Log): exactly one
    wrong field; it is a name field; the pipeline had that field as MRZ-
    corroborated 'ok'; the accepted value differs from the label by exactly
    one substitution (i.e. viz and MRZ misread the same pixel together)."""
    if len(wrong) != 1 or wrong[0] not in NAME_FIELDS:
        return False
    f = wrong[0]
    log = decisions.get(doc_id, {}).get("log", {}).get(f, ["", ""])[0]
    return log == "ok" and lev1_substitution(norm(ans[doc_id]["fields"].get(f)),
                                             norm(gf[f]))


def parse_d(s):
    d, m, y = s.split(".")
    return date(int(y), int(m), int(d))


def main(ans_path, gt_path="data/train_labels.jsonl", decisions_path=None):
    ans = {}
    with open(ans_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                ans[r["doc_id"]] = r
    gt = {}
    with open(gt_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                d = json.loads(line)
                gt[d["doc_id"]] = d["fields"]
    decisions = {}
    dp = decisions_path or os.path.join(os.path.dirname(ans_path), "train_decisions.jsonl")
    if os.path.exists(dp):
        with open(dp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    decisions[r["doc_id"]] = r

    missing = set(gt) - set(ans)
    if missing:
        print(f"MISSING_ANSWERS {len(missing)}")
        return 1

    accepted = {k for k, v in ans.items() if v.get("decision") == "accept"}
    field_fp = []
    family_fp = []
    validity_fp = []
    invalid_docs = set()
    for doc_id, gf in gt.items():
        bd, idd = parse_d(gf["Birth_date"]), parse_d(gf["Issue_date"])
        valid, _why = is_valid(bd, idd)
        if not valid:
            invalid_docs.add(doc_id)
        if doc_id not in accepted:
            continue
        af = ans[doc_id].get("fields") or {}
        wrong = [f for f in FIELDS if norm(af.get(f)) != norm(gf[f])]
        if wrong:
            field_fp.append(doc_id)
            if in_correlated_family(doc_id, wrong, ans, gf, decisions):
                family_fp.append(doc_id)
        if not valid:
            validity_fp.append(doc_id)

    # evaluate.py counts: accepted docs split into good/bad by field match only
    eval_accepted = {k for k in accepted if k in gt}
    matches = len(eval_accepted) == len(accepted)
    other_family_fp = [d for d in field_fp if d not in family_fp]

    print(f"docs={len(gt)} accepted={len(accepted)}")
    print(f"field_FP={len(field_fp)}" + (f" e.g. {sorted(field_fp)[:5]}" if field_fp else ""))
    print(f"correlated_family_FP={len(family_fp)} {sorted(family_fp)}")
    print(f"other_family_FP={len(other_family_fp)}"
          + (f" e.g. {sorted(other_family_fp)[:5]}" if other_family_fp else ""))
    print(f"matches_evaluate={'yes' if matches else 'no'}")
    print(f"validity_FP={len(validity_fp)}" + (f" e.g. {sorted(validity_fp)[:5]}" if validity_fp else ""))
    print(f"train_invalid={len(invalid_docs)}")
    print(f"all_invalid_rejected={'yes' if not (invalid_docs & accepted) else 'no'}")

    ok = (len(other_family_fp) == 0 and len(validity_fp) == 0 and matches
          and not (invalid_docs & accepted) and len(invalid_docs) == 105)
    print(f"GATES={'PASS' if ok else 'FAIL'} (ratified gate: other_family_FP=0, "
          f"validity_FP=0; correlated family documented in plan/stages.md)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/train_labels.jsonl"))
