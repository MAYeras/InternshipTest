#!/usr/bin/env python3
"""S3 calibration: honest holdout evaluation + accept-rate stability.

Two evaluations:
  realistic  full train, pool/sets built from ALL train labels, PLUS
             leave-one-out per doc (PP_LOO_LABELS) — each doc's own org entry
             hidden. Approximates test behaviour from the pessimistic side
             (test additionally benefits from every train label, which LOO
             removes for the scored doc itself).
  folds      5 deterministic folds; for fold k the org pool and place sets are
             rebuilt from the OTHER folds' labels only (the fold's own labels
             are invisible — a true train->test simulation), scored with no
             per-doc LOO. Reports per-fold accepts/FP and the spread.

Outputs a table + verdict lines; writes analysis_out/calibration.txt.
"""
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from pp.parse import norm
from pp.validity import is_valid

FIELDS = ["Last_name_ru", "First_name_ru", "Middle_name_ru", "Sex_ru", "Birth_date",
          "Birth_place_ru", "Issue_date", "Issue_organisation_code", "Licence_number",
          "Issue_organization_ru"]


def parse_d(s):
    d, m, y = s.split(".")
    return date(int(y), int(m), int(d))


def load_labels(path):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["doc_id"]] = r["fields"]
    return out


def run(in_path, out_path, env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    res = subprocess.run(
        [sys.executable, "postprocess.py", in_path, out_path],
        env=env, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def score(ans_path, labels):
    ans = {}
    with open(ans_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                ans[r["doc_id"]] = r
    accepted = {k for k, v in ans.items() if v.get("decision") == "accept"}
    fp = []
    vfp = []
    for doc_id, gf in labels.items():
        if doc_id not in accepted:
            continue
        af = ans[doc_id].get("fields") or {}
        if any(norm(af.get(f)) != norm(gf[f]) for f in FIELDS):
            fp.append(doc_id)
        bd, idd = parse_d(gf["Birth_date"]), parse_d(gf["Issue_date"])
        ok, _ = is_valid(bd, idd)
        if not ok:
            vfp.append(doc_id)
    return len(accepted), fp, vfp


def main():
    lines = []
    labels_all = load_labels("data/train_labels.jsonl")

    # ---- realistic (LOO) full-train run ----
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "realistic.jsonl")
        summary = run("data/train_predictions.jsonl", out, {"PP_LOO_LABELS": "data/train_labels.jsonl"})
        acc, fp, vfp = score(out, labels_all)
        lines.append(f"realistic LOO full-train: {summary}")
        lines.append(f"  accepted={acc} field_FP={len(fp)} {sorted(fp)} validity_FP={len(vfp)}")

    # ---- 5-fold: pool/sets from other folds only ----
    doc_ids = sorted(labels_all)
    n_folds = 5
    fold_of = {d: i % n_folds for i, d in enumerate(doc_ids)}
    per_fold = []
    with tempfile.TemporaryDirectory() as td:
        fold_files = {}
        for k in range(n_folds):
            p = os.path.join(td, f"train_fold{k}.jsonl")
            with open(p, "w", encoding="utf-8") as fh:
                for d in doc_ids:
                    if fold_of[d] != k:
                        fh.write(json.dumps({"doc_id": d, "fields": labels_all[d]}, ensure_ascii=False) + "\n")
            fold_files[k] = p
        for k in range(n_folds):
            pred_out = os.path.join(td, f"pred_fold{k}.jsonl")
            with open(pred_out, "w", encoding="utf-8") as fh:
                for line in open("data/train_predictions.jsonl", encoding="utf-8"):
                    r = json.loads(line)
                    if fold_of.get(r["doc_id"]) == k:
                        fh.write(line)
            ans_out = os.path.join(td, f"ans_fold{k}.jsonl")
            env = {"PP_LABELS_PATH": fold_files[k]}
            summary = run(pred_out, ans_out, env)
            fold_labels = {d: f for d, f in labels_all.items() if fold_of[d] == k}
            acc, fp, vfp = score(ans_out, fold_labels)
            rate = acc / max(1, len(fold_labels))
            per_fold.append((k, len(fold_labels), acc, rate, len(fp), sorted(fp), len(vfp)))
            lines.append(f"fold{k}: docs={len(fold_labels)} accepted={acc} ({rate:.1%}) "
                         f"field_FP={len(fp)} {sorted(fp)} validity_FP={len(vfp)}")

    rates = [r for _, _, _, r, _, _, _ in per_fold]
    mean_r = sum(rates) / len(rates)
    spread = max(rates) - min(rates)
    fps = sum(f for _, _, _, _, f, _, _ in per_fold)
    vfps = sum(v for _, _, _, _, _, _, v in per_fold)
    lines.append(f"folds summary: mean_accept_rate={mean_r:.1%} spread={spread:.1%} "
                 f"total_field_FP={fps} total_validity_FP={vfps}")
    lines.append(
        f"spread gate: {'PASS' if spread <= 0.15 else 'FAIL'} on the controller-ratified "
        f"reading (<=15 percentage points); strict '%-of-mean' reading "
        f"(<= {0.15 * mean_r:.1%}): {'PASS' if spread <= 0.15 * mean_r else 'FAIL'} — "
        f"see Amendment Log note 2026-10-24b")

    fp_docs = sorted({d for _, _, _, _, _, fl, _ in per_fold for d in fl})
    lines.append(f"all fold FP docs: {fp_docs}")

    report = "\n".join(lines)
    print(report)
    with open("analysis_out/calibration.txt", "w", encoding="utf-8") as fh:
        fh.write(report + "\n")

    ok = vfps == 0 and spread <= 0.15  # ratified reading: <=15 percentage points
    print(f"GATES={'PASS' if ok else 'FAIL'} (validity_FP=0 everywhere; "
          f"spread<=15pp per ratified gate; strict %-of-mean also printed above)")


if __name__ == "__main__":
    main()
