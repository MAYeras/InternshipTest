# HANDOFF: eliminate the remaining 22 S2 false accepts (tech agent)

Context: Stage 2 of plan/stages.md. Current state: accepted=542, field_FP=22
(Last_name_ru=5, Middle_name_ru=6, Birth_place_ru=11), validity gates PASS.
Run: `PP_LOO_LABELS=data/train_labels.jsonl python3 postprocess.py
data/train_predictions.jsonl analysis_out/train_answers_s2.jsonl
analysis_out/train_decisions.jsonl` then evaluate.py + scripts/selfcheck.py.

Already fixed (do not undo): MRZ century disambiguation; org exact-match-only
(ORG_DIST_MAX_*=0).

Goal: field_FP=0, accepted>=500, GATES=PASS in selfcheck, deterministic output.
Constraints: stdlib/offline/deterministic; don't touch evaluate.py, data/,
reference/, pp/mrz.py layout constants, S1 scripts; every new threshold needs a
comment with measured justification; report accepted-count regression after
each family fix.

## Diagnosed FP families + fixes

A) Middle_name space/hyphen (tr_00229/00679/01553/01834/01932): labels contain
SPACES ('САГИБ ОГЛЫ'); engine's NAME_ALLOWED excludes space -> viz unusable ->
reverse-map '<'->'-' produces wrong 'САГИБ-ОГЛЫ'. Fix: allow ' ' in names;
resolve '<' reverse ambiguity per field empirically (count '-' vs ' ' per name
field across ALL train labels; bake per-field rule).

B) Е/Ё MRZ-blindness (tr_00169 mincc=0.25, tr_00478 0.976, tr_00888 0.584):
MRZ maps Е and Ё to the same 'E', so MRZ agreement proves nothing about Ё.
Fix: names containing 'Ё' require a high min char conf — measure conf
distribution of accepted names with Ё (and count genuinely-Ё labels), pick
cheapest safe floor, document.

C) Correlated viz+MRZ misreads (tr_01371 'ЛЯМПЕРЧИК' vs 'ЛЯНПЕРЧИК' mincc
0.9985; tr_02183 'КИТУРКО' vs 'КИТУРКС' mincc 0.9982): both channels misread
the same image char and agree. Only lever: name conf floor. Measure min-char-
conf distribution over names of the 520 correct accepts; pick minimal floor
excluding both FPs while accepted>=500; bake as NAME_MIN_CONF (S3 validates on
holdout).

D) Low-conf SPACE hides dropped chars (tr_01672 'П БУРАННЫЙ' vs 'П. БУРАННЫЙ'
conf 0.6006 sits ON the space; tr_02021 'РЕСП БАШКОРТОСТАН' 0.8178; tr_02563
'ЧСЕВЕРНАЯ' vs 'СЕВЕРНАЯ' 0.995): engine._min_conf SKIPS spaces. Fix: include
real space confs (skip only None = joined positions). For tr_02563: if 'ЧС'
occurs in no train label, add a data-derived bad-cluster check for places.

E) Place truncation (tr_00985/01444/01503/01852/02085/02334/02399): missing
tail ('ЯРОСЛАВСКАЯ ОБЛ.' without 'ГОР. РЫБИНСК'; 'Х.ВЫСОКИЙ' without region;
'...СТАВРОПОЛЬСКОГО' dangling genitive). Fix: derive from train labels two
sets with 100% label coverage: settlement-prefix markers (first token) and
admin/region-final tokens (last token, e.g. ОБЛ., Р-НА, АО, ССР, КРАЙ...).
Require viz place to start with a settlement marker and end with an
admin-final token. Report the sets + coverage.

F) Place word-internal drop (tr_02911 'НИЖЕВАРТОВСК' vs 'НИЖНЕВАРТОВСК'
mincc 0.9886): measure place conf distribution; raise PLACE_CONF_FLOOR to the
cheapest floor that kills it (gate is absolute: must be killed somehow).

G) Wrong MRZ reverse-correction (tr_02597 'БАГАЙСКОВА' -> 'БАГАЙС-ОВА' from a
misread line1, which has no check digits): debug path; make reverse-
reconstruction defensive: surname piece must contain no '<'; corrected
patronymics must end with a valid suffix; '<' inside a piece where viz shows
none -> treat line1 misread -> reject, don't correct.

## Report back (<=40 lines)
Per-family: rule changed (file) + measured evidence (coverage %, conf
distributions, floor costs, accept-count after each family). Final:
accepted/FP, reject-reason breakdown, sha256 determinism (two runs identical).
