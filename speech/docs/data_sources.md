# Source verification on 2026-09-14

The user subsequently expanded ASR scope to aviation including ATC. The earlier
cockpit-only ATC exclusion is historical; see [current scope](aviation_scope.md).
ATCOSIM's complete published test partition is now acquired locally: 1,901 clips,
122.74 minutes of decoded audio, four verified source speakers, publisher transcripts. Pinned files,
original license and metadata are in `data/input/atcosim-v1/`; acquisition evidence
is in `reports/aviation-v1/acquisition/`. This is simulated controller speech.

The supplied `SOURCES.md` is preserved. Actual acquisition evidence is in `reports/`.

Latest direct-download search: [report](../reports/direct-data-search-v1/report.md).
NASA SOTERIA: CC BY 4.0 public S3, complete 11,143-object inventory; one 90,608,135-byte
MP4 acquired with verified multipart ETag and decoded offline (86.955 s stereo audio).
No ready verbatim transcript found; mixed cockpit/radio source requires screening.
Only Crew_02 exposed for development. The 12 crew groups do not establish the 20-group gate.
Boeing aviation-ner-BIO: MIT-labelled train JSON acquired and Git-blob verified;
894 service-difficulty reports, source-native entity tags, no audio or project event gold.
NUS VR project: [full prepared-payload inspection](../reports/nus-vr-v1/report.md):
all 10 public Parquet files acquired (34,631,443 bytes), 642 rows decoded offline,
313 unique PCM clips / 1,024.1 seconds, 11 conflicting reference groups, all original
start/end times missing. The user subsequently explicitly confirmed project training use;
[NUS training study](../reports/nus-training-v1/protocol.md) records that confirmation as
the rights basis, without claiming a public license or redistribution rights. 275 screened
source-reference pairs are exploratory train-only; no independent NUS benchmark admission.
Other exclusions and evidence
are in the report. No new ASR, NLP training, quality measurements, or promotion.

| Source | Checked in this implementation | Admission / restriction |
|---|---|---|
| Systran/faster-whisper-small | HF model API, model card, pinned revision and downloaded file SHA-256 | Local multilingual small, MIT model card |
| Systran/faster-whisper-large-v3 | Official conversion card/API; revision edaa852ec7e145841d8ffdb056a99866b5f0a478; 6 files with publisher LFS/Git checksum verification | MIT, local FP16 CT2; 661 offline GPU and 3 CPU calls completed; general RU gain, EN/noise regressions; not promoted |
| LibriSpeech SLR12 dev-clean | OpenSLR license CC BY 4.0; downloaded archive verified against publisher MD5; per-file SHA-256 | 50 fixed human read-speech controls, 39 readers; general-English regression, no cockpit claim |
| BLeRIOT-A | Full 1,710,792,035-byte RAR acquired; publisher MD5 verified; safe extraction: 40 WAV and 15 script documents; 260.44 audio minutes | Prepared for local noncommercial research review; human scope/alignment/annotation checks remain |
| BLeRIOT-C | Full 863,744,696-byte ZIP acquired; publisher MD5 verified; 28 WAV, 80.84 minutes | v2 retains all 27 unique variants, removes one exact misleadingly named duplicate; two parent acoustic links require review. One modeled chain/noise condition |
| HIWIRE | Catalogue exists; licensed delivery/archive not present | BLOCKED; no purchase or author contact performed |
| VOICI | Zenodo API, CC BY-SA 4.0; full WAV/PDF downloaded with publisher MD5 checks; all 50.28 minutes processed as 151 windows and 204 mixtures | Entire original dev only, no training/test use; publisher removed speech, local audio-content review remains |
| NLPVladimir aviation-command-dataset-ru | HF API and entire README; revision 9860fb2d9507dc36ebe5201427495e2011e97d07; 1,182 examples, voice/speed/noise fields | No license or human-recording provenance declaration in card; not admitted; synthetic origin is not established merely by field names |
| pyannote community-1 | Official local/gated model documentation | Model terms/token/weights not provided; ASR still works |
| openai/whisper-small Transformers | Public revision 973afd24965f72e36ca33b3055d56a652f456b4d; source card Apache-2.0; 12 local files, safetensors publisher LFS SHA-256 verified | Real offline LoRA executed: earlier 17/7 and expanded 33/35 weak train/dev pairs, 40 steps each; independent quality unconfirmed |
| IEM Pilot Speech Database | Original technical PDF retrieved successfully and inspected | BLOCKED: licensed audio/transcript delivery not found; publication alone is insufficient |
| DLR pilot speech 214890 | Official page and publication inspected | BLOCKED: licensed audio/transcript delivery not found |
| BLeRIOT-B v1 | All 7 files and 5 archives acquired; publisher MD5 checked; 102 WAV/NPY validated | CC BY-NC 4.0; 87 noise channels measured, two aircraft groups; no new speech or human noise audit |
| Google FLEURS RU dev | Official pinned revision; tar SHA-256 / TSV Git blob SHA-1 checked; 50 seeded phrases processed | CC BY 4.0; general Russian read speech, no speaker IDs; dev only, one conservative group |
| Noort CVR human safety-voice table | Public article and supplement acquired from Europe PMC; 21626 rows, 172 cases; frozen metadata-only partition | CC BY 4.0; 3281 strictly screened CAM/HOT/INT crew rows, 2838/394/49 train/dev/holdout; source-native text labels, not ASR/project events |
| EARS cockpit study | Primary full-text XML and supplementary inventory inspected | Raw data requested through authors; no public permitted dataset delivery found, not imported |
| DLR pilot speech 219140 | New official paper describes 409 manually transcribed segments from 18 simulator recordings | No licensed WAV/transcript delivery found; paper is not an audio corpus |
| Oye12 Pilot Speech Corpus | Entire dataset card inspected | Banking biometrics pilot, not aircraft; excluded |

Current acquisition, decisions and experiments: [additional_sources.md](additional_sources.md),
`reports/additional-sources-v1/discovery` and `source-decisions.json`.
Actual source-native human NLP training is now executed; no project human labels
are synthesized. The model underperformed broad rules on its one-case holdout;
scientific NLP status INCONCLUSIVE. ASR target still NEEDS_MORE_DATA.

Latest BLeRIOT preparation: [utterances and typed checklist fields](../reports/publisher-recovery-v3/report.md).
514 derived candidates received 1,028 fresh unprompted medium.en / large-v3 English
rechecks. After overlap removal, 125 weak pairs / 10.25 minutes were added to the
previous 96; the new train contains 221 pairs / 25.44 minutes / nine readers.
103 added pairs / 8.49 minutes do not overlap either previous preparation. Actual
PCM crops, prediction hashes and split integrity were verified; the 35 dev rows
are byte-identical. No new training or measured ASR gain is claimed.

Previous preparation: [pause-clip and document audit](../reports/publisher-phrases-v2/report.md).
675 existing train-only pause clips were decoded by unprompted medium.en and screened
against cached small/English predictions and publisher text. The result is 96 weak
pairs / 15.18 minutes; 59 pairs / 9.22 minutes do not overlap the previous 49 training
windows and are exported separately. Another 201 clips / 34.09 minutes remain in a
non-training review queue. The previous 35 dev rows are byte-identical. No human
verification, new training, or measured ASR gain is claimed.

Previous execution: [all_sources_experiment.md](all_sources_experiment.md).
Expanded BLeRIOT preparation covers 476 full train/dev windows in four documented
English checklist families, including TBM940 (processed, no pairs admitted).
That stage's HTTP responses and per-source decisions are retained in
`reports/all-sources-v1/source-audit/` and `source-decisions.json`.
No new human labels were generated. The 1048-response comparison did not establish
an improvement; the diagnostic VOICI non-speech guardrail failed.

BLeRIOT metadata describes 12 BEA plus 6 DGA readers; README speaker ranges are not
entirely consistent with that description. Even 18 independent speakers are below
the 20-group test requirement before allocating train/dev. Transcripts are supplied
as PDF/DOCX/scripts, not yet verified aligned utterances with independent entity and
event annotations. Do not infer speaker roles from biographies or label all CVR
content cockpit merely from a filename. The C README also has inconsistent DOI
cross-references; prefer verified dataset metadata, and verify actual parent files.

No private user recordings were transmitted to a service. No source listed above
currently establishes independent EN/RU/mixed cockpit quality. Source preparation
and four real offline CPU ASR development smoke runs are recorded in
`reports/bleriot-preparation.json` and `reports/bleriot-asr-smoke.json`.
The initial acquisition/preparation summary is `reports/data-resumption.md`.
Current v2 preparation and review workflow: `reports/bleriot-preparation-v2.json`
and `docs/review_packet.md`. Scripts from DGA CVR1/2/4/5 contain ATC; BEA CVR mixes
radio and cabin dialogue. None is admitted merely from a CVR filename. DGA CVR3
is French cabin speech, outside the primary EN claim. Publisher extraction and
machine context matching are review aids, never audio-verified human gold.
The earlier blocker audit is historical; lack of final-test sufficiency should
not have stopped source acquisition and preparation.

Primary sources:

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Whisper small conversion](https://huggingface.co/Systran/faster-whisper-small)
- [LibriSpeech SLR12](https://www.openslr.org/12/)
- [BLeRIOT-A metadata API](https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId=doi:10.57745/EWXJLT)
- [BLeRIOT-C metadata API](https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId=doi:10.57745/ASYVFP)
- [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
