# Train-only audio router, v9

Motivation: v8 medium.en text-likelihood selection failed, including on strong
synthetic noise. This subsequent hypothesis uses waveform features only to choose
between v5 balanced Whisper and v6 Parakeet. No text probabilities or references
enter the classifier. Its training labels describe known synthetic noise severity,
not the correctness of either ASR response.

Train population: original 231 clean cockpit train clips, excluding 16 real noisy
copies whose SNR is not known. Use each clean original plus 4 newly seeded variants
at each of 0, 5, 15, 25 dB using the existing v5 augmentation algorithm. Labels:
0/5 dB -> severe; clean/15/25 dB -> not severe. 3927 observations from 9 train readers.
Seeds start at 950000, disjoint from v5 train/dev seeds. Reuse of the augmentation
family is explicit: successful routing on that synthetic family is not evidence
for unseen real cockpit noise. Do not use held-out ASR error labels for training.

Features: 62 deterministic gain-invariant temporal/spectral features. No raw level,
filename, speaker id, SNR metadata, cohort, text or duration feature is supplied.
ExtraTreesClassifier: 256 trees, depth 12, min_samples_leaf 4, class_weight balanced,
random_state 55, n_jobs 4. Fit leave-one-reader-out predictions across 9 training
readers. Threshold = max(0.80, 99th percentile (higher) of negative OOF probabilities).
This threshold is chosen solely on training audio and known synthetic labels.
Then fit the final classifier on all 3927 training observations. No hyperparameter
search, no dev threshold adjustment. Report OOF confusion and held-reader partitions.

Inference: same frozen 541 candidates from v8/v5/v6. Russian is passed through.
An actual empty Parakeet response returns empty. For all other English inputs,
choose original Parakeet text iff predicted severe-noise probability >= threshold,
otherwise original Whisper text. Preserve selected text unchanged. No VAD inside
primary routing; report the old fixed VAD separately. No new ASR generation.

Primary diagnostic purpose: preserve original partial-human cockpit WER at or below
v5 balanced, improve its 5 dB versions, report all 35 weak-dev/noise/general/quiet
controls and train-fit separately. Use grouped bootstrap but do not claim independent
acceptance from reused partial/weak dev. New blind-dev and sealed test remain unused.
Freeze recipe/code before training and classifier/threshold before dev inference.
Verify training feature replay, group isolation, model fingerprint, every routed
input and independent edit totals. This is a separate candidate; retain the v8 FAIL.
