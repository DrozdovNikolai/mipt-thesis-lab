# Aviation ASR v1: user-authorized expansion on 2026-09-14

The user explicitly expanded the target from cockpit-only to any aviation speech,
including pilot/controller radiotelephony. This new scope supersedes the prior ATC
exclusion for this experiment. Historical cockpit SPEC/ACCEPTANCE and results remain
unchanged. New primary scope: English ATC; cockpit transfer is reported separately.

The fixed candidate is jacktol's CT2 Whisper medium.en fine-tuned on ATCO2/UWB-ATCC.
Compare against both the current multilingual small and the original medium.en:
the latter controls for model size and English specialization. No local training,
reference prompts, per-example corrections, test-driven checkpoint selection, or
number/word removal from primary scoring. Beam 5, float16 CUDA, explicit English.
The decoded raw text and timestamps are preserved. A secondary symmetric canonical
number-normalized score distinguishes formatting from some recognition errors;
it does not replace lexical WER or constitute a critical-entity validation.

Primary evaluation: every row in the pinned Jzuluaga ATCOSIM publisher test Parquet,
with valid source identity and reference. No ASR-based selection or trimming. Abort
on malformed audio/duplicate IDs; report exact duplicate PCM and metadata issues.
No overlap with our local train audio is allowed. ATCOSIM is controller speech from
simulations, not evidence for real VHF pilot recordings or cockpit conversations.
The candidate's card names ATCO2/UWB-ATCC, not ATCOSIM, as fine-tuning sources; an
external training manifest is unavailable, so cross-corpus separation is based
on declared provenance, not an independently verified training-data inventory.
Upstream Whisper pretraining overlap cannot be excluded.

Additionally score all five old human cockpit dev and 35 weak publisher-aligned
cockpit dev clips. Existing EN/general and quiet/noise clips are regression controls,
not the objective. No new general speech dataset is prepared. For this ATC profile,
noise is decoded explicitly as English and is compared to the same-language base.

There are exactly three base systems and their three speech-presence gate variants
(Silero threshold .5, minimum speech 100 ms; preserve full audio if any speech).
Budget: six configurations, one candidate checkpoint. Select the ATC candidate
only if both lexical and canonical ATCOSIM WER improve by at least 10% relative to
medium.en, its lexical WER beats current small, and zero execution failures occur.
Noise gate is preferred only if it does not increase ATCOSIM errors and both noise
cohorts have no more insertions than the current small English baseline. Otherwise
report the noise limitation and retain the ungated profile as an explicit preview.
Cockpit/general regressions prevent replacing their existing default routes; they
do not silently invalidate a separately named ATC-only preview.

Paired bootstrap uses original speaker IDs where verified, otherwise conservative
corpus grouping. Report per-speaker results, raw counts, all candidates and failures.
Fewer than 20 independent groups, unverified critical entities, absent target NLP
labels and no real VHF evaluation mean the original full SPEC gate remains unmet.

All model/data acquisitions are pinned and checksum verified. GPU inference has no
network or reference mount. Source corpus references are publisher transcriptions,
not newly human-reviewed local labels. Corpus licensing permits research/development;
its recordings are not licensed as operational pilot/controller training material.
