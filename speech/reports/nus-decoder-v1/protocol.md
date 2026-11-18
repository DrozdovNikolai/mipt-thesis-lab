# Fresh decoder-only LoRA on the existing full NUS/EN/RU mixture

User requested execution of the decoder-only proposal. This is one separately
frozen diagnostic training arm. Previous failures, protocols, data and serving stay
unchanged. The original release dev-search is exhausted; no release selection here.

Assumptions and checklist fixed before execution:
- Same byte-identical 675-row train manifest as nus-training-v1: 275 admitted NUS,
  200 EN + 200 RU general pairs, about 94.35 minutes. Preserve source rights,
  labels, unknown metadata and conservative groups; no new inferred annotations.
  NUS references are usable train supervision, not human-verified cockpit gold.
- Fresh original local Whisper-small base. LoRA rank 8, alpha 16, dropout .05,
  on decoder self/cross-attention q_proj/v_proj only (48 modules, 96 tensors).
  No encoder adapters. Check encoder tensor hashes before/after training, at both
  milestones and after merging. The original encoder must remain byte-identical.
- Exactly 1200 optimizer steps, batch 1, accumulation 4, fused AdamW, FP16,
  TF32 off, seed 55. LR for updates 1..240 follows the former 5e-5 linear decay;
  at completed step 240 the next update's LR becomes constant 2e-5 through 1200.
  Preserve optimizer moments across the phase boundary. No dev loss/early stopping.
  Custom LambdaLR overrides the TrainingArguments scheduler placeholder.
- Save exactly steps 240 and 1200. Evaluate both and predesignate 1200 as final;
  do not select another checkpoint after examining dev. Step 240 is a diagnostic
  comparison to the prior joint encoder+decoder 240-step full-mixture adapter.
  This is not bit-identical stochastic ablation: adapter topology/initialization
  and the absence of the old final dev-loss call are explicitly different.
- Score all 275 NUS train clips separately from the same 159 existing controls:
  five human cockpit dev, 50 clean EN, 50 RU, quiet variants, and two non-speech
  collections >=5 minutes each. No NUS held-out/generalization claim in this run.
- Frozen legitimate unadapted parent and old joint-240 historical answers, same
  CT2 float16, waveform/language information, beam 5 and standard timestamp decoder.
  No prompts, denoise, VAD, redecoding, changed normalizer or reference corrections.
- Reference-blind inference; offline local volumes. Train sees only the train
  transcript manifest. Scoring sees dev references after inference. All old model
  and audio volumes read-only; new north55-speech_nus_decoder_v1 is isolated.
- One arm, 1200 training updates, 550 fit + 318 control GPU ASR calls and 4 CPU
  calls (one EN/NUS and one RU control at each checkpoint). No adaptive extra run.
- Report all S/D/I counts, runtime failures, per-cohort WER, 2000-resample paired
  cluster bootstrap seed 55 and 95% CI. One-group RU bootstrap is descriptive and
  degenerate; three exposed cockpit groups are insufficient for independent proof.
- Keep original 10% relative WER target, CI upper <0, clean/RU +1pp tolerances,
  no noise insertion increase. Missing independent critical entities, >=20 groups,
  >=300 human cockpit utterances/>=3000 words and NLP/event/temporal evidence remain
  NEEDS_MORE_DATA even if available point estimates improve. Never promote release.
- Execute gradient/freeze tests, local GPU/CPU inference, source checksum checks,
  PowerShell/Linux replay and document implemented/executed/verified separately.
