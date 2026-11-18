# Frozen diagnostic: matched CE versus CE + base-model KL

## Assumptions and reason

User requests another concrete improvement using existing data, without bulk
manual annotation. Existing full decoder-only training improved NUS train fit
but harmed 25/50 clean EN, 21/50 general RU and 5/5 exposed human cockpit clips.
These observations are diagnostic dev exposure, not independent confirmation.
275 short NUS rows are 40.74% of utterances but 14.68% of training duration;
400 general examples did not by themselves prevent forgetting. This imbalance
is an observation, not an established cause. Uppercase EN output and repetitions
are additional observations; transcripts and lexical scoring will not be edited.

Hypothesis: an explicit KL penalty against the immutable original Whisper can
reduce forgetting while still learning the supplied train transcripts.
Method motivation: [Li and Hoiem, Learning without Forgetting](https://arxiv.org/abs/1606.09282).
That paper does not establish benefit for our speech task; this experiment tests it.

## Fixed design and budget

Two fresh decoder-only LoRA arms from the same original Whisper-small weights.
Arm 1: ordinary cross entropy (CE), matched ablation control.
Arm 2: CE + 1.0 * T^2 * mean_token KL(teacher || student), T=2.
Arm 2 is the candidate fixed in advance. No checkpoint or arm selection after scoring.
Teacher uses the same frozen base with adapters disabled and eval mode, under
the same human/publisher train prefix. It is not an EMA or a generated gold label.
KL covers all non-padding label positions on all 675 training utterances.
The existing transcripts, timestamp-token convention and per-utterance CE remain.

Each arm: exactly 1200 AdamW updates, batch 1, accumulation 4; constant LR 2e-5,
weight decay 0, max gradient norm 1; rank 8, alpha 16, LoRA dropout .05, seed 55.
Only the 48 decoder q/v projections train (96 LoRA tensors). Identical initial
adapters and the same 4800-example shuffled schedule are verified by hashes.
BF16 autocast, FP32 parameters/optimizer/KL arithmetic, TF32 off, no GradScaler.
Nonfinite losses or gradients fail rather than silently skipping updates.
The matched control shares these changes; old FP16 experiments are historical
context, not the causal comparison for the KL effect.
Frozen encoder output is cached on CPU, once per train waveform, in eval/BF16;
there are no trainable encoder parameters or stochastic encoder augmentation.
Entire frozen base state and a teacher logit probe must remain byte-identical.

Both final models are converted with the original CT2 float16 recipe. Each runs
275 NUS training-fit + 159 exposed diagnostic controls: 868 new GPU ASR calls total,
plus 2 EN/RU CPU smokes per arm (4 total). Arm numbers in checkpoint paths and
`step` compatibility fields mean arm IDs, never training-step counts.
No other hyperparameters, epochs, checkpoints or decoding options may be tried
inside this freeze. No final test is opened. The exhausted 16-trial release
dev-search budget is unchanged; this is a separate user-authorized diagnostic,
not release candidate selection. Serving stays on the prior admitted pipeline.

## Data, permissions, isolation

Use exactly the existing `nus-training-v1/train.jsonl`: 275 NUS + 200 EN LibriSpeech
+ 200 RU FLEURS, all train, 675 total. Preserve source restrictions and existing
user research permission hash; no new source/download/rights claim. NUS remains
one conservative unknown-speaker/session group and weak reference quality.
No event labels or temporal labels are fabricated. No new corpus split is made.
Known control speaker and waveform disjointness is checked against train.
Clean/noisy copies retain their historical group IDs. Unknown identities limit claims.
All old reports, user edits, annotation revisions and normative files are preserved.

Network disabled throughout training/inference. Source model/audio volumes RO;
new weights only in `north55-speech_nus_retention_v1`. Train sees only train texts,
inference sees no reference files, scorer runs after saved predictions.
Filenames, manifests, model files, code, effective decoding and decoded PCM identities
are checked; historical missing runtime PCM evidence remains explicitly marked.

## Measurements and decisions

Report unchanged lexical S/D/I/N, WER for each cohort, paired cluster bootstrap
2000 resamples, seed 55, 95% interval on exposed non-training speech, and non-speech
inserted words/minute. Compare arm 2 with arm 1 (KL ablation) and both with the
unchanged parent. NUS fitting is training error, not test quality. Five human clips,
115 words, three groups cannot prove the required independent improvement. RU
is conservatively one group; its bootstrap interval has no population confidence.
Runtime failures stay in scoring. Safety/entity/temporal NLP gaps remain explicit.

Original gate: >=10% relative lexical WER reduction, CI upper <0, EN/RU absolute
increase <=.01, no increase on either non-speech cohort, zero runtime failures.
All mandatory independent evidence requirements remain unchanged. Any measured
violation gives FAIL; insufficient independent evidence remains NEEDS_MORE_DATA.
Even a favorable descriptive result cannot promote arm 2 to release.

## Checklist frozen before execution

- [ ] KL direction, temperature scaling, padding and teacher detachment tests.
- [ ] Real tiny Whisper test: base teacher remains original after adapter updates.
- [ ] Freeze code, population, protocol, budgets and prior evidence identities.
- [ ] Execute both matched arms; verify 1200 actual updates and identical schedule.
- [ ] Verify base/encoder immutability, save optimizer states and teacher probes.
- [ ] Convert, run 868 GPU ASR and 4 CPU smokes with identical decoding policy.
- [ ] Score, retain all measurements and report independent evidence limitations.
- [ ] Run PowerShell commands and Linux replay; preserve failed attempts if any.
- [ ] Report implemented/executed/verified separately; no release promotion.

Completion is recorded in a separate decision/report; this protocol is immutable.
