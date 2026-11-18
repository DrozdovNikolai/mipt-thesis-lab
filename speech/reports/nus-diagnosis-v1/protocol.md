# NUS failure diagnosis v1 — pre-execution protocol

User instruction: «исправляй», following the explicit proposal to investigate
repeated decoding and measure fitting to the NUS training pairs. No retraining.

## Assumptions and boundaries

- Preserve all existing code changes, user annotations and earlier reports.
- Five human-reviewed cockpit dev clips / three groups remain exposed dev.
  Their quiet copies are dependent observations. No final-test access.
- All 275 selected NUS source pairs remain weak, one conservative train group.
  Training-set WER diagnoses fitting only, not generalization or release quality.
- Compare saved parent/NUS checkpoints at the same CUDA float16 precision,
  beam 5, temperature 0, input-language information and ordinary timestamp mode.
- Instrument get_prompt, generation, timestamp splitting and word alignment.
  Wrappers record and restore; they never edit waveforms, outputs or timestamps.
- Exactly one new factor: condition_on_previous_text=False, separately for both
  checkpoints. Default True is the retained control. No VAD, hints, denoise,
  repetition penalty, text deduplication, training or reference changes.
- This is a bounded diagnosis beyond the exhausted original dev-search budget,
  not a new final candidate selection or an extension of ACCEPTANCE thresholds.
- All inference containers have network none, read-only models/audio/source,
  sanitized inputs and their output directory. No reference/historical mounts.
- Preserve runtime failures as empty hypotheses and failures; no silent retry.

## Execution and decision checklist

1. [ ] Freeze code, models, inputs, references, protocol and source hashes.
2. [ ] Replay all five human clips and their quiet copies with all four variants.
       Check unchanged on-context traces against historical hypotheses.
3. [ ] Decode all 275 NUS training pairs on parent_on and nus_on; report lexical
       S/D/I/N and WER with existing lexical_normalizer_v1, without a quality CI.
4. [ ] If context-off changes decoded text in trace clips, evaluate both off
       variants on all 675 previously frozen dev/controls; retain every result.
       Otherwise record it as ineffective for these errors and skip expansion.
5. [ ] Run real CPU smoke and trace restoration/integrity tests.
6. [ ] Report actual decoder call boundaries, first-pass versus later-pass
       repetitions and fitting-versus-transfer findings. No invented audio audit.
7. [ ] Only address a demonstrated defect. Any additional behavioral proposal
       needs its own recorded bounded protocol before inference.
8. [ ] Keep baseline and release state unchanged unless all required gates PASS.

WER target remains >=10% relative, bootstrap 2000/seed55, clean tolerance .01,
no increase in non-speech insertions; independent human/entity evidence remains
required. Artifact/instrumentation PASS must not be presented as ML gate PASS.
