# Evaluation protocol

The original `ACCEPTANCE.yaml` is unchanged; `configs/acceptance.yaml` is its byte copy.
The loader verifies SHA-256
`32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071`.
`north55 acceptance-schema` emits its validated JSON schema. Thresholds are project
targets, not aviation standards or measured results.

Before training, the curator imports local audio and verifies bytes and canonical
decoded duplicates. Connected components join shared speakers, sessions, source
recordings, originals and all variants. Components stay intact in 70/15/15 grouped
partitions; a small number of components does not justify weakening independence.
A transcript-free partition proof records hashes and group membership. Script
overlap and unknown speakers are reported separately.

The baseline is multilingual Whisper small/int8 on CPU, beam=5, temperature=0,
task=transcribe, no hints, no external VAD, no denoise and no re-decode. Decoder
parameters are explicit and recorded. A0–A4 use the same model, precision, device,
input-language information and common audio preparation. A5 (LoRA) and small vs
large comparisons are separate checkpoint experiments.

`configs/search.yaml` contains eight bounded trials (limit 16). Selection first
requires measured entity/clean/non-speech guardrails; then compares lexical WER,
RTF and active stage count. All attempts are retained. Missing guardrail annotation
prevents selection. No stage is an improvement merely because it executes.

Freeze selection, model, configuration, data membership, acceptance and scorer
before opening final references. Evaluator queues sanitized requests to the normal
worker, receives every result/failure and then scores. Test access is logged; a
different selection cannot reuse the same final reference cohort. Failed inference
is an empty hypothesis plus an operational failure, not an excluded sample.

Lexical corpus WER is summed (S+D+I)/N, not mean file WER. NFC/case/controlled
punctuation normalization is symmetric and preserves decimal values, negation and
directions. Entities match occurrences one-to-one and count a wrong value once as
a substitution. Temporal matching is class-compatible maximum matching at IoU 0.5;
duplicate predictions are false positives. Unknown salience is not a true negative.

Paired bootstrap resamples frozen independent groups 2,000 times, seed 55. Delta is
candidate minus baseline. PASS requires relative lexical WER reduction >=10%, upper
95% CI <0, all normative guardrails and evidence minima. Baseline WER=0 is
INCONCLUSIVE. Missing human evidence is NEEDS_MORE_DATA. Separate NLP-only and ASR→NLP
reports compare learned labels with rules on the same inputs. Temporal status is
separate from utterance classification.

Research reports contain predictions, edit counts, strata/support, confusions,
timings, frozen hashes, JSON/CSV/Markdown/HTML. General-speech smoke reports and
synthetic code tests are engineering evidence only and must never be presented as
cockpit benchmark improvement. No release pointer is created automatically.
