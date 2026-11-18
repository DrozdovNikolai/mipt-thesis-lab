# Decoding and VAD diagnostics v1 — frozen before inference

Authorization: the user approved the two checks proposed in the retraining failure
audit. This adds exactly four fixed configurations to the previous cumulative 18
(22 total), under SPEC's explicit additional-budget provision. ACCEPTANCE's
original limit and quality thresholds are unchanged. No adaptive search or training.

## Assumptions and population

- Use the saved parent and augmented433 CT2 weights separately, CUDA float16.
- Reuse hash-verified original baseline outputs; recognize new quiet copies afresh
  with the same baseline. Historical baseline runtime is not a timing comparison.
- Select all five reviewed cockpit dev clips, all 50 clean EN and 50 RU controls,
  and every reference-eligible weak publisher clip and its existing 0/10dB mixture.
- In each noise cohort, sort by audio SHA256 then ID and take whole recordings
  until at least 300 seconds. Selection uses metadata, never words or WER.
- Add -12dB amplitude copies of all five human clips and all clean EN utterances
  no longer than four seconds. Keep source references, time axis and group IDs.
  No normalization, extra noise or new speech is introduced.
- All data are already exposed dev/diagnostic data. No final test is accessed.

## Two independent interventions

1. `text`: only `without_timestamps=True`, with `word_timestamps=True` for actual
   backend word alignment. No VAD or change in prompting, beam, thresholds or weights.
2. `vad`: retain original timestamp decoding. External bundled Silero v6 ONNX;
   threshold .4, minimum speech 50ms, minimum silence 400ms, padding 250ms, max30s.
   These are fixed conservative settings, not a search. Transcribe disjoint windows
   individually; retain original sample offsets. Do not concatenate gaps, suppress
   repeated text, infer roles, or repair numbers semantically.

Do not run a combined text+VAD configuration or select any release variant here.

## Measurements and acceptance

- Unchanged lexical WER, S/D/I/N, paired cluster bootstrap2000 seed55,95%CI per cohort.
  Compare each intervention to its own checkpoint baseline.
- Report noise insertions/minute, clean/RU WER regression, empty utterances,
  deletions in quiet and short cohorts, failures and actual precision.
- Human command boundaries and critical entities are insufficient: quiet/short
  utterance deletions are diagnostics, not verified critical-command recall.
- Word timestamps must remain inside the actual original input windows. Report
  absent and zero-duration word alignments; do not claim human timing accuracy.
- Relative WER target10%; clean/RU delta<=.01; noise delta<=0; no runtime failures.
  Full acceptance still requires independent groups, human utterances, words,
  critical entities and clean controls specified in ACCEPTANCE.yaml.
- Do not pool quiet/clean siblings as independent observations or treat weak
  alignments/general speech as cockpit gold. NLP/temporal labels are unchanged.

## Checklist

- [ ] Test metadata selection, silence, repeated commands and original offsets.
- [ ] Freeze code, input, model, VAD, protocol and scorer identities before inference.
- [ ] Execute both baselines on quiet copies and four diagnostic systems offline.
- [ ] Score all predeclared items, including failures, without changing references.
- [ ] Execute CPU smoke and resume through PowerShell and Linux/WSL.
- [ ] Save verification/report/status; keep serving release unchanged.

This checklist is immutable after freeze; completion is recorded in verification.json.
