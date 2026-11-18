from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import logging
import os
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from north55_speech.core import SpeechError, confined, digest, settings
from north55_speech.db import (
    DB,
    AudioAsset,
    EventRow,
    OutboxEvent,
    ProcessingJob,
    ReviewRevision,
    Session,
    TranscriptSegment,
    engine,
    uid,
)
from north55_speech.jobs import celery_app, publish_outbox, recover_expired
from north55_speech.journal import export_result
from north55_speech.schemas import InferenceRequest, Review, UploadMetadata

log = logging.getLogger("north55.api")


async def dispatch_loop():
    while True:
        try:
            await asyncio.to_thread(recover_expired)
            await asyncio.to_thread(publish_outbox)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("dispatcher_unavailable error_type=%s", type(e).__name__)
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if len(settings.api_key) < 32 or len(settings.session_secret) < 32:
        raise RuntimeError("Generate local secrets with bootstrap before starting API")
    for root in [settings.audio_root, settings.artifact_root]:
        root.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(dispatch_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="55 Север · Speech evidence", version="0.1.0", lifespan=lifespan)
assets = Path(__file__).parent / "web"
templates = Jinja2Templates(directory=str(assets))
app.mount("/static", StaticFiles(directory=str(assets)), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Native form POSTs need their real origin; external sites still receive no referrer.
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    return response


def serializer():
    return URLSafeTimedSerializer(settings.session_secret, salt="north55-ui-v1")


def cookie_session(request: Request):
    try:
        return serializer().loads(request.cookies.get("north55_session", ""), max_age=28800)
    except BadSignature:
        return None


def authorize(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> str:
    if x_api_key and settings.api_key and hmac.compare_digest(x_api_key, settings.api_key):
        return "local-owner"
    session = cookie_session(request)
    if session:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(csrf, session["csrf"]):
                raise HTTPException(403, "CSRF token required")
        return session["owner"]
    raise HTTPException(401, "Valid API key or UI session required")


Owner = Annotated[str, Depends(authorize)]


def get_session(db, session_id: str, owner: str) -> Session:
    session = db.get(Session, session_id)
    if not session or session.deleted or session.owner != owner:
        raise HTTPException(404, "Session not found")
    return session


def get_job(db, job_id: str, owner: str) -> ProcessingJob:
    job = db.get(ProcessingJob, job_id)
    if not job or job.owner != owner:
        raise HTTPException(404, "Job not found")
    if job.session_id:
        get_session(db, job.session_id, owner)
    return job


@app.exception_handler(SpeechError)
async def speech_error(request, error: SpeechError):
    status = {
        "UNSAFE_PATH": 400,
        "AUDIO_TOO_LARGE": 413,
        "UNSUPPORTED_CONTAINER": 415,
        "FILE_NOT_FOUND": 404,
        "DISK_FULL": 507,
    }.get(error.code, 422)
    return JSONResponse(status_code=status, content={"error": error.as_dict()})


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    try:
        with engine.connect() as conn:
            revision = conn.execute(text("select version_num from alembic_version")).scalar_one()
        with celery_app.connection_for_write() as conn:
            conn.ensure_connection(max_retries=0)
        for path in (settings.audio_root, settings.artifact_root):
            if not os.access(path, os.W_OK):
                raise RuntimeError("volume unavailable")
        return {"status": "ready", "migration": revision}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})


@app.get("/v1/capabilities")
def capabilities(owner: Owner):
    from north55_speech.release import runtime_selection

    _, release = runtime_selection()
    models = [p.parent.name for p in settings.model_root.glob("*/manifest.json")]
    return {
        "schema_version": "1.0",
        "models": models,
        "language_modes": ["en", "ru", "mixed", "auto"],
        "language_quality": {
            lang: "validated_in_frozen_scope"
            if lang in release["validated_scope"]
            else "unvalidated"
            for lang in ("en", "ru", "mixed")
        },
        **release,
        "scope": "cockpit_simulator_crew_speech",
        "diarization_modes": ["off", "channel_mapping", "pyannote_local"],
        "offline_inference": True,
        "external_transcription_api": False,
    }


@app.get("/v1/csrf")
def csrf(request: Request, owner: Owner):
    session = cookie_session(request)
    return {"csrf": session["csrf"] if session else None}


@app.post("/v1/sessions", status_code=202)
async def upload_session(
    owner: Owner,
    audio: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form()],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
):
    try:
        meta = UploadMetadata.model_validate_json(metadata)
    except (ValidationError, ValueError) as e:
        raise HTTPException(400, "Invalid JSON metadata or missing rights/provenance") from e
    upload_id = uid()
    temporary_dir = settings.audio_root / "incoming"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary = temporary_dir / upload_id
    h, size = hashlib.sha256(), 0
    stored: Path | None = None
    committed = False
    try:
        with temporary.open("xb") as stream:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "Upload exceeds configured size limit")
                if shutil.disk_usage(temporary_dir).free < settings.minimum_free_bytes + len(chunk):
                    raise SpeechError("DISK_FULL", "Insufficient free space for upload")
                h.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if not size:
            raise HTTPException(422, "Empty audio")
        request_hash = digest({"audio_sha256": h.hexdigest(), "metadata": meta.model_dump()})
        try:
            with DB.begin() as db:
                existing = db.scalar(
                    select(ProcessingJob).where(
                        ProcessingJob.owner == owner,
                        ProcessingJob.idempotency_key == idempotency_key,
                    )
                )
                if existing:
                    if existing.request_hash != request_hash:
                        raise HTTPException(409, "Idempotency key was used for a different request")
                    if existing.session_id is None:
                        raise HTTPException(409, "Idempotency key belongs to a non-session job")
                    get_session(db, existing.session_id, owner)
                    return {"session_id": existing.session_id, "job_id": existing.id}
                session_id, job_id = uid(), uid()
                locator = f"sessions/{session_id}/original"
                stored = confined(settings.audio_root, locator, must_exist=False)
                stored.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary, stored)
                request = InferenceRequest(
                    sample_id=session_id,
                    audio_locator=locator,
                    audio_sha256=h.hexdigest(),
                    **meta.model_dump(exclude={"rights_confirmed", "provenance"}),
                )
                from north55_speech.release import runtime_selection

                config, _ = runtime_selection()
                db.add(Session(id=session_id, owner=owner, metadata_json=meta.model_dump()))
                db.flush()
                db.add(
                    AudioAsset(
                        session_id=session_id,
                        locator=locator,
                        sha256=h.hexdigest(),
                        size_bytes=size,
                    )
                )
                db.add(
                    ProcessingJob(
                        id=job_id,
                        session_id=session_id,
                        owner=owner,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        request_json=request.model_dump(),
                        config_json=config.model_dump(),
                    )
                )
                db.flush()
                db.add(OutboxEvent(job_id=job_id))
            committed = True
            return {"session_id": session_id, "job_id": job_id}
        except IntegrityError as e:
            with DB() as db:
                existing = db.scalar(
                    select(ProcessingJob).where(
                        ProcessingJob.owner == owner,
                        ProcessingJob.idempotency_key == idempotency_key,
                    )
                )
                if existing and existing.request_hash == request_hash:
                    return {"session_id": existing.session_id, "job_id": existing.id}
            raise HTTPException(409, "Concurrent idempotency conflict") from e
    except OSError as e:
        if e.errno == 28:
            raise SpeechError("DISK_FULL", "Storage capacity exhausted") from e
        raise
    finally:
        temporary.unlink(missing_ok=True)
        if stored and not committed:
            stored.unlink(missing_ok=True)
        await audio.close()


@app.get("/v1/jobs")
def list_jobs(owner: Owner):
    with DB() as db:
        rows = db.scalars(
            select(ProcessingJob)
            .join(Session)
            .where(ProcessingJob.owner == owner, Session.deleted.is_(False))
            .order_by(ProcessingJob.created_at.desc())
            .limit(100)
        )
        return [
            {
                "job_id": j.id,
                "session_id": j.session_id,
                "status": j.status,
                "stage": j.stage,
                "progress": j.progress,
                "error": j.error,
            }
            for j in rows
        ]


@app.get("/v1/jobs/{job_id}")
def job_status(job_id: str, owner: Owner):
    with DB() as db:
        j = get_job(db, job_id, owner)
        return {
            "job_id": j.id,
            "session_id": j.session_id,
            "status": j.status,
            "stage": j.stage,
            "progress": j.progress,
            "attempts": j.attempts,
            "cancel_requested": j.cancel_requested,
            "error": j.error,
        }


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, owner: Owner):
    with DB.begin() as db:
        db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
        job = get_job(db, job_id, owner)
        if job.status in {"QUEUED", "RUNNING"}:
            job.cancel_requested = True
            if job.status == "QUEUED":
                job.status, job.stage = "CANCELLED", "cancelled"
        return {"status": job.status, "cancel_requested": job.cancel_requested}


@app.post("/v1/jobs/{job_id}/retry")
def retry_job(job_id: str, owner: Owner):
    retryable_codes = {
        "MODEL_NOT_AVAILABLE",
        "MODEL_LOAD_FAILED",
        "DISK_FULL",
        "IO_ERROR",
        "DB_UNAVAILABLE",
        "RETRY_EXHAUSTED",
        "PROCESSING_FAILED",
    }
    with DB.begin() as db:
        db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
        job = get_job(db, job_id, owner)
        if job.status != "FAILED" or not job.error or job.error["code"] not in retryable_codes:
            raise HTTPException(409, "Job is not eligible for retry")
        if job.attempts >= settings.max_attempts:
            raise HTTPException(
                409, "Attempt budget exhausted; inspect the failure before a new upload"
            )
        job.status, job.stage, job.progress, job.error = "QUEUED", "retry_pending", 0.0, None
        job.cancel_requested = False
        db.add(OutboxEvent(job_id=job.id))
        return {"job_id": job.id, "status": job.status}


@app.get("/v1/sessions/{session_id}/result")
def session_result(session_id: str, owner: Owner):
    with DB() as db:
        session = get_session(db, session_id, owner)
        if session.result is None:
            raise HTTPException(409, "Result is not available yet")
        return session.result | {"revision": session.revision}


@app.get("/v1/sessions/{session_id}/audio")
def session_audio(session_id: str, owner: Owner):
    with DB() as db:
        get_session(db, session_id, owner)
        asset = db.scalar(select(AudioAsset).where(AudioAsset.session_id == session_id))
        if asset is None:
            raise HTTPException(404, "Audio asset not found")
        path = confined(settings.audio_root, asset.locator)
    # Starlette FileResponse implements byte Range and conditional range responses.
    return FileResponse(
        path, media_type="application/octet-stream", headers={"Content-Disposition": "inline"}
    )


@app.get("/v1/sessions/{session_id}/export")
def session_export(session_id: str, owner: Owner, format: str = "json"):
    result = session_result(session_id, owner)
    try:
        content, media = export_result(result, format)
    except ValueError as e:
        raise HTTPException(400, "Use json, csv, vtt or srt") from e
    return Response(
        content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{session_id}.{format}"'},
    )


@app.post("/v1/sessions/{session_id}/reviews")
def review_session(session_id: str, review: Review, owner: Owner):
    with DB.begin() as db:
        db.scalar(select(Session).where(Session.id == session_id).with_for_update())
        session = get_session(db, session_id, owner)
        if session.revision != review.expected_revision:
            raise HTTPException(409, "Review revision conflict; reload current result")
        if not session.result:
            raise HTTPException(409, "Result not ready")
        result = copy.deepcopy(session.result)
        collection, key, target_id = (
            ("segments", "segment_id", review.segment_id)
            if review.segment_id
            else ("events", "event_id", review.event_id)
        )
        target = next((x for x in result[collection] if x[key] == target_id), None)
        if target is None:
            raise HTTPException(404, "Review target not found")
        before = copy.deepcopy(target)
        allowed = (
            {"reviewed_text", "role"}
            if review.segment_id
            else {"labels", "salient_for_review", "review_status"}
        )
        for field in allowed:
            value = getattr(review, field)
            if value is not None:
                target[field] = value
        if review.role is not None:
            target["role_provenance"] = f"human_review:{review.author}"
        related_before = []
        if review.segment_id:
            segment_map = {s["segment_id"]: s for s in result["segments"]}
            for event in result["events"]:
                if review.segment_id not in event["evidence_segment_ids"]:
                    continue
                related_before.append(copy.deepcopy(event))
                evidence = [segment_map[s] for s in event["evidence_segment_ids"]]
                event["reviewed_evidence_quote"] = " ".join(
                    s.get("reviewed_text")
                    if s.get("reviewed_text") is not None
                    else s["display_text"]
                    for s in evidence
                )
                roles = {s["role"] for s in evidence}
                event["role"] = next(iter(roles)) if len(roles) == 1 else "unknown"
                event["role_provenance"] = f"human_review:{review.author}"
                event["review_status"] = "draft"
                event["needs_review"] = True
                event["risk_reasons"] = sorted(
                    set(event.get("risk_reasons", []))
                    | {"reviewed_text_entities_require_verification"}
                )
        session.revision += 1
        result["revision"] = session.revision
        session.result = result
        db.add(
            ReviewRevision(
                session_id=session_id,
                revision=session.revision,
                author=review.author,
                reason=review.reason,
                before=before,
                after=copy.deepcopy(target)
                | (
                    {
                        "related_events_before": related_before,
                        "related_events_after": [
                            e
                            for e in result["events"]
                            if review.segment_id in e["evidence_segment_ids"]
                        ],
                    }
                    if review.segment_id
                    else {}
                ),
            )
        )
        return {"revision": session.revision, "target": target}


@app.get("/v1/sessions/{session_id}/reviews")
def review_history(session_id: str, owner: Owner):
    with DB() as db:
        get_session(db, session_id, owner)
        rows = db.scalars(
            select(ReviewRevision)
            .where(ReviewRevision.session_id == session_id)
            .order_by(ReviewRevision.revision)
        )
        return [
            {
                "revision": r.revision,
                "author": r.author,
                "reason": r.reason,
                "before": r.before,
                "after": r.after,
                "created_at": r.created_at,
            }
            for r in rows
        ]


@app.delete("/v1/sessions/{session_id}")
def delete_session(session_id: str, owner: Owner):
    with DB.begin() as db:
        jobs = list(
            db.scalars(
                select(ProcessingJob)
                .where(ProcessingJob.session_id == session_id)
                .with_for_update()
            )
        )
        db.scalar(select(Session).where(Session.id == session_id).with_for_update())
        session = get_session(db, session_id, owner)
        session.deleted, session.result, session.metadata_json = True, None, {}
        for job in jobs:
            job.cancel_requested, job.attempt_token, job.result = True, None, None
            job.status, job.stage, job.request_json = "CANCELLED", "deleted", {}
        for model in [TranscriptSegment, EventRow, ReviewRevision, AudioAsset]:
            db.execute(delete(model).where(model.__table__.c.session_id == session_id))
        job_ids = [j.id for j in jobs]
    original_dir = settings.audio_root / "sessions" / session_id
    if original_dir.resolve().is_relative_to((settings.audio_root / "sessions").resolve()):
        shutil.rmtree(original_dir, ignore_errors=True)
    for job_id in job_ids:
        artifacts = settings.artifact_root / "attempts" / job_id
        if artifacts.resolve().is_relative_to((settings.artifact_root / "attempts").resolve()):
            shutil.rmtree(artifacts, ignore_errors=True)
    return {"status": "deleted", "retained": "content-free tombstone and attempt metadata"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"logged_in": bool(cookie_session(request))}
    )


@app.post("/login")
def login(request: Request, api_key: Annotated[str, Form()]):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Cross-origin login is forbidden")
    if not settings.api_key or not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(401, "Invalid API key")
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "north55_session",
        serializer().dumps({"owner": "local-owner", "csrf": secrets.token_urlsafe(32)}),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=28800,
    )
    return response


@app.post("/logout")
def logout(owner: Owner):
    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie("north55_session")
    return response
