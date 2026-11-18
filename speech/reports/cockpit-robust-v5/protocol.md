# Balanced acoustic augmentation and silence training

Three fresh decoder-only LoRA runs from the same immutable Whisper-small and
byte-identical adapter initialization: uniform control, balanced speech augmentation,
and exactly the same balanced speech objective plus synthetic nonspeech loss weight
0.1. All runs: 240 actual AdamW updates, learning rate 2e-5, BF16 with FP32 trainable
weights, rank 8, alpha 16, dropout 0.05. No KL. Fixed final candidate: balanced-silence.
No checkpoint selection or tuning after control outputs. Base/encoder weights frozen.

Uniform control repeats the existing 247 weak train pairs using the previous seed-55
uniform permutation schedule: 960 speech presentations. Balanced schedules use one
retained original, one hard original, one augmented clean original per update, plus
a paired noisy clip every fourth update or another augmented clean original otherwise.
Exactly 420 acoustic variants, 480 unmodified original presentations, 60 paired-noise
presentations. Both balanced arms use identical speech tensors/order. Only the final
arm adds 240 deterministic synthetic silence/noise examples with a separate weighted
loss; its speech loss normalization remains unchanged. Nonspeech labels are the
actual Whisper <|nocaptions|> token followed by EOS, shifted from SOT, not an invented
human transcript. These signals contain no recorded speech.

Each augmented presentation has its own frozen seed: noise SNR 5/10/15/20 dB,
white/colored/harmonic/band-shaped synthetic noise, two mild early reflections,
gain in [-12,0] dB, and small time/frequency masks restricted to actual audio frames.
Frozen encoder states may be cached after rendering each scheduled presentation;
the variant is never reused with a different parent or label. Original weak texts
are unchanged. Variants do not count as new speech minutes or independent speakers.

Evaluation: all previous 441 inputs (194 controls plus 247 train-fit cases), plus
two predetermined noise/reflection/gain variants of each of the 40 old cockpit dev
clips (5 partial human and 35 weak), plus 20 synthetic nonspeech controls. Evaluation
seeds 750000+ and 850000+ never enter training. Exactly 541 cases per system, four
systems. Original baseline's 441 cached answers may be reused only after checking
waveforms/options/model hashes, with explicit provenance; 100 new baseline ASR calls
and 1623 candidate calls planned. Two CPU smoke calls per trained model.

All speech/noise comparisons use matching source audio/options/languages. Report raw
ASR and the same fixed VAD gate (threshold .5, minimum speech 100 ms) for every model.
Gate retains an entire window when speech is detected; otherwise text is empty.
Measure false suppression of speech, including quiet and synthetic-noisy dev.
All counts are diagnostics; new synthetic conditions are not new independent voices.
Paired group intervals retain the original recording/speaker groups.

Existing diagnostic guards: >=10% relative point improvement on partial human dev,
upper paired 95% interval below zero, <=1 pp EN/RU degradation, no noise insertion
increase. Also report quiet/noisy speech loss and empty-output rates. No release
promotion from weak/exposed references even if all diagnostics pass. Do not open
the 42 blind-dev queue, sealed test, or user annotation revisions. No new human
labels. Preserve all earlier measured artifacts and running serving profiles.
