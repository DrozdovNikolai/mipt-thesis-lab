"""Freeze available human reviews, then rescore retained dev predictions without selection."""

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from north55_speech.benchmark import scorer_hash
from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import load_manifest, write_manifest
from north55_speech.metrics import corpus_counts, edit_counts, paired_cluster_bootstrap
from north55_speech.reporting import write_csv
from north55_speech.training import check_training_partitions
from scripts.materialize_reviewed_training import collect


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(args):
    if args.output.exists():
        raise ValueError("Use a new immutable reviewed-data version")
    accepted, pending, revisions = collect(args.packet, "asr")
    held = [s for s in accepted if s.reference_text.rstrip().endswith(("-", "–")) and not s.unintelligible]
    accepted = [s for s in accepted if s not in held]
    pending += [{"id": s.sample_id, "split": s.split, "reasons": ["truncated_word_without_scoring_mask"]} for s in held]
    train, dev = [s for s in accepted if s.split == "train"], [s for s in accepted if s.split == "dev"]
    check_training_partitions(train, dev)
    originals = [s for split in ("train", "dev") for s in load_manifest(args.packet / f"{split}.jsonl")]
    # Freeze annotation availability and quality flags before loading any model answers.
    plan = {
        "status": "FROZEN_PARTIAL_HUMAN_REVIEW", "sample_ids": {"train": [s.sample_id for s in train], "dev": [s.sample_id for s in dev]},
        "planned_dev_ids": [s.sample_id for s in originals if s.split == "dev"],
        "counts": {"verified_before_holds": len(accepted) + len(held), "held_boundary": len(held), "train": len(train), "dev": len(dev)},
        "groups": {"train": len({s.group_id for s in train}), "dev": len({s.group_id for s in dev})},
        "pending": pending, "source_revisions": revisions,
        "reference_flags": {s.sample_id: ["digit_notation_requires_lexical_convention_review"] for s in accepted if re.search(r"\d", s.reference_text)},
        "source_prediction_sha256": {name: file_hash(args.reports / name) for name in ("pending-dev-ablation.json", "publisher-weak-v1/comparison.json")},
        "source_manifest_sha256": {split: file_hash(args.packet / f"{split}.jsonl") for split in ("train", "dev")},
        "script_sha256": file_hash(Path(__file__)), "scorer_sha256": scorer_hash(),
        "exporter_sha256": file_hash(Path(__file__).with_name("materialize_reviewed_training.py")),
        "selection_allowed": False, "test_accessed": False, "quality_gate_evidence": False,
        "reference_edits_by_automation": False,
        "limitations": ["Only the available human-reviewed dev subset is scored; hard unreviewed items remain pending.",
                        "One annotator could see publisher and model suggestions; not an independent blind test.",
                        "Literal human spelling is preserved, including digit notation; no numerical expansion is guessed.",
                        "No event, salience or critical-entity labels are inferred."],
    }
    args.output.mkdir(parents=True)
    for split, samples in (("train", train), ("dev", dev)):
        write_manifest(args.output / f"{split}.jsonl", samples)
    # Preserve reviewed revisions including held records, without modifying the live packet.
    for entry in revisions:
        src = args.packet / entry["file"]
        if file_hash(src) != entry["sha256"]:
            raise ValueError("Review changed during snapshot")
        dst = args.output / "source-revisions" / entry["id"] / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    plan["export_sha256"] = {split: file_hash(args.output / f"{split}.jsonl") for split in ("train", "dev")}
    atomic_json(args.output / "plan.json", plan)
    print(json.dumps({"status": plan["status"], **plan["counts"]}))


def same_audio_content(sample, row, audio_root):
    """A5 used deterministic 16 kHz resampling of the exact human-reviewed source window."""
    original = audio_root / sample.audio_path
    converted = audio_root / row["audio_path"]
    if file_hash(original) != sample.audio_sha256 or file_hash(converted) != row["audio_sha256"]:
        raise ValueError("Audio checksum mismatch")
    waveform, rate = sf.read(original, dtype="float32")
    actual, actual_rate = sf.read(converted, dtype="float32")
    divisor = math.gcd(rate, 16000)
    expected = resample_poly(waveform, 16000 // divisor, rate // divisor).astype(np.float32)
    if waveform.ndim != 1 or actual_rate != 16000 or not np.array_equal(expected, actual):
        raise ValueError("Cached A5 prediction is not the exact resampling of reviewed audio")
    return {"original_sha256": sample.audio_sha256, "prediction_audio_sha256": row["audio_sha256"], "resampled_array_equal": True}


def score(args):
    plan = read(args.output / "plan.json")
    if file_hash(Path(__file__)) != plan["script_sha256"] or scorer_hash() != plan["scorer_sha256"]:
        raise ValueError("Frozen scoring code changed")
    for split, sha in plan["export_sha256"].items():
        if file_hash(args.output / f"{split}.jsonl") != sha:
            raise ValueError("Frozen human references changed")
    for name, sha in plan["source_prediction_sha256"].items():
        if file_hash(args.reports / name) != sha:
            raise ValueError("Original prediction report changed")
    dev = load_manifest(args.output / "dev.jsonl")
    groups = {s.sample_id: s.group_id for s in dev}
    prediction_sources = {
        "A0_A4_fixed_small_int8_cpu": read(args.reports / "pending-dev-ablation.json"),
        "A5_parent_vs_lora_float16_gpu": read(args.reports / "publisher-weak-v1/comparison.json"),
    }
    results = {}
    identities = {}
    records = []
    for experiment, source in prediction_sources.items():
        is_a5 = experiment.startswith("A5")
        rows = source["rows" if is_a5 else "runs"]
        index = {(r["id" if is_a5 else "sample_id"], r["system" if is_a5 else "trial"]): r for r in rows}
        if len(index) != len(rows):
            raise ValueError("Duplicate cached prediction")
        systems = list(dict.fromkeys(r["system" if is_a5 else "trial"] for r in rows))
        scores = {}
        for system in systems:
            per_sample = {}
            for sample in dev:
                row = index[(sample.sample_id, system)]
                if is_a5:
                    identities[sample.sample_id] = same_audio_content(sample, row, args.audio)
                elif row["audio_sha256"] != sample.audio_sha256:
                    raise ValueError("Ablation audio differs from human-reviewed audio")
                if sample.unintelligible:
                    raise ValueError("This pilot has no adjudicated masks; add a separately versioned masked protocol")
                counts = edit_counts(sample.reference_text, row["hypothesis"])
                per_sample[sample.sample_id] = counts
                records.append({"experiment": experiment, "system": system, "id": sample.sample_id,
                    "group": sample.group_id, "reference": sample.reference_text, "hypothesis": row["hypothesis"],
                    "reference_flags": plan["reference_flags"].get(sample.sample_id, []), "runtime_failure": row["runtime_failure"], **counts})
            scores[system] = per_sample
        baseline = "parent" if is_a5 else "A0"
        summaries = {}
        for system in systems:
            totals = corpus_counts(list(scores[system].values()))
            base_totals = corpus_counts(list(scores[baseline].values()))
            base_errors = sum(base_totals[k] for k in ("S", "D", "I"))
            errors = sum(totals[k] for k in ("S", "D", "I"))
            paired = [{"group_id": groups[key], "baseline": scores[baseline][key], "candidate": scores[system][key]} for key in groups]
            summaries[system] = {**totals, "relative_error_reduction": 1-errors/base_errors if base_errors else None,
                                "diagnostic_ci": paired_cluster_bootstrap(paired), "ci_is_acceptance_evidence": False}
        results[experiment] = {"baseline": baseline, "systems": summaries, "samples": len(dev), "groups": len(set(groups.values()))}
    folder = args.reports / "reviewed-pilot-v1"
    folder.mkdir(parents=True, exist_ok=True)
    report = {"status": "EXECUTED_PARTIAL_HUMAN_REVIEW", "plan_sha256": file_hash(args.output / "plan.json"),
        "results": results, "records": records, "audio_identity": identities,
        "dev_planned": len(plan["planned_dev_ids"]), "dev_scored": len(dev),
        "unreviewed_dev": sorted(set(plan["planned_dev_ids"]) - set(groups)),
        "reference_flags": plan["reference_flags"], "limitations": plan["limitations"],
        "ASR_QUALITY_GATE": "NEEDS_MORE_DATA", "NLP_QUALITY_GATE": "NEEDS_MORE_DATA",
        "statistical_confirmation": "INCONCLUSIVE", "critical_entity_quality": "NOT_MEASURED",
        "candidate_selected": False, "release_promoted": False, "new_training_executed": False, "test_accessed": False}
    atomic_json(folder / "comparison.json", report)
    write_csv(folder / "predictions.csv", ["experiment", "system", "id", "group", "reference", "hypothesis", "S", "D", "I", "N", "wer", "reference_flags", "runtime_failure"], records)
    summary_rows = [{"experiment": exp, "system": system, **values} for exp, result in results.items() for system, values in result["systems"].items()]
    write_csv(folder / "summary.csv", ["experiment", "system", "S", "D", "I", "N", "wer_lexical_corpus", "relative_error_reduction"], summary_rows)
    lines = ["# Пилотное сравнение по сохранённым человеческим расшифровкам", "",
        "Научная приёмка: **NEEDS_MORE_DATA**. Статистическое подтверждение: **INCONCLUSIVE**. Release не изменён.", "",
        f"Зафиксированы {plan['counts']['train']} train и {plan['counts']['dev']} dev расшифровок. "
        f"{plan['counts']['held_boundary']} подтверждённый фрагмент с оборванным словом отложен без изменения человеческой ревизии.", "",
        f"Пересчитаны {len(records)} сохранённых предсказаний на {len(dev)} из {len(plan['planned_dev_ids'])} dev-фрагментов. "
        "Другие фрагменты остаются без оценки; их не засчитали как правильные ответы.", "",
        "Один dev-текст содержит цифровую запись чисел и требует согласования с lexical conventions. "
        "Текст человека сохранён дословно: развёртки цифр и исправления по смыслу не выполнялись. "
        "Таблица показывает ошибки относительно сохранённой орфографии, а не окончательный независимый lexical WER.", "",
        "| Эксперимент | Система | Ошибки / слова | Доля ошибок | Изменение относительно baseline |",
        "|---|---|---:|---:|---:|"]
    for row in summary_rows:
        errors = sum(row[k] for k in ("S", "D", "I"))
        lines.append(f"| {row['experiment']} | {row['system']} | {errors}/{row['N']} | {100*row['wer_lexical_corpus']:.2f}% | {100*row['relative_error_reduction']:+.2f}% |")
    lines += ["", "A0–A4 сравниваются на неизменных small/int8 CPU весах; A5 — отдельное сравнение исходных и адаптированных весов в float16. "
        "Аудио A5 проверено на точное совпадение после детерминированного resampling исходного проверенного окна.", "",
        "95% интервалы посчитаны парным bootstrap по трём группам (2000 повторов, seed 55) и сохранены в JSON. "
        "При таком объёме, одном разметчике, доступных подсказках и неполном dev-пакете они диагностические. "
        "Критические сущности и NLP/event labels отсутствуют; результаты не выбирают candidate и не допускают release.", "",
        "Старые отчёты на автоматически привязанных издательских текстах сохранены отдельно; состав подвыборок отличается.", "",
        f"Данные: data/curated/{args.output.name}. Измерения: comparison.json, predictions.csv, summary.csv."]
    (folder / "report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "dev_scored": len(dev), "predictions_scored": len(records), "results": results}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "score"])
    parser.add_argument("--packet", type=Path, default=Path("/packet"))
    parser.add_argument("--output", type=Path, default=Path("/curated/reviewed-pilot-v2"))
    parser.add_argument("--reports", type=Path, default=Path("/reports"))
    parser.add_argument("--audio", type=Path, default=Path("/audio"))
    args = parser.parse_args()
    (prepare if args.action == "prepare" else score)(args)


if __name__ == "__main__":
    main()
