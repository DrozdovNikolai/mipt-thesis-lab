# Language and large-v3 study, frozen design before inference

2026-09-14. User explicitly requested the two recommended checks now.

- Preserve all existing requirements, baseline, user reviews, models and results.
  No AGENTS.md exists in the repository or its checked parent directories.
- Part 1: compare the prior small/auto outputs with a new small run that passes
  EN only for existing human-reviewed dev entries whose language is EN and whose
  scope/listening verification is present. Use saved metadata, never reference
  words or model-detected language to decide which inputs receive EN. Leave all
  other input modes unchanged, including RU controls and unknown/noise inputs.
- Part 2: run pinned Systran faster-whisper-large-v3 FP16 conversion without
  training. Compare fresh small and large on the identical 661 existing dev/
  diagnostic inputs, language policy, CUDA/float16, beam=5, temperature=0, raw
  whole clips and all other decoding settings. No VAD, denoise, hints or re-decode.
  A checkpoint comparison is not evidence of same-checkpoint pipeline improvement.
- These are two new configurations, using the remaining 2 of the conservatively
  recorded 16-configuration budget. No additional configuration search, threshold
  changes, test access, training or candidate promotion is authorized by the data.
- Fix code, source revisions, model/audio/reference/config hashes and all selected
  inputs before either inference. Inference containers get no transcript file;
  scoring reads reference files separately after outputs are complete.
- Run models sequentially on RTX 5070 Ti GPU 0 without network. Fresh small
  inference provides matching runtime measurements. Preserve all sample failures
  as empty hypotheses. Record initialization and per-sample wall time, real device
  and precision, sampled GPU memory and process RSS with their measurement limits.
- Preserve the original time scale and raw words; do not normalize away numbers,
  translate French/mixed speech, infer a speaker role or infer aircraft state.
- Keep weak publisher references, 5 partial human dev transcripts, EN/RU general
  controls, mixtures and publisher-described noise as separate cohorts. Compute
  paired group-bootstrap CIs, 2000/seed55; one-group CIs cannot prove generalization.
- Engineering checklist: acquire/hash 6 model files; freeze; contract tests;
  both GPU runs; real large CPU smoke; compare all records; independent metrics/
  integrity checks; PowerShell/Linux score replay; measured report and limitations.
- ASR release quality remains NEEDS_MORE_DATA without independent cockpit final
  test and critical entities, regardless of a favorable diagnostic point result.
  No new NLP results or labels are produced by this study.
