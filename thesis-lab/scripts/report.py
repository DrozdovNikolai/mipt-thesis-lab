"""Generate CSV, descriptive statistics, paired cluster-bootstrap CIs and exportable plots."""

import csv
import json
from pathlib import Path
import random
import statistics as st
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(sys.argv[1]).resolve()


def read(name):
    p = root / name
    return (
        [json.loads(line) for line in p.read_text().splitlines() if line]
        if p.exists()
        else []
    )


def quantile(values, q):
    a = sorted(values)
    x = (len(a) - 1) * q
    i = int(x)
    return a[i] + (a[min(i + 1, len(a) - 1)] - a[i]) * (x - i)


def csv_export(name, rows):
    if not rows:
        return
    keys = sorted(set().union(*(r.keys() for r in rows)))
    with (root / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    k: (
                        json.dumps(v, ensure_ascii=False)
                        if isinstance(v, (dict, list))
                        else v
                    )
                    for k, v in r.items()
                }
            )


def interval(baseline, candidate, metric, percentile=False):
    """Resample matched independent SERIES, keeping requests inside each series together."""
    b = {x["rep"]: x for x in baseline}
    c = {x["rep"]: x for x in candidate}
    keys = sorted(b.keys() & c.keys())
    if not keys:
        return None

    def estimate(selected):
        if percentile:
            bb = [v for i in selected for v in b[i][metric]]
            cc = [v for i in selected for v in c[i][metric]]
            return quantile(cc, 0.95) / quantile(bb, 0.95)
        return st.mean(c[i][metric] for i in selected) / st.mean(
            b[i][metric] for i in selected
        )

    rng = random.Random(9016)
    samples = [estimate(rng.choices(keys, k=len(keys))) for _ in range(2000)]
    return dict(
        ratio=estimate(keys),
        ci95=[quantile(samples, 0.025), quantile(samples, 0.975)],
        paired_series=len(keys),
    )


def ratio_text(result):
    return f"{result['ratio']:.2f} [{result['ci95'][0]:.2f}; {result['ci95'][1]:.2f}]"


def table(lines, headers, rows):
    lines += [
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines += ["| " + " | ".join(map(str, r)) + " |" for r in rows]


h1 = read("h1.jsonl")
h2 = read("h2.jsonl")
h3 = read("h3.jsonl")
checks = read("h3-checks.jsonl")
for name, rows in [
    ("h1.csv", h1),
    ("h2.csv", h2),
    ("h3.csv", h3),
    ("h3-checks.csv", checks),
    ("http.csv", read("requests.jsonl")),
    ("h3-http.csv", read("h3-requests.jsonl")),
]:
    csv_export(name, rows)
lines = [
    "# Экспериментальный отчёт Firefly",
    "",
    f"Каталог: `{root.name}`.",
    (
        "Серия завершена."
        if (root / "complete.json").exists()
        else "**Серия не завершена: выводы предварительные.**"
    ),
    "",
    "Реальный TCP HTTP/Uvicorn и PostgreSQL. Контрольный backend запущен из baseline worktree; экспериментальный — из candidate.",
    "Исходные запросы, конфигурация и хеши кода сохранены рядом. Пилоты не включены в этот отчёт.",
    "",
    "Общая машина с посторонней нагрузкой; приведённые задержки не являются production SLA. "
    "95% интервалы ниже получены парным bootstrap по повторным сериям, а не по отдельным запросам. "
    "Шесть повторов дают ориентировочную оценку неопределённости. Отношение candidate/baseline меньше 1 означает снижение метрики.",
]
summary = {}
if h1:
    lines += [
        "",
        "## H1. Синхронизация",
        "",
        f"Завершено и проверено: {sum(r['correct_completion'] for r in h1)}/{len(h1)} тренировок. "
        "Проверены тексты и идентификаторы комментариев, число событий и повторная финализация. "
        "Эта выборка не устанавливает статистическую non-inferiority с узким допуском и не доказывает отсутствие всех возможных потерь.",
        "Измеряются байты JSON request/response bodies, включая повторы; заголовки, TCP и TLS не учитываются. "
        "В lost_ack_restart время включает запуск отдельного Python-процесса.",
    ]
    rows = []
    summ = []
    for cache in sorted({r["cache_bytes"] for r in h1}):
        for fault in sorted({r["fault"] for r in h1}):
            b = [
                r
                for r in h1
                if r["cache_bytes"] == cache
                and r["fault"] == fault
                and r["variant"] == "split_full"
            ]
            for v in ("split_full", "split_compact", "unified_compact"):
                a = [
                    r
                    for r in h1
                    if r["cache_bytes"] == cache
                    and r["fault"] == fault
                    and r["variant"] == v
                ]
                if not a:
                    continue
                ci = interval(b, a, "body_bytes")
                tci = interval(b, a, "delivery_ms")
                row = dict(
                    cache_bytes=cache,
                    fault=fault,
                    variant=v,
                    n=len(a),
                    mean_body_bytes=st.mean(x["body_bytes"] for x in a),
                    mean_requests=st.mean(x["requests"] for x in a),
                    median_delivery_ms=st.median(x["delivery_ms"] for x in a),
                    bytes_ratio=ci,
                    time_ratio=tci,
                )
                summ.append(row)
                rows.append(
                    [
                        cache,
                        fault,
                        v,
                        len(a),
                        f"{row['mean_body_bytes']/1024:.1f}",
                        f"{row['mean_requests']:.1f}",
                        f"{row['median_delivery_ms']:.1f}",
                        ratio_text(ci),
                    ]
                )
    table(
        lines,
        [
            "UI-кэш, байт",
            "Профиль",
            "Вариант",
            "n",
            "КиБ/трен.",
            "Запросы",
            "Медиана доставки, мс",
            "Отношение байтов [CI]",
        ],
        rows,
    )
    summary["h1"] = summ
    fig, ax = plt.subplots(figsize=(8, 4))
    variants = ["split_full", "split_compact", "unified_compact"]
    for i, cache in enumerate((0, 16384)):
        vals = [
            st.mean(
                r["body_bytes"]
                for r in h1
                if r["cache_bytes"] == cache
                and r["fault"] == "clean"
                and r["variant"] == v
            )
            / 1024
            for v in variants
        ]
        ax.bar(
            [j + (i - 0.5) * 0.36 for j in range(3)],
            vals,
            width=0.36,
            label=f"UI cache {cache} bytes",
        )
    ax.set_xticks(range(3), variants)
    ax.set_ylabel("JSON KiB / training")
    ax.legend()
    ax.set_title("H1: successful delivery, 12 observations")
    fig.tight_layout()
    fig.savefig(root / "h1-traffic.png", dpi=180)
    fig.savefig(root / "h1-traffic.svg")
    plt.close(fig)
    lines += ["", "![Объём синхронизации](h1-traffic.png)"]
if h2:
    lines += [
        "",
        "## H2. Сохранение сценария",
        "",
        "Частоты относятся к заданной матрице внедрённых сбоев, а не к вероятности этих сбоев в эксплуатации. "
        "Для interrupted_between снимок не отправлялся, поэтому этот профиль не включён в сравнение скорости.",
        "Время измеряет только HTTP-сохранение; создание сценария, чтение исходной версии и проверка результата исключены.",
    ]
    rows = []
    for fault in sorted({x["fault"] for x in h2}):
        for v in ("crud_legacy", "crud_versioned", "snapshot"):
            a = [x for x in h2 if x["fault"] == fault and x["variant"] == v]
            rows.append(
                [
                    fault,
                    v,
                    len(a),
                    sum(x["partial"] for x in a),
                    sum(x["lost_update"] for x in a),
                    sum(x["conflict_detected"] for x in a),
                ]
            )
    table(
        lines,
        [
            "Профиль",
            "Вариант",
            "Операции",
            "Частичные",
            "Потеря чужой правки",
            "Явные конфликты",
        ],
        rows,
    )
    rows = []
    summ = []
    for size in sorted({r["size"] for r in h2}):
        b = [
            r
            for r in h2
            if r["size"] == size
            and r["fault"] == "clean"
            and r["variant"] == "crud_versioned"
        ]
        for v in ("crud_legacy", "crud_versioned", "snapshot"):
            a = [
                r
                for r in h2
                if r["size"] == size and r["fault"] == "clean" and r["variant"] == v
            ]
            ci = interval(b, a, "save_ms")
            summ.append(dict(size=size, variant=v, time_ratio_vs_versioned_crud=ci))
            rows.append(
                [
                    size,
                    v,
                    f"{st.median(x['save_ms'] for x in a):.1f}",
                    f"{st.mean(x['body_bytes'] for x in a)/1024:.1f}",
                    ratio_text(ci),
                ]
            )
    table(
        lines,
        [
            "Упражнения",
            "Вариант",
            "Медиана, мс",
            "КиБ/сохранение",
            "Время / CRUD с CAS [CI]",
        ],
        rows,
    )
    summary["h2"] = summ
if h3:
    lines += [
        "",
        "## H3. Аналитика",
        "",
        "Исследован endpoint распределения оценок компетенций. Проекция обновляется по затронутым пилотам "
        "и сохраняет историю для asOfDate; результаты не распространяются автоматически на все экраны Commander.",
        f"Проверки совпадения и устойчивости: {sum(x.get('count',1) for x in checks)}; "
        f"успешные записи проверок: {sum(x['passed'] for x in checks)}/{len(checks)}. "
        "Начальная выборка дополнительно проверена независимым арифметическим эталоном.",
    ]
    rows = []
    summ = []
    groups = sorted(
        {
            (r["size"], json.dumps(r["filters"], sort_keys=True), r["concurrency"])
            for r in h3
        }
    )
    for size, f, c in groups:
        variants = {
            v: [
                r
                for r in h3
                if r["size"] == size
                and json.dumps(r["filters"], sort_keys=True) == f
                and r["concurrency"] == c
                and r["variant"] == v
            ]
            for v in ("baseline", "projection")
        }
        if not all(variants.values()):
            continue
        ci = interval(
            variants["baseline"],
            variants["projection"],
            "latencies_ms",
            percentile=True,
        )
        for v, a in variants.items():
            vals = [x for r in a for x in r["latencies_ms"]]
            result = dict(
                size=size,
                filters=json.loads(f),
                concurrency=c,
                variant=v,
                n=len(vals),
                p50_ms=quantile(vals, 0.5),
                p95_ms=quantile(vals, 0.95),
                p99_ms=quantile(vals, 0.99),
                mean_throughput=st.mean(r["throughput"] for r in a),
                backend_cpu_ms_per_request=1000
                * sum(r["backend_cpu_seconds"] for r in a)
                / len(vals),
                p95_ratio=ci,
            )
            summ.append(result)
            rows.append(
                [
                    size,
                    "asOf" if f != "{}" else "current",
                    c,
                    v,
                    len(vals),
                    f"{result['p50_ms']:.1f}",
                    f"{result['p95_ms']:.1f}",
                    f"{result['mean_throughput']:.1f}",
                    ratio_text(ci) if v == "projection" else "—",
                ]
            )
    table(
        lines,
        [
            "Тренировки",
            "Срез",
            "Клиенты",
            "Вариант",
            "n",
            "p50, мс",
            "p95, мс",
            "Запросы/с",
            "Отношение p95 [CI]",
        ],
        rows,
    )
    summary["h3"] = summ
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, concurrency in zip(axes, (1, 8)):
        for v in ("baseline", "projection"):
            a = [
                x
                for x in summ
                if x["variant"] == v
                and x["concurrency"] == concurrency
                and x["filters"] == {}
            ]
            ax.plot(
                [x["size"] for x in a], [x["p95_ms"] for x in a], marker="o", label=v
            )
        ax.set_xscale("log")
        ax.set_xlabel("Training sessions in selected tenant")
        ax.set_ylabel("HTTP p95, ms")
        ax.set_title(f"H3: {concurrency} concurrent clients")
        ax.legend()
    fig.tight_layout()
    fig.savefig(root / "h3-latency.png", dpi=180)
    fig.savefig(root / "h3-latency.svg")
    plt.close(fig)
    lines += [
        "",
        "![Задержка аналитики](h3-latency.png)",
        "",
        "Размеры таблиц и время полного построения: `h3-storage.jsonl`. "
        "Задержка очереди в `h3-checks.jsonl` измерена часами PostgreSQL от постановки события до обработки; "
        "это не отдельная оценка SLA при непрерывном потоке записей.",
    ]
lines += [
    "",
    "## Ограничения",
    "",
    "Синтетические данные и заданные точки сбоев. SQLite-драйвер бенчмарка H1 написан на Python; "
    "надёжность реального Flutter-хранилища проверяется отдельными тестами SQLite/IndexedDB. "
    "Наличие успешных тестов не доказывает корректность на любом устройстве или при любом отказе. "
    "Физические Android/iOS, отключение питания и реальные условия эксплуатации в эти результаты не входят.",
    "Дополнительное пространство и работа обработчика являются ценой проекции. "
    "Исторические запросы и небольшие наборы данных могут не ускориться. "
    "Сохранение полного сценария может быть дороже точечного обновления; преимущества целостности и скорости оцениваются отдельно.",
]
(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
(root / "REPORT.md").write_text("\n".join(lines) + "\n")
print(root / "REPORT.md")
