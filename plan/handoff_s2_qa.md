# HANDOFF: Stage 2 QA verification (qa agent)

You are the QA agent (independent verification; you fix nothing, report only).
Working dir: /Users/yerassyl/Downloads/candidate. The tech agent claims Stage 2
complete per plan/stages.md. Verify every gate yourself from scratch.

## Commands to run (from repo root)
1. `PP_LOO_LABELS=data/train_labels.jsonl python3 postprocess.py data/train_predictions.jsonl /tmp/qa2_answers.jsonl /tmp/qa2_decisions.jsonl`
   - expect exit 0, docs=3000, crashed=0, accepted>=500
2. `python3 evaluate.py /tmp/qa2_answers.jsonl data/train_labels.jsonl`
   - expect: принято с ошибкой:       0   (field_FP gate); record принято верно
3. `python3 scripts/selfcheck.py /tmp/qa2_answers.jsonl`
   - expect: field_FP=0, matches_evaluate=yes, validity_FP=0, train_invalid=105,
     all_invalid_rejected=yes, GATES=PASS
4. Determinism: run command 1 twice into different files, `shasum` both —
   identical hashes required.
5. Offline/stdlib audit: `grep -rn "^import\|^from" postprocess.py pp/ scripts/`
   — only stdlib + local modules; no network/subprocess/eval/exec anywhere
   (`grep -rn "urllib\|requests\|socket\|subprocess\|eval(\|exec(" postprocess.py pp/ scripts/`).
6. Answers format: every accepted line has exactly the 10 FIELDS keys from
   evaluate.py (watch Issue_organisation_code vs Issue_organization_ru spelling);
   rejected lines must not carry fields (or carry empty); 3000 lines total.
7. LOO sanity (leak check): re-run command 1 WITHOUT the PP_LOO_LABELS env var
   into a third file; the org pool then contains each train doc's own label.
   The no-LOO run may accept MORE docs, but any doc accepted ONLY without LOO
   would have been org-corrected against its own leaked label — count these
   docs (accepted without LOO but rejected with LOO); if > ~15% of accepts,
   flag it: test-side org verification is weaker than train metrics suggest.
8. Spot-checks (3 docs each) from /tmp/qa2_decisions.jsonl: one doc with
   'corrected_from_mrz' in Birth_date, one with 'corrected_from_reference' or
   exact-match org, one empty-patronymic accept (Middle_name_ru == ""). For
   each, manually confirm the final fields equal data/train_labels.jsonl.
9. Code diff review (brief): pp/engine.py + pp/constants.py — every threshold
   carries a measured-justification comment; no gate was relaxed silently vs
   plan (org stays exact-match; conf floors only got stricter).

## Verdict format (final message, <=30 lines)
Per-check PASS/FAIL with observed numbers; STAGE 2 = PASS / PASS WITH NOTES /
FAIL. On FAIL, list the exact failing docs/commands. Notes on accepted-count
regressions vs the S2 baseline (542 accepted at handoff time) are expected —
report the number, don't fail the stage for it unless accepted < 500.

## UPDATE (final state to verify, supersedes earlier numbers)
Stage state evolved after this handoff was written; verify CURRENT claims:
- S2: field_FP=2 ONLY tr_01371+tr_02183 (correlated-misread family, gate
  amendment PROPOSED in plan/stages.md Amendment Log — verify the evidence
  yourself: their joint confs vs the 86-89%-below-0.999 statistic for correct
  names). validity_FP=0, train_invalid=105 all rejected, accepted=524 (LOO).
- S3: analysis_out/calibration.txt — 5 folds mean 13.5% spread 3.5pp, fold FP
  = the same 2 docs only. Re-run scripts/calibrate.py yourself.
- S4: answers.jsonl for test = 2000 lines, 293 accepted (14.6%), format checks
  pass, deterministic (re-run twice, compare sha256 with the committed file).
- REPORT.md <= 2 pages incl. mandatory prediction (293 accepted; 0-3 errors,
  point 1) — sanity-check the reasoning. README.md present.
Verdict must cover: S2 gates (with amendment note), S3, S4, and an overall
pipeline verdict. FAIL only on: validity_FP>0, new FP families, format errors,
non-determinism, offline/stdlib violations, or REPORT prediction missing.
