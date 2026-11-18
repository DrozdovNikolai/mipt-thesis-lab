# Completed text-window repair: frozen protocol

User explicitly requested fixing the audited tail replay and comparing saved
models afterwards. Two repaired configurations, parent and augmented433, add2
to the previous22 (24 cumulative); two ordinary baselines are exact replays.
No training, VAD, denoise, hints, changed thresholds, adaptive search or release.

Use all264 unchanged inputs from decoding-v1, including all14 quiet copies.
Keep every original/group/reference and lexical scorer unchanged. Same CT2
manifests and CUDA float16 for all four freshly executed systems. Historical
baseline and broken text outputs are hash-checked separately and are absent from
inference mounts. Reference files are available only to the scorer. No final test.

The repaired text-only adapter consumes each backend audio window once. It keeps
the genuine word alignment but prevents last_word_end from reopening the window.
No text deduplication or semantic corrections. No monkeypatch of shared models.
The baseline loader still uses the original backend. Fail closed on backend
version/source mismatch, unexpected timestamp tokens or unsupported silence-seek
options. Compare fresh baselines to all528 old corresponding answers.

Mechanical regression uses the audited3536-8226-0027 source at engineered placement offset30s,
a copy repeated twice with1s silence, and empty audio. Parent checkpoint only.
These engineered regression waveforms are not added to quality evidence.
All bounded utterances must invoke neural text generation once; the repeated
waveform must retain both utterances and actual original-coordinate word times.
Unit tests additionally cover two windows, actual backend regression sensitivity,
real repeated-command tokens, numbers/negation, silence and unsupported modes.

Score lexical S/D/I/N, WER/CER, paired bootstrap2000 seed55 95%CI, noise words/min,
clean EN/RU guardrails, quiet/short deletions, failures and alignment coverage.
Report improvement versus broken text separately from improvement versus the
proper baseline. Point target>=10% relative; clean/RU delta<=.01; noise delta<=0;
no runtime failures. Existing acceptance evidence minimums remain unchanged.
Five exposed human dev clips /115words /3groups cannot establish independent
release quality or critical-entity nonregression. General RU is not cockpit RU.

Checklist (completion goes in verification.json, not edits to this frozen file):
- [ ] Pass mechanical tests and real repeated-audio regression.
- [ ] Freeze code/config/model/input/protocol before quality inference.
- [ ] Execute1056 GPU records and8 CPU smoke records offline.
- [ ] Verify baseline replay and all hashes, preserve previous reports/annotations.
- [ ] Check resume and scorer/report replay in PowerShell and Linux/WSL.
- [ ] Report exact quality status; keep serving release on the existing baseline.
