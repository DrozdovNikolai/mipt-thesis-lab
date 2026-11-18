# English recognition experiment v2

The user's renewed request authorizes this separate, bounded exploratory experiment.
All earlier reports, thresholds, releases and sealed test partitions stay intact.

Before any candidate inference, freeze four systems: existing multilingual small,
Whisper small.en, Whisper medium.en, and Distil-Whisper large-v3.5 CT2.
Beam 5, FP16 CUDA, explicit English, no reference prompts or hotwords. The distilled
model uses condition_on_previous_text=false as recommended by faster-whisper.
For each, derive an additional Silero speech-presence gate variant (threshold .5,
minimum speech 100 ms). This totals eight configurations, with zero training steps.
The gate keeps the full audio when speech is detected, otherwise returns empty text.

Evaluate all five old human cockpit dev clips, 35 publisher-aligned weak dev clips,
50 existing general English controls, existing quiet English controls and two noise
collections. Noise is explicitly decoded as English in this experiment, unlike the
old auto-language noise measurements. Add five previously unused utterances per
LibriSpeech dev-clean reader (excluding old smoke reader 2277), selected by seeded
ID hash before reading transcripts. Exclude previously exposed IDs, local training
readers and waveforms. These are new utterances, not new speakers or cockpit speech.
General corpus references are publisher transcripts; no local human verification.
Upstream pretrained model corpus overlap cannot be ruled out.

Selection for a standalone preview requires zero failures; at least 10% relative
improvement on old human cockpit dev; no increase on the weak cockpit dev;
at most +1 pp WER on each old/new general English cohort; no increase on quiet
human or quiet general controls; no increase in insertions/minute on either noise
cohort relative to the English small baseline. Prefer lowest human WER, then weak
WER, then ungated and smaller systems. All tried configurations will be reported.
Old cockpit dev is exploratory and already exposed, so a selected preview is NOT
a release or full SPEC pass. Missing independent human cockpit evaluation, entity
labels, NLP labels and group-level statistical evidence remain explicit.

Also transcribe all three original checklist recordings in the existing BLeRIOT
dev partition with baseline and the selected preview (if any). Do not assign an
automatic transcript human/gold status or compute WER against unaligned scripts.
Long recordings provide runtime and timestamp diagnostics and reviewable outputs.

Model downloads are explicit, at most 4 GiB total, pinned to repository commits;
no audio leaves the host. Prepare and scoring can read references; GPU inference
receives only audio, frozen model/config metadata and source identifiers.
