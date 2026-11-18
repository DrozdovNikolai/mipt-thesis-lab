"""Failure injection against the real storage layer without filling the owner's disk."""

import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from sqlalchemy import select

from north55_speech.api import app
from north55_speech.core import settings
from north55_speech.db import DB, ProcessingJob, Session

pytestmark = pytest.mark.integration


def test_low_disk_upload_and_byte_limit(monkeypatch):
    key = str(uuid.uuid4())
    headers = {"X-API-Key": settings.api_key, "Idempotency-Key": key}
    metadata = json.dumps({"rights_confirmed": True, "provenance": "storage_failure_fixture"})
    with TestClient(app) as client:
        monkeypatch.setattr(settings, "minimum_free_bytes", 2**60)
        response = client.post(
            "/v1/sessions",
            headers=headers,
            files={"audio": ("a.wav", b"abc")},
            data={"metadata": metadata},
        )
        assert response.status_code == 507
        assert response.json()["error"]["code"] == "DISK_FULL"
        monkeypatch.setattr(settings, "minimum_free_bytes", 0)
        monkeypatch.setattr(settings, "max_upload_bytes", 2)
        assert (
            client.post(
                "/v1/sessions",
                headers=headers,
                files={"audio": ("a.wav", b"abc")},
                data={"metadata": metadata},
            ).status_code
            == 413
        )
    with DB() as db:
        assert db.scalar(select(ProcessingJob).where(ProcessingJob.idempotency_key == key)) is None


def test_concurrent_reviews_use_expected_revision():
    sid = str(uuid.uuid4())
    with DB.begin() as db:
        db.add(
            Session(
                id=sid,
                metadata_json={},
                result={
                    "segments": [
                        {"segment_id": "a", "raw_asr_text": "immutable", "reviewed_text": None}
                    ],
                    "events": [],
                },
            )
        )
    patch = {
        "expected_revision": 0,
        "author": "concurrency-test",
        "reason": "synthetic engineering fixture",
        "segment_id": "a",
        "reviewed_text": "one",
    }

    def review(i):
        return httpx.post(
            settings.api_url + f"/v1/sessions/{sid}/reviews",
            headers={"X-API-Key": settings.api_key},
            json=patch | {"reviewed_text": str(i)},
            timeout=20,
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(review, [1, 2])) == [200, 409]
    assert (
        httpx.delete(
            settings.api_url + f"/v1/sessions/{sid}", headers={"X-API-Key": settings.api_key}
        ).status_code
        == 200
    )


def test_delete_running_fences_late_writes():
    card = json.loads((settings.audio_root / "smoke/provenance.json").read_text())
    audio, rate = sf.read(
        settings.audio_root / "smoke" / card["samples"][0]["filename"], dtype="float32"
    )
    buffer = io.BytesIO()
    sf.write(buffer, np.tile(audio, 20), rate, format="WAV")
    with httpx.Client(
        base_url=settings.api_url, headers={"X-API-Key": settings.api_key}, timeout=30
    ) as client:
        response = client.post(
            "/v1/sessions",
            files={"audio": ("race.wav", buffer.getvalue())},
            data={
                "metadata": json.dumps(
                    {
                        "language": "en",
                        "rights_confirmed": True,
                        "provenance": "CC-BY-4.0 LibriSpeech engineering repetition",
                    }
                )
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 202
        ids = response.json()
        sid = ids["session_id"]
        assert client.delete(f"/v1/sessions/{sid}").status_code == 200
        assert client.get(f"/v1/sessions/{sid}/audio").status_code == 404
    with DB() as db:
        job = db.get(ProcessingJob, ids["job_id"])
        assert job.cancel_requested and job.attempt_token is None
        assert db.get(Session, sid).deleted
