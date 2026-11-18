"""Local human annotation sidecar. Mount a train/dev packet, never sealed test data."""

from __future__ import annotations

import hmac
import json
import math
import os
import secrets
import threading
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import Field

from north55_speech.core import StrictModel, atomic_json, confined, digest, file_hash, now, settings
from north55_speech.datasets import load_manifest, validate_groups
from north55_speech.schemas import LABELS


class Annotation(StrictModel):
    revision: int = Field(ge=0)
    scope: Literal["unknown", "read_cockpit", "cockpit", "simulator", "atc"]
    language: Literal["unknown", "en", "ru", "fr", "mixed"]
    transcript: str | None = Field(default=None, max_length=20000)
    entities: list[dict] | None = None
    labels: list[str] | None = None
    salient: bool | None = None
    temporal: list[dict] | None = None
    unintelligible: list[dict] = Field(default_factory=list)
    listened: bool = False
    verify_scope: bool = False
    verify_transcript: bool = False
    verify_entities: bool = False
    verify_events: bool = False
    verify_temporal: bool = False


def create_app(packet: Path, audio_root: Path, api_key: str, secret: str) -> FastAPI:
    if len(api_key) < 32 or len(secret) < 32:
        raise ValueError("Use the existing bootstrap secrets")
    samples = []
    for split in ("train", "dev"):
        rows = load_manifest(packet/f"{split}.jsonl")
        if any(row.split != split for row in rows):
            raise ValueError("Annotation sidecar only accepts train/dev")
        samples.extend(rows)
    validate_groups(samples)
    originals = {sample.sample_id: sample for sample in samples}
    if any(len(key) != 32 or not key.isalnum() for key in originals):
        raise ValueError("Packet requires opaque sample IDs")
    app = FastAPI(title="55 Север — разметка train/dev")
    signer = URLSafeTimedSerializer(secret, salt="north55-annotation-v1")
    lock = threading.Lock()
    assets = Path(__file__).parent/"annotation_web"

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # no-referrer makes native form POSTs send Origin: null, which login must reject.
        # same-origin preserves local form origins without leaking referrers to other sites.
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self'; frame-ancestors 'none'; form-action 'self'"
        return response

    def auth(request: Request):
        try:
            session = signer.loads(request.cookies.get("annotation_session", ""), max_age=12*3600)
        except BadSignature as exc:
            raise HTTPException(401, "Войдите в локальную разметку") from exc
        if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", ""), session["csrf"]
        ):
            raise HTTPException(403, "Неверный CSRF token")
        return session

    def current(sample_id: str):
        if sample_id not in originals:
            raise HTTPException(404, "Неизвестный фрагмент")
        revisions = sorted((packet/"revisions"/sample_id).glob("revision-*.json"))
        if revisions:
            path = revisions[-1]
            record = json.loads(path.read_text(encoding="utf-8"))
            return record["revision"], originals[sample_id].model_validate(record["sample"]), file_hash(path)
        return 0, originals[sample_id].model_copy(deep=True), digest(originals[sample_id].model_dump())

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        try:
            auth(request)
            path = assets/"index.html"
        except HTTPException:
            path = assets/"login.html"
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.post("/login")
    def login(request: Request, key: str = Form(), annotator: str = Form()):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Неверный origin")
        if not hmac.compare_digest(key.encode(), api_key.encode()) or not 1 <= len(annotator.strip()) <= 100:
            raise HTTPException(403, "Проверьте ключ и имя разметчика")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("annotation_session", signer.dumps({"actor": annotator.strip(), "csrf": secrets.token_hex(24)}),
                            httponly=True, samesite="strict", max_age=12*3600)
        return response

    @app.get("/styles.css")
    def styles():
        return FileResponse(assets/"styles.css", media_type="text/css")

    @app.get("/annotation.js")
    def javascript():
        return FileResponse(assets/"annotation.js", media_type="application/javascript")

    @app.get("/api/packet")
    def listing(session=Depends(auth)):
        rows = []
        for key in originals:
            revision, sample, _ = current(key)
            rows.append({"id": key, "split": sample.split, "source": sample.annotation_provenance["source_sample_id"],
                         "start_sec": sample.annotation_provenance["original_start_sec"], "revision": revision,
                         "transcript_status": sample.transcript_status, "events_status": sample.events_status})
        return {"items": rows, "csrf": session["csrf"], "actor": session["actor"], "labels": LABELS}

    @app.get("/api/item/{sample_id}")
    def item(sample_id: str, session=Depends(auth)):
        revision, sample, _ = current(sample_id)
        return {"revision": revision, "sample": sample.model_dump(),
                "publisher_proposal_available": (packet/"publisher-proposals"/f"{sample_id}.json").is_file()}

    @app.post("/api/publisher-proposal/{sample_id}")
    def publisher_proposal(sample_id: str, session=Depends(auth)):
        _, sample, _ = current(sample_id)
        path = packet/"publisher-proposals"/f"{sample_id}.json"
        if not path.is_file():
            raise HTTPException(404, "Издательский текст ещё не привязан")
        proposal = json.loads(path.read_text(encoding="utf-8"))
        if (proposal.get("sample_id") != sample_id or proposal.get("split") != sample.split
                or proposal.get("source_sample_id") != sample.annotation_provenance["source_sample_id"]
                or proposal.get("original_start_sec") != sample.annotation_provenance["original_start_sec"]
                or proposal.get("target_source_audio_sha256") != sample.annotation_provenance.get("source_audio_sha256")
                or proposal.get("human_verified") is not False):
            raise HTTPException(409, "Привязка не соответствует исходному фрагменту")
        with lock:
            atomic_json(packet/"script-exposure"/sample_id/(secrets.token_hex(12)+".json"),
                        {"actor": session["actor"], "time": now(), "event": "publisher_aligned_proposal_revealed",
                         "proposal_sha256": file_hash(path)})
        return proposal

    @app.get("/api/audio/{sample_id}")
    def audio(sample_id: str, session=Depends(auth)):
        _, sample, _ = current(sample_id)
        path = confined(audio_root, sample.audio_path)
        if file_hash(path) != sample.audio_sha256:
            raise HTTPException(409, "Аудио изменено")
        return FileResponse(path, media_type="audio/wav")

    @app.post("/api/draft/{sample_id}")
    def draft(sample_id: str, session=Depends(auth)):
        current(sample_id)
        with lock:
            exposure = packet/"draft-exposure"/sample_id/(secrets.token_hex(12)+".json")
            atomic_json(exposure, {"actor": session["actor"], "time": now(), "event": "machine_draft_revealed"})
        result = json.loads((packet/"drafts"/f"{sample_id}.json").read_text(encoding="utf-8"))
        return {"text": result["text"], "status": "machine", "human_verified": False}

    @app.post("/api/script-hint/{sample_id}")
    def script_hint(sample_id: str, session=Depends(auth)):
        current(sample_id)
        path = packet/"script-hints"/f"{sample_id}.json"
        if not path.exists():
            raise HTTPException(404, "Контекст сценария ещё не подготовлен")
        result = json.loads(path.read_text(encoding="utf-8"))
        with lock:
            atomic_json(packet/"script-exposure"/sample_id/(secrets.token_hex(12)+".json"),
                        {"actor": session["actor"], "time": now(), "event": "publisher_script_context_revealed",
                         "hint_sha256": file_hash(path)})
        return result

    @app.post("/api/review/{sample_id}")
    def save(sample_id: str, data: Annotation, session=Depends(auth)):
        flags = [data.verify_scope, data.verify_transcript, data.verify_entities, data.verify_events, data.verify_temporal]
        if any(flags) and not data.listened:
            raise HTTPException(422, "Для подтверждения нужно прослушать весь фрагмент")
        if data.verify_scope and (data.scope == "unknown" or data.language == "unknown"):
            raise HTTPException(422, "Укажите scope и язык")
        if data.verify_transcript and data.transcript is None:
            raise HTTPException(422, "Не указан текст")
        if data.verify_entities and data.entities is None:
            raise HTTPException(422, "Укажите сущности или явно подтвердите пустой список []")
        if data.verify_events and (data.labels is None or data.salient is None):
            raise HTTPException(422, "Отметьте события и отдельно значимость")
        if data.labels is not None and (not set(data.labels) <= set(LABELS) or
                                       ("OTHER" in data.labels and len(data.labels) > 1)):
            raise HTTPException(422, "Неверные категории")
        if data.verify_temporal and data.temporal is None:
            raise HTTPException(422, "Не заданы временные события")
        with lock:
            revision, before, before_hash = current(sample_id)
            if revision != data.revision:
                raise HTTPException(409, "Фрагмент уже изменён; загрузите свежую ревизию")
            for entity in data.entities or []:
                if not {"type", "canonical_value", "unit", "polarity", "start_sec", "end_sec"} <= entity.keys():
                    raise HTTPException(422, "Сущность требует type, canonical_value, unit, polarity и таймкоды")
                if entity["type"] not in {"flaps_setting", "gear_position_mention", "speed_mention", "altitude_mention", "heading_mention", "checklist_name", "warning_mention"}:
                    raise HTTPException(422, "Неизвестный тип сущности")
                if entity["polarity"] not in {"affirmative", "negated", "uncertain"}:
                    raise HTTPException(422, "Неверная полярность")
                if isinstance(entity["canonical_value"], float) and not math.isfinite(entity["canonical_value"]):
                    raise HTTPException(422, "Нечисловое значение сущности")
            for event in data.temporal or []:
                if not event.get("labels") or not set(event["labels"]) <= set(LABELS):
                    raise HTTPException(422, "Временное событие требует допустимые labels")
            for collection in (data.entities or [], data.temporal or [], data.unintelligible):
                for span in collection:
                    try:
                        valid = 0 <= float(span["start_sec"]) < float(span["end_sec"]) <= before.duration_sec
                    except (KeyError, ValueError, TypeError):
                        valid = False
                    if not valid:
                        raise HTTPException(422, "Таймкоды должны быть внутри фрагмента, в секундах от его начала")
            def status(value, verified):
                return "human_verified" if verified else "weak" if value is not None else "missing"
            after = before.model_copy(deep=True, update={
                "scope": data.scope, "scope_verified": data.verify_scope, "language": data.language,
                "reference_text": data.transcript, "transcript_status": status(data.transcript, data.verify_transcript),
                "critical_entities": data.entities, "entities_status": status(data.entities, data.verify_entities),
                "labels": data.labels, "salient_for_review": data.salient,
                "events_status": status(data.labels, data.verify_events), "events": data.temporal,
                "temporal_status": status(data.temporal, data.verify_temporal), "unintelligible": data.unintelligible,
                "primary": False,
            })
            after.annotation_provenance.update({"annotator": session["actor"], "reviewed_audio": data.listened,
                                               "reviewed_at": now().isoformat(), "verification_method": "identified_human_self_attestation",
                                               "machine_draft_exposed": any((packet/"draft-exposure"/sample_id).glob("*.json"))})
            after.annotation_provenance["publisher_script_exposed"] = any((packet/"script-exposure"/sample_id).glob("*.json"))
            after = type(after).model_validate(after.model_dump())
            record = {"revision": revision+1, "sample": after.model_dump(), "audit": {
                "actor": session["actor"], "time": now(), "before_sha256": before_hash,
                "after_sha256": digest(after.model_dump()), "operation": "human_annotation_revision",
                "verified_tasks": [name for name, enabled in zip(("scope", "transcript", "entities", "events", "temporal"), flags, strict=True) if enabled],
            }}
            destination = packet/"revisions"/sample_id/f"revision-{revision+1:08d}.json"
            if destination.exists():
                raise HTTPException(409, "Ревизия уже существует")
            atomic_json(destination, record)
        return {"saved": True, "revision": revision+1}

    @app.get("/api/export/{split}")
    def export(split: Literal["train", "dev"], session=Depends(auth)):
        rows = [current(key)[1] for key, sample in originals.items() if sample.split == split]
        return Response("".join(row.model_dump_json()+"\n" for row in rows), media_type="application/x-ndjson",
                        headers={"Content-Disposition": f'attachment; filename="{split}-annotations.jsonl"'})

    return app


def factory():
    return create_app(Path(os.environ.get("NORTH55_ANNOTATION_ROOT", "/packet")), settings.audio_root,
                      settings.api_key, settings.session_secret)
