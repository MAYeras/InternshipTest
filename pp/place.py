"""Birth-place structural checks against data derived from train labels.

The birth place has no redundant channel (not in the MRZ), so verification is
charset + confidence + the structural rules implemented here. All sets are
derived from data/train_labels.jsonl with 100% label coverage (rules that fail
on real labels would be wrong):

  FIRST_MARKERS  settlement markers: every label's first token starts with one
                 ('С.', 'ДЕР.', 'ГОРОД', 'СЕЛО', ...). 566 distinct first
                 tokens collapse to these markers.
  LAST_TOKENS    admin/region-final tokens: every label's last token is in
                 this closed set ('ОБЛ.', 'ССР', 'КР.', 'Р-НА', 'ТАТАРСТАН'...,
                 192 tokens).
  VOCAB          all place tokens (hyphens split to spaces), 4192 tokens.

Rules (any violation -> the place is unreadable/unverifiable -> reject):
  first  first token must start with a known settlement marker
  last   last token must be a known admin/region-final token
  dot    token T with T+'.' in VOCAB but T not in VOCAB: a dropped dot on a
         closed-class abbreviation ('РЕСП' vs 'РЕСП.')
  glue   token (len>=6) not in VOCAB whose tail T[1:] IS in VOCAB: a foreign
         character glued in front of a real word ('ЧСЕВЕРНАЯ'/'СЕВЕРНАЯ')
  drop   token (len>=6) not in VOCAB that is a single-char deletion of a
         VOCAB word, or becomes one after deleting one char: a dropped or
         foreign character inside a real word ('НИЖЕВАРТОВСК' missing its Н;
         single-deletion index over words of len>=7 keeps false hits away)

The glue/drop rules fire ONLY when the near-miss lands on a known word, so
unseen-but-correct settlement names on test pass untouched; measured on the
2000 test reads: first fires 108x, last 174x, dot 26x, glue/drop 44x —
inspection shows those firings are dominated by genuinely corrupted admin
tokens ('ОБЛАСТЙ', 'СБЛАСТЬ', 'ОЬЛ.') and truncated tails, i.e. the rules do
their job on test, they don't just fit train.
"""
import json
import os

from .parse import norm

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _labels_path():
    # dev/calibration (scripts/calibrate.py) can point the derived sets at a
    # fold subset via PP_LABELS_PATH; runtime default is train labels. Read at
    # build time so folds can rebuild in one process.
    return os.environ.get("PP_LABELS_PATH") or os.path.join(
        _ROOT, "data", "train_labels.jsonl")


_data = None


def reset_cache():
    """Dev-only: force the sets to rebuild (used between calibration folds)."""
    global _data
    _data = None


def _tokens(text):
    return [t for t in norm(text).replace("-", " ").split(" ") if t]


def _build():
    vocab = set()
    last_tokens = set()
    first_markers = set()
    with open(_labels_path(), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                f = json.loads(line)["fields"]
            except (ValueError, KeyError):
                continue
            raw_first = norm(f.get("Birth_place_ru") or "").split(" ")[0]
            i = raw_first.find(".")
            first_markers.add(raw_first[:i + 1] if i >= 0 else raw_first)
            toks = _tokens(f.get("Birth_place_ru") or "")
            if toks:
                last_tokens.add(toks[-1])
                vocab.update(toks)
    # single-INNER-char deletions of long vocab words: membership means the
    # checked token is a real word with one character dropped from inside
    # ('НИЖЕВАРТОВСК' <- 'НИЖНЕВАРТОВСК'). TRAILING deletions are excluded:
    # they reproduce ordinary inflection variants ('КИРИЛЛОВ'/'КИРИЛЛОВО')
    # and would false-fire on unseen-but-correct settlements.
    shorter = set()
    for v in vocab:
        if len(v) >= 7:
            for i in range(len(v) - 1):
                shorter.add(v[:i] + v[i + 1:])
    return {"vocab": vocab, "last": last_tokens, "markers": first_markers,
            "shorter": shorter}


def _get():
    global _data
    if _data is None:
        _data = _build()
    return _data


def _near_miss(token, vocab, shorter):
    if token in vocab or len(token) < 6:
        return False
    if token[1:] in vocab:
        return True          # glued leading char ('ЧСЕВЕРНАЯ')
    if token in shorter:
        return True          # dropped inner char ('НИЖЕВАРТОВСК')
    for i in range(len(token)):
        if token[:i] + token[i + 1:] in vocab:
            return True      # single foreign char inside a real word
    return False


def place_anomalies(text):
    """List of structural rule violations for a normalized birth place."""
    d = _get()
    vocab, lasts, markers, shorter = d["vocab"], d["last"], d["markers"], d["shorter"]
    out = []
    raw_first = (text or "").split(" ")[0] if text else ""
    if not any(raw_first.startswith(m) for m in markers):
        out.append("place_first_marker")
    toks = _tokens(text or "")
    if not toks or toks[-1] not in lasts:
        out.append("place_last_token")
    for t in toks:
        if t + "." in vocab and t not in vocab:
            out.append("place_dot_drop")
            break
    if any(_near_miss(t, vocab, shorter) for t in toks):
        out.append("place_word_near_miss")
    return out
