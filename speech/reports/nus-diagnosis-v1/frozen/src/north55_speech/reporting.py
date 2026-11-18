"""Measured-only benchmark artifacts; presentation never selects or promotes a model."""

from __future__ import annotations

import csv
import html
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, TypeGuard

from north55_speech.core import atomic_json
from north55_speech.journal import csv_safe
from north55_speech.metrics import corpus_counts

SYSTEMS = ("baseline", "candidate")
MISSING = "не измерено"


def numeric(value: Any) -> TypeGuard[int | float]:
    return type(value) in (int, float) and math.isfinite(value)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            # Escape metadata, never turn signed numerical measurements into strings.
            writer.writerow(
                {
                    key: csv_safe(row.get(key)) if isinstance(row.get(key), str) else row.get(key)
                    for key in fields
                }
            )


def event_rows(report: dict | None) -> list[dict]:
    """Keep human-text, each ASR input and salience as distinct tasks/cohorts."""
    report = report or {}
    conditions = {
        "human_text": {
            "rules": report.get("rules_human_text"),
            "candidate": report.get("candidate_human_text"),
            "salience": report.get("salience_human_text"),
        },
        "candidate_asr": report.get("end_to_end") or {},
        "baseline_asr": report.get("baseline_asr_to_same_frozen_nlp") or {},
    }
    rows = []
    for input_kind, systems in conditions.items():
        for system in ("rules", "candidate", "salience"):
            scores = systems.get(system) or {}
            base = {
                "input": input_kind,
                "system": system,
                "task": "salience" if system == "salience" else "utterance_classification",
            }
            if system == "salience":
                rows.append(
                    base
                    | {
                        "label": "salient_for_review",
                        **scores,
                        "status": "measured" if scores else "NOT_RUN",
                    }
                )
                continue
            rows.append(
                base
                | {
                    "label": "__aggregate__",
                    "macro_f1": scores.get("macro_f1"),
                    "micro_f1": scores.get("micro_f1"),
                    "status": "measured" if scores.get("per_label") else "NOT_RUN",
                }
            )
            for label, values in scores.get("per_label", {}).items():
                matrix = values.get("confusion_matrix")
                cells = (
                    dict(
                        zip(
                            ("tn", "fp", "fn", "tp"),
                            [v for row in matrix for v in row],
                            strict=True,
                        )
                    )
                    if matrix
                    else {}
                )
                rows.append(base | {"label": label, **values, **cells})
    return rows


def figures(directory: Path, report: dict, rows: list[dict], events: list[dict]) -> list[dict]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.hashsalt": "north55-report-v1",
        }
    )
    target = directory / "figures"
    target.mkdir(exist_ok=True)
    outputs: list[dict] = []

    def missing(name: str, title: str, reason: str = "Нет проверенных измерений") -> None:
        outputs.append({"name": name, "title": title, "status": "NOT_MEASURED", "reason": reason})

    def save(fig, name: str, title: str, data: Any, note: str = "") -> None:
        paths = []
        fig.suptitle(title, fontsize=13)
        for suffix in ("png", "svg"):
            path = target / f"{name}.{suffix}"
            metadata: dict[str, Any] = {"Software": "north55_speech"} if suffix == "png" else {"Date": None}
            fig.savefig(path, dpi=150, bbox_inches="tight", metadata=metadata)
            paths.append(str(path.relative_to(directory)).replace("\\", "/"))
        plt.close(fig)
        outputs.append(
            {
                "name": name,
                "title": title,
                "status": "MEASURED",
                "files": paths,
                "data": data,
                "note": note,
            }
        )

    quality_allowed = not report.get("missing_annotations") and not report.get("integrity_errors")
    measured_wer = quality_allowed and all(numeric(report.get(f"{s}_wer")) for s in SYSTEMS)
    if measured_wer:
        fig, (ax, delta_ax) = plt.subplots(1, 2, figsize=(9, 3.6), layout="constrained")
        values = [report[f"{s}_wer"] for s in SYSTEMS]
        ci = report.get("delta_ci") or {}
        intervals = ci.get("system_intervals") or {}
        for x, (system, value) in enumerate(zip(SYSTEMS, values, strict=True)):
            ax.plot(x, 100 * value, "o", color=("#255f85", "#b35625")[x])
            interval = intervals.get(system, {})
            low, high = interval.get("lower"), interval.get("upper")
            if numeric(low) and numeric(high) and low <= high:
                ax.vlines(x, 100 * low, 100 * high, color="#333333")
                ax.plot([x, x], [100 * low, 100 * high], "_", color="#333333")
        ax.set(xticks=[0, 1], xticklabels=SYSTEMS, ylabel="Lexical WER (%)", xlim=(-0.5, 1.5))
        ax.set_ylim(bottom=0)
        low, high = ci.get("lower"), ci.get("upper")
        if numeric(low) and numeric(high) and low <= high:
            delta_ax.hlines(0, 100 * low, 100 * high, color="#333333")
            delta_ax.plot(100 * (values[1] - values[0]), 0, "o")
            delta_ax.axvline(0, linestyle="--", color="#999999")
            delta_ax.set(yticks=[], xlabel="Candidate − baseline (percentage points)")
        else:
            delta_ax.text(0.5, 0.5, f"CI: {MISSING}", ha="center", transform=delta_ax.transAxes)
            delta_ax.set_axis_off()
        save(
            fig,
            "wer-ci",
            "WER: primary cohort",
            {"wer": values, "ci": ci},
            "Интервалы получены из одних cluster bootstrap draws. Для gate используется paired delta CI. "
            "Без system_intervals показаны только точки WER; CI не заимствуется у delta.",
        )
    else:
        missing("wer-ci", "WER и доверительный интервал")

    strata = report.get("strata") or {}
    for dimension in ("language", "condition"):
        data = {
            key.split(":", 1)[1]: value
            for key, value in strata.items()
            if key.startswith(dimension + ":")
            and quality_allowed
            and all(numeric(value.get(s, {}).get("wer_lexical_corpus")) for s in SYSTEMS)
        }
        if not data:
            missing(f"wer-{dimension}", f"WER by {dimension}")
            continue
        fig, ax = plt.subplots(figsize=(8, max(3, 0.55 * len(data))), layout="constrained")
        y = np.arange(len(data))
        for i, system in enumerate(SYSTEMS):
            ax.barh(
                y + (i - 0.5) * 0.35,
                [100 * v[system]["wer_lexical_corpus"] for v in data.values()],
                height=0.35,
                label=system,
            )
        ax.set(yticks=y, yticklabels=list(data), xlabel="Corpus lexical WER (%)")
        ax.legend()
        save(
            fig,
            f"wer-{dimension}",
            f"WER by {dimension}",
            data,
            "Все оцениваемые строки соответствующего stratum; это не отдельные gate cohorts.",
        )

    primary = [r for r in rows if r.get("primary") and not r.get("non_speech")]
    entity_data = (
        {
            s: {k: sum(r[s]["entities"][k] for r in primary) for k in ("C_sub", "C_del", "C_ins")}
            for s in SYSTEMS
        }
        if primary
        else {}
    )
    if quality_allowed and entity_data:
        fig, ax = plt.subplots(figsize=(7, 3.5), layout="constrained")
        y = np.arange(3)
        for i, system in enumerate(SYSTEMS):
            ax.bar(
                y + (i - 0.5) * 0.35, list(entity_data[system].values()), width=0.35, label=system
            )
        ax.set(
            xticks=y, xticklabels=["Substitution", "Deletion", "Insertion"], ylabel="Occurrences"
        )
        ax.legend()
        save(fig, "critical-entities", "Critical entity errors: primary cohort", entity_data)
    else:
        missing("critical-entities", "Ошибки критических сущностей")

    confusion_groups: dict[tuple, list] = defaultdict(list)
    for row in events:
        if row["task"] == "utterance_classification" and all(
            numeric(row.get(k)) for k in ("tn", "fp", "fn", "tp")
        ):
            confusion_groups[(row["input"], row["system"])].append(row)
    if not confusion_groups:
        missing(
            "event-confusions", "Multi-label confusion matrices", "Нет человеческих event labels"
        )
    for (input_kind, system), values in confusion_groups.items():
        fig, axes = plt.subplots(
            math.ceil(len(values) / 3),
            min(3, len(values)),
            squeeze=False,
            figsize=(9, 3 * math.ceil(len(values) / 3)),
            layout="constrained",
        )
        for ax, row in zip(axes.flat, values, strict=False):
            matrix = np.array([[row["tn"], row["fp"]], [row["fn"], row["tp"]]])
            ax.imshow(matrix, cmap="Blues", vmin=0)
            for (cell_y, cell_x), value in np.ndenumerate(matrix):
                ax.text(
                    cell_x,
                    cell_y,
                    str(value),
                    ha="center",
                    va="center",
                    color="black",
                    bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"},
                )
            ax.set(
                title=row["label"].replace("_", "\n"),
                xticks=[0, 1],
                yticks=[0, 1],
                xlabel="Predicted",
                ylabel="Human reference",
            )
        for ax in list(axes.flat)[len(values) :]:
            ax.set_axis_off()
        save(
            fig,
            f"events-{input_kind}-{system}",
            f"Utterance labels: {input_kind} / {system}",
            values,
            "Не является temporal event detection. Отсутствие положительных примеров не означает F1=1.",
        )

    runtime_points = []
    for system in SYSTEMS:
        if primary and all(
            numeric(r[system].get("timing", {}).get("end_to_end_sec")) for r in primary
        ):
            duration = sum(r["duration_sec"] for r in primary)
            if duration > 0 and measured_wer:
                runtime_points.append(
                    {
                        "system": system,
                        "wer": report[f"{system}_wer"],
                        "rtf": sum(r[system]["timing"]["end_to_end_sec"] for r in primary)
                        / duration,
                    }
                )
    if len(runtime_points) == 2:
        fig, ax = plt.subplots(figsize=(7, 3.5), layout="constrained")
        for point in runtime_points:
            ax.scatter(point["rtf"], 100 * point["wer"])
            ax.annotate(
                point["system"],
                (point["rtf"], 100 * point["wer"]),
                xytext=(5, 5),
                textcoords="offset points",
            )
        ax.set(xlabel="End-to-end RTF (sum runtime / sum audio duration)", ylabel="Lexical WER (%)")
        save(fig, "quality-runtime", "Quality / runtime: same primary cohort", runtime_points)
    else:
        missing("quality-runtime", "Качество / время", "Нужны WER и полные timing одного cohort")

    trials = report.get("runtime_trials") or []
    measured_trials = [t for t in trials if numeric(t.get("rtf")) and t["rtf"] >= 0]
    if measured_trials:
        fig, ax = plt.subplots(
            figsize=(8, max(3, 0.45 * len(measured_trials))), layout="constrained"
        )
        bars = ax.barh([t["trial"] for t in measured_trials], [t["rtf"] for t in measured_trials])
        ax.bar_label(bars, fmt="%.3f", padding=4)
        ax.set_xlim(right=max(t["rtf"] for t in measured_trials) * 1.16 or 1)
        ax.set(xlabel="Wall-clock RTF (sum elapsed / sum audio duration)")
        save(
            fig,
            "dev-runtime",
            "Measured unscored dev runtime",
            measured_trials,
            "Один проход каждой конфигурации. Это измерение скорости; WER/F1 не измерены, candidate не выбран.",
        )
    atomic_json(directory / "figures.json", outputs)
    return outputs


def write_report(
    directory: Path, report: dict, rows: list[dict], gates: dict, events: dict | None = None
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory / "metrics.json", report)
    atomic_json(directory / "gate.json", gates)
    atomic_json(directory / "per-sample-predictions.json", rows)
    atomic_json(directory / "event-metrics.json", events or {"status": "NOT_RUN"})
    fields = [
        "sample_id",
        "group_id",
        "language",
        "condition",
        "primary",
        "clean_control",
        "non_speech",
        "system",
        "S",
        "D",
        "I",
        "N",
        "wer",
        "hypothesis",
        "runtime_failure",
    ]
    samples = [{**row, **row[system], "system": system} for row in rows for system in SYSTEMS]
    write_csv(directory / "per-sample.csv", fields, samples)
    write_csv(
        directory / "timing.csv",
        [
            "sample_id",
            "system",
            "end_to_end_sec",
            "asr_sec",
            "end_to_end_rtf",
            "asr_rtf",
            "runtime_failure",
        ],
        [
            {
                "sample_id": row["sample_id"],
                "system": system,
                **row[system]["timing"],
                "runtime_failure": row[system]["runtime_failure"],
            }
            for row in rows
            for system in SYSTEMS
        ],
    )
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(row)
    grouped = []
    for group, members in sorted(groups.items()):
        for system in SYSTEMS:
            counts = corpus_counts([r[system] for r in members])
            grouped.append(
                {
                    "group_id": group,
                    "system": system,
                    "cohort": "all_scored_rows",
                    **counts,
                    "wer": counts["wer_lexical_corpus"],
                }
            )
    write_csv(
        directory / "group-metrics.csv",
        ["group_id", "system", "cohort", "S", "D", "I", "N", "wer"],
        grouped,
    )
    confusion_rows = [
        {
            "sample_id": row["sample_id"],
            "system": system,
            **{
                key: json.dumps(confusion[key], ensure_ascii=False)
                for key in ("reference", "prediction")
            },
        }
        for row in rows
        for system in SYSTEMS
        for confusion in row[system]["entities"]["confusions"]
    ]
    write_csv(
        directory / "entity-confusions.csv",
        ["sample_id", "system", "reference", "prediction"],
        confusion_rows,
    )
    scored_events = event_rows(events)
    write_csv(
        directory / "event-metrics.csv",
        [
            "task",
            "input",
            "system",
            "label",
            "status",
            "precision",
            "recall",
            "f1",
            "support",
            "macro_f1",
            "micro_f1",
            "tn",
            "fp",
            "fn",
            "tp",
            "unknown",
            "coverage",
        ],
        scored_events,
    )
    outputs = figures(directory, report, rows, scored_events)
    statuses = {
        key: value.get("status", "NOT_RUN")
        for key, value in gates.items()
        if isinstance(value, dict)
    }
    md = "# 55 Север — отчёт измерений\n\n"
    md += "\n".join(f"- {key}: {value}" for key, value in statuses.items())
    md += "\n\nОтсутствующие значения — **не измерено**, а не ноль. Графики не меняют quality gates.\n"
    md += "Качество ограничено зафиксированной выборкой; классификация фрагментов не доказывает temporal detection.\n"
    cards = []
    for output in outputs:
        title = html.escape(output["title"])
        if output["status"] == "MEASURED":
            path = output["files"][0]
            md += f"\n## {output['title']}\n\n![{output['title']}]({path})\n\n{output['note']}\n"
            body = f'<img src="{path}" alt="{title}"><p>{html.escape(output["note"])}</p>'
        else:
            md += f"\n- {output['title']}: **{MISSING}** — {output['reason']}.\n"
            body = f'<p class="missing">{MISSING}</p><p>{html.escape(output["reason"])}</p>'
        cards.append(f"<section><h2>{title}</h2>{body}</section>")
    (directory / "report.md").write_text(md, encoding="utf-8")
    downloads = [
        "metrics.json",
        "gate.json",
        "figures.json",
        "per-sample-predictions.json",
        "per-sample.csv",
        "group-metrics.csv",
        "entity-confusions.csv",
        "event-metrics.csv",
        "timing.csv",
    ]
    links = " · ".join(f'<a href="{name}">{name}</a>' for name in downloads)
    status_html = "".join(
        f"<li><strong>{html.escape(k)}</strong>: {html.escape(str(v))}</li>"
        for k, v in statuses.items()
    )
    page = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
    page += "<title>55 Север — отчёт измерений</title><style>body{font:16px system-ui,sans-serif;background:#eef1f4;color:#172d3c;margin:0}main{max-width:1100px;margin:auto;padding:28px}section,header{background:white;padding:24px;margin:18px 0;border-radius:10px}img{max-width:100%;height:auto}h1{font-size:28px}h2{font-size:20px}.missing{color:#815112;font-weight:bold}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#135c88}nav{line-height:2;overflow-wrap:anywhere}</style><main>"
    page += f"<header><h1>55 Север — отчёт измерений</h1><ul>{status_html}</ul><p>Отсутствующие значения — не измерено, а не ноль. Графики не меняют quality gates. Качество ограничено зафиксированной выборкой.</p><p>Классификация фрагментов не доказывает temporal event detection.</p><nav>{links}</nav></header>"
    page += "".join(cards)
    page += (
        "<details><summary>Исходные метрики</summary><pre>"
        + html.escape(json.dumps(report, ensure_ascii=False, indent=2))
        + "</pre></details></main></html>"
    )
    (directory / "report.html").write_text(page, encoding="utf-8")
