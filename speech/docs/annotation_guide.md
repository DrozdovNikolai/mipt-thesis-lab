# Annotation guide v1

Annotate permitted cockpit/simulator conversation. Pilot–ATC radio traffic is
excluded segment by segment before examining model comparison errors. Read cockpit
scripts, spontaneous conversation and synthetic noise variants are different
conditions. Confirm license/consent, source version and original recording identity.

1. Listen to the original audio. Transcribe what was said, retaining numbers,
   negation, direction, hesitations relevant to meaning and units. Do not repair a
   command using assumptions about the aircraft. `fifty` is not `fifteen`.
2. Keep transcript, entity, event, temporal and diarization verification statuses
   separate. `null` means unannotated. A verified empty list means a human checked
   that no target occurrences exist. Machine suggestions stay `machine` until an
   identified annotator actually checks the audio and content.
3. Mark every critical entity occurrence, including repeated values. Types:
   flaps_setting, gear_position_mention, speed_mention, altitude_mention,
   heading_mention, checklist_name, warning_mention. Include canonical value,
   explicit unit or null, polarity and the original evidence interval. Ambiguous
   values stay unresolved. Never derive evaluation truth from the tested parser.
4. Labels are multi-label CHECKLIST, CONFIGURATION_MENTION, CREW_COORDINATION,
   REPORTED_DEVIATION, WARNING_MENTION, INSTRUCTOR_FEEDBACK, OTHER. OTHER is exclusive.
   Instructor role requires explicit evidence. Assign salience independently; a
   checklist is not automatically salient and OTHER is not automatically negative.
5. For temporal evaluation annotate actual event start/end on continuous audio.
   Combine related utterances only within a contextual episode; record interruptions,
   overlaps and repeated commands. Prepared utterance classification does not
   establish event detection on full recordings.
6. Speaker labels are pseudonyms. Keep speaker/session/recording/original/variant
   IDs consistent across all sources and transformations. Do not infer captain or
   first officer from vocal timbre. Ground-truth role provenance is explicit.
7. Record annotator ID, guide version, whether audio was listened to and optional
   second annotator/adjudicator. Do not invent independent agreement statistics.

The manifest schema is `Sample` in `datasets.py`. Use `datasets annotation-template`
to export and `datasets import-annotations` to create a new auditable revision.
The API review UI is for operational corrections; it does not automatically turn
current test material into training data. Freeze test labels before inference.

Unintelligible spans must be marked before scoring; never omit a file because the
candidate failed or needs review. Each mask contains original `start_sec`, `end_sec`
and half-open `reference_start_token`, `reference_end_token` indices into
lexical_normalizer_v1(reference_text). The scorer masks reference tokens and
hypothesis words by timestamp midpoint, symmetrically for both systems. It rejects
invalid masks and missing word timestamps. Any scorer amendment requires
versioning and symmetric rescoring, never threshold tuning on final test results.

Augmented audio retains its parent's split/group. Inherited annotations are weak
until a person listens to the noisy variant and verifies them, including
unintelligible spans. Noise provenance, active-speech SNR, seed, offset and gain
are recorded. Publish a new protocol directory with `datasets publish-partitions`
after annotation/augmentation; existing projections and sealed files cannot be
overwritten. Point Compose mounts and YAML paths to that protocol before dev/freeze.
