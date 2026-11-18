from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select

from north55_speech.asr import local_model_manifest
from north55_speech.core import (
    SpeechError,
    atomic_json,
    digest,
    file_hash,
    now,
    read_yaml,
    settings,
)
from north55_speech.datasets import Sample, inference_projection, load_manifest
from north55_speech.db import DB, BenchmarkRun, OutboxEvent, ProcessingJob, uid
from north55_speech.gates import asr_gate, gate, load_acceptance, nlp_gate
from north55_speech.metrics import (
    apply_scoring_masks,
    canonical_normalizer_v1,
    corpus_counts,
    edit_counts,
    entity_score,
    paired_cluster_bootstrap,
)
from north55_speech.reporting import write_report
from north55_speech.schemas import PipelineConfig


def code_hash() -> str:
    root = Path(__file__).parent
    return digest(
        {
            str(p.relative_to(root)): file_hash(p)
            for p in sorted(root.rglob("*"))
            if p.is_file() and p.suffix in {".py", ".html", ".js", ".css"}
        }
    )


def scorer_hash() -> str:
    root = Path(__file__).parent
    return digest(
        {
            name: file_hash(root / name)
            for name in ("metrics.py", "gates.py", "benchmark.py", "datasets.py")
        }
    )


def pipeline_model_hash(config: PipelineConfig) -> str:
    """Freeze ASR weights and every trained NLP weight/threshold together."""
    classifier = None
    from north55_speech.release import verify_model_files

    if config.classifier == "tfidf_logreg_v1":
        from north55_speech.training import TrainedEventClassifier

        classifier = TrainedEventClassifier.load(config.classifier_artifact).manifest
    return digest({"asr": verify_model_files(config.model), "classifier": classifier})


def freeze_baseline(config: PipelineConfig, destination: Path) -> dict:
    if config.name != "baseline" or config.beam_size != 5 or config.temperature != 0:
        raise SpeechError(
            "INVALID_BASELINE",
            "Baseline must retain beam=5, temperature=0 and baseline stage policy",
        )
    manifest = {
        "config": config.model_dump(),
        "model": local_model_manifest(config.model),
        "code_hash": code_hash(),
        "scorer_hash": scorer_hash(),
        "created_at": now().isoformat(),
        "common_audio_preparation": "ffmpeg_pcm16k_v1",
        "hardware": platform.platform(),
        "normalizer": "lexical_normalizer_v1",
        "status": "FROZEN_BASELINE_NOT_QUALITY_PASS",
    }
    if destination.exists():
        existing = json.loads(destination.read_text())
        for key in ("config", "model", "code_hash", "scorer_hash"):
            if existing[key] != manifest[key]:
                raise SpeechError(
                    "BASELINE_FROZEN", "Existing baseline differs; create a new protocol directory"
                )
        return existing
    atomic_json(destination, manifest)
    return manifest


def assert_same_model(baseline: PipelineConfig, candidate: PipelineConfig) -> None:
    for key in (
        "model",
        "compute_type",
        "device",
        "task",
        "beam_size",
        "temperature",
        "word_timestamps",
    ):
        if getattr(baseline, key) != getattr(candidate, key):
            raise SpeechError("UNFAIR_COMPARISON", f"Baseline and candidate differ in {key}")


def infer_samples(samples: list[Sample], config: PipelineConfig, run_id: str, timeout=1800) -> dict:
    """Only sanitized payloads go to the ordinary worker. No Docker socket or references."""
    mapping = {}
    with DB.begin() as db:
        for sample in samples:
            request = inference_projection(sample)
            key = digest({"run": run_id, "config": config.config_hash, "sample": request.sample_id})
            existing = db.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.owner == "evaluator", ProcessingJob.idempotency_key == key
                )
            )
            if existing:
                mapping[sample.sample_id] = existing.id
                continue
            identifier = uid()
            db.add(
                ProcessingJob(
                    id=identifier,
                    owner="evaluator",
                    kind="benchmark",
                    idempotency_key=key,
                    request_hash=digest(request.model_dump()),
                    request_json=request.model_dump(),
                    config_json=config.model_dump(),
                )
            )
            db.flush()
            db.add(OutboxEvent(job_id=identifier))
            mapping[sample.sample_id] = identifier
    deadline = time.monotonic() + timeout
    predictions: dict[str, Any] = {}
    while len(predictions) < len(mapping) and time.monotonic() < deadline:
        with DB() as db:
            for sample_id, job_id in mapping.items():
                if sample_id in predictions:
                    continue
                job = db.get(ProcessingJob, job_id)
                if job is None:
                    raise SpeechError("JOB_MISSING", "Frozen inference job disappeared")
                if job.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    predictions[sample_id] = {
                        "status": job.status,
                        "result": job.result,
                        "error": job.error,
                        "job_id": job_id,
                    }
        if len(predictions) < len(mapping):
            time.sleep(0.5)
    for sample_id, job_id in mapping.items():
        if sample_id not in predictions:
            predictions[sample_id] = {
                "status": "TIMEOUT",
                "result": None,
                "job_id": job_id,
                "error": {"code": "INFERENCE_TIMEOUT"},
            }
            with DB.begin() as db:
                job = db.get(ProcessingJob, job_id)
                if job is not None:
                    job.cancel_requested = True
    return predictions


def summarize(
    samples: list[Sample], baseline: dict, candidate: dict, acceptance: dict
) -> tuple[dict, list[dict]]:
    rows, errors = [], []
    if set(baseline) != {s.sample_id for s in samples} or set(candidate) != {
        s.sample_id for s in samples
    }:
        errors.append("prediction_set_does_not_equal_all_frozen_samples")
    primary = [s for s in samples if s.primary and s.scope != "non_speech"]
    permitted = acceptance["scope"]["permitted_primary_scopes"]
    for sample in primary:
        if (
            sample.scope not in permitted
            or sample.speech_origin != "recorded_human"
            or not sample.scope_verified
        ):
            errors.append("primary_scope_or_human_origin_unverified:" + sample.sample_id)
        if sample.language not in acceptance["scope"]["primary_language_scope"]:
            errors.append("primary_language_outside_frozen_scope:" + sample.sample_id)
    for sample in samples:
        if not sample.decoded_audio_sha256 or not sample.group_id:
            errors.append("missing_decoded_checksum_or_group:" + sample.sample_id)
        if sample.clean_control and (
            sample.speech_origin != "recorded_human"
            or sample.augmentation is not None
            or sample.scope in {"atc", "unknown"}
            or not sample.scope_verified
        ):
            errors.append("invalid_clean_control:" + sample.sample_id)
        if sample.scope == "non_speech" and (
            sample.reference_text != "" or not sample.scope_verified
        ):
            errors.append("unverified_non_speech_control:" + sample.sample_id)
    if len({s.original_utterance_id for s in primary}) != len(primary):
        errors.append("multiple_primary_variants_per_original")
    for sample in samples:
        values: dict[str, Any] = {
            "sample_id": sample.sample_id,
            "group_id": sample.group_id,
            "language": sample.language,
            "condition": sample.acoustic_condition,
            "duration_sec": sample.duration_sec,
            "primary": sample in primary,
            "clean_control": sample.clean_control,
            "non_speech": sample.scope == "non_speech",
        }
        for name, predictions in (("baseline", baseline), ("candidate", candidate)):
            pred = predictions.get(sample.sample_id, {"status": "MISSING", "result": None})
            result = pred.get("result") or {}
            hypothesis = (
                " ".join(s["raw_asr_text"] for s in result.get("segments", []))
                if pred["status"] == "SUCCEEDED"
                else ""
            )
            reference = sample.reference_text or ""
            if sample.unintelligible:
                reference, hypothesis = apply_scoring_masks(
                    reference, result.get("segments", []), sample.unintelligible
                )
            values[name] = edit_counts(reference, hypothesis)
            values[name]["canonical"] = edit_counts(
                canonical_normalizer_v1(reference), canonical_normalizer_v1(hypothesis)
            )
            values[name]["hypothesis"] = hypothesis
            values[name]["runtime_failure"] = pred["status"] != "SUCCEEDED"
            values[name]["timing"] = result.get("timing", {})

            def outside_mask(entity, masks=sample.unintelligible):
                midpoint = (entity.get("start_sec", 0) + entity.get("end_sec", 0)) / 2
                return not any(m["start_sec"] <= midpoint < m["end_sec"] for m in masks)

            values[name]["entities"] = entity_score(
                [e for e in sample.critical_entities or [] if outside_mask(e)],
                [
                    e
                    for event in result.get("events", [])
                    for e in event["entities"]
                    if outside_mask(e)
                ],
            )
        rows.append(values)
    selected = [r for r in rows if r["primary"]]
    b = corpus_counts([r["baseline"] for r in selected])
    c = corpus_counts([r["candidate"] for r in selected])

    def difference(subset, metric="wer"):
        if not subset:
            return None
        if metric == "wer":
            left, right = (
                corpus_counts([r[k] for r in subset])["wer_lexical_corpus"]
                for k in ("baseline", "candidate")
            )
            return right - left if left is not None and right is not None else None
        totals = {}
        for k in ("baseline", "candidate"):
            tp, sub, delete, insert = (
                sum(r[k]["entities"][key] for r in subset)
                for key in ("tp", "C_sub", "C_del", "C_ins")
            )
            if metric == "f1":
                totals[k] = (
                    2 * tp / (2 * tp + 2 * sub + delete + insert)
                    if 2 * tp + 2 * sub + delete + insert
                    else None
                )
            else:
                totals[k] = (
                    (sub + delete + insert) / (tp + sub + delete) if tp + sub + delete else None
                )
        left, right = totals["baseline"], totals["candidate"]
        return right - left if left is not None and right is not None else None

    noise_rows = [r for r in rows if r["non_speech"]]
    minutes = sum(r["duration_sec"] for r in noise_rows) / 60
    evidence = {
        "independent_groups": len({s.group_id for s in primary if s.group_id}),
        "distinct_original_human_utterances": len(
            {s.original_utterance_id for s in primary if s.speech_origin == "recorded_human"}
        ),
        "reference_words": b["N"],
        "human_verified_critical_entity_occurrences": sum(
            len(s.critical_entities or []) for s in primary if s.entities_status == "human_verified"
        ),
        "clean_control_utterances": len(
            {s.original_utterance_id for s in samples if s.clean_control}
        ),
        "non_speech_control_minutes": minutes,
    }
    uncertainty = acceptance["asr_quality_gate"]["uncertainty"]
    report = {
        "executed": bool(samples),
        "integrity_errors": sorted(set(errors)),
        "evidence": evidence,
        "missing_annotations": [
            "unverified_transcript:" + s.sample_id
            for s in samples
            if s.transcript_status != "human_verified"
        ]
        + [
            "unverified_entities:" + s.sample_id
            for s in primary
            if s.entities_status != "human_verified"
        ]
        + [
            "missing_human_annotation_provenance:" + s.sample_id
            for s in samples
            if not s.annotation_provenance.get("annotator")
            or not s.annotation_provenance.get("reviewed_audio")
        ],
        "baseline_wer": b["wer_lexical_corpus"],
        "candidate_wer": c["wer_lexical_corpus"],
        "baseline_counts": b,
        "candidate_counts": c,
        "baseline_wer_canonical": corpus_counts([r["baseline"]["canonical"] for r in selected])[
            "wer_lexical_corpus"
        ],
        "candidate_wer_canonical": corpus_counts([r["candidate"]["canonical"] for r in selected])[
            "wer_lexical_corpus"
        ],
        "delta_ci": paired_cluster_bootstrap(
            selected, uncertainty["resamples"], uncertainty["seed"], uncertainty["confidence_level"]
        ),
        "critical_entity_f1_delta": difference(selected, "f1"),
        "critical_entity_error_rate_delta": difference(selected, "error_rate"),
        "clean_wer_increase": difference([r for r in rows if r["clean_control"]]),
        "non_speech_inserted_words_per_minute_delta": sum(
            r["candidate"]["I"] - r["baseline"]["I"] for r in noise_rows
        )
        / minutes
        if minutes
        else None,
        "unhandled_runtime_failures": sum(
            r[k]["runtime_failure"] for r in rows for k in ("baseline", "candidate")
        ),
        "strata": {},
    }
    for language in acceptance["scope"]["primary_language_scope"]:
        report[f"language_{language}_wer_increase"] = difference(
            [r for r in rows if r["language"] == language and not r["non_speech"]]
        )
    import numpy as np

    report["runtime"] = {}
    for system in ("baseline", "candidate"):
        runtime: dict[str, Any] = {
            "failure_rate": sum(r[system]["runtime_failure"] for r in rows) / len(rows)
            if rows
            else None
        }
        for metric in ("end_to_end_rtf", "asr_rtf"):
            observed = [r[system]["timing"][metric] for r in rows if metric in r[system]["timing"]]
            runtime[metric] = {
                "measured": len(observed),
                "p50": float(np.percentile(observed, 50)) if observed else None,
                "p95": float(np.percentile(observed, 95)) if observed else None,
            }
        report["runtime"][system] = runtime
    for key in ("language", "condition"):
        for value in sorted({r[key] for r in rows}):
            subset = [r for r in rows if r[key] == value]
            report["strata"][f"{key}:{value}"] = {
                "utterances": len(subset),
                "groups": len({r["group_id"] for r in subset}),
                **{
                    name: corpus_counts([r[name] for r in subset])
                    for name in ("baseline", "candidate")
                },
            }
    return report, rows


def dev_search(config: dict) -> dict:
    from north55_speech.datasets import verify_partition_proof

    path = Path(config["dev_manifest"])
    if not path.is_file():
        raise SpeechError(
            "MISSING_DEV_DATA", "No admitted dev manifest; acquire/annotate/split lawful recordings"
        )
    samples = load_manifest(path)
    proof = json.loads(Path(config["partition_proof"]).read_text())
    verify_partition_proof(proof, samples, "dev")
    access_log = settings.report_root / "test_access_log.jsonl"
    if access_log.exists() and any(
        json.loads(line)["sealed_sha256"] == proof["test_references_sha256"]
        for line in access_log.read_text().splitlines()
        if line
    ):
        raise SpeechError(
            "TEST_ALREADY_OPENED", "New dev selection requires a new independent final test cohort"
        )
    if not samples or any(s.split != "dev" for s in samples):
        raise SpeechError(
            "TEST_ACCESS_FORBIDDEN", "Dev search accepts a nonempty dev-only manifest"
        )
    if any(s.reference_text is None or s.transcript_status != "human_verified" for s in samples):
        raise SpeechError(
            "MISSING_HUMAN_DEV_TRANSCRIPTS", "Dev selection requires verified reference transcripts"
        )
    acceptance = load_acceptance(Path(config.get("acceptance", "configs/acceptance.yaml")))
    trials = config["trials"]
    budget = min(config.get("max_configurations", 16), acceptance["search"]["max_configurations"])
    if len(trials) > budget:
        raise SpeechError("SEARCH_BUDGET", "Configured trials exceed the frozen development budget")
    baseline = PipelineConfig.model_validate(read_yaml(Path(config["baseline"])))
    baseline.device, baseline.compute_type = settings.device, settings.compute_type
    run_id = "dev-" + uid()
    directory = settings.report_root / "runs" / run_id
    directory.mkdir(parents=True)
    freeze_baseline(baseline, directory / "baseline.lock.json")
    predictions = infer_samples(samples, baseline, run_id + "-A0")
    atomic_json(directory / "A0-predictions.json", predictions)
    all_trials = []
    for trial in trials:
        candidate = PipelineConfig.model_validate(
            baseline.model_dump() | {"name": trial["id"]} | trial.get("overrides", {})
        )
        assert_same_model(baseline, candidate)
        output = (
            predictions
            if trial["id"] == "A0"
            else infer_samples(samples, candidate, run_id + "-" + trial["id"])
        )
        atomic_json(directory / (trial["id"] + "-predictions.json"), output)
        summary, rows = summarize(samples, predictions, output, acceptance)
        guard_names = [
            "critical_entity_f1_delta",
            "critical_entity_error_rate_delta",
            "clean_wer_increase",
            "non_speech_inserted_words_per_minute_delta",
        ]
        missing = [key for key in guard_names if summary[key] is None]
        guard_ok = (
            not summary["integrity_errors"]
            and not summary["missing_annotations"]
            and not missing
            and summary["critical_entity_f1_delta"] >= 0
            and summary["critical_entity_error_rate_delta"] <= 0
            and summary["clean_wer_increase"] <= 0.01
            and summary["non_speech_inserted_words_per_minute_delta"] <= 0
            and summary["unhandled_runtime_failures"] == 0
        )
        seconds = sum(row["candidate"]["timing"].get("end_to_end_sec", 0) for row in rows)
        stages = sum(
            [
                candidate.vad.enabled,
                candidate.denoise.enabled,
                bool(candidate.hotwords),
                candidate.redecode,
            ]
        )
        record = {
            "id": trial["id"],
            "config": candidate.model_dump(),
            "summary": summary,
            "guardrails_satisfied": guard_ok,
            "missing_guardrails": missing,
            "end_to_end_rtf": seconds / sum(s.duration_sec for s in samples),
            "active_stages": stages,
        }
        all_trials.append(record)
        atomic_json(directory / "all-dev-trials.json", all_trials)
    admissible = [
        t
        for t in all_trials
        if t["guardrails_satisfied"] and t["summary"]["candidate_wer"] is not None
    ]
    selected = (
        min(
            admissible,
            key=lambda t: (t["summary"]["candidate_wer"], t["end_to_end_rtf"], t["active_stages"]),
        )
        if admissible
        else None
    )
    result = {
        "run_id": run_id,
        "status": "SELECTED_ON_DEV" if selected else "NEEDS_MORE_DATA",
        "selected": selected,
        "trials": all_trials,
        "dev_manifest_sha256": file_hash(path),
        "release_promoted": False,
    }
    atomic_json(directory / "selection-dev.json", result)
    return result


def freeze_selection(config: dict, acceptance_path: Path, destination: Path) -> dict:
    from north55_speech.datasets import verify_partition_proof

    acceptance = load_acceptance(acceptance_path)
    development = Path(config["development_selection"])
    if not development.is_file():
        raise SpeechError(
            "MISSING_DEV_SELECTION", "Run bounded dev search before final selection freeze"
        )
    dev = json.loads(development.read_text())
    if not dev.get("selected"):
        raise SpeechError(
            "NO_ADMISSIBLE_CANDIDATE", "No candidate satisfied development guardrails"
        )
    baseline = PipelineConfig.model_validate(read_yaml(Path(config["baseline"])))
    candidate = PipelineConfig.model_validate(dev["selected"]["config"])
    baseline.device, baseline.compute_type = candidate.device, candidate.compute_type
    assert_same_model(baseline, candidate)
    inference_path = Path(config["test_inference_manifest"])
    requests = [
        json.loads(line) for line in inference_path.read_text().splitlines() if line.strip()
    ]
    from north55_speech.schemas import InferenceRequest

    for request in requests:
        InferenceRequest.model_validate(request)
    if not requests:
        raise SpeechError("MISSING_TEST_AUDIO", "Cannot freeze an empty final test cohort")
    model = local_model_manifest(baseline.model)
    proof_path = Path(config["partition_proof"])
    proof = json.loads(proof_path.read_text())
    verify_partition_proof(proof)
    if proof["test_references_sha256"] != config["sealed_references_sha256"]:
        raise SpeechError("PARTITION_PROOF_MISMATCH", "Sealed checksum differs from curator proof")
    manifest = {
        "protocol_id": acceptance["protocol_id"],
        "created_at": now().isoformat(),
        "baseline": baseline.model_dump(),
        "candidate": candidate.model_dump(),
        "model_manifest": model,
        "test_inference_sha256": file_hash(inference_path),
        "test_sample_ids": sorted(r["sample_id"] for r in requests),
        "sealed_references_sha256": config["sealed_references_sha256"],
        "development_selection_sha256": file_hash(development),
        "dev_manifest_sha256": dev["dev_manifest_sha256"],
        "primary_scope": acceptance["scope"],
        "claimed_labels": acceptance["nlp_quality_gate"]["claimed_labels"],
        "partition_proof": proof,
        "partition_proof_sha256": file_hash(proof_path),
        "hashes": {
            "code": code_hash(),
            "data": digest(
                {
                    "inference": file_hash(inference_path),
                    "sealed": config["sealed_references_sha256"],
                }
            ),
            "config": digest(candidate.model_dump()),
            "model": pipeline_model_hash(candidate),
            "scorer": scorer_hash(),
            "acceptance": file_hash(acceptance_path),
        },
    }
    if destination.exists():
        raise SpeechError("SELECTION_ALREADY_FROZEN", "Do not replace an existing selection lock")
    atomic_json(destination, manifest)
    return manifest


def annotation_cohort(samples: list[Sample], acceptance: dict, task: str) -> tuple[list[Sample], list[dict]]:
    """Limit each annotation claim to its frozen language/domain and human evidence."""
    if task not in {"events", "temporal"}:
        raise ValueError("Unknown annotation task")
    selected, excluded = [], []
    for sample in samples:
        reasons = []
        # Human-verified non-speech controls still contribute temporal false positives.
        noise_control = task == "temporal" and sample.scope == "non_speech"
        if not noise_control and sample.language not in acceptance["scope"]["primary_language_scope"]:
            reasons.append("outside_frozen_language_scope")
        if not sample.scope_verified or (not noise_control and sample.scope not in acceptance["scope"]["permitted_primary_scopes"]):
            reasons.append("outside_verified_crew_scope")
        if noise_control and (sample.speech_origin != "noise" or sample.reference_text != ""
                              or sample.transcript_status != "human_verified" or sample.events != []):
            reasons.append("unverified_non_speech_control")
        if not noise_control and sample.speech_origin != "recorded_human":
            reasons.append("not_recorded_human")
        if not sample.annotation_provenance.get("annotator") or sample.annotation_provenance.get("reviewed_audio") is not True:
            reasons.append("missing_human_audio_review_provenance")
        if task == "events":
            if sample.transcript_status != "human_verified" or sample.reference_text is None:
                reasons.append("missing_human_text")
            if sample.events_status != "human_verified" or sample.labels is None or sample.salient_for_review is None:
                reasons.append("missing_human_event_or_salience_labels")
        elif sample.temporal_status != "human_verified" or not sample.continuous_recording:
            reasons.append("missing_human_continuous_temporal_annotations")
        if reasons:
            excluded.append({"sample_id": sample.sample_id, "reasons": reasons})
        else:
            selected.append(sample)
    return selected, excluded


def final_test(selection: Path, references: Path, inference_manifest: Path) -> dict:
    from north55_speech.datasets import verify_partition_proof

    if not settings.evaluator:
        raise SpeechError("EVALUATOR_REQUIRED", "Only evaluator may open final test references")
    locked = json.loads(selection.read_text())
    acceptance = load_acceptance(Path("configs/acceptance.yaml"))
    if locked["hashes"]["code"] != code_hash() or locked["hashes"]["scorer"] != scorer_hash():
        raise SpeechError("FROZEN_CODE_CHANGED", "Code/scorer changed after freeze")
    if (
        file_hash(references) != locked["sealed_references_sha256"]
        or file_hash(inference_manifest) != locked["test_inference_sha256"]
    ):
        raise SpeechError("FROZEN_DATA_CHANGED", "Frozen manifests were modified")
    selection_hash = file_hash(selection)
    log_path = settings.report_root / "test_access_log.jsonl"
    if log_path.exists():
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line]
        if any(
            e["sealed_sha256"] == locked["sealed_references_sha256"]
            and e["selection_sha256"] != selection_hash
            for e in entries
        ):
            raise SpeechError(
                "TEST_REUSE_FOR_SELECTION",
                "This test was already opened under a different selection",
            )
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "at": now().isoformat(),
                    "selection_sha256": selection_hash,
                    "sealed_sha256": locked["sealed_references_sha256"],
                }
            )
            + "\n"
        )
    samples = load_manifest(references)
    verify_partition_proof(locked["partition_proof"], samples, "test")
    if any(s.split != "test" for s in samples):
        raise SpeechError("INVALID_TEST_SPLIT", "Final manifest must be test-only")
    actual = sorted(inference_projection(s).sample_id for s in samples)
    if actual != locked["test_sample_ids"]:
        raise SpeechError("COHORT_MISMATCH", "Sealed references do not match frozen audio cohort")
    baseline = PipelineConfig.model_validate(locked["baseline"])
    candidate = PipelineConfig.model_validate(locked["candidate"])
    assert_same_model(baseline, candidate)
    if pipeline_model_hash(candidate) != locked["hashes"]["model"]:
        raise SpeechError("FROZEN_MODEL_CHANGED", "Model files/revision differ")
    run_id = "test-" + selection_hash[:16]
    directory = settings.report_root / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    b = infer_samples(samples, baseline, run_id + "-A0")
    c = infer_samples(samples, candidate, run_id + "-candidate")
    atomic_json(directory / "per-sample-predictions.json", {"baseline": b, "candidate": c})
    summary, rows = summarize(samples, b, c, acceptance)
    engineering_path = settings.report_root / "engineering-gate.json"
    engineering = (
        json.loads(engineering_path.read_text())
        if engineering_path.exists()
        else gate("NOT_RUN", ["engineering_evidence_missing"])
    )
    gates: dict[str, Any] = {
        "engineering_gate": engineering,
        "asr_quality_gate": asr_gate(summary, acceptance),
        "nlp_quality_gate": nlp_gate({}, acceptance),
        "temporal_event_gate": gate("NEEDS_MORE_DATA", ["temporal_annotations_not_evaluated"]),
        "validated_scope": [],
        "deployment_candidate": "baseline",
        "release_promoted": False,
    }
    event_report = None
    if candidate.classifier == "tfidf_logreg_v1":
        from north55_speech.training import TrainedEventClassifier, evaluate_events

        annotated, excluded = annotation_cohort(samples, acceptance, "events")
        atomic_json(directory / "event-cohort.json", {
            "included_ids": [s.sample_id for s in annotated], "excluded_annotations": excluded,
            "frozen_scope": acceptance["scope"], "exclusions_based_on_predictions": False,
        })
        if annotated:
            classifier = TrainedEventClassifier.load(candidate.classifier_artifact)
            event_report = evaluate_events(
                annotated, classifier, {r["sample_id"]: r["candidate"]["hypothesis"] for r in rows}
            )
            baseline_asr_report = evaluate_events(
                annotated, classifier, {r["sample_id"]: r["baseline"]["hypothesis"] for r in rows}
            )
            event_report["baseline_asr_to_same_frozen_nlp"] = baseline_asr_report.get("end_to_end")
            atomic_json(directory / "event-metrics.json", event_report)
            # Complete claimed-label gate derives from independent annotations and ASR output.
            from north55_speech.metrics import multilabel_score
            from north55_speech.nlp import EventClassifier

            labels = acceptance["nlp_quality_gate"]["claimed_labels"]
            candidate_scores = multilabel_score(
                [cast(list[str], s.labels) for s in annotated],
                [classifier.predict(cast(str, s.reference_text))["labels"] for s in annotated],
                labels,
            )
            rules_scores = multilabel_score(
                [cast(list[str], s.labels) for s in annotated],
                [
                    EventClassifier().predict(cast(str, s.reference_text))["labels"]
                    for s in annotated
                ],
                labels,
            )
            gates["nlp_quality_gate"] = nlp_gate(
                {
                    "executed": True,
                    "human_verified_labels": True,
                    "evidence": {
                        "independent_groups": len({s.group_id for s in annotated if s.group_id}),
                        "human_verified_episodes_or_utterances": len(annotated),
                        "positives_per_label": {
                            label: sum(label in (s.labels or []) for s in annotated)
                            for label in labels
                        },
                        "salience_positives": sum(s.salient_for_review is True for s in annotated),
                        "salience_negatives": sum(s.salient_for_review is False for s in annotated),
                    },
                    "candidate_macro_f1": candidate_scores["macro_f1"],
                    "rules_macro_f1": rules_scores["macro_f1"],
                    "end_to_end_salience": (event_report["end_to_end"] or {}).get("salience") or {},
                },
                acceptance,
            )
    temporal, excluded_temporal = annotation_cohort(samples, acceptance, "temporal")
    atomic_json(directory / "temporal-cohort.json", {
        "included_ids": [s.sample_id for s in temporal], "excluded_annotations": excluded_temporal,
        "frozen_scope": acceptance["scope"], "exclusions_based_on_predictions": False,
    })
    if temporal:
        from north55_speech.gates import temporal_gate
        from north55_speech.metrics import prf, temporal_event_score

        totals = {"tp": 0, "fp": 0, "fn": 0}
        for sample in temporal:
            reference_events = [
                e for e in sample.events or [] if e.get("salient_for_review") is True
            ]
            result = c[sample.sample_id].get("result") or {}
            predicted_events = [
                e for e in result.get("events", []) if e.get("salient_for_review") is True
            ]
            score = temporal_event_score(
                reference_events,
                predicted_events,
                sample.duration_sec,
                acceptance["temporal_event_gate"]["minimum_temporal_iou"],
            )
            for key in totals:
                totals[key] += score[key]
        temporal_metrics = prf(**totals)
        temporal_metrics["false_positives_per_audio_hour"] = totals["fp"] / (
            sum(s.duration_sec for s in temporal) / 3600
        )
        gates["temporal_event_gate"] = temporal_gate(
            {
                "executed": True,
                "human_verified_time_intervals": True,
                "continuous_recordings": True,
                "metrics": temporal_metrics,
            },
            acceptance,
        )
    if all(
        gates[key]["status"] == "PASS"
        for key in ("engineering_gate", "asr_quality_gate", "nlp_quality_gate")
    ):
        gates["validated_scope"] = acceptance["scope"]["primary_language_scope"]
    atomic_json(
        directory / "run_manifest.json",
        {"run_id": run_id, "hashes": locked["hashes"], "selection_sha256": selection_hash},
    )
    atomic_json(directory / "selection.lock.json", locked)
    atomic_json(
        directory / "environment.json",
        {"platform": platform.platform(), "python": platform.python_version()},
    )
    atomic_json(directory / "model_manifest.json", locked["model_manifest"])
    import yaml

    (directory / "effective_config.yaml").write_text(
        yaml.safe_dump({"baseline": baseline.model_dump(), "candidate": candidate.model_dump()}),
        encoding="utf-8",
    )
    (directory / "dataset_manifest.sha256").write_text(
        locked["sealed_references_sha256"] + "\n", encoding="ascii"
    )
    write_report(directory, summary, rows, gates, event_report)
    with DB.begin() as db:
        row = db.get(BenchmarkRun, run_id)
        if not row:
            db.add(
                BenchmarkRun(
                    id=run_id,
                    status=gates["asr_quality_gate"]["status"],
                    manifest={"hashes": locked["hashes"]},
                )
            )
    return {"run_id": run_id, "gates": gates}
