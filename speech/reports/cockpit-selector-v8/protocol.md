# Fixed acoustic selector, v8

Two existing English hypotheses, from v5 balanced Whisper small and v6 Parakeet,
are rescored on their identical original audio by unadapted Whisper medium.en.
This is a new inference composition, with no training or manual labeling.
Only this primary rule is evaluated; thresholds will not be swept on dev.

Non-English inputs keep the Whisper response. An actual empty Parakeet response
returns empty text. A missing response is an error, never a substitute for silence.
If Whisper alone is empty, keep Parakeet. Identical normalized text keeps Whisper.
Otherwise, normalize both candidates identically with lexical_normalizer_v1 and
compute mean log token probability using CTranslate2 Whisper.align. This is the
teacher-forced text probability conditioned on audio AND preceding candidate text,
not a calibrated confidence or purely acoustic likelihood. No end-token, timestamp
or prompt likelihood is included. No checklist or reference is used in selection.

Parakeet replaces Whisper only if its mean log probability exceeds Whisper by
strictly more than 0.10 nats/token. This fixed modest margin favors keeping Whisper
on close scores; it is not fitted. Output the selected ORIGINAL response unchanged.
Unscoreable empty-normalized or over-context candidates are explicitly recorded;
if only one is scoreable select it, if neither is scoreable fail. Audio must fit
within 30 seconds. Do not silently trim audio or text. Float32 GPU computation.

Inputs: all 541 v5 inputs, including 247 training-fit probes, 50 Russian pass-through
controls, 60 nonspeech controls, and original/quiet/synthetic noisy cockpit dev.
As in v6, all 491 inputs outside the explicit Russian control use the English
profile. Previous Whisper "auto" is a decoding option, not a verified source
language; preserve it as original_input_language. Do not infer routing from WER.
Reused ASR: 541 baseline, 541 balanced, 491 Parakeet; input and prediction hashes
must match completed v5/v6 execution. Rescoring receives no cohort/reference/gate
metadata. Fixed v5 VAD composition is reported separately after raw selection.

Two train-only disagreements chosen by sorted id at preparation are replayed on
CPU float32 and GPU float32. Record actual align/encoder forward calls separately
from the 2 CPU and 2 GPU replay inputs. Require identical replay selections and
token ids, mean-log score differences below 0.01 CPU / 0.00001 GPU.
Record these forward calls separately
from ASR generation; this experiment generates no new ASR hypotheses. Test rule
handling of empty/missing responses, exact normalization, numbers/negation/state
disagreement, finite probabilities, and fixed score margin before freezing.

Score unchanged lexical WER/CER and grouped paired bootstrap. Primary point target:
at least 10% relative reduction on five old partial-human cockpit dev vs balanced,
with 95% grouped interval upper bound below zero. Also report weak-dev, controls,
nonspeech words/minute AND raw nonempty responses, and every training-fit result
separately. No oracle selection or model promotion. Exposed partial/weak dev cannot
confirm SPEC acceptance. Blind-dev and sealed test remain untouched. The previous
Parakeet results motivated the hypothesis; this is exploratory on reused audio.

API reference: https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html
Local faster-whisper find_alignment uses text_token_probs from this API. Those
probabilities also include a language prior and may favor fluent wrong candidates.
