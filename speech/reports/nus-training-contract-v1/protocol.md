# NUS training contract diagnosis v1

This is a bounded training-only diagnosis following the user's request to act on
the existing transcripts. It does not resume the exhausted release dev-search.

Assumptions: the 275 screened NUS pairs remain source-provided weak train data;
the 400 general EN/RU pairs retain their existing provenance. Our import must not
alter audio/text. A source assertion of manual checking is not a local listening
claim. No new human labels, test access, source deletion or serving changes.

Checklist frozen before execution:
- [ ] Verify all 675 training file hashes, duration, channel, waveform equality
  between librosa training and soundfile inference, log-mel agreement (max abs
  difference <= 1e-4), label language/task/end prefix and no truncation.
- [ ] Independently reload the base and adapter, merge in FP32 and compare every
  stored merged tensor exactly. Verify original artifact hashes first.
- [ ] On the first 32 NUS IDs sorted by audio SHA256 then ID, measure saved parent
  and NUS teacher-forced loss on matching audio and cyclically different audio.
  128 forward passes, FP16 GPU; not WER, not independent quality evidence.
- [ ] On ALL 275 NUS train inputs, run each saved CT2 model once with exactly the
  historical options except without_timestamps=True. Keep word timestamps and
  the unmodified faster-whisper loop. No hints, references or previous predictions
  are mounted in these generation processes. Budget 550 ASR calls, no tuning.
- [ ] Compare with retained timestamp-enabled training-fit results. Report this
  as training-fit diagnostic only. Keep failures and no automatic text correction.
- [ ] Run guard tests and document actual commands/results and limitations.

The timestamp factor probes a concrete mismatch: supervised labels contain the
notimestamps token while historical inference requests timestamp tokens. It is
not assumed to be the cause or an effective fix. No development re-evaluation,
retraining, release selection, candidate promotion, or threshold change in this
study. Cases disputed by machines remain disputed, never human-verified.
