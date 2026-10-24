# HANDOFF: final acceptance review (review agent)

You are the REVIEW agent — the last gate of the pipeline. Simulate a strict
external reviewer receiving this repository as a test-task submission. You fix
nothing; you produce the acceptance verdict. Repo: /Users/yerassyl/Downloads/candidate.

Read: TASK.md (the requirements), evaluate.py, README.md, REPORT.md,
plan/stages.md (plan + Amendment Log), plan/handoff_s2_qa.md, then the code
(postprocess.py, pp/*.py, scripts/*.py).

## Acceptance checklist (verify each item yourself, cite evidence)

1. TASK.md deliverable 1 — code: `python postprocess.py data/test_predictions.jsonl answers.jsonl`
   runs offline, CPU, stdlib-only (grep imports), deterministic (run twice,
   sha256), exit 0.
2. TASK.md deliverable 2 — answers.jsonl: 2000 lines, every test doc_id exactly
   once, decision in {accept, reject}, fields (exactly the 10 evaluate.py keys,
   note Issue_organisation_code vs Issue_organization_ru) present iff accept.
3. TASK.md deliverable 3 — REPORT.md: <= 2 pages (render/side-count honestly),
   describes approach/findings, contains the MANDATORY prediction with numbers
   (accepted count and expected erroneous accepts) and sane justification.
4. Correctness evidence: run the train pipeline with LOO
   (PP_LOO_LABELS=data/train_labels.jsonl python postprocess.py
   data/train_predictions.jsonl /tmp/rev_train.jsonl), then evaluate.py and
   scripts/selfcheck.py — confirm field_FP=2 (only tr_01371/tr_02183, the
   documented correlated-misread family per the Amendment Log), validity_FP=0,
   train_invalid=105 all rejected.
5. Amendment integrity: plan/stages.md Amendment Log documents the FP<=2 gate
   proposal with evidence; controller ratification status is stated there;
   nothing was silently relaxed (org matching is exact-only; conf floors only
   got stricter; validity rule implemented per TASK.md reading).
6. Code quality pass: crash-proof parsing (spot-check a null-field doc, a
   no-MRZ doc, a 1-line-MRZ doc end-to-end), no dead giveaways of train/test
   leakage into test scoring (PP_LOO_LABELS and PP_LABELS_PATH are dev-only;
   default test run uses train labels + CSV as learned references, which is
   legitimate), thresholds commented with measured justifications.
7. Prediction plausibility: accepted=293 (14.6%) sits between the fold (13.5%)
   and LOO (17.5%) bounds; error estimate 0-3 (point 1) derives from the
   2/3000 correlated-error rate scaled by acceptance — check the arithmetic.
8. Repo hygiene: README accurate, .gitignore sane, no __pycache__/junk,
   analysis_out artifacts present (translit.json, calibration.txt).

## Verdict format (final message, <=35 lines)
Per-item PASS/FAIL with one-line evidence; overall 'SUBMISSION = ACCEPT' if
items 1-5 and 8 pass (6-7 may carry notes), else 'SUBMISSION = REVISE' with a
numbered fix list. Be adversarial: if you find any way the submission could be
rejected by a real evaluator, name it.
