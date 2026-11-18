# Hard/noisy aviation: matched training regimes

One frozen train population: existing verified-by-pipeline weak publisher pairs,
new full train clips where small disagrees but medium.en and explicit-English
large-v3 agree with each other and the publisher document, plus locally checked
noisy copies from acoustically confirmed BLeRIOT-C parents. Remove old intervals
overlapping new full clips instead of counting duplicate speech twice. No disputed
review transcript or blind development queue transcript enters training.

Train three fresh LoRA adapters from original Whisper-small: decoder with KL=1,
decoder with KL=0, encoder+decoder with KL=0. These two contrasts separately examine
removing the teacher constraint and adapting the audio encoder. Shared decoder
adapter initialization is byte-identical; the same seed-55 shuffled sample schedule
is used in every arm. Rank 8, alpha 16, dropout .05, AdamW learning rate 2e-5,
weight decay zero, BF16 autocast with FP32 weights, accumulation 4, 240 actual updates
per arm, teacher temperature 2. No skipped updates, early stopping, or checkpoint
selection. Fixed final candidate is full-ce; report all arms without selecting a
winner from development performance. All original base weights remain immutable;
encoder outputs are cached only for decoder-only arms.

Convert each final checkpoint to CT2 float16. Freshly run the original matched CT2
baseline and all three candidates on all training rows (fit diagnostics only),
the complete previous 194 diagnostic cases, and all admissible paired noisy versions
of the 35 old weak dev clips. Exact cohort/call counts are frozen in plan.json before
training. Options, languages and waveforms match within each comparison. No prompt,
hotwords, reference text or documents are supplied to inference. Two CPU int8 smoke
calls per candidate. No performance/latency claims from concurrent runs.

Report corpus lexical WER, train-hard/retained/noisy cohorts separately, paired
cluster confidence intervals on controls, and inserted words/minute on both noise
sets. Existing diagnostic guards: >=10% relative human point improvement and negative
upper paired CI; <=1pp general EN/RU degradation; no noise insertion increase; no
runtime failure. Weak/exposed references remain exploratory even if guards pass.
The new time-stratified blind dev review packet is unscored until a human transcribes
it. It spans additional intervals/recordings but does not create new speaker identities.
Do not access the sealed test, alter the previous selection ledger, or promote a release.
