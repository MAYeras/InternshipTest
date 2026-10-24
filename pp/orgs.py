"""Subdivision code / issuing-organisation reference data.

Pool per code = names from reference/subdivisions.csv UNION names from
data/train_labels.jsonl (code -> Counter of norm()ed org names, so a name
backed by several sources survives leave-one-out).

API:
    known_code(code)          -> bool (code exists in the reference union)
    names_for(code, loo=None) -> set of norm()ed org names (may be empty)
    damerau_levenshtein(a, b) -> int
    nearest(text, code, loo=None) -> (dist, best_name, second_dist) or (None,..)

loo=(code, name) implements leave-one-out for CALIBRATION on train: it hides
that doc's own label entry — unless the same name is independently present via
the CSV or another train doc — so train metrics are not leak-inflated. Runtime
scoring (test) never passes loo.

All functions deterministic; CSV parsed with stdlib csv, utf-8.
"""
import csv
import json
import os
from collections import Counter

from .parse import norm

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(_ROOT, "reference", "subdivisions.csv")


def _labels_path():
    # dev/calibration (scripts/calibrate.py) can point the label-derived part
    # of the pool at a fold subset via PP_LABELS_PATH; runtime default is train
    # labels. Read at build time so folds can rebuild in one process.
    return os.environ.get("PP_LABELS_PATH") or os.path.join(
        _ROOT, "data", "train_labels.jsonl")


_pool = None


def reset_cache():
    """Dev-only: force the pool to rebuild (used between calibration folds)."""
    global _pool
    _pool = None


def _build():
    pool = {}
    with open(CSV_PATH, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code, name = (row.get("code") or "").strip(), norm(row.get("name"))
            if code and name:
                pool.setdefault(code, Counter())[name] += 1
    path = _labels_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    f = json.loads(line)["fields"]
                except (ValueError, KeyError):
                    continue
                code, name = f.get("Issue_organisation_code"), norm(f.get("Issue_organization_ru"))
                if code and name:
                    pool.setdefault(code, Counter())[norm(name)] += 1
    return pool


def pool():
    global _pool
    if _pool is None:
        _pool = _build()
    return _pool


def known_code(code):
    return code in pool()


def names_for(code, loo=None):
    names = pool().get(code)
    if not names:
        return set()
    if loo is not None and loo[0] == code and names.get(loo[1], 0) <= 1:
        return {n for n in names if n != loo[1]}
    return set(names)


def damerau_levenshtein(a, b):
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def nearest(text, code, loo=None):
    """(best_dist, best_name, second_dist) over the code's pool; (None,)*3 if empty.

    Deterministic tie-break: lexicographically smallest name among equals.
    """
    names = names_for(code, loo=loo)
    if not names:
        return None, None, None
    scored = sorted((damerau_levenshtein(text, n), n) for n in names)
    best_d, best_n = scored[0]
    second_d = scored[1][0] if len(scored) > 1 else None
    return best_d, best_n, second_d
