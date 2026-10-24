#!/usr/bin/env python3
"""Post-process passport OCR predictions: decide accept/reject per document.

Usage:  python postprocess.py <predictions.jsonl> <out_answers.jsonl> [decisions_log.jsonl]

Third argument is OPTIONAL (dev/calibration only): when given, writes one JSON
line per doc with the full per-field decision log. The two-argument form is the
deliverable interface. CPU-only, offline, Python stdlib only, deterministic.
"""
import json
import os
import sys

from pp.engine import decide
from pp.parse import FIELDS, parse_doc


def _load_loo_labels():
    """Dev-only leave-one-out: PP_LOO_LABELS=<train_labels.jsonl>.

    For CALIBRATION on train: the org reference pool is built partly from train
    labels, so scoring a train doc against a pool containing its own answer
    would leak. With this env var set, each doc's own (code, org) entry is
    hidden from the pool (unless independently corroborated). The deliverable
    two-argument run on test never sets it."""
    path = os.environ.get("PP_LOO_LABELS")
    if not path:
        return {}
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            f = d.get("fields") or {}
            out[d.get("doc_id")] = (f.get("Issue_organisation_code"),
                                    " ".join(str(f.get("Issue_organization_ru") or "").split()).upper())
    return out


def process(in_path, out_path, log_path=None):
    """Run the pipeline; returns summary counts. Deterministic."""
    docs = accepted = rejected = crashed = 0
    loo_labels = _load_loo_labels()
    log_fh = open(log_path, "w", encoding="utf-8") if log_path else None
    try:
        with open(out_path, "w", encoding="utf-8") as out:
            with open(in_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    docs += 1
                    doc_id = None
                    res = None
                    try:
                        raw = json.loads(line)
                        doc_id = raw.get("doc_id")
                        parsed = parse_doc(raw)
                        res = decide(parsed, loo_org=loo_labels.get(doc_id))
                    except Exception:
                        res = None
                    if res is None or res.get("decision") not in ("accept", "reject"):
                        crashed += 1
                        res = {"decision": "reject", "fields": None,
                               "log": {"doc": ("reject", "engine_exception")}}
                    rec = {"doc_id": doc_id, "decision": res["decision"]}
                    if res["decision"] == "accept":
                        accepted += 1
                        rec["fields"] = {f: res["fields"][f] for f in FIELDS}
                    else:
                        rejected += 1
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    if log_fh is not None:
                        log_fh.write(json.dumps(
                            {"doc_id": doc_id, "decision": res["decision"],
                             "fields": res.get("fields"), "log": res.get("log")},
                            ensure_ascii=False) + "\n")
    finally:
        if log_fh is not None:
            log_fh.close()
    return {"docs": docs, "accepted": accepted, "rejected": rejected,
            "crashed": crashed}


def main(argv):
    if len(argv) not in (3, 4):
        sys.stderr.write("usage: python postprocess.py <predictions.jsonl> "
                         "<out.jsonl> [decisions_log.jsonl]\n")
        return 2
    summary = process(argv[1], argv[2], argv[3] if len(argv) == 4 else None)
    print("docs={docs} accepted={accepted} rejected={rejected} "
          "crashed={crashed}".format(**summary))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
