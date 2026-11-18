"""Reproducible engineering exercises. Never supplies benchmark acceptance evidence."""

from __future__ import annotations

import io
import json
import time
import uuid
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from north55_speech.cli import wait_job
from north55_speech.core import atomic_json, read_yaml, settings
from north55_speech.schemas import InferenceRequest, PipelineConfig


def create_job(kind: str) -> dict:
    card = json.loads((settings.audio_root / "smoke/provenance.json").read_text())
    sample = card["samples"][0]
    path = settings.audio_root / "smoke" / sample["filename"]
    audio, rate = sf.read(path, dtype="float32")
    if kind == "long":
        audio = np.tile(np.concatenate([audio, np.zeros(rate, dtype=np.float32)]), 30)
    buffer = io.BytesIO()
    sf.write(buffer, audio, rate, format="WAV", subtype="PCM_16")
    with httpx.Client(
        base_url=settings.api_url, headers={"X-API-Key": settings.api_key}, timeout=30
    ) as client:
        result = client.post(
            "/v1/sessions",
            files={"audio": ("engineering.wav", buffer.getvalue())},
            data={
                "metadata": json.dumps(
                    {
                        "language": "en",
                        "rights_confirmed": True,
                        "provenance": "LibriSpeech CC-BY-4.0 repeated human engineering control; not benchmark",
                    }
                )
            },
            headers={"Idempotency-Key": "selftest-" + str(uuid.uuid4())},
        )
        result.raise_for_status()
        ids = result.json()
    atomic_json(settings.report_root / f"selftest-{kind}-job.json", ids)
    return ids


def wait_for_job(kind: str) -> dict:
    ids = json.loads((settings.report_root / f"selftest-{kind}-job.json").read_text())
    with httpx.Client(
        base_url=settings.api_url, headers={"X-API-Key": settings.api_key}, timeout=30
    ) as client:
        status = wait_job(client, ids["job_id"], timeout=900)
        result = (
            client.get(f"/v1/sessions/{ids['session_id']}/result").json()
            if status["status"] == "SUCCEEDED"
            else None
        )
    report = {
        "kind": "engineering_recovery_control",
        "job": status,
        "result": result,
        "verification": "PASS" if status["status"] == "SUCCEEDED" else "FAIL",
        "quality_evidence": False,
    }
    atomic_json(settings.report_root / f"selftest-{kind}-result.json", report)
    return {"job": status, "verification": report["verification"]}


def wait_running(kind: str) -> dict:
    ids = json.loads((settings.report_root / f"selftest-{kind}-job.json").read_text())
    with httpx.Client(
        base_url=settings.api_url, headers={"X-API-Key": settings.api_key}, timeout=30
    ) as client:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            response = client.get(f"/v1/jobs/{ids['job_id']}")
            response.raise_for_status()
            status = response.json()
            if status["status"] == "RUNNING" and status["stage"] == "asr":
                return status
            if status["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                raise RuntimeError("Job completed before interruption point")
            time.sleep(0.2)
    raise RuntimeError("Job did not enter ASR in the expected time")


def pipeline_stages() -> dict:
    """Exercise actual VAD, denoise, hints, mixed and bounded re-decode on a human control.

    No WER selection or cockpit benchmark claim is made from these fixtures.
    """
    from north55_speech.pipeline import run_pipeline

    card = json.loads((settings.audio_root / "smoke/provenance.json").read_text())
    sample = card["samples"][0]
    request = InferenceRequest(
        sample_id="human-engineering-control",
        audio_locator="smoke/" + sample["filename"],
        audio_sha256=sample["sha256"],
        language="en",
    )
    baseline = PipelineConfig.model_validate(read_yaml(Path("configs/baseline.yaml")))
    baseline.device, baseline.compute_type = settings.device, settings.compute_type
    variants = [
        ("baseline", baseline, request),
        (
            "vad_hints_denoise_redecode",
            PipelineConfig.model_validate(
                baseline.model_dump()
                | {
                    "name": "engineering_stages",
                    "vad": {"enabled": True},
                    "denoise": {"enabled": True},
                    "hotwords": "checklist, flaps, landing gear",
                    "glossary_version": "glossary_en_v1",
                    "redecode": True,
                    "redecode_logprob_threshold": 0,
                }
            ),
            request,
        ),
        ("mixed", baseline.model_copy(), request.model_copy(update={"language": "mixed"})),
        ("ru_input_contract", baseline.model_copy(), request.model_copy(update={"language": "ru"})),
    ]
    outputs = {}
    for name, config, req in variants:
        result = run_pipeline(
            req, config, settings.artifact_root / "selftest" / name, lambda stage, p: None
        )
        outputs[name] = {"status": "EXECUTED", "language_mode": req.language, "result": result}
    report = {
        "kind": "engineering_stage_execution_only",
        "quality_evidence": False,
        "language_caveat": "RU mode here processes EN control audio; it does not validate RU recognition",
        "variants": outputs,
    }
    atomic_json(settings.report_root / "pipeline-stage-smoke.json", report)
    return {"executed_variants": list(outputs), "quality_evidence": False}
