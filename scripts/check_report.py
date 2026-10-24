#!/usr/bin/env python3
"""Check REPORT.md against the TASK.md report contract.

Usage: python3 scripts/check_report.py [REPORT.md]

Contract: at most 2 pages (~<=1100 words as a text proxy) and MUST contain a
numeric prediction of how many test documents will be accepted and how many
accepted documents will contain errors. Exit 0 = compliant.
"""
import re
import sys


def main(path="REPORT.md"):
    text = open(path, encoding="utf-8").read()
    words = len(re.findall(r"[\wА-Яа-яЁё.-]+", text))
    problems = []
    if words > 1100:
        problems.append(f"too long: {words} words (>1100 proxy for 2 pages)")
    has_accept = re.search(r"(принят\w*|accepted)[^\n]{0,80}?\d{2,4}", text, re.I)
    has_errors = re.search(r"(ошибк\w*|errors?)[^\n]{0,80}?\d", text, re.I)
    if not has_accept:
        problems.append("no numeric accepted-count prediction found")
    if not has_errors:
        problems.append("no numeric error prediction found")
    print(f"REPORT {path}: words={words} (proxy <=1100 for 2 pages)")
    print(f"prediction_accepted={'yes' if has_accept else 'NO'}")
    print(f"prediction_errors={'yes' if has_errors else 'NO'}")
    if problems:
        for p in problems:
            print("  " + p)
        print("REPORT=FAIL")
        return 1
    print("REPORT=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "REPORT.md"))
