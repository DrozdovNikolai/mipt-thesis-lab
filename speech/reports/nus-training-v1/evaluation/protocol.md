# One NUS LoRA experiment, fixed before training

User confirmation: `можно можно обучать, делай`, recorded in permission.json.
The rights basis is the user's project-use confirmation, not a newly discovered public license.
No redistribution or author permission document is claimed. The old source inspection remains historical.

- One run from the original local Whisper-small Transformers checkpoint, not a failed adapter.
- Replace the 33 weak BLeRIOT train pairs with all eligible NUS pairs; preserve the 400
  balanced EN/RU general-speech train pairs. Existing 35 weak dev pairs are byte-identical.
- Deduplicate PCM; exclude all 11 reference-conflict groups, explicit radio text indicators,
  malformed/zero-signal/overlength clips. Do not rewrite any remaining reference.
- Screening is train-only, deterministic and unverified by human listening. Scope unknown,
  transcripts weak, no role/state/entity/event labels. Source start/end remain unknown.
- All NUS in one conservative train group. No NUS validation/test split or training-WER claim.
- Rank 8, seed 55, LR 0.00005, 240 optimizer steps, one checkpoint/eval at 240.
  This is a prespecified recipe with new data and gentler LR, not an isolated causal data ablation.
  The 960 sample positions suffice for one full pass over the expected <720 train rows.
- Same unchanged standard timestamp decoder, CUDA float16, beam 5, no prompts/hints,
  no VAD/denoise/redecode. No changes to deployment configuration.
- Evaluate all existing 675 diagnostic inputs; compare parent and previous balanced model
  through hash-verified historical predictions on identical input audio/decoding options.
  They are known dev/controls, never a new independent final test. No references/history mount at inference.
- Freeze scorer before training; preserve all outputs/errors. No second run based on results.
- WER counts and paired group bootstrap: seed 55, 2000 resamples, 95% interval. Original 10%
  relative reduction, clean 1pp tolerance, no increased noise insertions. No weakened thresholds.
- No independent critical-entity or event gold. Independent ASR/NLP/temporal remain
  NEEDS_MORE_DATA even if point estimates improve. No release promotion from this study.
- ASR adaptation uses different weights: not a same-checkpoint A0–A4 pipeline success claim.

Checklist: prepare and validate; freeze; one GPU train/merge/convert/smoke; freeze evaluation;
675 GPU predictions; 4 CPU smokes; score; verify hashes and replay from Linux; document actual result.
Old artifacts and user annotations are preserved. No external ASR API or new author contact.
