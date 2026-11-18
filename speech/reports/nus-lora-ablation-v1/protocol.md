# NUS LoRA component ablation — frozen before component inference

Reason: NUS full-adapter fitting WER fell 63.08% -> 51.50%, but exposed cockpit
dev worsened. The dominant repeated output was generated in the first decoder
call with zero previous tokens. Context carry-over does not explain that case.

One bounded component ablation, two complementary arms, no new training:

- encoder: retain all saved encoder LoRA A/B; zero decoder B only;
- decoder: retain all saved decoder LoRA A/B; zero encoder B only.

Both use the original parent Transformers base and the exact saved NUS adapter.
No learning rates, epochs, mixing coefficients, lexical replacements or penalties
are searched. Keep all tensors/checksums and source copies. No source mutation.

Compare to the frozen original parent and full NUS checkpoint using the same
ordinary timestamp decoder, previous text=True, language information, float16,
beam=5, temperature=0; VAD/hints/denoise/redecode stay off. Never feed references.

Input membership is fixed by metadata before the new inference:
all 275 NUS train fitting clips; all existing 50 general EN, 50 general RU,
five human cockpit dev, their five quiet copies, nine quiet short EN controls;
at least five minutes from each existing noise cohort, sorted by audio hash/id.
No publisher-weak/mixed-noise expansion or parameter search. Reference values
are unchanged. Fitting and exposed development evidence are reported separately.

This is a diagnostic extension after the original search budget, not release
candidate selection. No final test. No statistical/generalization claim from
one NUS group or five cockpit clips. Critical entity/NLP/temporal evidence is
still missing. Original acceptance and baseline hashes remain frozen.

Checklist: freeze -> verify source/partition/convert -> actual offline GPU
fit/control -> CPU smoke -> score all cases -> report component effects.
Even a favorable component result cannot be promoted without independent gates.
