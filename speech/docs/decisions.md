# Decisions and assumptions

2026-09-13, initial inspection: repository commit `ee853e1`, clean working tree.
No AGENTS.md in the repository or its parent directories. Existing requirement files
are preserved. The initial repository contains specifications only, no application,
models, recordings or annotations.

1. Python 3.11, Docker Compose, FastAPI/Celery/PostgreSQL/RabbitMQ as specified.
   CPU execution is the required first target. Docker Desktop 4.45.0, engine
   28.3.3 and Compose 2.39.2 are available. Host Python is not a deployment dependency.
2. One local owner, API-key authentication and signed HttpOnly UI sessions with
   CSRF protection. UUIDs are identifiers, not authorization.
3. The normative ACCEPTANCE.yaml will be copied byte-for-byte, hashed and checked;
   no threshold relaxation. No language currently has validated quality.
4. Default ASR is multilingual small/int8 with beam 5, temperature 0, transcribe.
   Optional stages remain research mechanisms until development selection and gates.
5. No dataset is admitted merely by its name. External downloads require verified
   provenance and terms. General speech can verify engineering only. Annotation
   statuses are separate for text, entities, event labels and temporal intervals.
6. Dataset groups are connected components across sessions, recordings, speakers,
   originals, variants and decoded duplicates. Test references live in a separate
   evaluator mount. Benchmark outputs never create instructor journals.
7. Research evidence can remain NEEDS_MORE_DATA while engineering is completed.
   Synthetic fixtures are unit tests only. No invented improvement, labels or roles.
8. Hardware inventory shows RTX 5070 Ti (16 GB) and GTX 1080 Ti (11 GB), driver
   581.80. This is visibility, not verified container inference or training.

Further decisions and actual verification outcomes are appended as work proceeds.

9. Direct Dataverse API access succeeded for BLeRIOT A/C despite webpage errors.
   Both are CC BY-NC 4.0; metadata/README are retained. About 18 readers and script
   transcripts cannot meet the 20-group independent test minimum by themselves.
   Audio has not been admitted without alignment/scope verification. LibriSpeech
   CC-BY-4.0 was acquired solely as an engineering human-speech control.
10. Added a `curator` Compose profile for import and partitioning. Full manifests
    and sealed references are not mounted into normal dev tools/trainer/worker.
    A reference-free partition proof permits independent integrity checking.
11. Docker Desktop on the checked version did not publish the API port with only
    an internal network. An API-only ingress network enables localhost binding;
    inference worker remains on the internal network.
12. Compose build definitions live once per image to avoid concurrent BuildKit tag
    export races seen in the initial build. BuildKit dependency cache mounts avoid
    putting a second copy of package downloads into image layers.
13. Skops loading permits only its default safe types plus the specific pinned
    sklearn `_ConstantPredictor` needed for absent training labels. A fitted
    classifier's checksum and local provenance are checked; uploaded pickle is not
    supported. Absent classes remain not_evaluable in metrics.
14. GPU small/float16 real inference executed successfully. ASR mode metadata comes
    from the API configuration as well as worker configuration in the GPU override,
    preventing a CPU-configured job from being labelled a GPU test.
15. Job-local stage caches survive retries, are keyed by audio/config/model/code,
    and are removed on session cancellation/deletion. They are not global caches
    that could retain deleted user speech through another session.
16. Final image-hash checking detected a late full build replacing a Docker tag
    with an earlier source snapshot. The engineering assessment correctly returned
    BLOCKED (`reports/image-drift-detected.json`). After all builds finished,
    refreshing source with exact pyproject/lock comparison restored the tested
    code hash. The final assessment is PASS; the temporary BLOCKED evidence remains.
17. Current CPU/GPU/training images were updated after full dependency builds.
    `scripts/Dockerfile.refresh` refuses dependency drift; optional runtime refresh
    reconciles the frozen lock through uv. Final CPU/GPU no-network ASR and the
    random-tensor LoRA gradient/save/merge check use the packaged current source.
18. The user clarified that dataset sources were already supplied. The earlier
    no-data blocker audit stopped too early: absence of a qualifying final holdout
    does not prevent public source acquisition, inspection, preparation, or
    development work. Preparation of manifests is the implementer's responsibility.
    BLeRIOT A/C acquisition resumed for local noncommercial diploma research under
    their CC BY-NC 4.0 declarations. This does not authorize product redistribution.
19. Quarantine acquisition and benchmark admission are separate states. Downloaded
    publisher transcripts are not automatically audio-verified gold. The source
    preparation step preserves original files, records archive/file hashes, and
    leaves language/scope/annotation review explicit. No test text is used to
    generate hints, tune settings, or select configurations.
20. The Dataverse metadata table reports ingested TAB size with original CSV MD5.
    Retrieving `format=original` produced 4,634 bytes and the exact publisher MD5;
    the rendered TAB variant was retained only as diagnostic evidence. The archive
    host stalls long transfers; bounded HTTP ranges with final full-file size,
    publisher MD5, and SHA-256 checks make acquisition reproducible.
21. A second acoustic linkage audit uses reference-free source coherence. One C
    file with a BEA name is an exact duplicate of DGA CVR4 reader104. v2 retains
    all 27 unique C recordings; two uncertain pairings remain conservatively
    grouped with their parents pending review. Existing split identities remain.
22. Publisher documents reveal substantial ATC content in CVR families. The first
    review packet uses only documented checklist families, six train/dev readers
    and fixed 30–50/90–110 second windows selected before ASR. No test clips enter
    annotation, hint matching, adaptation readiness or pending-dev inference.
23. Extracted text, OCR, ASR drafts and exact lexical anchor context are machine
    review aids. They never set human_verified. The sidecar requires identified
    human self-attestation for each annotation task and stores immutable revisions.
24. Full Transformers small weights were explicitly acquired at a pinned public
    revision, verified against publisher LFS SHA-256 and tested offline on RTX5070Ti.
    This resolves model availability, not the missing reviewed training labels.
25. Before human gold exists, execute the eight already declared ASR configurations
    on every fixed dev clip and preserve failures. Do not calculate invented WER,
    select a candidate or activate a stage from unscored drafts. This inference
    plan is not the final-test selection freeze.
26. Before final-test access, amend numeric gate validation and annotation claim
    scope after concrete corrupted-metric regression tests found false-PASS paths.
    Acceptance bytes and baseline parameters/checkpoint remain identical. Preserve
    old inference reports and their image tag; create a new baseline/scorer lock.
    Current verification: 220 tests plus CPU/GPU offline and actual queue recovery.
27. Finish SPEC 17.3 export before waiting for human gold: event-metrics CSV,
    per-sample predictions and measured-only PNG/SVG/HTML. Marginal WER intervals
    reuse the same bootstrap draws; the paired delta gate is unchanged. Historical
    unscored dev runtimes keep their original code identity. Current verification
    has 228 tests and new CPU/GPU offline smoke; prior recovery evidence is reused
    explicitly because its source bytes and dependency versions remain unchanged.
28. Reuse the supplied publisher documents without requiring wholesale manual
    transcription. Recover PDF column order from coordinates and align only
    fixed train/dev windows using local Whisper attention/DTW. Publisher scripts
    are weak segment targets until independently checked against the audio.
29. Freeze the publisher preparation thresholds and 40-step LoRA budget before
    execution. Reject numerical disagreement instead of guessing a correction.
    Retain rejected alignments and infer all dev windows; score only the declared
    eligible proxy subset, explicitly reporting its selection bias.
30. Compare A5 against a float16 CT2 conversion of its exact Transformers parent.
    Keep this checkpoint-adaptation comparison distinct from same-checkpoint
    A0–A4 pipeline ablation. A proxy decrease cannot select/promote a release.
31. Use one supported GPU after an observed zero-step DataParallel failure with
    an unsupported second GPU. Preserve attempt 1, run attempt 2 into a new output
    directory, seed before adapter initialization, and save actual trainer history.
32. Surface publisher proposals in review without creating human revisions or
    checking verification boxes. Human event labels and independent final-test
    references remain absent; no rules-derived replacements are admitted.
33. After the user stopped manual listening, preserve available reviews and leave
    ambiguous references unverified. Expand the A5 clean-control diagnostic using
    50 existing LibriSpeech dev-clean publisher transcripts. Freeze a seeded
    speaker-balanced ID selection before reading transcripts or predictions;
    exclude reader 2277 used previously. No further tuning, cockpit-test access,
    human-label substitution or release selection is allowed from these controls.
    Checklist: verify cached archive/license; freeze IDs/config/weights/scorer;
    execute both models offline at identical float16 settings; preserve failures;
    score all 50 pairs against unchanged acceptance tolerance; record the missing
    independent listening audit and the separate overall NEEDS_MORE_DATA status.
34. On the user's instruction to use all existing sources, recheck the previous
    source list and expand only permitted local material. Freeze all full 20-second
    train/dev windows of documented EN checklist families (including TBM940),
    preserve existing grouping and alignment/numeric admission thresholds, and
    retain rejected windows. Train one new 40-step weak-reference LoRA without
    touching prior models. Assign the entire VOICI original to dev only; use
    full noise and 0/10 dB mixtures as explicitly unverified publisher diagnostics,
    never as normal admitted training augmentation or independent flights.
    Checklist: source evidence; preparation freeze; 33/35 weak pairs; actual
    training; comparison freeze; all 1048 responses; separate reference scoring;
    CPU smoke; artifact verification; PowerShell/Linux replay. No human NLP labels
    invented; no test access or release selection. Negative results are retained.
35. After an actual storage I/O error, snapshot the container error and all 707
    completed prediction hashes before resuming the same frozen runtime. Execute
    only the remaining 341 predictions and verify that completed answers did not
    change. Count the infrastructure interruption separately from errors in final
    persisted ASR records. PostgreSQL/RabbitMQ had not restarted after Docker;
    use unless-stopped consistently with API/worker, retain existing volumes and
    verify service health. The underlying storage-error cause remains unknown.
36. On the user's request for further sources, acquire the licensed BLeRIOT-B
    assets, official FLEURS RU dev and the Noort CVR human-label supplement.
    Keep aircraft noise channels correlated and RU speakers unknown; no source
    description becomes an independent listening audit. Freeze three new ASR
    pause-handling designs plus the existing segment VAD on the exact parent
    checkpoint/precision. Reuse 524 parent answers only after full hash/config
    checks. Checklist completed: 661 inputs, 3305 outputs, 4022 new ASR calls,
    original-time checks, bootstrap, CPU smoke, 15 tests, PS/Linux byte replay.
    Preserve all negative outcomes. Partial human dev 34→33 errors is below the
    10% goal, CI upper bound zero. No stage or candidate is promoted.
37. Use source-native human safety-voice labels only for that separate NLP task.
    Freeze case partition before training; screen explicit CVR/CAM/HOT/INT/crew
    metadata without guessing roles by voice. Preserve unknown-channel exclusions
    and the resulting one-case holdout rather than rebalance after seeing results.
    Checklist completed: 2838 train / 394 dev, 12 bounded model configurations,
    two fixed rule baselines, selection freeze, label-free holdout inference,
    separate 49-row reference scoring and independent precision/recall/F1 checks.
    Holdout macro-F1 .5000 vs .6449 broad rules is INCONCLUSIVE for generalization.
    No further tuning on that holdout, project label substitution, temporal claim
    or production model installation is allowed by these diagnostic results.
38. On the explicit request to check input language and large-v3, freeze two
    further configurations, bringing the conservative search count to 16.
    Pass EN only from five saved human language/scope/listening declarations;
    never infer EN from a weak scenario or override FR/mixed metadata. Run
    small and pinned SYSTRAN large-v3 afresh on all 661 inputs at identical
    CUDA/float16 and language information. Isolate references from inference,
    sample device memory and preserve original timestamps. Checklist completed:
    acquisition; 108-file source freeze; 12 tests; 1322 offline GPU calls;
    large CPU smoke; 40 artifact checks; PS/Linux identical score replay.
    Language change reduces partial dev errors 34→16; large with same EN gives
    20 and fails EN/noise guardrails. These are language-information and checkpoint
    effects, not same-information/checkpoint pipeline gains. No release promotion.
    Preserve the initial CPU mount failure and raw scorer's coarse group-only CI
    flag; a separate interpretation artifact rejects empty/single-group intervals.
