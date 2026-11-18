# Fixed ASR retraining follow-up, 2026-09-14

Authorization: user requested «так переобучай» after the previous response reported
the exhausted 16/16 development budget and the newly prepared training pairs.
SPEC.md §362 permits a user-authorized resource increase. This is one bounded
follow-up with two training arms, not a reset of prior trial history. Original
ACCEPTANCE.yaml, SPEC.md, SOURCES.md and baseline configuration remain unchanged.

## Assumptions and frozen checklist

- Use the existing 33 weak English cockpit pairs; preserve their weak status.
- Supplement with exactly 200 LibriSpeech EN and 200 FLEURS RU train pairs.
  Publisher-supervised text is not a new local human audit or cockpit evidence.
- Control: 33 pairs. Augmented arm: the same 33 plus 400 general-speech pairs.
- Both start from the same local Whisper-small Transformers parent, seed 55,
  LoRA rank 8 / alpha 16 / dropout .05 on q_proj and v_proj, learning rate .0001,
  batch 1, accumulation 4, 120 optimizer steps. One dev evaluation/checkpoint
  at step 120; no checkpoint search. Existing early-stopping callback remains
  available but cannot stop before this single scheduled evaluation.
- 120 steps permit a complete pass through 433 examples. Record actual loader
  coverage and optimizer steps; do not infer coverage from the requested budget.
- The 35 weak dev pairs are unchanged. No test manifests or test answers enter
  training. General controls were already exposed in past diagnostics and are
  explicitly not an independent final test.
- Compare unadapted parent, newly trained control and augmented model on all
  661 previously frozen diagnostic inputs; same known/auto language information,
  beam 5, GPU float16, baseline preprocessing, no hints/denoise/VAD/redecode.
- Primary reference baseline remains the unadapted parent. Comparing the two
  training arms tests data addition at equal optimizer steps, not equal epochs
  or equal cockpit exposure. Compare neither to a deliberately weakened baseline.
- Freeze code/config/data before training, model hashes before diagnostic
  inference. Inference mounts contain no reference texts or prior predictions.
- Preserve every sample/failure and raw edit counts. Report cluster bootstrap
  (2000, seed 55, 95%) separately for each cohort; one-group intervals are not
  independent-sampling evidence. Weak-reference WER is a diagnostic discrepancy.
- Keep the original 10% target, strict negative upper CI, critical-entity and
  +.01 clean/language WER guardrails. Missing independent cockpit/entity/event
  evidence remains NEEDS_MORE_DATA; report observed failures as FAIL separately.
- Real converted-model GPU and CPU smoke, no network after weights acquisition.
- No release promotion, event-label fabrication, new manual annotation task,
  threshold change or additional adaptive trials. General EN/RU training does
  not validate cockpit RU/mixed quality or temporal event detection.

Checklist execution and measurements are recorded in plan.json, training arm
manifests, evaluation/comparison.json, verification.json and report.md.
