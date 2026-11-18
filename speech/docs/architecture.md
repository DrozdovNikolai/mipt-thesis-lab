# Architecture

`north55_speech` is a local Python 3.11 package for cockpit, crew and instructor
speech. The API produces draft evidence for review, never aircraft telemetry.

`api.py` serves authenticated FastAPI endpoints and a small Jinja/JavaScript UI.
It does not instantiate an ASR model. PostgreSQL stores session ownership,
immutable source checksums, jobs, attempts, results, revisions and registry rows.
Files live in named audio/model/artifact volumes. RabbitMQ receives persistent
Celery messages from a transactional DB outbox; its ports are not published.

`jobs.py` claims a queued row under a database lock, creates an attempt token and
renews a lease on a separate heartbeat thread. Duplicate deliveries cannot claim
an active attempt. The API dispatcher requeues expired leases within a three-attempt
budget. Writes check the current token and tombstone; a late worker cannot commit
over a newer attempt or deleted session. This is at-least-once delivery, not exactly
once. Cancellation is cooperative at stage/chunk/generator boundaries; a running
native decode cannot be interrupted instantly.

`audio.py` validates actual containers with ffprobe, permits only file/pipe input
protocols and decodes to 16 kHz working signals. Separate channels remain separate;
explicit identities need owner provenance. Correlated duplicate channels are
marked as crosstalk and recognized once; original channel bytes remain available.
This simple correlation check is not a validated crosstalk separation algorithm.

`pipeline.py` coordinates VAD, optional spectral gating, local faster-whisper,
optional diarization, formatting, entities, episodes and review risk. Chunk offsets
are original timeline offsets. `raw_asr_text`, display formatting and human review
are separate. Re-decode stores alternatives and never resolves conflicting
critical values by aircraft plausibility. Raw confidence signals remain uncalibrated.

`datasets.py`, `training.py`, `lora.py`, `metrics.py`, `gates.py` and `benchmark.py`
provide the research path. Benchmark jobs have no user session, journal or reviews.
Only a sanitized typed inference request reaches the worker. `curator` is the
special data preparation profile; tools/trainer have train/dev inputs, evaluator
has sealed test references. Worker/API do not mount dataset manifests.

Runtime worker networking is an internal Compose network. Acquisition uses the
tools profile with a separate outbound network. API additionally has an ingress
network to publish 127.0.0.1:8000 on this Docker Desktop version. All application
containers run as uid 10001 without privileges, Docker socket or host networking.

Deletion clears audio, results and review content and retains a content-free
tombstone/attempt history. Active workers are fenced and clean their attempt files
on cancellation. External backups are controlled by the operator and are outside
this deletion transaction; no instantaneous backup erasure is promised.
