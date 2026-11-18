"""Standalone paired-result figures and Russian report from the frozen matrix."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from h2.cloudru_report import COLORS, finish, read
from h2.cloudru_ops import save, stamp

LABELS = {"short": "Короткие записи", "long": "Длинные записи", "mixed": "Смешанная очередь"}


def report(run):
    plan = read(run / "main/plan.json")
    rows = read(run / "main/rows.json")
    analysis = read(run / "main/analysis.json")
    by_id = {x["trial"]: x for x in rows}
    out = run / "figures"
    out.mkdir(exist_ok=True)
    primary = [x for x in plan["trials"] if x["analysis_group"] == "primary"]
    fig, axes = plt.subplots(2, 3, figsize=(12, 7), constrained_layout=True)
    for column, scenario in enumerate(LABELS):
        pairs = defaultdict(dict)
        for spec in primary:
            if spec["scenario"] == scenario and spec["id"] in by_id:
                pairs[spec["block"]][spec["variant"]] = by_id[spec["id"]]
        axes[0, column].set_title(LABELS[scenario])
        for block, pair in sorted(pairs.items()):
            if set(pair) != {"count", "work"}:
                continue
            x = np.array([0, 1]) + (block - 1.5) * .025
            values = [pair[v] for v in ("count", "work")]
            if all(row["correct"] for row in values):
                low = np.array([r["cost_lower_rub"] / r["correct"] for r in values])
                high = np.array([r["cost_upper_rub"] / r["correct"] for r in values])
                axes[0, column].errorbar(x, (low + high) / 2, yerr=(high - low) / 2,
                    fmt="o-", color=COLORS[block % len(COLORS)], capsize=4, label=f"Блок {block + 1}")
            timely = [100 * r["on_time"] / r["accepted"] for r in values]
            axes[1, column].plot(x, timely, "o-", color=COLORS[block % len(COLORS)])
        for row in range(2):
            axes[row, column].set_xticks([0, 1], ["Count", "Work"])
            axes[row, column].set_xlim(-.2, 1.2)
            axes[row, column].set_ylim(bottom=0)
            axes[row, column].grid(alpha=.2)
        axes[1, column].set_ylim(0, 105)
        axes[1, column].axhline(95, color="#64748b", linestyle="--", linewidth=1)
    axes[0, 0].set_ylabel("Расчётные ₽ / корректную задачу")
    axes[1, 0].set_ylabel("Корректно и в срок, % всех принятых")
    axes[0, 0].legend(fontsize=8)
    fig.suptitle("Firefly H2 · парные облачные прогоны\nВМ + SSD, включая запуск и простой; отдельно от фактического Billing", fontsize=14)
    finish(fig, out / "main-paired-cost-and-on-time")

    # Block zero is selected by the frozen design, never by the best saving.
    for scenario in LABELS:
        first = [x for x in primary if x["scenario"] == scenario and x["block"] == 0]
        if any(x["id"] not in by_id for x in first):
            continue
        fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, constrained_layout=True)
        fig.suptitle(LABELS[scenario] + " · заранее выбранный блок 1", fontsize=14)
        for spec in first:
            path = run / "trials" / spec["id"]
            points = [json.loads(line) for line in (path / "timeline.jsonl").read_text().splitlines()]
            submitted = read(path / "submitted.json")
            origin = min(x["accepted_at"] for x in submitted)
            times = [(x["at"] - origin) / 60 for x in points]
            color = COLORS[0] if spec["variant"] == "count" else COLORS[2]
            label = spec["variant"].capitalize()
            axes[0].step(times, [len(x["instances"]) for x in points], where="post", color=color, label=label)
            axes[1].step(times, [x["metrics"]["completed"] for x in points], where="post", color=color, label=label)
            axes[2].plot(times, [x["cost"]["estimated_rub_upper"] for x in points], color=color, label=label)
        for axis, label in zip(axes, ("Фактические ВМ", "Завершённые задания", "ВМ + SSD, расчётные ₽")):
            axis.set_ylabel(label)
            axis.set_ylim(bottom=0)
            axis.grid(alpha=.2)
            axis.legend(loc="upper left")
            axis.axvline(30, color="#64748b", linestyle="--", linewidth=1)
        axes[0].set_yticks([0, 1, 2, 3])
        axes[2].set_xlabel("Минуты после первого приёма; пунктир — конец общего окна наблюдения")
        finish(fig, out / ("main-" + scenario + "-block-1"))

    lines = ["# H2: результаты основной серии Cloud.ru", "", "Сформировано " + stamp() + ".", ""]
    if analysis.get("complete") and analysis.get("interpretation_policy") == "complete-pairs-across-sessions-v1":
        lines.append("**Все запланированные пары завершены. " +
            ("H2 подтверждена по заданным критериям исследованного стенда.**" if analysis["h2_confirmed"]
             else "H2 не подтверждена по заданным критериям исследованного стенда.**"))
    elif analysis.get("complete") and analysis.get("protocol_deviations"):
        met = analysis.get("original_numerical_criteria_met", False)
        lines.append("**Все запланированные пары измерены с раскрытым перерывом между кластерами. "
            + ("Численные критерии выполнены." if met else "Численные критерии не выполнены.")
            + " Строгое подтверждение по исходному непрерывному протоколу не заявляется.**")
    elif analysis.get("complete"):
        lines.append("**H2 подтверждена по заранее заданным критериям этого стенда.**" if analysis["h2_confirmed"]
                     else "**H2 не подтверждена по заранее заданным критериям этого стенда.**")
    else:
        lines.append("**Основная серия неполная; подтверждение H2 недопустимо.**")
    for deviation in analysis.get("protocol_deviations", plan.get("protocol_deviations", [])):
        lines += ["", deviation]
    lines += ["", f"SLO: {plan['slo_seconds']} с. Count threshold: {plan['config']['target_queue']}. "
              "CPU ASR tiny.en; по 24 задания; 30 минут наблюдения на прогон.", "",
              "| Сценарий | Стратегия | Прогонов | Принято | Корректно | В срок | ВМ + SSD, расчётные ₽ |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for scenario in LABELS:
        for variant in ("count", "work", "fixed"):
            selected = [by_id[x["id"]] for x in plan["trials"] if x["scenario"] == scenario and x["variant"] == variant
                        and not x["fault"] and x["id"] in by_id]
            if not selected:
                continue
            sums = {key: sum(r[key] for r in selected) for key in ("accepted", "correct", "on_time", "cost_lower_rub", "cost_upper_rub")}
            lines.append(f"| {LABELS[scenario]} | {variant} | {len(selected)} | {sums['accepted']} | {sums['correct']} | "
                         f"{sums['on_time']} | {sums['cost_lower_rub']:.3f}–{sums['cost_upper_rub']:.3f} |")
    if "cost_ratio_ci95" in analysis:
        lo, hi = analysis["cost_ratio_ci95"]
        lines += ["", f"Консервативное отношение стоимости Work/Count: **{analysis['conservative_cost_per_correct_ratio']:.3f}**, "
                  f"95% CI **[{lo:.3f}; {hi:.3f}]**. Независимые единицы анализа — {analysis['blocks']} парных блоков; "
                  "задания внутри одного прогона не считаются независимыми повторениями."]
    lines += ["", "![Парные результаты](../figures/main-paired-cost-and-on-time.png)", "",
              "Денежные значения — оценка по времени существования ВМ/SSD и тарифам. "
              "В неё входят provisioning, лишние узлы Autoscaler и простой. Начисления Billing "
              "по кластеру, общий master/системный узел, Registry и сетевые расходы сохраняются отдельно; "
              "это не процент экономии полного счёта и не отдельные начисления по каждому прогону.", "",
              "Прогоны fixed — описательный контроль с готовыми worker до приёма; их первоначальный "
              "запуск сохранён в затратах. Необязательная пара со сбоем анализируется отдельно от первичного CI.", "",
              "Область вывода ограничена синтетической речью, выбранной моделью, CPU-конфигурацией "
              "и проверенным облачным окном. Малое число блоков не доказывает отсутствие редких сбоев. "
              "Точное правило, все варианты и порядок находятся в [PLAN.md](PLAN.md) и [plan.json](plan.json).", ""]
    (run / "main/RESULTS.md").write_text("\n".join(lines))
    save(out / "main-sources.json", {"at": stamp(), "sources": ["main/plan.json", "main/rows.json", "main/analysis.json", "trials/*/timeline.jsonl"],
        "representative_trace_rule": "Block zero in each scenario, independently of measured outcome."})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    report(parser.parse_args().run)
