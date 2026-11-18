# Effect of cross-family weak training data, v7

Authorized on 2026-09-15. Two fixed training arms from the same original
Whisper-small weights and identical decoder LoRA initialization:

- control: old 247 pairs, exactly the v5 balanced presentation schedule;
- expanded: 259 pairs (old 247 minus 6 fully contained short clips plus 18
  cross-family weak labels). No partial overlap may silently remove old audio.

The supplemental clips come only from original train speakers and sources.
All new text remains weak and unprompted Parakeet output backed by the fixed
v6 selection evidence. Original dev references are unchanged. Admission verifies
train/dev partitions before freezing; trainer and inference do not mount dev
references, blind review packets or sealed test labels.

Each arm: 240 real AdamW updates, 4 presentations/update, lr 2e-5, r8/alpha16,
dropout .05, BF16 forward with FP32 parameters, decoder q/v LoRA only, no KL
and no nonspeech loss. All original weights and the encoder remain frozen.
The same slot types and acoustic seeds are used in both arms: 420 retained,
480 hard, 60 paired-noisy presentations; 420 of the speech presentations have
the identical v5 augmentation recipe and feature masking. Supplemental clips
join the hard bucket. Each training clip must be presented at least once.
This estimates the effect of the expanded/replaced population under the fixed
balanced training regime; it does not isolate every individual new clip.

Evaluation: unchanged 541 v5 inputs, including English/Russian controls,
noise-only, quiet, original cockpit and synthetic noisy versions, plus 18
supplemental training-fit probes. Frozen baseline 541 results are hash-verified
and reused; 18 baseline probes and 2 x 559 candidate GPU recognitions are new.
Two predetermined CPU smoke inputs per candidate. Previous v5 balanced is
shown for context on 541 inputs; the freshly trained control is the matched
comparison. No best-checkpoint or seed selection. Candidate is expanded final.

Lexical WER/CER and grouped paired bootstrap unchanged. Raw and fixed-v5-VAD
results are separate. New training-fit rows are never evaluation evidence.
Reusing exposed partial/weak dev cannot establish SPEC acceptance, even if
point metrics improve. No production replacement or automatic release.
