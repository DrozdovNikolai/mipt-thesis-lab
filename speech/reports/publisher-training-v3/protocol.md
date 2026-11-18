# Publisher recovery v3: one fixed training pilot

Train from the original Whisper-small Transformers snapshot on all 221 recovered
English BLeRIOT training pairs (25.44 minutes, nine speakers). Labels remain weak.
One decoder-only LoRA: rank 8, alpha 16, dropout .05, seed 55, AdamW 2e-5,
weight decay zero, batch 1 accumulated four times, 240 actual optimizer updates.
BF16 autocast, FP32 weights/optimizer; no gradient scaler or skipped updates.
Add train-token KL to the unchanged original decoder: weight 1, temperature 2.
The encoder stays frozen in evaluation mode; cache its audio-derived states.
Verify all frozen base tensors and actual optimizer counters. Save the final
checkpoint without early stopping or checkpoint selection using evaluation data.

Convert the merged adapter to CT2 float16. Baseline is the existing CT2 conversion
of the same original Transformers base. Freshly decode both with identical frozen
options and waveforms: all 221 training pairs (fit diagnostic), all 35 old weak
publisher dev pairs, all 159 historical controls, totaling 830 GPU ASR calls.
Controls include 50 general English, 50 Russian, five partially human-reviewed
cockpit clips, 14 quiet variants and 40 noise clips. Variants and overlapping
references are not independent observations. Use the previous language inputs
for controls, original auto language for publisher dev, explicit EN for train fit.
No prompt/hotwords. Two CPU int8 candidate calls only establish runtime usability.

Report corpus lexical WER and paired speaker/group bootstrap intervals; for noise,
report inserted words per minute. Report every cohort, including regressions.
Weak dev transcripts and old partially reviewed/exposed controls cannot establish
independent quality. General EN/RU WER degradation >1 percentage point or increased
noise insertions fails the existing diagnostic guards. Human point improvement
target is 10% relative, with a negative upper paired CI for statistical support.
Do not alter old search budgets, references, split membership, production model,
or acceptance criteria. Do not access the held-out test or claim release readiness.
Train, inference, and scoring run offline; inference has no reference-text mount.
