# Known limitations

- No independent cockpit/simulator final test has been admitted. The required 20
  independent groups, 300 original human utterances, 3,000 reference words, 100 human
  critical-entity occurrences, 50 clean controls and five minutes of non-speech
  controls are not present as a verified test cohort. ASR improvement is unconfirmed.
- No independent human cockpit event/salience annotations are available. Real
  estimator fitting in synthetic code tests proves that training and artifact
  loading run; it does not establish NLP precision, recall or F1 for the product.
  An additional model is now trained on 2838 actual Noort human safety-voice
  labels, a separate source-native task. Its 49-row/one-case holdout macro-F1 is
  .5000 versus .6449 for broad rules (INCONCLUSIVE). Those labels are not renamed
  to project events/salience, and the observed holdout is closed to further tuning.
- No human-labelled continuous temporal-event or speaker-time test exists. DER/JER
  and temporal scorers have code fixtures, not validated speaker/event performance.
- EN/RU/mixed are technical modes. No language has validated cockpit quality. RU
  mode exercised on an EN engineering control is explicitly not RU recognition
  validation. Mixed segments are marked language unknown when the backend does not
  expose per-segment language evidence.
  Fifty actual Russian FLEURS dev phrases now provide a general-speech control:
  parent WER 9.55%, gate+denoise 9.23%. Speaker IDs are absent, so this is one
  conservative group without meaningful sampling CI, not verified RU cabin quality.
- Current public BLeRIOT metadata describes fewer than the required 20 independent
  speakers even before splitting. Its NC license, human script alignment, segment
  scope and A/C parent matching require dataset-specific work before admission.
  A/C archives are now fully downloaded and checksum-verified; benchmark admission
  remains separate from acquisition.
- No independently verified cockpit large-v3 or LoRA quality result exists.
  A real large-v3 diagnostic now exists: 661 CUDA/float16 responses, three CPU
  smoke calls, pinned publisher checksums. On five partial human dev transcripts,
  passing saved EN reduces small errors 34→16; large with the same EN gives 20.
  Large improves general RU WER 9.55%→5.21% but worsens general EN 3.62%→6.10%
  and increases noise insertions. These two checks change input information or
  checkpoint respectively; neither meets same-checkpoint pipeline proof. See language_large.md.
  A bounded small LoRA run completed 40 steps using 17 weak publisher train pairs
  and seven dev pairs, followed by merge/CT2 conversion and real CPU/GPU inference.
  Publisher-text disagreement fell from 70/178 to 57/178; automatic alignment,
  conditional sample admission and repeated scripts make this a biased proxy,
  not proof of the requested lexical WER reduction. See publisher_experiment.md.
- Local pyannote weights/accepted gated terms are absent. Its optional adapter
  reports blocked and leaves speaker unknown; it does not block transcription.
- The earlier random-tensor LoRA smoke is superseded for execution by the actual
  publisher experiment, but it remains historical evidence, not an accuracy test.
  The pinned PyTorch CUDA 12.8 build does not support GTX 1080 Ti (sm_61).
  Training explicitly exposes one supported GPU; the first unisolated attempt
  failed at zero optimizer steps and is retained in the logs.
- Long recordings are decoded in bounded blocks for diagnostics, but inference
  currently holds one complete 16 kHz channel in RAM. Native decode/model calls
  are bounded by duration/time limits; four-hour/many-channel stress performance
  has not been measured. Recorded GPU memory snapshots are not sampled peak VRAM.
- Number/entity parsing and episode grouping are conservative baseline methods,
  not linguistically complete or calibrated. Ambiguous one-sixty retains alternatives;
  the system cannot resolve factual aircraft state from speech.
- Spectral gating, VAD thresholds, hints and re-decode have engineering executions,
  not confirmed domain benefit. Default stages remain off. No candidate is promoted.
  The additional-source study measured strong noise insertion suppression with
  VAD gating, but gate+denoise only reduces partial human dev errors 34→33 out of
  115 words (2.94% relative; paired CI upper bound zero). The 10% target fails.
  Segment-by-segment VAD worsens that dev WER to 65.22%. BLeRIOT-B's 87 channels
  belong to two aircraft groups and lack an independent speech-absence audit.
- Audio decode and native model calls support cooperative cancellation between
  observable boundaries, not instantaneous preemption. Queue delivery is at least
  once, with DB leases/fencing and bounded retries.
- The service is for one authenticated local owner. It is not a multi-tenant IAM,
  a certified safety system, or an automatic pilot-rating system. Off-host backups
  and storage retention need operator policy. Review does not silently retrain models.
- Public Whisper pretraining membership cannot be ruled out; no pretraining-disjoint
  generalization claim is made. General English audiobook smoke audio is not cockpit
  performance evidence.

Required next evidence: lawfully supplied human recordings from sufficiently many
independent sessions/speakers, aligned transcripts, independently verified entity
occurrences and event/salience labels, continuous event intervals if temporal claims
are desired, and predeclared clean/non-speech controls. Import, annotate and split
before training or development search; freeze all hashes before opening final test.

The later 50-utterance / 39-reader LibriSpeech control is executed: parent and
LoRA both 44 errors / 1214 words; measured clean WER delta is zero. These publisher
references have no new local listening audit. This replaces the earlier two-clip
limit for the diagnostic only, not the missing independent cockpit release test.
See [clean_controls.md](clean_controls.md); the checkpoint remains unpromoted.

The later all-sources expansion is executed, with 33/35 weak pairs and a new
40-step checkpoint. Across 1048 saved answers, the partial human-dev errors rose
34/115 to 36/115 (95% paired CI for WER delta −0.021739 to +0.043478). Weak clean
dev also worsened, 201/879 to 203/879. Common clean controls remained 44/1214.
Although weak-reference mixtures improved, their one shared VOICI noise source
makes the cluster bootstrap degenerate. The complete publisher-declared non-speech
recording yielded 555 versus 706 inserted words: diagnostic noise guardrail FAIL.
No checkpoint promotion is justified. See [all_sources_experiment.md](all_sources_experiment.md).

An actual storage I/O error interrupted this run; it was resumed preserving all
707 completed prediction hashes. The lost unsaved hypothesis and underlying
storage-error cause are unavailable. Final saved records contain no ASR exceptions,
which does not erase the infrastructure failure. A first artifact-verifier check
also failed because it mistakenly prohibited the admitted BLeRIOT-C audio chain
when checking for VOICI training use; the failed report and precise verifier
correction are retained. Frozen experiment data and metrics were not altered.
# Data preparation resumed on 2026-09-13

BLeRIOT A/C and VOICI are now acquired and checksum-verified. The historical
no-data blocker audit is superseded for acquisition/preparation by
`reports/data-resumption.md`; research acceptance remains NEEDS_MORE_DATA.
The v2 review manifests contain 67 unique decoded recordings and 18 speaker groups.
Scope, language and human annotation verification are still pending.

The four dev-only BLeRIOT PC7 smoke runs expose language-switching errors after
short VAD chunks and repetitions on the simulated noisy audio. This is an observed
development failure mode, not a measured WER result. Preserve the same baseline,
model and precision when investigating language policy/chunking; do not enable
VAD or alter the release selection based on these unverified drafts.

The first annotation packet is 18 fixed 20-second train/dev clips, not a qualifying
test cohort. Its temporal labels cannot establish continuous temporal detection.
The annotation UI records identified self-attestation and revision hashes; it
cannot independently prove that a human listened. Do not automate confirmations.
The initial pending-dev ablation precomputes all declared hypotheses without gold;
there is still no scored selection, statistical improvement or release promotion.
DOCX text was extracted from OOXML. LibreOffice was absent, so the image-only CVR1
used its embedded EMF, Windows GDI+ rendering and local OCR. Full DOCX layout
rendering through LibreOffice was not verified.
