"""Render recorded dev runtimes without gold, ASR reruns, selection or test access."""

import argparse
import json
from collections import Counter
from pathlib import Path

from north55_speech.benchmark import code_hash
from north55_speech.core import atomic_json, file_hash
from north55_speech.reporting import numeric, write_csv, write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/reports/pending-dev-ablation.json"))
    parser.add_argument(
        "--plan", type=Path, default=Path("/reports/pending-dev-ablation-plan.json")
    )
    parser.add_argument("--output", type=Path, default=Path("/reports/reporting-v1/dev-runtime"))
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if source["plan_sha256"] != file_hash(args.plan) or source["status"] != "EXECUTED_UNSCORED":
        raise ValueError("Expected a complete execution record matching the original frozen plan")
    runs = source["runs"]
    expected = Counter(
        (trial, sample) for trial in plan["configs"] for sample in plan["sample_ids"]
    )
    if Counter((r["trial"], r["sample_id"]) for r in runs) != expected:
        raise ValueError("Missing, duplicate or extra trial/sample; report cannot hide runs")
    if any(
        r["split"] != "dev"
        or not numeric(r["elapsed_sec"])
        or r["elapsed_sec"] < 0
        or not numeric(r["duration_sec"])
        or r["duration_sec"] <= 0
        for r in runs
    ):
        raise ValueError("Expected dev-only rows and recorded finite timing")
    if (
        plan["test_mounted"]
        or plan["selection_allowed"]
        or source["candidate_selected"]
        or source["release_promoted"]
    ):
        raise ValueError("This renderer accepts unselected development inference only")
    identities = {(c["model"], c["device"], c["compute_type"]) for c in plan["configs"].values()}
    if len(identities) != 1:
        raise ValueError("Model and precision differ between trials")
    trials = []
    for trial in plan["configs"]:
        subset = [r for r in runs if r["trial"] == trial]
        duration = sum(r["duration_sec"] for r in subset)
        elapsed = sum(r["elapsed_sec"] for r in subset)
        trials.append(
            {
                "trial": trial,
                "runs": len(subset),
                "audio_sec": duration,
                "elapsed_sec": elapsed,
                "rtf": elapsed / duration,
                "failures": sum(r["runtime_failure"] is not None for r in subset),
            }
        )
    report = {
        "kind": "historical_unscored_dev_runtime",
        "runtime_trials": trials,
        "baseline_wer": None,
        "candidate_wer": None,
        "nlp_f1": None,
        "source_report_sha256": file_hash(args.source),
        "source_plan_sha256": file_hash(args.plan),
        "inference_code_hash": plan["code_hash"],
        "renderer_code_hash": code_hash(),
        "model_device_precision": list(next(iter(identities))),
        "runs": len(runs),
        "quality_evidence": False,
        "test_accessed": False,
        "candidate_selected": False,
        "source_note": "Historical timing retained under its original inference code; no new ASR or final test execution.",
    }
    gates = {
        "asr_quality_gate": {"status": "NEEDS_MORE_DATA"},
        "nlp_quality_gate": {"status": "NEEDS_MORE_DATA"},
        "temporal_event_gate": {"status": "NEEDS_MORE_DATA"},
        "selection": {"status": "NOT_RUN"},
        "release_promoted": False,
    }
    write_report(args.output, report, [], gates)
    timing = [
        {
            "sample_id": r["sample_id"],
            "trial": r["trial"],
            "elapsed_sec": r["elapsed_sec"],
            "duration_sec": r["duration_sec"],
            "rtf": r["elapsed_sec"] / r["duration_sec"],
            "runtime_failure": r["runtime_failure"] is not None,
        }
        for r in runs
    ]
    write_csv(args.output / "timing.csv", list(timing[0]), timing)
    write_csv(args.output / "runtime-trials.csv", list(trials[0]), trials)
    atomic_json(args.output / "execution-manifest.json", report)
    atomic_json(
        args.output / "unscored-predictions.json",
        [
            {
                key: r[key]
                for key in (
                    "sample_id",
                    "trial",
                    "group_id",
                    "audio_sha256",
                    "hypothesis",
                    "runtime_failure",
                )
            }
            for r in runs
        ],
    )
    print(
        json.dumps(
            {
                "status": "RENDERED",
                "recorded_runs": len(runs),
                "quality_evidence": False,
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
