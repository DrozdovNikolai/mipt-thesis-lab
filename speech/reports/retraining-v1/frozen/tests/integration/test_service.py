"""Real PostgreSQL, RabbitMQ, API and local ASR; lawful engineering controls only."""

import io
import json
import uuid
from datetime import timedelta

import httpx
import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import select

from north55_speech.cli import wait_job
from north55_speech.core import SpeechError, now, settings
from north55_speech.db import DB, JobAttempt, ProcessingJob, Session
from north55_speech.jobs import checkpoint, claim, finish, recover_expired

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with httpx.Client(
        base_url=settings.api_url, headers={"X-API-Key": settings.api_key}, timeout=30
    ) as c:
        yield c


def upload(client, content, name="test.wav", key=None, metadata=None):
    return client.post(
        "/v1/sessions",
        files={"audio": (name, content)},
        data={
            "metadata": json.dumps(
                metadata
                or {
                    "language": "en",
                    "rights_confirmed": True,
                    "provenance": "test engineering control",
                }
            )
        },
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


def silence():
    out = io.BytesIO()
    sf.write(out, np.zeros(8000), 16000, format="WAV")
    return out.getvalue()


def test_auth_metadata_and_private_resource(client):
    assert httpx.get(settings.api_url + "/v1/jobs").status_code == 401
    assert client.get("/v1/sessions/unknown/audio").status_code == 404
    assert (
        client.post(
            "/v1/sessions",
            files={"audio": ("a", b"bad")},
            data={"metadata": "{"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        ).status_code
        == 400
    )
    assert client.get("/health/ready").status_code == 200
    assert client.get("/v1/capabilities").json()["validated_scope"] == []


def test_invalid_audio_typed_failure(client):
    ids = upload(client, b"corrupt audio").json()
    status = wait_job(client, ids["job_id"], 60)
    assert status["status"] == "FAILED"
    assert status["error"]["code"] == "INVALID_AUDIO"
    assert client.post(f"/v1/jobs/{ids['job_id']}/retry").status_code == 409
    assert client.delete(f"/v1/sessions/{ids['session_id']}").status_code == 200


@pytest.mark.real_asr
def test_real_e2e_idempotency_review_range_export_delete(client):
    card = json.loads((settings.audio_root / "smoke/provenance.json").read_text())
    sample = card["samples"][1]
    source = settings.audio_root / "smoke" / sample["filename"]
    original = source.read_bytes()
    key = str(uuid.uuid4())
    response = upload(client, original, sample["filename"], key)
    assert response.status_code == 202
    ids = response.json()
    sid = ids["session_id"]
    assert upload(client, original, sample["filename"], key).json() == ids
    assert upload(client, b"different", key=key).status_code == 409
    status = wait_job(client, ids["job_id"])
    assert status["status"] == "SUCCEEDED", status
    result = client.get(f"/v1/sessions/{sid}/result").json()
    assert result["segments"]
    assert client.get(f"/v1/sessions/{sid}/audio").content == original
    ranged = client.get(f"/v1/sessions/{sid}/audio", headers={"Range": "bytes=0-31"})
    assert ranged.status_code == 206 and ranged.content == original[:32]
    assert all(
        0 <= s["start_sec"] <= s["end_sec"] <= result["audio"]["duration_sec"] + 0.05
        for s in result["segments"]
    )
    segment = result["segments"][0]
    before = segment["raw_asr_text"]
    patch = {
        "expected_revision": 0,
        "author": "test-operator",
        "reason": "Engineering audit fixture, not a human annotation",
        "segment_id": segment["segment_id"],
        "reviewed_text": "<script>alert(1)</script> пятьдесят",
        "role": "instructor",
    }
    assert client.post(f"/v1/sessions/{sid}/reviews", json=patch).status_code == 200
    assert client.post(f"/v1/sessions/{sid}/reviews", json=patch).status_code == 409
    edited = client.get(f"/v1/sessions/{sid}/result").json()
    assert edited["segments"][0]["raw_asr_text"] == before
    history = client.get(f"/v1/sessions/{sid}/reviews").json()
    assert len(history) == 1 and history[0]["before"]["reviewed_text"] is None
    for fmt in ("json", "csv", "vtt", "srt"):
        exported = client.get(f"/v1/sessions/{sid}/export", params={"format": fmt})
        assert exported.status_code == 200 and exported.content
    with DB() as db:
        assert db.scalar(select(Session).where(Session.id == sid)).revision == 1
    assert client.delete(f"/v1/sessions/{sid}").status_code == 200
    assert client.get(f"/v1/sessions/{sid}/result").status_code == 404
    assert client.get(f"/v1/sessions/{sid}/audio").status_code == 404
    assert not (settings.audio_root / "sessions" / sid / "original").exists()


def test_cookie_auth_csrf_and_xss(client):
    with httpx.Client(base_url=settings.api_url, timeout=10) as browser:
        page = browser.get("/")
        assert page.headers["referrer-policy"] == "same-origin"
        for origin in ("https://evil.invalid", "null"):
            assert browser.post(
                "/login",
                data={"api_key": settings.api_key},
                headers={"Origin": origin},
            ).status_code == 403
        login = browser.post("/login", data={"api_key": settings.api_key},
                             headers={"Origin": settings.api_url.rstrip("/")})
        assert login.status_code == 303
        assert (
            "HttpOnly" in login.headers["set-cookie"]
            and "SameSite=strict" in login.headers["set-cookie"]
        )
        assert settings.api_key not in browser.get("/").text
        assert "script-src 'self'" in browser.get("/").headers["content-security-policy"]
        assert browser.post("/logout").status_code == 403
        csrf = browser.get("/v1/csrf").json()["csrf"]
        assert browser.post("/logout", headers={"X-CSRF-Token": csrf}).status_code == 200


def create_isolated_job():
    identifier = str(uuid.uuid4())
    with DB.begin() as db:
        db.add(
            ProcessingJob(
                id=identifier,
                kind="test",
                idempotency_key=identifier,
                request_hash="f" * 64,
                request_json={},
                config_json={},
            )
        )
    return identifier


def test_duplicate_delivery_lease_recovery_and_fencing():
    jid = create_isolated_job()
    old = claim(jid)[0]
    assert claim(jid) is None
    with DB.begin() as db:
        job = db.get(ProcessingJob, jid)
        job.lease_until = now() - timedelta(seconds=10)
    assert recover_expired() >= 1
    new = claim(jid)
    # API dispatcher may deliver the intentionally invalid test job; either claim is fenced.
    with pytest.raises(SpeechError):
        checkpoint(jid, old)
    assert finish(jid, old, None, SpeechError("FAKE", "obsolete")) is False
    with DB.begin() as db:
        job = db.get(ProcessingJob, jid)
        job.cancel_requested = True
        if new:
            token = new[0]
        else:
            token = job.attempt_token
    if token:
        finish(jid, token, None, SpeechError("CANCELLED", "test completed"))
    with DB() as db:
        attempts = list(db.scalars(select(JobAttempt).where(JobAttempt.job_id == jid)))
        assert any(a.status == "LEASE_EXPIRED" for a in attempts)


def test_cancel_queued_job():
    jid = create_isolated_job()
    with DB.begin() as db:
        db.get(ProcessingJob, jid).cancel_requested = True
    assert claim(jid) is None
    with DB() as db:
        assert db.get(ProcessingJob, jid).status == "CANCELLED"
