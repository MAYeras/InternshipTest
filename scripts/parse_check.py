#!/usr/bin/env python3
"""S1 gate: run the parser over ALL docs in train+test predictions.

Prints per-split and total docs/parsed/crashed counts, per-field null/empty
viz-field counts, and MRZ structure statistics (clean 2x44 vs malformed).
Deterministic, stdlib only, analysis-only (writes nothing).

Exit 0 always unless a file is unreadable; the gate itself is judged on the
printed `docs=5000 parsed=5000 crashed=0` line.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pp.parse import FIELDS, parse_doc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLITS = [
    ("train", os.path.join(ROOT, "data", "train_predictions.jsonl")),
    ("test", os.path.join(ROOT, "data", "test_predictions.jsonl")),
]


def classify_mrz(m):
    """One-line MRZ structure label."""
    if not m["present"]:
        return "null"
    n = m["n_lines"]
    if n == 0:
        return "zero_lines"
    lens = [len(t) for t in m["lines"]]
    if n == 1:
        return "one_line_44" if lens[0] == 44 else "one_line_len_%d" % lens[0]
    if n == 2 and lens == [44, 44]:
        return "clean_2x44"
    if n == 2:
        return "two_lines_len_%d_%d" % tuple(lens)
    return "%d_lines" % n


def scan(path):
    stats = {
        "docs": 0, "parsed": 0, "crashed": 0,
        "null_fields": Counter(), "empty_fields": Counter(),
        "mrz": Counter(),
    }
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            stats["docs"] += 1
            try:
                raw = json.loads(line)
                doc = parse_doc(raw)
            except Exception:
                stats["crashed"] += 1
                continue
            stats["parsed"] += 1
            for f in FIELDS:
                pf = doc["viz"][f]
                if pf is None:
                    stats["null_fields"][f] += 1
                elif not pf["text"]:
                    stats["empty_fields"][f] += 1
            stats["mrz"][classify_mrz(doc["mrz"])] += 1
    return stats


def fmt_split(name, s):
    lines = ["%s: docs=%d parsed=%d crashed=%d" % (name, s["docs"], s["parsed"], s["crashed"])]
    lines.append("  mrz structure: " + ", ".join(
        "%s=%d" % kv for kv in sorted(s["mrz"].items(), key=lambda kv: (-kv[1], kv[0]))))
    nf = ", ".join("%s=%d" % (f, s["null_fields"][f]) for f in FIELDS if s["null_fields"][f])
    ef = ", ".join("%s=%d" % (f, s["empty_fields"][f]) for f in FIELDS if s["empty_fields"][f])
    lines.append("  viz null fields:  " + (nf or "none"))
    if ef:
        lines.append("  viz empty-text:   " + ef)
    return "\n".join(lines)


def main():
    total = {"docs": 0, "parsed": 0, "crashed": 0}
    for name, path in SPLITS:
        s = scan(path)
        print(fmt_split(name, s))
        for k in total:
            total[k] += s[k]
    print()
    print("docs=%d parsed=%d crashed=%d" % (total["docs"], total["parsed"], total["crashed"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
