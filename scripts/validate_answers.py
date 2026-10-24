#!/usr/bin/env python3
"""Validate an answers.jsonl file against the TASK.md output contract.

Usage: python3 scripts/validate_answers.py <answers.jsonl> <predictions.jsonl>

Checks: one line per prediction doc_id (no dupes, none missing), decision in
{accept, reject}, accepted lines carry EXACTLY the 10 evaluate.py field keys
(watching Issue_organisation_code vs Issue_organization_ru) with format-valid
values (dates DD.MM.YYYY + calendar, code XXX-XXX, licence 'DD DD DDDDDD',
sex МУЖ./ЖЕН.), rejected lines carry no fields. Exit 0 = valid.
"""
import json
import re
import sys
from datetime import date

FIELDS = ["Last_name_ru", "First_name_ru", "Middle_name_ru", "Sex_ru", "Birth_date",
          "Birth_place_ru", "Issue_date", "Issue_organisation_code", "Licence_number",
          "Issue_organization_ru"]
DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


def valid_date(s):
    m = DATE_RE.match(s or "")
    if not m:
        return False
    d, mo, y = map(int, m.groups())
    try:
        date(y, mo, d)
        return True
    except ValueError:
        return False


def main(ans_path, pred_path):
    preds = {}
    with open(pred_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                d = json.loads(line)
                preds[d["doc_id"]] = d
    errs = []
    seen = {}
    n = accepted = 0
    with open(ans_path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                r = json.loads(line)
            except ValueError:
                errs.append(f"line {i}: bad JSON")
                continue
            did = r.get("doc_id")
            if did not in preds:
                errs.append(f"line {i}: unknown doc_id {did!r}")
            if did in seen:
                errs.append(f"line {i}: duplicate doc_id {did!r}")
            seen[did] = True
            dec = r.get("decision")
            if dec not in ("accept", "reject"):
                errs.append(f"{did}: decision {dec!r}")
            if dec == "accept":
                accepted += 1
                f = r.get("fields")
                if not isinstance(f, dict) or set(f) != set(FIELDS):
                    errs.append(f"{did}: fields keys != the 10 required")
                    continue
                for k in FIELDS:
                    if k == "Middle_name_ru":
                        continue  # may legitimately be an empty patronymic
                    if not f[k] or not str(f[k]).strip():
                        errs.append(f"{did}: empty {k}")
                if not valid_date(f.get("Birth_date")):
                    errs.append(f"{did}: bad Birth_date {f.get('Birth_date')!r}")
                if not valid_date(f.get("Issue_date")):
                    errs.append(f"{did}: bad Issue_date {f.get('Issue_date')!r}")
                if not re.fullmatch(r"\d{3}-\d{3}", f.get("Issue_organisation_code") or ""):
                    errs.append(f"{did}: bad code {f.get('Issue_organisation_code')!r}")
                if not re.fullmatch(r"\d{2} \d{2} \d{6}", f.get("Licence_number") or ""):
                    errs.append(f"{did}: bad licence {f.get('Licence_number')!r}")
                if f.get("Sex_ru") not in ("МУЖ.", "ЖЕН."):
                    errs.append(f"{did}: bad sex {f.get('Sex_ru')!r}")
            else:
                if r.get("fields"):
                    errs.append(f"{did}: reject line carries fields")
    missing = set(preds) - set(seen)
    if missing:
        errs.append(f"{len(missing)} prediction doc_ids missing, e.g. {sorted(missing)[:3]}")
    print(f"lines={n} accepted={accepted} docs_covered={len(seen)}/{len(preds)}")
    if errs:
        print(f"ERRORS={len(errs)}")
        for e in errs[:20]:
            print("  " + e)
        return 1
    print("FORMAT=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
