# Fixed NUS convergence diagnostic

Authorization: user explicitly said "делай" after the proposal to check fitting
on a small fixed NUS subset and, only if it learns, assess other recordings.

Assumptions/checklist (frozen before any new training):
- 275 existing screened NUS source-provided weak training pairs retain their
  original texts, rights evidence, unknown speaker metadata and one source group.
  Select exactly 32 by ascending audio SHA256 then sample ID. Selection does not
  use ASR answers. No manual relabeling or upgraded human-verification status.
- Initialize from the same unadapted local Whisper-small Transformers weights,
  seed 55, rank 8, alpha 16, q/v LoRA, dropout .05. Use AdamW fused, LR 5e-5, linear
  decay, zero warmup, batch 1, accumulation 4, FP16 AMP, TF32 off. 240 steps =
  960 training positions, nominally 30 passes over 32 items. Deterministic audio
  features may be cached; they are the previously audited preparation.
- Save steps 40, 120, 240, without early stopping, dev evaluation or best-model
  loading. Retain all checkpoints and training history. These points show a
  learning curve; they are not candidate selection under the exhausted dev-search.
- Convert all three to CT2 float16 and independently generate all 32 transcripts.
  Keep the ordinary timestamp decoder, beam 5, temperature 0, English input,
  unchanged word timestamps, no VAD, hints, denoise or redecode. Generation gets
  no reference mount. Baseline step 0 reuses hashed historical parent answers.
- Training-fit success means final step 240 lexical corpus WER <= 0.10, with no
  runtime failures anywhere in the fixed curve. This is a diagnostic fitting
  criterion, NOT a change to ACCEPTANCE or a release gate. No threshold tuning.
- If final train-fit passes, assess ONLY step 240 on the remaining 243 NUS clips
  and the same 159 prior controls: five human cockpit clips, general EN/RU, quiet
  copies and >=5 min each of the two noise sets. All groups/splits stay unchanged.
  The remaining NUS are same-source train diagnostics, not independent validation.
  Report repeated-text overlap and unknown speakers; do not claim independence.
- Independent cockpit test, entities and NLP/temporal evidence remain missing.
  No release promotion even if fitting and exploratory transfer improve. No
  absolute guarantee of target-quality improvement from memorizing training data.
- Budget: one training arm, 240 optimizer steps, 96 new fit GPU ASR calls, at most
  402 conditional transfer GPU calls and one CPU smoke. No adaptive new recipes.
- Check source preservation, offline/readonly mounts, guard tests, actual device
  and precision, and PowerShell/Linux replay. Freeze scorer with implementation.

Outputs are isolated in a new Docker volume north55-speech_nus_convergence_v1.
The previous model volume and all source audio remain read-only in this study.
