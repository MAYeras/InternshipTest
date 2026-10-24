"""JSONL loading and per-document parsing into a normalized structure.

Normalized doc structure (returned by parse_doc):
    {
      "doc_id": str,
      "source": str,
      "quality": {"sharpness": float|None, "doc_px": ..., "glare": ...},
      "viz": {field: {  # field absent from viz / null -> None
                 "text": str,             # lines joined with single spaces, ws collapsed
                 "conf": float|None,      # field-level confidence from prediction
                 "char_confs": [float|None, ...],  # aligned 1:1 with "text"
                 "line_texts": [str, ...],
             } | None, ... for each of FIELDS},
      "mrz": <pp.mrz.parse_mrz result>,
    }

Everything here is crash-proof by contract: parse_doc never raises on weird input,
it degrades to Nones. Comparison normalization equals evaluate.py's norm().
"""
import json

from . import mrz

# Exact field keys/order as in evaluate.py. NOTE the two different spellings:
# 'Issue_organisation_code' (British, with s) vs 'Issue_organization_ru' (with z).
FIELDS = [
    "Last_name_ru", "First_name_ru", "Middle_name_ru", "Sex_ru", "Birth_date",
    "Birth_place_ru", "Issue_date", "Issue_organisation_code", "Licence_number",
    "Issue_organization_ru",
]

NAME_FIELDS = ("Last_name_ru", "First_name_ru", "Middle_name_ru")


def norm(s):
    """Same normalization as evaluate.py: case-insensitive, collapse whitespace."""
    return " ".join(str(s or "").split()).upper()


def iter_jsonl(path):
    """Yield one dict per JSONL line. Raises only on unreadable file / bad JSON."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_jsonl(path):
    return list(iter_jsonl(path))


def _clean_line(text, char_conf):
    """Collapse whitespace inside one line; keep (char, conf) pairs aligned.

    Returns (chars, confs): chars without leading/trailing/multiple spaces,
    confs[j] is the char_conf for chars[j] or None when unknown/mismatched.
    """
    chars, confs = [], []
    prev_space = True  # suppress leading spaces
    if not isinstance(text, str):
        text = str(text or "")
    confs_src = char_conf if isinstance(char_conf, (list, tuple)) else []
    for j, ch in enumerate(text):
        conf = confs_src[j] if j < len(confs_src) else None
        if isinstance(conf, bool) or not isinstance(conf, (int, float)):
            conf = None
        if ch.isspace():
            if not prev_space:
                chars.append(" ")
                confs.append(None)
                prev_space = True
        else:
            chars.append(ch)
            confs.append(conf)
            prev_space = False
    # drop a trailing space if present
    if chars and chars[-1] == " ":
        chars.pop()
        confs.pop()
    return chars, confs


def parse_viz_field(field):
    """Assemble one viz field into {text, conf, char_confs, line_texts}.

    text = line texts joined with a single space, all whitespace collapsed.
    char_confs is aligned 1:1 with text (None for joined/unknown positions).
    """
    if not isinstance(field, dict):
        return None
    raw_lines = field.get("lines")
    if not isinstance(raw_lines, list):
        raw_lines = []
    parts, line_texts = [], []
    all_chars, all_confs = [], []
    for ln in raw_lines:
        if not isinstance(ln, dict):
            continue
        chars, confs = _clean_line(ln.get("text"), ln.get("char_conf"))
        if not chars:
            continue
        line_texts.append("".join(chars))
        if all_chars:  # join lines with a single space of unknown confidence
            all_chars.append(" ")
            all_confs.append(None)
        all_chars.extend(chars)
        all_confs.extend(confs)
    conf = field.get("conf")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        conf = None
    return {
        "text": "".join(all_chars),
        "conf": conf,
        "char_confs": all_confs,
        "line_texts": line_texts,
    }


def parse_viz(viz):
    """Normalize the viz dict: {field: parsed|None for field in FIELDS}."""
    out = {}
    src = viz if isinstance(viz, dict) else {}
    for f in FIELDS:
        out[f] = parse_viz_field(src.get(f))
    return out


def parse_doc(doc):
    """Parse one prediction dict into the normalized structure. Never raises."""
    doc = doc if isinstance(doc, dict) else {}
    quality_raw = doc.get("quality")
    quality = {}
    if isinstance(quality_raw, dict):
        for k in ("sharpness", "doc_px", "glare"):
            v = quality_raw.get(k)
            quality[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return {
        "doc_id": doc.get("doc_id"),
        "source": doc.get("source"),
        "quality": quality,
        "viz": parse_viz(doc.get("viz")),
        "mrz": mrz.parse_mrz(doc.get("mrz")),
    }
