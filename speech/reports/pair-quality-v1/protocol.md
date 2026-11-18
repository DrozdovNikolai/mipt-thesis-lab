# Train-only preparation protocol · pair-quality-v1

Frozen before ASR or pair selection. Existing commit: b22c91c. No existing user
reviews, source audio, partitions, acceptance thresholds or release config change.
No manual annotation is requested. Sources remain subject to CC BY-NC 4.0.

Checklist:

- Preserve hashes of old requirements, source manifests, reviews and experiments.
- Use only existing English checklist-family clean train originals (nine readers).
- VAD with 300 ms silence and no padding identifies natural boundaries. Join short
  speech intervals towards eight seconds, with a maximum 24-second speech span and
  two-second internal pause. Hold continuous speech exceeding 24 seconds instead
  of cutting it. Add up to 200 ms silence per edge without overlap.
- Decode every window with small/EN and large-v3/auto, both float16, beam 5,
  temperature zero, no prompts, hints, denoise or previous-text conditioning.
- Require large's unforced language to be EN and exact lexical agreement of both
  recognizers and the matched publisher span, at least eight words. Require word
  probability >= .35, positive word intervals and >=80 ms clip-edge margins.
- Apply unchanged previous publisher alignment checks as an additional filter.
  No changes to spoken numbers, negations or publisher words to make a pair pass.
- Keep accepted targets weak, scope unverified, and human/event/entity labels absent.
- Keep old 35-pair dev manifest byte-identical. Verify full speaker/session/original
  split constraints. No dev/test references are used for pair selection.
- Keep every rejection, ASR exception, prediction, model/code/audio hash and attempt.
- Measure yield and execution, run negative contract tests and verify artifacts.

The previous language-large-v1 plan records 16/16 development configurations.
ACCEPTANCE.yaml requires stopping when this budget is exhausted. This preparation
uses train only, adds zero development configurations and does not restart that
budget. The proposed subsequent old/new training comparison using dev checkpoint
selection is BLOCKED_SEARCH_BUDGET_EXHAUSTED under the current contract. No hidden
additional tuning or release selection is performed. Report this limitation even
if pairs pass automatic filters. Further data acquisition/preparation is independent.

Exact consensus is not an estimate of true pair correctness: both recognizers
are Whisper models and share possible errors. Automatic language, VAD and alignment
can be wrong. Script reuse and read speech limit generalization. The strict policy
may yield fewer than 33 old weak pairs; do not relax it after seeing the yield.
Unknown critical-entity accuracy and absent independent test keep quality at
NEEDS_MORE_DATA. No same-checkpoint 10% WER improvement is claimed by training.
