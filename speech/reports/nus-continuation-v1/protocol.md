# NUS continuation and unconditional transfer diagnosis

New, separately frozen study authorized by the user's request to continue improving
the result. The completed convergence-v1 protocol and its FAIL remain unchanged.

Reason: old training ended at AdamW step 240 with LR exactly zero, while logged
train loss still decreased to 0.5504 and lexical train WER fell to 17.93%.
This suggests additional optimization is worth testing; it does not prove its benefit.

Assumptions and checklist fixed before new training:
- Same 32 NUS audio/text pairs, original labels, same source group and permission
  evidence. No removals, spelling corrections, new labels, prompts or dictionary.
- Start from saved checkpoint 240; restore adapter, all AdamW moments and step
  counters and AMP scaler. Reset the LR schedule to constant 2e-5 for exactly 400
  additional steps. Restart seeded data order/dropout at seed 55; this is an
  explicitly new optimization phase, not bit-identical continuation of the old
  zero-LR schedule. Keep rank 8, alpha 16, dropout .05, fused AdamW, accumulation 4.
- Save additions 160 and 400 (total optimizer steps 400 and 640). Convert both
  to CT2 float16; generate all 32 training clips with the unchanged baseline decoder.
  Use the same lexical primary scorer; canonical WER is a secondary symmetric
  formatting probe only and cannot change fit/release criteria.
- Assess SOURCE step 240 and FINAL step 640 on exactly the previous 402 other
  inputs, regardless of train WER: 243 remaining NUS plus 159 prior EN/RU, cockpit,
  quiet and non-speech controls. No intermediate checkpoint is evaluated there.
  This new study removes conditional diagnostic execution, not an acceptance guard.
- Compare both to the legitimate frozen unadapted parent, not only to each other.
  Report same-text-as-fit NUS separately (52 of 243), keeping all of NUS in its
  existing train group. They are exposed same-source probes, not final test.
- One training continuation, 400 added steps; 64 new fit ASR calls, 804 transfer
  calls, one CPU smoke. No adaptive new recipe, checkpoint choice, extra training
  or release selection based on results. Original dev-search budget stays exhausted.
- Keep independent test, entities, NLP/temporal and RU/mixed cockpit validation
  limitations explicit. Fit success cannot promote release, all ACCEPTANCE guards
  remain unchanged, and fewer than 20 independent groups cannot certify quality.
- All prior model/audio volumes read-only. New artifacts in separately initialized
  north55-speech_nus_continuation_v1. Run tests, exact inference-input matching,
  source checksums, local GPU/CPU smoke and PowerShell/Linux replay.
