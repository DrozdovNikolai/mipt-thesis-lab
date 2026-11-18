# Cross-family ASR diagnostic, v6

This is a development experiment authorized by the user on 2026-09-15.
The preselected recognizer is NVIDIA parakeet-tdt-0.6b-v2, revision
ae9ad07059c7c739ffaf932226a8fe64ae2620b0. It is English-only. GPU float32,
greedy_batch, batch size 4, word timestamps, no text prompts and no VAD.
Acquisition is the only networked stage; inference has no references or network.

Population: 491 unchanged v5 English/speechless inputs, including 247 weak train-fit
clips, plus all 352 previously rejected v4 training candidates. No new blind-dev
or sealed test audio or annotations are used. The comparison reuses hash-verified
Whisper outputs on exactly identical float32 audio. VAD is the same fixed v5 gate.
Primary diagnostic metrics keep lexical WER/CER unchanged. A symmetric existing
numeric canonicalizer may be reported separately; it never replaces lexical WER.
Already exposed controls and weak/partial references cannot establish acceptance.

Before scoring, freeze model identity, inputs, implementation, historical predictions,
references and selection policy. Select new weak training labels only from train:
at least four words, 3–25 seconds, <=5 words/second, plausible ordered word times;
Parakeet agrees with a reliable Whisper medium.en or large-v3 output at <=8%
normalized word disagreement (exact below 8 words), with exact numeric and
state/negation sequences. The supporting Whisper must have median word confidence
>=.65 and <=25% zero-duration timestamps. Publisher checklist support must cover
>=90% of words and support critical tokens. Targets remain unprompted ASR output,
never copied or completed from a checklist. All labels remain explicitly weak.
Report both summed clip duration and union of original source intervals so overlap
does not masquerade as additional data. Audit existing labels; do not automatically
replace them merely because a different model disagrees.

Noise investigation: inspect the 16 paired real noisy train clips, verify unchanged
parent text and waveforms, quantify amplitude, spectral energy, timing correlation,
and actual emitted Whisper segment no-speech/log-probability behavior. Correlation,
coherence, or VAD rejection alone is not proof that a recording contains no speech.
No production model replacement is authorized by diagnostic success alone.
