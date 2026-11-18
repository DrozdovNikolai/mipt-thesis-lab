# Speech-aware tail repair — fourth fixed implementation

The first repair consumed the entire window after text generation. Its frozen
mechanical regression FAILED: a real utterance repeated twice was emitted once.
The proper baseline emitted both. That failed implementation and its264-input
comparison remain in text-window-fix-v1. They are never overwritten or promoted.

This second implementation follows the same explicit user request to repair the
tail bug and preserve spoken repeats. Two repaired checkpoints add2 to28 (30
cumulative including the failed first repair); proper baselines are replays.
No training or parameter search. Development choices use the engineered repeat
failure and source-code trace, not WER-driven tuning or final-test answers.

Use all264 unchanged decoding-v1 inputs. Same weights, CUDA float16, source/scorer
references and baseline options. Freshly run parent/augmented proper baseline
and repaired text mode. Reuse broken-text outputs only for separate comparison.
Never advertise repair gains versus broken text as gains versus proper baseline.

Change exactly the upstream seek-after-word-alignment condition. Reopen the tail
only if Silero detects remaining speech within the current window. VAD analyzes
the prepared input once and never crops, concatenates, or changes the audio sent
to ASR. The initial window is always decoded with unchanged no-speech thresholds.
Fixed tail detector: threshold.4, minimum speech50ms, minimum silence400ms, pad0ms,
max speech30s. No padding because it would call trailing silence new speech.
No confidence calibration or guaranteed quiet-command recall is claimed.
VAD false negatives remain an explicit risk measured on quiet/short controls.

Word alignment remains unchanged; no word/token deduplication, numeric repair,
role inference or telemetry inference. Input intervals are scoped per generator
iteration, not stored as mutable shared model state. The MIT upstream loop is
vendored readably with one conditional change and original license. Source/version
guard fails closed on an unreviewed backend upgrade.

Mechanical acceptance: original2.27s clip needs1 decoder invocation; two real
copies with1s pause need2, with both utterances retained; empty input needs0;
word times stay in the engineered +30s coordinate system. Source3536-8226-0027
is general EN, not cockpit-command gold. Extra examples are not quality evidence.

Quality protocol stays unchanged: lexical S/D/I/N, WER/CER; paired cluster
bootstrap2000 seed55 95%CI; target>=10%relative, clean/RU delta<=.01, noise
insertions/minute delta<=0, no runtime failures. All counts and failed gates stay.
Five exposed cockpit dev clips/115words/3groups cannot establish independent
ASR/critical-entity/NLP/temporal quality; no release promotion or final-test access.

Checklist completion is recorded separately, preserving this frozen protocol:
- [ ] Mechanical tests, original audio, two actual copies, empty input and offsets.
- [ ] Freeze identities before quality inference;1056 GPU records and8 CPU smokes.
- [ ] All528 proper-baseline replies replay historical hypotheses and word times.
- [ ] PowerShell/Linux resume and byte-identical scorer/report replay.
- [ ] Preserve original plans/results/data; report unresolved gates honestly.

EOF correction fixed before quality inference: v2 failed its mechanical test
because the detector had not observed its400ms terminating silence at EOF.
Append16000 zero samples only to VAD analysis, clip detected intervals back to
the original sample count, and send the unchanged original waveform to Whisper.
This finalizes pending speech; it neither extends the ASR input nor its timestamps.
The frozen v2 failed regression remains preserved; it did not run quality inference.
Both v1 and v2 are rejected; no choices are made from their WER to tune this fix.

Final mechanical correction before quality inference: v3 still classified the
acoustic tail of the already recognized utterance as speech. Re-entry now needs
a distinct speech onset after last_word_end, within the current window. Advance
to that onset minus250ms context, bounded below by the last word and strictly
after the previous seek. Never re-enter the same already-covered speech region.
The first window and tokens stay unchanged. Later re-entry is a feature-frame
seek in the original signal, with original offsets; no waveform concatenation.
This supersedes the earlier broad end>last_word_end guard description above.
V2/v3 did not run quality inference. V1 full measurements and all failed
mechanical regressions remain preserved. Count all four paired implementation
prototypes conservatively in the resource log; no acceptance thresholds change.
Risk: missed new onsets or continuous repeats without a detected pause may still
be omitted by ASR. Explicit repeat, quiet/short and full dev checks are required;
no guarantee of critical-command recall or release PASS is inferred.
