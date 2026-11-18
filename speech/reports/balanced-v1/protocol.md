# Fixed EN sampling-policy experiment

Authorized by the user's "делай" after the recovery-data-audit-v1 proposal.
Freeze this protocol and source before preparation/training. One additional
training arm; conservative cumulative development configurations 30 -> 31.
No threshold relaxation or release selection. Do not update historical studies.

Assumptions: the acquired LibriSpeech train shard contains 19 known speakers;
duration/duplicate checks can reduce eligibility. Speaker balancing changes
utterance content and duration distribution too. This is a comparison of sampling
policies, not an isolated causal estimate of the number of speakers. No automatic
selection score is a probability of transcript correctness.

Select exactly 200 eligible EN records from the pinned already acquired shard.
Eligibility: finite mono 16kHz, 1-30 seconds, nonempty unchanged publisher text,
no known dev speaker or decoded-waveform overlap, no duplicate decoded waveform.
Order speakers and each speaker's records by SHA256("55:" + identifier), ID tie
break, then round-robin one record per speaker until 200. Exhausted speakers are
skipped; do not fabricate or duplicate examples. Sort selected source IDs before
replacing the existing 200 EN support positions. If fewer than 200 exist, stop.
Do not use ASR outputs, reference answers, dev loss or final test for sampling.

The other 233 records (200 RU and 33 weak cockpit), their positions and metadata
remain unchanged. The 35 weak dev rows remain byte-identical. New EN references
retain publisher annotation provenance; no local human listening is claimed.
NLP labels, critical entities and temporal events are not generated.

Training: exact previous lora.py, same offline image, parent Transformers snapshot,
seed 55, LoRA rank8, alpha16, dropout .05, q_proj/v_proj, LR .0001, FP16, batch1,
gradient accumulation4, 120 steps, eval/save at120. The sole checkpoint-120 is
preselected. Keep all logs and prove all433 records were loaded. One new model
output whisper-small-balanced-v1; do not overwrite any saved checkpoint.

Evaluation: normal timestamp-enabled decoder only, parent and previous augmented
model remain reference systems. Same CUDA float16 and effective options except
checkpoint. All661 previous diagnostic inputs plus14 prior quiet copies; inherit
original reference IDs/groups for variants. Reuse and hash-seal all675 old answers
per reference model, separate from new inference. Historical timing is not a new
speed comparison. Candidate inference mounts no reference answers or history.
Four CPU int8 smoke cases check execution only. Verify inference resume without
recomputing completed answers. No post-hoc filtering of failures or difficult cases.

Metrics: unchanged lexical scorer S/D/I/N and CER; paired cluster bootstrap2000,
seed55, 95% CI. Compare candidate with parent and prior augmented separately.
Target relative WER reduction >=10%; statistical confirmation requires 95% CI of
candidate-minus-reference WER below0. Clean EN delta<=.01; RU diagnostic delta<=.01;
noise words/minute delta<=0; runtime failures0. Report all fails and unscorable
weak rows. Describe repeat n-grams and missing words as diagnostics, not temporal
event detection or proof of physical command execution.

Primary independent ASR/entity gate remains NEEDS_MORE_DATA: five exposed human
dev clips/115words/3groups cannot meet original300 utterances/3000words/20groups
and100 verified entities. General RU does not validate RU cockpit or mixed.
LoRA changes checkpoint, so it cannot establish same-checkpoint pipeline gain.
Release is never promoted from this diagnostic; a failed hypothesis is stopped.

Checklist results must be recorded separately, leaving this protocol immutable:
- Prepare balanced pairs and verify groups/protected data.
- Run one120-step training and saved-artifact GPU smoke.
- Freeze model/evaluation identities; execute675 GPU +4 CPU cases.
- Score both comparisons; audit errors, noise, repetitions and alignment.
- Verify saved hashes, CPU service health, Linux resume/report replay.
- Preserve failures and report implemented/executed/verified separately from quality.
