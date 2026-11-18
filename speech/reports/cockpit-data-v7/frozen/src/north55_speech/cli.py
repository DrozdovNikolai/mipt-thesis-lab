from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import typer

from north55_speech.core import SpeechError, atomic_json, file_hash, read_yaml, settings

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
assets_app = typer.Typer()
datasets_app = typer.Typer()
benchmark_app = typer.Typer()
train_app = typer.Typer()
evaluate_app = typer.Typer()
selftest_app = typer.Typer()
app.add_typer(assets_app, name="assets")
app.add_typer(datasets_app, name="datasets")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(train_app, name="train")
app.add_typer(evaluate_app, name="evaluate")
app.add_typer(selftest_app, name="selftest")


def main():
    from pydantic import ValidationError

    try:
        app()
    except SpeechError as error:
        blocked = error.code in {
            "MODEL_NOT_AVAILABLE",
            "GPU_NOT_AVAILABLE",
            "CLASSIFIER_NOT_AVAILABLE",
            "TRAINING_DEPENDENCY_MISSING",
            "EVALUATOR_REQUIRED",
        } or error.code.startswith("MISSING_")
        emit({"status": "BLOCKED" if blocked else "FAIL", "error": error.as_dict()})
        raise SystemExit(
            5 if blocked else 3 if error.code.startswith("PROMOTION_") else 2
        ) from error
    except (ValidationError, ValueError) as error:
        emit(
            {
                "status": "FAIL",
                "error": {"code": "INVALID_CONFIGURATION", "type": type(error).__name__},
            }
        )
        raise SystemExit(2) from error
    except FileNotFoundError as error:
        emit({"status": "BLOCKED", "error": {"code": "FILE_NOT_AVAILABLE", "path": error.filename}})
        raise SystemExit(5) from error


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


@assets_app.command("fetch")
def assets_fetch(preset: str = "cpu-demo", smoke_audio: bool = True):
    from north55_speech.assets import fetch_model, fetch_smoke

    if preset != "cpu-demo":
        raise typer.BadParameter(
            "Supported preset: cpu-demo. Use assets fetch-model for explicit revisions."
        )
    model = fetch_model()
    emit({"model": model["model"], "revision": model["revision"], "files": model["files"]})
    if smoke_audio:
        card = fetch_smoke()
        emit(
            {"smoke_audio": card["source"], "samples": len(card["samples"]), "scope": card["scope"]}
        )


@assets_app.command("fetch-model")
def assets_fetch_model(model: str, repo: str, revision: str):
    from north55_speech.assets import fetch_model

    emit(fetch_model(model, repo, revision))


@assets_app.command("fetch-snapshot")
def assets_snapshot(repo: str, revision: str, local_name: str, accepted_terms: bool = False):
    from north55_speech.assets import fetch_snapshot

    result = fetch_snapshot(repo, revision, local_name, accepted_terms)
    emit({"repo": result["repo"], "revision": result["revision"], "files": len(result["files"])})


@app.command()
def doctor():
    from sqlalchemy import text

    from north55_speech.asr import local_model_manifest
    from north55_speech.db import engine
    from north55_speech.jobs import celery_app

    report: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "checks": {},
        "gpu_inference_verified": False,
        "versions": {
            name: importlib.metadata.version(name)
            for name in [
                "fastapi",
                "celery",
                "sqlalchemy",
                "faster-whisper",
                "ctranslate2",
                "jiwer",
            ]
        },
    }
    try:
        with engine.connect() as c:
            report["checks"]["migration"] = c.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
    except Exception as e:
        report["checks"]["database"] = type(e).__name__
    try:
        with celery_app.connection_for_write() as c:
            c.ensure_connection(max_retries=0)
            report["checks"]["broker"] = "available"
    except Exception as e:
        report["checks"]["broker"] = type(e).__name__
    report["checks"]["ffmpeg"] = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True
    ).stdout.splitlines()[0]
    report["checks"]["volumes"] = {
        str(p): {"exists": p.exists(), "free_bytes": shutil.disk_usage(p).free}
        for p in (settings.audio_root, settings.model_root, settings.artifact_root)
    }
    try:
        manifest = local_model_manifest("small")
        report["checks"]["model"] = {
            "status": "available",
            "revision": manifest["revision"],
            "files_verified": all(
                file_hash(settings.model_root / "small" / p) == h
                for p, h in manifest["files"].items()
            ),
        }
    except SpeechError as e:
        report["checks"]["model"] = e.as_dict()
    import ctranslate2

    report["gpu_visible_count"] = ctranslate2.get_cuda_device_count()
    report["offline_ready"] = (
        report["checks"].get("model", {}).get("files_verified", False)
        and report["checks"].get("broker") == "available"
        and report["checks"].get("migration") == "0001"
    )
    atomic_json(settings.report_root / "doctor.json", report)
    emit(report)
    if not report["offline_ready"]:
        raise typer.Exit(5)


def wait_job(client, job_id: str, timeout: float = 600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/v1/jobs/{job_id}")
        response.raise_for_status()
        status = response.json()
        if status["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return status
        time.sleep(0.5)
    raise SpeechError("JOB_TIMEOUT", "Job exceeded waiting budget")


@app.command()
def demo(real_asr: bool = False):
    if not real_asr:
        emit({"status": "BLOCKED", "reason": "Use --real-asr; there is no mock demo backend"})
        raise typer.Exit(5)
    card_path = settings.audio_root / "smoke" / "provenance.json"
    if not card_path.exists():
        emit({"status": "BLOCKED", "reason": "Run assets fetch --preset cpu-demo first"})
        raise typer.Exit(5)
    card = json.loads(card_path.read_text())
    sample = card["samples"][0]
    source = settings.audio_root / "smoke" / sample["filename"]
    metadata = {
        "language": "en",
        "rights_confirmed": True,
        "provenance": "LibriSpeech CC-BY-4.0 engineering control",
    }
    with httpx.Client(
        base_url=settings.api_url, headers={"X-API-Key": settings.api_key}, timeout=30
    ) as client:
        with source.open("rb") as audio:
            response = client.post(
                "/v1/sessions",
                files={"audio": (sample["filename"], audio)},
                data={"metadata": json.dumps(metadata)},
                headers={"Idempotency-Key": "demo-" + str(time.time_ns())},
            )
        response.raise_for_status()
        ids = response.json()
        status = wait_job(client, ids["job_id"])
        report = {
            "kind": "real_human_asr_engineering_smoke",
            "provenance": card,
            "ids": ids,
            "job": status,
            "quality_evidence": False,
        }
        if status["status"] == "SUCCEEDED":
            result = client.get(f"/v1/sessions/{ids['session_id']}/result").json()
            from north55_speech.metrics import edit_counts

            hypothesis = " ".join(s["raw_asr_text"] for s in result["segments"])
            report.update(
                result=result,
                technical_control_edit_counts=edit_counts(sample["reference_text"], hypothesis),
            )
            if not hypothesis.strip():
                report["verification"] = "FAIL_EMPTY_TRANSCRIPT"
            else:
                report["verification"] = "PASS"
        else:
            report["verification"] = "FAIL"
        atomic_json(settings.report_root / "real-asr-smoke.json", report)
        emit({"job": status, "verification": report["verification"], "quality_evidence": False})
        if report["verification"] != "PASS":
            raise typer.Exit(1)


@datasets_app.command("import-local")
def datasets_import(manifest: Path, output: Path = Path("/data/curated/manifest.jsonl")):
    from north55_speech.datasets import import_local

    emit(import_local(manifest, settings.input_root, output))


@datasets_app.command("validate")
def datasets_validate(manifest: Path):
    from north55_speech.datasets import load_manifest, validate_groups

    emit(validate_groups(load_manifest(manifest)))


@datasets_app.command("inspect")
def datasets_inspect(config: Path = Path("configs/datasets.yaml")):
    emit(read_yaml(config))


@datasets_app.command("annotation-template")
def annotations_export(manifest: Path, output: Path):
    from north55_speech.datasets import annotation_template

    annotation_template(manifest, output)
    emit({"written": output, "human_verification": False})


@datasets_app.command("import-annotations")
def annotations_import(manifest: Path, annotations: Path, output: Path):
    from north55_speech.datasets import import_annotations

    import_annotations(manifest, annotations, output)
    emit({"written": output})


@app.command("acceptance-schema")
def schema(output: Path = Path("/reports/acceptance.schema.json")):
    from north55_speech.gates import acceptance_schema

    atomic_json(output, acceptance_schema(Path("configs/acceptance.yaml")))
    emit({"written": output})


@train_app.command("events")
def train_events_command(config: Path = Path("configs/events_train.yaml")):
    from north55_speech.training import train_events

    try:
        emit(train_events(read_yaml(config)))
    except SpeechError as e:
        report = {"status": "BLOCKED", "error": e.as_dict(), "executed": False}
        atomic_json(settings.report_root / "events-training-status.json", report)
        emit(report)
        raise typer.Exit(5) from e


@train_app.command("asr")
def train_asr_command(config: Path = Path("configs/asr_lora.yaml")):
    from north55_speech.lora import train_asr

    try:
        emit(train_asr(read_yaml(config)))
    except SpeechError as e:
        report = {"status": "BLOCKED", "error": e.as_dict(), "executed": False}
        atomic_json(settings.report_root / "asr-training-status.json", report)
        emit(report)
        raise typer.Exit(5) from e


@evaluate_app.command("events")
def evaluate_events_command(
    manifest: Path, model: str, output: Path = Path("/reports/event-evaluation.json")
):
    from north55_speech.datasets import load_manifest
    from north55_speech.training import TrainedEventClassifier, evaluate_events

    samples = load_manifest(manifest)
    if any(s.split == "test" for s in samples) and not settings.evaluator:
        raise typer.BadParameter("Test annotations may only be opened in evaluator")
    report = evaluate_events(samples, TrainedEventClassifier.load(model))
    atomic_json(output, report)
    emit(report)


@benchmark_app.command("prepare")
def benchmark_prepare(config: Path = Path("configs/datasets.yaml")):
    from north55_speech.datasets import prepare_splits

    data = read_yaml(config)
    emit(prepare_splits(Path(data["manifest"]), Path(data["split_output"])))


@benchmark_app.command("dev")
def benchmark_dev(config: Path = Path("configs/search.yaml")):
    from north55_speech.benchmark import dev_search

    try:
        result = dev_search(read_yaml(config))
        emit(result)
        if result["status"] == "NEEDS_MORE_DATA":
            raise typer.Exit(4)
    except SpeechError as e:
        report = {
            "status": "NEEDS_MORE_DATA" if e.code.startswith("MISSING_") else "FAIL",
            "error": e.as_dict(),
            "executed": False,
        }
        atomic_json(settings.report_root / "dev-search-status.json", report)
        emit(report)
        raise typer.Exit(4 if report["status"] == "NEEDS_MORE_DATA" else 2) from e


@benchmark_app.command("freeze-baseline")
def benchmark_baseline(
    config: Path = Path("configs/baseline.yaml"),
    output: Path = Path("/artifacts/baseline.lock.json"),
):
    from north55_speech.benchmark import freeze_baseline
    from north55_speech.schemas import PipelineConfig

    cfg = PipelineConfig.model_validate(read_yaml(config))
    cfg.device, cfg.compute_type = settings.device, settings.compute_type
    emit(freeze_baseline(cfg, output))


@benchmark_app.command("freeze")
def benchmark_freeze(
    acceptance: Path = Path("configs/acceptance.yaml"),
    config: Path = Path("configs/freeze.yaml"),
    output: Path = Path("/artifacts/selection.lock.json"),
):
    from north55_speech.benchmark import freeze_selection

    emit(freeze_selection(read_yaml(config), acceptance, output))


@benchmark_app.command("test")
def benchmark_test(
    selection: Path = Path("/artifacts/selection.lock.json"),
    references: Path = Path("/sealed/test.jsonl"),
    inference_manifest: Path = Path("/data/test-inference/test.jsonl"),
):
    from north55_speech.benchmark import final_test
    from north55_speech.gates import EXIT_CODES

    result = final_test(selection, references, inference_manifest)
    emit(result)
    statuses = [
        result["gates"][key]["status"]
        for key in ("engineering_gate", "asr_quality_gate", "nlp_quality_gate")
    ]
    raise typer.Exit(max(EXIT_CODES[s] for s in statuses))


@benchmark_app.command("report")
def benchmark_report(run_id: str):
    from north55_speech.core import confined

    directory = confined(settings.report_root / "runs", run_id, must_exist=False)
    path = directory / "report.md"
    if not path.is_file():
        raise typer.BadParameter("No executed run with this ID")
    typer.echo(path.read_text(encoding="utf-8"))


@app.command("promote")
def promote_command(run_id: str):
    from north55_speech.benchmark import code_hash, pipeline_model_hash, scorer_hash
    from north55_speech.core import confined
    from north55_speech.gates import promote

    path = confined(settings.report_root / "runs", run_id, must_exist=False)
    if not settings.evaluator:
        raise typer.BadParameter(
            "Promotion runs in evaluator to verify sealed data hashes without mounting answers into runtime"
        )
    from north55_speech.core import digest
    from north55_speech.release import verify_model_files
    from north55_speech.schemas import PipelineConfig

    selection = json.loads((path / "selection.lock.json").read_text())
    verify_model_files(selection["candidate"]["model"])
    hashes = {
        "code": code_hash(),
        "scorer": scorer_hash(),
        "acceptance": file_hash(Path("configs/acceptance.yaml")),
        "model": pipeline_model_hash(PipelineConfig.model_validate(selection["candidate"])),
        "config": digest(selection["candidate"]),
        "data": digest(
            {
                "inference": file_hash(Path("/data/test-inference/test.jsonl")),
                "sealed": file_hash(Path("/sealed/test.jsonl")),
            }
        ),
    }
    emit(promote(path, settings.artifact_root / "release.json", hashes))


@selftest_app.command("create-job")
def selftest_create(kind: str = "short"):
    from north55_speech.selftest import create_job

    emit(create_job(kind))


@selftest_app.command("wait-job")
def selftest_wait(kind: str = "short"):
    from north55_speech.selftest import wait_for_job

    result = wait_for_job(kind)
    emit(result)
    if result["verification"] != "PASS":
        raise typer.Exit(1)


@selftest_app.command("wait-running")
def selftest_running(kind: str = "long"):
    from north55_speech.selftest import wait_running

    emit(wait_running(kind))


@selftest_app.command("pipeline-stages")
def selftest_stages():
    from north55_speech.selftest import pipeline_stages

    emit(pipeline_stages())


@datasets_app.command("augment")
def datasets_augment(
    manifest: Path, noise_manifest: Path, output: Path, snr_db: float = 10, seed: int = 55
):
    from north55_speech.augmentation import augment

    emit(augment(manifest, noise_manifest, output, snr_db, seed))


@datasets_app.command("publish-partitions")
def datasets_publish(manifest: Path, output: Path):
    from north55_speech.datasets import load_manifest, publish_partitions

    emit(publish_partitions(load_manifest(manifest), output))


@evaluate_app.command("diarization")
def evaluate_diarization(
    reference: Path,
    prediction: Path,
    output: Path,
    collar: float = 0.25,
    skip_overlap: bool = False,
):
    from north55_speech.metrics import diarization_score

    gold = json.loads(reference.read_text())
    if gold.get("annotation_status") != "human_verified":
        raise typer.BadParameter("Human speaker/time labels required")
    if gold.get("split") == "test" and not settings.evaluator:
        raise typer.BadParameter("Test scoring is evaluator-only")
    pred = json.loads(prediction.read_text())
    result = diarization_score(gold["turns"], pred["turns"], collar, skip_overlap)
    atomic_json(output, result)
    emit(result)
