import json

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import Sample, validate_groups, write_manifest
from scripts.materialize_reviewed_training import collect
from scripts.review_dataset import create_app


@pytest.fixture
def sidecar(tmp_path):
    packet, audio = tmp_path/"packet", tmp_path/"audio"
    packet.mkdir()
    audio.mkdir()
    sf.write(audio/"original.wav", np.zeros(16000, dtype=np.float32), 16000)
    sample = Sample(sample_id="a"*32, audio_path="original.wav", audio_sha256=file_hash(audio/"original.wav"),
                    source_dataset="unit_fixture", source_version="1", recording_id="unit-recording", session_id="unit-session",
                    original_utterance_id="unit-original", speaker_ids=["unit-speaker"], language="unknown", scope="unknown",
                    speech_origin="synthetic", duration_sec=1, license_id="test_fixture", provenance="Unit test only, not benchmark data",
                    rights_confirmed=True, split="train", primary=False,
                    annotation_provenance={"source_sample_id":"fixture", "original_start_sec":0})
    validate_groups([sample])
    write_manifest(packet/"train.jsonl", [sample])
    write_manifest(packet/"dev.jsonl", [])
    atomic_json(packet/"drafts"/(sample.sample_id+".json"), {"text":"machine fifty"})
    app = create_app(packet, audio, "k"*32, "s"*32)
    with TestClient(app) as client:
        yield client, packet, audio, sample


def login(client):
    response = client.post("/login", data={"key":"k"*32,"annotator":"Unit test annotator"}, follow_redirects=False)
    assert response.status_code == 303
    return {"X-CSRF-Token": client.get("/api/packet").json()["csrf"]}


def test_native_login_preserves_same_origin_and_session_protection(sidecar):
    client, packet, _, _ = sidecar
    page = client.get("/")
    assert page.headers["referrer-policy"] == "same-origin"
    assert "form-action 'self'" in page.headers["content-security-policy"]
    response = client.post("/login", data={"key": "k"*32, "annotator": "Browser regression fixture"},
                           headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert response.status_code == 303
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/api/packet").json()["actor"] == "Browser regression fixture"
    assert not (packet/"revisions").exists()


@pytest.mark.parametrize("origin", ["null", "https://evil.invalid", "http://testserver:99", "https://testserver"])
def test_login_still_rejects_opaque_and_foreign_origins(sidecar, origin):
    client, packet, _, _ = sidecar
    response = client.post("/login", data={"key": "k"*32, "annotator": "Rejected fixture"},
                           headers={"Origin": origin}, follow_redirects=False)
    assert response.status_code == 403
    assert "annotation_session" not in client.cookies
    assert not (packet/"revisions").exists()


def test_publisher_proposal_does_not_create_human_reference(sidecar):
    client, packet, _, sample = sidecar
    headers = login(client)
    path = packet/"publisher-proposals"/(sample.sample_id+".json")
    atomic_json(path, {"sample_id": sample.sample_id, "split": "train", "source_sample_id": "fixture",
                      "original_start_sec": 0, "target_source_audio_sha256": None, "human_verified": False,
                      "text": "publisher fifty", "reasons": [], "eligible_for_exploratory_training": True})
    assert client.get(f"/api/item/{sample.sample_id}").json()["publisher_proposal_available"]
    response = client.post(f"/api/publisher-proposal/{sample.sample_id}", headers=headers, json={})
    assert response.status_code == 200 and response.json()["human_verified"] is False
    stored = client.get(f"/api/item/{sample.sample_id}").json()
    assert stored["revision"] == 0 and stored["sample"]["reference_text"] is None
    assert stored["sample"]["transcript_status"] == "missing"
    assert not (packet/"revisions").exists()
    assert list((packet/"script-exposure"/sample.sample_id).glob("*.json"))
    broken = json.loads(path.read_text()) | {"split": "test"}
    atomic_json(path, broken)
    assert client.post(f"/api/publisher-proposal/{sample.sample_id}", headers=headers, json={}).status_code == 409


def payload(**changes):
    return {"revision":0,"scope":"read_cockpit","language":"en","transcript":"fifty",
            "entities":[],"labels":["CHECKLIST"],"salient":False,"listened":True,
            "verify_scope":True,"verify_transcript":True,"verify_entities":True,"verify_events":True,**changes}


def test_annotation_requires_auth_csrf_and_actual_listening_attestation(sidecar):
    client, _, _, sample = sidecar
    assert client.get("/api/packet").status_code == 401
    assert client.post("/login",data={"key":"плохой","annotator":"test"}).status_code == 403
    headers = login(client)
    assert client.post(f"/api/review/{sample.sample_id}", json=payload()).status_code == 403
    assert client.post(f"/api/review/{sample.sample_id}", headers=headers,json=payload(listened=False)).status_code == 422


def test_annotation_revision_audit_export_and_original_audio_preserved(sidecar):
    client, packet, audio, sample = sidecar
    headers = login(client)
    before_hash = file_hash(audio/"original.wav")
    response = client.post(f"/api/review/{sample.sample_id}", headers=headers,json=payload())
    assert response.json() == {"saved":True,"revision":1}
    assert client.post(f"/api/review/{sample.sample_id}", headers=headers,json=payload()).status_code == 409
    record = json.loads(next((packet/"revisions"/sample.sample_id).glob("revision-*.json")).read_text())
    assert record["audit"]["actor"] == "Unit test annotator"
    assert record["sample"]["reference_text"] == "fifty"
    assert record["sample"]["events_status"] == "human_verified"
    assert record["sample"]["temporal_status"] == "missing"
    assert record["sample"]["primary"] is False
    assert record["sample"]["audio_sha256"] == before_hash == file_hash(audio/"original.wav")
    exported = json.loads(client.get("/api/export/train").text.strip())
    assert exported["group_id"] == sample.group_id
    assert client.get("/api/export/test").status_code == 422
    assert client.get(f"/api/audio/{sample.sample_id}",headers={"Range":"bytes=0-11"}).status_code == 206


def test_draft_exposure_is_recorded_without_upgrading_annotation(sidecar):
    client, packet, _, sample = sidecar
    headers = login(client)
    assert client.post(f"/api/draft/{sample.sample_id}",headers=headers,json={}).json()["human_verified"] is False
    current = client.get(f"/api/item/{sample.sample_id}").json()["sample"]
    assert current["reference_text"] is None and current["transcript_status"] == "missing"
    assert len(list((packet/"draft-exposure"/sample.sample_id).glob("*.json"))) == 1


def test_script_exposure_has_provenance_and_is_not_gold(sidecar):
    client, packet, _, sample = sidecar
    headers = login(client)
    endpoint = f"/api/script-hint/{sample.sample_id}"
    assert client.post(endpoint, headers=headers, json={}).status_code == 404
    atomic_json(packet/"script-hints"/f"{sample.sample_id}.json", {"human_verified": False, "candidates": []})
    assert client.post(endpoint, headers=headers, json={}).json()["human_verified"] is False
    assert client.post(f"/api/review/{sample.sample_id}", headers=headers, json=payload()).status_code == 200
    result = client.get(f"/api/item/{sample.sample_id}").json()["sample"]
    assert result["annotation_provenance"]["publisher_script_exposed"] is True


def test_training_export_rejects_synthetic_fixture_even_with_review(sidecar):
    client, packet, _, sample = sidecar
    headers = login(client)
    client.post(f"/api/review/{sample.sample_id}", headers=headers, json=payload())
    accepted, pending, _ = collect(packet, "events")
    assert accepted == []
    assert pending[0]["reasons"] == ["unverified_rights_or_human_origin"]


def test_training_export_rejects_atc_and_absent_human_revision(sidecar):
    client, packet, _, sample = sidecar
    assert collect(packet, "asr")[1][0]["reasons"] == ["no_human_revision"]
    headers = login(client)
    client.post(f"/api/review/{sample.sample_id}", headers=headers, json=payload(scope="atc"))
    assert "scope_outside_crew_training" in collect(packet, "asr")[1][0]["reasons"]


def test_training_export_rejects_tampered_revision(sidecar):
    client, packet, _, sample = sidecar
    headers = login(client)
    client.post(f"/api/review/{sample.sample_id}", headers=headers, json=payload())
    path = next((packet/"revisions"/sample.sample_id).glob("*.json"))
    record = json.loads(path.read_text())
    record["sample"]["reference_text"] = "fifteen"
    atomic_json(path, record)
    with pytest.raises(ValueError, match="checksum"):
        collect(packet, "asr")


def test_partial_review_export_keeps_full_packet_groups(sidecar):
    _, packet, audio, sample = sidecar
    # Declared eligibility in a unit fixture only; no actual benchmark is created.
    original = sample.model_copy(update={"speech_origin": "recorded_human", "group_id": None})
    sibling = original.model_copy(update={"sample_id": "b"*32, "original_utterance_id": "unit-next-window", "group_id": None})
    validate_groups([original, sibling])
    full_group = original.group_id
    write_manifest(packet/"train.jsonl", [original, sibling])
    with TestClient(create_app(packet, audio, "k"*32, "s"*32)) as browser:
        headers = login(browser)
        assert browser.post(f"/api/review/{original.sample_id}", headers=headers, json=payload()).status_code == 200
    accepted, pending, _ = collect(packet, "asr")
    assert len(accepted) == 1 and accepted[0].group_id == full_group
    assert pending == [{"id": sibling.sample_id, "split": "train", "reasons": ["no_human_revision"]}]
    # Validating the full source graph still catches tampering in an unreviewed row.
    sibling.group_id = "x"*24
    write_manifest(packet/"train.jsonl", [original, sibling])
    from north55_speech.core import SpeechError
    with pytest.raises(SpeechError, match="Stored group ID"):
        collect(packet, "asr")


@pytest.mark.parametrize("changes", [
    {"audio_path":"../elsewhere"}, {"entities":[{"type":"speed_mention","start_sec":0,"end_sec":1}]},
    {"temporal":[{"start_sec":0,"end_sec":2,"labels":["CHECKLIST"]}]},
    {"labels":["OTHER","CHECKLIST"]}, {"scope":"unknown"}, {"entities":None},
])
def test_invalid_annotations_are_rejected_without_a_revision(sidecar,changes):
    client, packet, _, sample = sidecar
    headers = login(client)
    assert client.post(f"/api/review/{sample.sample_id}",headers=headers,json=payload(**changes)).status_code == 422
    assert not (packet/"revisions").exists()
