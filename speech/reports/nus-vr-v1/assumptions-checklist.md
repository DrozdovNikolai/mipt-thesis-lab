# NUS / Singapore Airlines VR: acquisition and admission audit

## Assumptions fixed before opening payloads

- The user explicitly requested downloading the public prepared recordings and trying their use.
- Public retrieval is for local source inspection. It does not establish reuse/training rights.
- Preserve all existing data, annotations, experiments, baseline and acceptance thresholds.
- Pin source revision `0c520edbcd345cb9005cc77c3345eedbfef7147b`; verify Git blob and SHA256.
- Download prepared Parquet files only, plus provenance metadata. Do not execute publisher code,
  download their checkpoints, physiological data, YouTube video or unrelated `test.wav`.
- All opened NUS payloads are exploratory exposure, never a new independent final test.
- Sample filenames are not verified speaker/session IDs. Until provenance is established,
  treat the whole source as one conservative leakage group; keep every duplicate together.
- Source transcripts remain source references, never automatically human-verified project gold.
- No ASR training/inference or production import before source-use permission is established.
  This follows the original request and SOURCES.md admission requirements, not an extra
  request for user confirmation. No messages to authors are authorized or sent.

## Checklist

- [x] Inspect existing repository state, ancestor instructions, SOURCES.md and prior source audit.
- [x] Refresh public repository metadata, complete tree and source permission evidence.
- [x] Retrieve all prepared Parquet files with bounded downloads and immutable hash checks.
- [x] Inspect schema, embedded audio, durations, transcript fields, duplicates and origin metadata.
- [x] Record a concrete admission decision and any blocked execution stage.
- [x] Verify the audit tools and reproducible PowerShell/Linux commands.
- [x] Document actual implemented / executed / verified status without invented ML results.
