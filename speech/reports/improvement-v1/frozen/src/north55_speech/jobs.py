from __future__ import annotations

import logging
import shutil
import threading
from datetime import timedelta

from celery import Celery
from kombu import Queue
from sqlalchemy import select

from north55_speech.core import SpeechError, now, settings
from north55_speech.db import (
    DB,
    AudioAsset,
    EventRow,
    JobAttempt,
    ModelVersion,
    OutboxEvent,
    PipelineRun,
    ProcessingJob,
    Session,
    TranscriptSegment,
    uid,
)
from north55_speech.schemas import InferenceRequest, PipelineConfig

logger = logging.getLogger("north55.jobs")
celery_app = Celery("north55", broker=settings.broker_url)
celery_app.conf.update(
    task_queues=(Queue("north55", durable=True),),
    task_default_queue="north55",
    task_default_delivery_mode="persistent",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"confirm_publish": True},
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    broker_connection_timeout=3,
    task_publish_retry=False,
    worker_hijack_root_logger=False,
)


def publish_outbox() -> int:
    count = 0
    # Commit publication only after broker confirms; a crash may redeliver, hence DB fencing.
    with DB.begin() as db:
        rows = db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        for event in rows:
            celery_app.send_task(
                "north55.process", args=[event.job_id], task_id=event.id, retry=False
            )
            event.published_at = now()
            count += 1
    return count


def recover_expired() -> int:
    count = 0
    with DB.begin() as db:
        jobs = db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.status == "RUNNING", ProcessingJob.lease_until < now())
            .with_for_update(skip_locked=True)
        )
        for job in jobs:
            old = db.get(JobAttempt, job.attempt_token)
            if old:
                old.status, old.finished_at = "LEASE_EXPIRED", now()
            job.attempt_token, job.lease_until = None, None
            if job.cancel_requested:
                job.status, job.stage = "CANCELLED", "cancelled"
            elif job.attempts >= settings.max_attempts:
                job.status, job.stage = "FAILED", "failed"
                job.error = SpeechError(
                    "RETRY_EXHAUSTED", "Worker recovery budget exhausted"
                ).as_dict()
            else:
                job.status, job.stage = "QUEUED", "recovered"
                db.add(OutboxEvent(job_id=job.id))
            job.updated_at = now()
            count += 1
    return count


def claim(job_id: str) -> tuple[str, dict, dict, str | None] | None:
    with DB.begin() as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
        if job is None or job.status != "QUEUED":
            return None
        session = db.get(Session, job.session_id) if job.session_id else None
        if job.cancel_requested or (session and session.deleted):
            job.status, job.stage = "CANCELLED", "cancelled"
            return None
        token = uid()
        job.attempts += 1
        job.progress = 0.0
        job.error = None
        job.status, job.stage, job.attempt_token = "RUNNING", "starting", token
        job.lease_until = now() + timedelta(seconds=settings.lease_seconds)
        job.updated_at = now()
        db.add(JobAttempt(token=token, job_id=job.id, number=job.attempts))
        return token, job.request_json, job.config_json, job.session_id


def checkpoint(job_id: str, token: str, stage: str | None = None, progress: float | None = None):
    with DB.begin() as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
        if not job or job.attempt_token != token or job.status != "RUNNING":
            raise SpeechError("STALE_ATTEMPT", "Attempt no longer owns this job")
        session = db.get(Session, job.session_id) if job.session_id else None
        if job.cancel_requested or (session and session.deleted):
            raise SpeechError("CANCELLED", "Processing was cancelled")
        if stage:
            job.stage = stage
        if progress is not None:
            job.progress = max(job.progress, min(0.99, progress))
        job.lease_until = now() + timedelta(seconds=settings.lease_seconds)
        job.updated_at = now()


def finish(job_id: str, token: str, result: dict | None, error: SpeechError | None = None) -> bool:
    with DB.begin() as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
        if not job or job.attempt_token != token:
            return False
        session = (
            db.scalar(select(Session).where(Session.id == job.session_id).with_for_update())
            if job.session_id
            else None
        )
        attempt = db.get(JobAttempt, token)
        if job.cancel_requested or (session and session.deleted):
            error = SpeechError("CANCELLED", "Processing was cancelled")
        if error:
            job.error = error.as_dict()
            job.status = "CANCELLED" if error.code == "CANCELLED" else "FAILED"
            job.stage = job.status.lower()
            if error.retryable and job.attempts < settings.max_attempts:
                job.status, job.stage = "QUEUED", "retry_pending"
                db.add(OutboxEvent(job_id=job.id))
        else:
            assert result is not None
            job.status, job.stage, job.progress = "SUCCEEDED", "completed", 1.0
            job.result, job.error = result, None
            model_version_id = (
                result["effective_config"]["model"] + ":" + result["model_manifest"]["revision"]
            )
            if db.get(ModelVersion, model_version_id) is None:
                db.add(ModelVersion(id=model_version_id, manifest=result["model_manifest"]))
            db.add(
                PipelineRun(
                    job_id=job.id,
                    attempt_token=token,
                    config_hash=result["config_hash"],
                    manifest={
                        "model_manifest": result["model_manifest"],
                        "effective_config": result["effective_config"],
                        "timing": result["timing"],
                    },
                )
            )
            if session:
                result["session_id"] = session.id
                from north55_speech.release import runtime_selection

                selected, release = runtime_selection()
                if selected.config_hash == result["config_hash"]:
                    result.update(release)
                session.result = result
                asset = db.scalar(select(AudioAsset).where(AudioAsset.session_id == session.id))
                if asset:
                    asset.diagnostics = result["audio"]
                for segment in result["segments"]:
                    db.add(
                        TranscriptSegment(
                            session_id=session.id,
                            segment_id=segment["segment_id"],
                            start_sec=segment["start_sec"],
                            end_sec=segment["end_sec"],
                            payload=segment,
                        )
                    )
                for event in result["events"]:
                    db.add(
                        EventRow(
                            session_id=session.id,
                            event_id=event["event_id"],
                            start_sec=event["start_sec"],
                            end_sec=event["end_sec"],
                            payload=event,
                        )
                    )
        if attempt:
            attempt.finished_at, attempt.status, attempt.error = now(), job.status, job.error
        job.attempt_token, job.lease_until, job.updated_at = None, None, now()
        return error is None


@celery_app.task(name="north55.process")
def process_job(job_id: str):
    claimed = claim(job_id)
    if claimed is None:
        return
    token, raw_request, raw_config, session_id = claimed
    stopped = threading.Event()
    heartbeat_failed: list[Exception] = []

    def heartbeat():
        while not stopped.wait(max(1, settings.lease_seconds // 3)):
            try:
                checkpoint(job_id, token)
            except Exception as e:
                heartbeat_failed.append(e)
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    # Attempts have isolated artifacts. Late workers cannot resurrect a committed session.
    work = settings.artifact_root / "attempts" / job_id / token

    def progress(stage, fraction):
        if heartbeat_failed:
            error = heartbeat_failed[0]
            if isinstance(error, SpeechError):
                raise error
            raise SpeechError("DB_UNAVAILABLE", "Heartbeat database connection failed", True)
        checkpoint(job_id, token, stage, fraction)

    keep = False
    try:
        from north55_speech.pipeline import run_pipeline

        result = run_pipeline(
            InferenceRequest.model_validate(raw_request),
            PipelineConfig.model_validate(raw_config),
            work,
            progress,
        )
        keep = finish(job_id, token, result)
    except SpeechError as e:
        finish(job_id, token, None, e)
        logger.warning("job_failed job_id=%s code=%s", job_id, e.code)
    except OSError as e:
        code = "DISK_FULL" if e.errno == 28 else "IO_ERROR"
        finish(
            job_id, token, None, SpeechError(code, "Local storage operation failed", e.errno != 28)
        )
    except Exception as e:
        # Do not log exception payloads: decoders can include transcript or local paths.
        finish(
            job_id,
            token,
            None,
            SpeechError("PROCESSING_FAILED", f"Stage failed: {type(e).__name__}"),
        )
        logger.warning("job_failed job_id=%s error_type=%s", job_id, type(e).__name__)
    finally:
        stopped.set()
        thread.join(timeout=5)
        if not keep and work.is_relative_to(settings.artifact_root / "attempts"):
            shutil.rmtree(work, ignore_errors=True)
            with DB() as db:
                job = db.get(ProcessingJob, job_id)
                session = db.get(Session, session_id) if session_id else None
                deleted_or_cancelled = bool(
                    (session and session.deleted) or (job and job.cancel_requested)
                )
            if deleted_or_cancelled:
                shutil.rmtree(work.parent, ignore_errors=True)
