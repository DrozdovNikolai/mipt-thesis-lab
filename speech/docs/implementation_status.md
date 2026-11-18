# Implementation and acceptance checklist

The research objective is **not achieved**. Baseline remains active, no candidate
is selected or promoted, and validated EN/RU/mixed cockpit scope is empty.
The latest experiment verification is `reports/nus-retention-v1/summary.json`.
The serving baseline verification remains `reports/reporting-v1/verification.json`;
its recovery evidence was not rerun or relabelled as an adapted-model test.
The initial core evidence is `reports/delivery.json`; absent measurements
are null, never zero or invented example scores.

| Work item | Implemented | Executed | Verified | Evidence / blocker |
|---|---|---|---|---|
| Repository and requirements inspection | yes | yes | yes | Clean ee853e1; no AGENTS.md |
| Matched CE / teacher-KL decoder adaptation | yes | 2 × 1200 actual updates, 868 GPU ASR, 4 CPU EN/RU smokes | 51 tests, base/teacher hashes, optimizer audit, tamper rejection, byte-identical PS/Linux replay | nus-retention-v1: CE+KL EN 5.44% vs CE 7.99%, but parent 3.62%; cockpit 24.35% vs parent 13.91%. Candidate FAIL, independent quality NEEDS_MORE_DATA; not promoted |
| CPU Compose and GPU override | yes | yes | yes | Actual Docker services; compose-validation.json; CPU and CUDA small smoke |
| PostgreSQL migration / RabbitMQ / outbox / leases | yes | yes | yes | Fresh isolated DB upgrade, repeated upgrade, downgrade, upgrade; migration-tests.json |
| API / auth / original audio / reviews / exports | yes | yes | API integration | final-tests.xml: byte ranges, original hashes, revision conflicts, audit, CSV/XSS |
| Minimal UI | yes | yes | partial | Login page visually inspected; authenticated workflows tested via API, not a full browser suite |
| Decode / channels / VAD / denoise / original timeline | yes | yes | engineering | Real human stage smoke; channel/timestamp contracts and checksums |
| Local small/int8 ASR and explicit asset acquisition | yes | yes | engineering | CPU int8 and GPU float16; no-network container inference; pinned MIT weights |
| Optional local diarization / DER / JER | yes | missing-weights branch and scorer fixtures | partial | Gated terms/weights and speaker/time test not supplied; actual inference BLOCKED |
| Safe normalization / entities / episodes / risk | yes | yes | code contracts | Unsafe numbers, negation, Unicode raw spans, role and telemetry limitations tested |
| Local importer / annotation / split graph / augmentation | yes | yes | engineering | data-workflow.json: two lawful controls, no human labels invented; SNR arithmetic fixture |
| Trainable event and salience classifier | yes | fixture fitting/reload | code only | Real sklearn/skops execution; no independently labelled human cockpit training/test |
| ASR LoRA train/merge/convert path | yes | 40 real steps on publisher weak train/dev pairs; adapter/merged/CT2 saved; 52 GPU comparisons and CPU adapted smoke | execution verified; quality unconfirmed | publisher-weak-v1/verification.json; 17 train / 7 dev pairs; weak-reference proxy is not independent WER |
| Scorers / bootstrap / freeze / bounded search / promotion | yes | code fixtures, baseline freeze, missing-data refusals | protocol contracts | Acceptance unchanged; no domain candidate selected; CLI logs and baseline.lock.json |
| CPU E2E / real human ASR / recovery / offline | yes | yes | engineering | final-tests.xml; offline-asr-smoke.json; actual broker outage and worker SIGKILL, attempts=2 |
| Reproducible reports and PowerShell/Linux commands | yes | yes | documented subset | PS bootstrap/build/demo/recovery; Ubuntu WSL bootstrap/config/doctor; Linux recovery script syntax checked |
| BLeRIOT A/C and VOICI acquisition | yes | yes | checksums and complete decode | 67 unique A/C recordings, 18 speaker groups; preparation-v2 supersedes initial 55-recording preparation |
| Publisher scripts / source scope / duplicate linkage | yes | extraction, PDF OCR, acoustic matching | machine evidence only | Exact mislabeled duplicate found; ATC-containing CVR families excluded from first packet; two acoustic linkages still require review |
| Human annotation sidecar | yes | live service, HTTP path and authenticated browser login on isolated fixture | origin regression checks; actual browser login | login-origin-fix-v1; 18 real audio ranges and preserved exports; no human labels created by automation |
| Reviewed-data training export | yes | immutable partial human-reviewed snapshot | 20 sidecar/export tests; full-packet groups preserved | reviewed-pilot-v2: 3 train / 5 dev; known truncated word held; no synthetic/ATC admission |
| SPEC 17.3 event CSV and measured plots | yes | report tests and 64-run runtime report | 228 full tests; HTML/PNG visual inspection | reporting-v1/verification.json; missing WER/F1 explicitly unmeasured |
| Publisher text extraction / alignment / annotation proposals | yes | 76 clips, 24 eligible weak pairs, 14 review proposals | 243 full tests including 9 integration; provenance and immutable reference checks | publisher-weak-v1; PDF columns fixed; 5 proposals eligible for autofill; no human labels created |
| Expanded available-source experiment | yes | 476 A/C windows, 33/35 weak train/dev pairs, 40-step new LoRA, 1048 offline GPU responses | Artifact verifier; 5 new contract tests; real CPU int8_float32 smoke | all-sources-v1; clean proxy and partial human point targets failed, noise diagnostic FAIL; quality NEEDS_MORE_DATA |
| Complete VOICI diagnostic | yes | 151 noise windows (50.2806 min), 204 fixed 0/10 dB mixtures | Actual waveform/SNR reconstruction, original dev-only grouping | One noise source, no human audit; mixtures do not provide independent statistical evidence |
| Expanded-run storage recovery | yes | 707 completed predictions preserved, 341 remaining executed | Exact hashes unchanged; final exit 0; original Errno 5 and exit 255 retained | all-sources-v1/resumption; one real infrastructure interruption, final per-sample ASR failures 0 |
| PostgreSQL/RabbitMQ restart policies | yes | unless-stopped applied to existing containers and Compose | Config validation, actual policies/healthy state, API and annotation HTTP 200 | No forced Docker-restart retest; same existing volumes |
| Additional licensed sources | yes | BLeRIOT-B 102 assets, official FLEURS RU dev, Noort human CVR table acquired | Publisher B/FLEURS checksums; safe decode; immutable metadata-only CVR case partition | additional-sources-v1; 87 noise channels, 50 RU controls, 3281 admitted text rows; no new independent cockpit ASR gold |
| Same-checkpoint pause-handling study | yes | 661 inputs × 5 systems; 524 reused baseline outputs and 4022 new ASR calls | Raw hashes, independent edit counts, 2000 cluster bootstrap, PS/Linux identical scores | partial human dev 34→33 errors for gate+denoise, target FAIL; no significance; quality NEEDS_MORE_DATA |
| Source-native human NLP training | yes | 2838 train / 394 dev; 12 TF-IDF/logistic trials, two rule baselines; frozen 49-row holdout | Isolated no-network train/inference; hashes; independently recomputed precision/recall/F1 | Holdout 1 case: macro-F1 .5000 vs broad rules .6449, INCONCLUSIVE; not project labels or temporal detection |
| Additional-source CPU/contract verification | yes | Real RU/noise CPU int8_float32 and 15 contract tests | CPU PASS; artifacts checked; core E2E/recovery evidence remains historical | additional-sources-v1/cpu-smoke.json, contracts.xml, verification.json |
| Human-declared language / large-v3 diagnostics | yes | 1322 fresh GPU responses; 661 old responses preserved; 3 real large CPU calls | 12 contract tests; publisher model hashes; frozen artifacts; identical PS/Linux scores | language-large-v1: small auto→EN 34→16 errors, large same EN 20; large clean/noise guardrails FAIL; primary quality NEEDS_MORE_DATA |
| Fresh model speed and memory measurement | yes | Both sequential CUDA/float16 runs, per-input timings, GPU polling and CPU process RSS | Raw runtime traces and timing sums; shared-device peak caveat | large ASR RTF .0469 overall but slower on speech; 7410 MiB sampled device-wide peak; no per-process GPU claim |

Current execution/quality summary: [research-readiness-v2.md](../reports/research-readiness-v2.md).
Previous scorer amendment and 220-test verification: [gate_amendment_v1.md](gate_amendment_v1.md).
Current report amendment and 228-test verification: [reporting_v1.md](reporting_v1.md).
Current publisher experiment, 243-test verification and measured limitations: [publisher_experiment.md](publisher_experiment.md).
Partial human-reviewed dev rescoring and exporter regression: [reviewed_pilot.md](reviewed_pilot.md).
Expanded clean-speech diagnostic: [clean_controls.md](clean_controls.md).
Latest source expansion and reproducible PowerShell/Linux commands:
[all_sources_experiment.md](all_sources_experiment.md). The new checkpoint has
36/115 errors on partial human dev versus parent 34/115; CI crosses zero.
Its clean control is unchanged, while VOICI inserted words/min rises
11.0381 to 14.0412. It is not selected or promoted.
Executed 100 offline GPU inferences on 50 publisher-transcribed dev-clean clips,
39 readers; parent/LoRA both 44/1214 lexical errors, measured clean delta 0.
The diagnostic tolerance passes; formal release evidence is not claimed without
independent listening audit and the remaining cockpit/NLP evidence.
Current data/review instructions: [review_packet.md](review_packet.md).
The initial `reports/data-resumption.json` describes v1, not the current v2 manifest.
`reports/pending-dev-ablation.json` records every execution of the eight declared
pipelines on the same eight dev clips. Its current completion count is authoritative;
unscored inference does not mean completed scored search or candidate selection.

ENGINEERING_GATE is computed from actual evidence in `reports/engineering-gate.json`.
ASR_QUALITY_GATE, NLP_QUALITY_GATE and TEMPORAL_EVENT_GATE: NEEDS_MORE_DATA.
Independent final scientific benchmark: NOT_RUN. Exploratory publisher agreement
and general-control measurements are executed; no release promotion.

A functioning scorer, successful smoke test or fitting synthetic fixtures does not
demonstrate 10% relative lexical WER improvement. No read-to-spontaneous or
synthetic-noise-to-real-flight generalization is claimed. See known_limitations.md.

Checklist follows SPEC sections 0–20 and all integrity, support, guardrail and
promotion requirements in ACCEPTANCE.yaml. A skipped check is never verified.
