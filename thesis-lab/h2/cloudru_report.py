"""Render shareable pilot figures from retained observations, without inventing data."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from h2.cloudru_ops import save, stamp

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "savefig.facecolor": "white"})
COLORS = ("#2563eb", "#f59e0b", "#059669", "#7c3aed")


def read(path):
    return json.loads(path.read_text())


def finish(fig, output):
    fig.savefig(output.with_suffix(".png"), dpi=180, bbox_inches="tight")
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def trial_plot(directory, out):
    points = [json.loads(line) for line in (directory / "timeline.jsonl").read_text().splitlines()]
    if not points:
        return None
    submitted = read(directory / "submitted.json") if (directory / "submitted.json").exists() else []
    origin = min((t["accepted_at"] for t in submitted if "accepted_at" in t), default=points[0]["at"])
    times = np.array([(p["at"] - origin) / 60 for p in points])
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True, constrained_layout=True)
    pilot = not directory.name.startswith("main-")
    fig.suptitle(directory.name + (" · подготовительный облачный прогон" if pilot else " · основной облачный прогон"), fontsize=14, fontweight="bold")
    counts = [("ВМ в Compute", [len(p["instances"]) for p in points]),
              ("Желаемые ASR pod", [p["desired_pods"] for p in points]),
              ("Готовые ASR pod", [p["deployment_status"].get("readyReplicas", 0) for p in points]),
              ("SSD рабочих узлов", [len(p["disks"]) for p in points])]
    for (label, values), color, style, marker in zip(counts, COLORS, ("-", "--", "-.", ":"), ("o", None, None, "x")):
        axes[0].step(times, values, where="post", label=label, color=color, linewidth=1.8,
                     linestyle=style, marker=marker, markersize=3, markevery=5)
    axes[0].set_ylabel("Количество")
    axes[0].legend(ncol=2, loc="upper right")
    for label, field, color in (("Принято", "accepted", COLORS[0]), ("Завершено", "completed", COLORS[2]),
                                 ("Ожидает", "queued", COLORS[1]), ("Выполняется", "running", COLORS[3])):
        axes[1].step(times, [p["metrics"][field] for p in points], where="post", label=label, color=color)
    axes[1].set_ylabel("Задания")
    axes[1].legend(ncol=4, loc="upper left")
    low = [p["cost"]["estimated_rub_lower"] for p in points]
    high = [p["cost"]["estimated_rub_upper"] for p in points]
    axes[2].plot(times, high, color=COLORS[0], label="ВМ + SSD: верхняя оценка")
    axes[2].fill_between(times, low, high, color=COLORS[0], alpha=.2, label="Интервал наблюдения удаления")
    axes[2].set_ylabel("Расчётные ₽")
    axes[2].set_xlabel("Минуты после первого принятого задания")
    axes[2].legend(loc="upper left")
    axes[2].set_title("Время существования ресурсов × тариф; это не отдельное начисление Billing", fontsize=10)
    events = directory.parent.parent / "events.jsonl"
    for relative in ("pilot/cold-starts.json", "pilot-v2/cold-starts.json"):
        calibration = directory.parent.parent / relative
        if calibration.exists():
            for probe in read(calibration):
                if probe["trial"] == directory.name and probe.get("automatic_zero_observed"):
                    minute = (probe["automatic_zero_at"] - origin) / 60
                    for axis in axes:
                        axis.axvline(minute, color=COLORS[2], linestyle=":", alpha=.8)
                    axes[0].text(minute, 1.45, "Автоматический ноль\nВМ и SSD", ha="right", va="center",
                                 fontsize=8, color=COLORS[2])
    if events.exists():
        for line in events.read_text().splitlines():
            event = json.loads(line)
            if event.get("name") == "request" and event.get("label") == "delete-pool:" + directory.name:
                minute = (datetime.fromisoformat(event["at"]).timestamp() - origin) / 60
                for axis in axes:
                    axis.axvline(minute, color="#64748b", linestyle="--", alpha=.7)
                axes[0].text(minute, 2.05, "Ручное удаление\nгруппы узлов", ha="right", va="center",
                             fontsize=8, color="#475569")
                break
    for axis in axes:
        axis.grid(alpha=.2)
        axis.set_ylim(bottom=0)
    axes[0].set_yticks([0, 1, 2, 3])
    axes[0].set_ylim(0, 3.25)
    finish(fig, out / (directory.name + "-timeline"))
    return {"trial": directory.name, "samples": len(points), "source": str(directory / "timeline.jsonl"),
            "cost_basis": "resource_time_estimate_not_billing", "pilot_only": pilot}


def native_plot(run, out, cluster_id):
    metrics = run / "native-monitoring"
    cpu_path = metrics / "container_cpu_usage_seconds_total.json"
    mem_path = metrics / "container_memory_working_set_bytes.json"
    if not cpu_path.exists() or not mem_path.exists():
        return None
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, constrained_layout=True)
    fig.suptitle("Firefly H2 · нативные метрики Cloud.ru", fontsize=14, fontweight="bold")
    series = 0
    for index, path in enumerate((cpu_path, mem_path)):
        for row in read(path):
            labels = row["metric"]
            if labels.get("cluster_id") != cluster_id or labels.get("container") != "worker":
                continue
            if not labels.get("namespace", "").startswith(("ff-h2-pilot-", "ff-h2-main-")):
                continue
            if labels.get("namespace") == "ff-h2-pilot-zero-diagnostic":
                # The diagnostic sleeper pulls the same image but does no ASR.
                continue
            ts = np.asarray(row["timestamps"], dtype=float) / 1000
            values = np.asarray(row["values"], dtype=float)
            if index == 0:
                intervals = np.diff(ts)
                delta = np.diff(values)
                good = (intervals > 0) & (intervals <= 240) & (delta >= 0)
                values = np.divide(delta, intervals, out=np.full(delta.shape, np.nan), where=good)
                ts = ts[1:]
            else:
                values = values / 2**20
            if not len(ts) or not np.isfinite(values).any():
                continue
            dates = [datetime.fromtimestamp(t, ZoneInfo("Europe/Moscow")) for t in ts]
            label = labels.get("namespace", "") + "/" + labels.get("pod", "")[-5:]
            axes[index].plot(dates, values, label=label, linewidth=1.4, marker="o", markersize=3)
            series += 1
    if not series:
        plt.close(fig)
        return {"available": False, "reason": "No native ASR worker samples yet; no empty result chart generated"}
    axes[0].set_ylabel("CPU, занятые ядра")
    axes[0].set_title("Разность нативного CPU-счётчика / интервал; пропуски >4 минут не соединяются", fontsize=9)
    axes[1].set_ylabel("Working set, MiB")
    axes[1].set_xlabel("Время, Москва (UTC+3)")
    axes[1].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7, tz=ZoneInfo("Europe/Moscow")))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=ZoneInfo("Europe/Moscow")))
    axes[0].axhline(1.5, color="#64748b", linestyle="--", linewidth=1, label="Лимит: 1,5 CPU на pod")
    axes[1].axhline(2048, color="#64748b", linestyle="--", linewidth=1, label="Лимит: 2048 MiB на pod")
    for axis in axes:
        axis.grid(alpha=.2)
        axis.set_ylim(bottom=0)
        handles, labels = axis.get_legend_handles_labels()
        if len(handles) <= 12:
            axis.legend(fontsize=7, loc="upper left", ncol=2)
    axes[0].set_ylim(0, max(1.65, axes[0].get_ylim()[1]))
    axes[1].set_ylim(0, max(2200, axes[1].get_ylim()[1]))
    finish(fig, out / "native-asr-resources")
    return {"available": True, "series": series, "source": "Native Cloud.ru Monitoring exports"}


def report(run):
    out = run / "figures"
    out.mkdir(exist_ok=True)
    state = read(run / "state.json")
    summary = {"at": stamp(), "trials": []}
    for directory in sorted((run / "trials").glob("*")):
        if (directory / "timeline.jsonl").exists():
            summary["trials"].append(trial_plot(directory, out))
    summary["native_resources"] = native_plot(run, out, state["cluster"]["id"])
    summary["pilot_only"] = not any(x and not x["pilot_only"] for x in summary["trials"])
    save(out / "sources.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    print(json.dumps(report(parser.parse_args().run), ensure_ascii=False))
