"""Export native Cloud.ru metrics and create a reproducible pilot dashboard.

Native node/pod metrics are NOT presented as a bill. Trial VM/disk allocation
and resource-level Billing evidence are collected separately.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import uuid

from h2.cloudru_access import NoRedirect
from h2.cloudru_ops import Cloud, save, stamp

METRICS = ("kube_node_info", "kube_pod_status_phase", "kube_pod_container_status_running",
           "kube_pod_container_status_restarts_total", "container_cpu_usage_seconds_total",
           "container_memory_working_set_bytes", "node_cpu_seconds_total",
           "node_memory_MemAvailable_bytes", "node_memory_MemTotal_bytes")


def export_metric(cloud, metric, start_ms, end_ms):
    if metric not in METRICS or start_ms >= end_ms:
        raise ValueError("Invalid bounded metric export")
    params = {"match": metric, "start": int(start_ms), "end": int(end_ms)}
    url = "https://monitoring.api.cloud.ru/v1/" + cloud.client.project_id + "/export_metrics?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + cloud.client.bearer()})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=60) as response:
        rows = [json.loads(line) for line in response if line.strip()]
    for row in rows:
        if "metric" not in row or len(row.get("values", [])) != len(row.get("timestamps", [])):
            raise ValueError("Incomplete or truncated Monitoring export")
    return rows


def dashboard_request(cluster_id):
    uuid.UUID(cluster_id)
    def scoped(expression):
        expression = expression.replace('namespace=~"ff-h2-pilot-.*",',
            'namespace=~"ff-h2-pilot-.*",namespace!="ff-h2-pilot-zero-diagnostic",')
        return re.sub(r"\b(" + "|".join(METRICS) + r")(\{)?",
            lambda match: match[1] + '{cluster_id="' + cluster_id + '"' + ("," if match[2] else "}"),
            expression)
    panels = [{"type": "text", "title": "Firefly H2 · облачный пилот", "description": "Область интерпретации",
        "position": {"i": "intro", "x": 0, "y": 0, "w": 12, "h": 3}, "properties": {"content":
            "Подготовка эксперимента: Kubernetes/KEDA, CPU ASR, один системный узел и 0–3 ASR-узла. "
            "Графики ниже — нативные метрики Cloud.ru. Число pod и зарегистрированных узлов не равно "
            "числу оплачиваемых ВМ. Стоимость измеряется отдельно по ID и времени существования ВМ/дисков "
            "с последующей сверкой Billing. Пилот не является подтверждением гипотезы."}}]
    queries = [
        ("Зарегистрированные узлы Kubernetes", "count(count by(node) (kube_node_info))", "Узлы", "Уникальные node; системный узел включён. Это не инвентарь оплачиваемых ВМ."),
        ("ASR pod: Running и Pending", [('Running', 'sum(kube_pod_status_phase{namespace=~"ff-h2-pilot-.*",pod=~"worker-.*",phase="Running"})'),
                                            ('Pending', 'sum(kube_pod_status_phase{namespace=~"ff-h2-pilot-.*",pod=~"worker-.*",phase="Pending"})')], "", "Pending показывает ожидание размещения и загрузки образа."),
        ("Использование CPU контейнерами ASR, ядра", 'sum by(namespace) (rate(container_cpu_usage_seconds_total{namespace=~"ff-h2-pilot-.*",container="worker"}[2m]))', "{{namespace}}", "Сглаживание rate: 2 минуты."),
        ("Память ASR, MiB", 'sum by(namespace) (container_memory_working_set_bytes{namespace=~"ff-h2-pilot-.*",container="worker"}) / 1048576', "{{namespace}}", "Working set; лимит одного ASR pod — 2048 MiB."),
        ("CPU узлов, %", '100 * (1 - avg by(hostname) (rate(node_cpu_seconds_total{mode="idle"}[2m])))', "{{hostname}}", "Нагрузка на CPU, не денежные затраты."),
        ("Доступная память узлов, %", '100 * node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes', "{{hostname}}", "MemAvailable / MemTotal."),
        ("Перезапуски контейнеров ASR", 'sum by(namespace) (kube_pod_container_status_restarts_total{namespace=~"ff-h2-pilot-.*",container="worker"})', "{{namespace}}", "Удалённые pod исчезают из этой метрики; сбои дополнительно фиксируются журналом очереди."),
    ]
    for index, (title, query, alias, description) in enumerate(queries):
        series = query if isinstance(query, list) else [(alias, query)]
        panels.append({"type": "timeseries", "title": title, "description": description,
            "position": {"i": str(index), "x": (index % 2) * 6, "y": 3 + (index // 2) * 6, "w": 6, "h": 6},
            "properties": {"queries": [{"refId": chr(65 + i), "legendAlias": label, "displayResults": True, "query": scoped(expr)}
                                        for i, (label, expr) in enumerate(series)],
                "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                "decimals": 2, "tooltip": {"show": True, "mode": "multi"},
                "leftAxis": {"chartType": "line", "interpolation": "linear", "thickness": 2, "opacity": 12,
                             "displayDots": False, "dotsSize": 1, "category": "default", "barAlignment": "middle"}}})
    return {"title": "Firefly H2 · пилот Cloud.ru · 2026-10-14", "description": "Нативные метрики CPU ASR. Экономические выводы требуют отдельного учёта VM/disk и Billing.",
            "panels": panels, "variables": []}


def export(cloud):
    out = cloud.run / "native-monitoring"
    out.mkdir(exist_ok=True)
    start = int(datetime.fromisoformat(cloud.state["created_at"]).timestamp() * 1000)
    end = int(datetime.now(UTC).timestamp() * 1000)
    summary = {"at": stamp(), "start_ms": start, "end_ms": end, "metrics": {}}
    for metric in METRICS:
        try:
            rows = export_metric(cloud, metric, start, end)
            save(out / (metric + ".json"), rows)
            summary["metrics"][metric] = {"series": len(rows), "points": sum(len(r["values"]) for r in rows)}
        except Exception as error:
            summary["metrics"][metric] = {"error": cloud.client.redact(str(error))}
    save(out / "summary.json", summary)
    return summary


def create_dashboard(cloud):
    # Retained for the owner after compute cleanup; this is a requested result artifact.
    path = "/api/monaas-dashboards/v1/projects/" + cloud.client.project_id + "/dashboards"
    body = dashboard_request(cloud.state["cluster"]["id"])
    body["title"] = "Firefly H2 · " + cloud.run.name
    save(cloud.run / "dashboard-request.json", body)
    identity_path = cloud.run / "dashboard-created.json"
    if identity_path.exists():
        identity = json.loads(identity_path.read_text())
    else:
        identity = cloud.mutate("monitoring", path, body=body, label="native-dashboard")
        save(identity_path, identity)
    actual = cloud.client.request("monitoring", path + "/" + str(identity["dashboardId"]))
    save(cloud.run / "dashboard-readback.json", actual)
    return identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "dashboard"])
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    cloud = Cloud(args.run)
    print(json.dumps(export(cloud) if args.action == "export" else create_dashboard(cloud), ensure_ascii=False))
