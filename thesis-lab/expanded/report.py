"""Export all cells, paired block bootstrap intervals, figures, and a Russian report."""

import csv
import hashlib
import json
from pathlib import Path
import random
import statistics as st
import sys
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read(path):
    return (
        [json.loads(x) for x in path.read_text().splitlines() if x]
        if path.exists()
        else []
    )


def q(values, percentile):
    a = sorted(values)
    if not a:
        return None
    x = (len(a) - 1) * percentile
    i = int(x)
    return a[i] + (a[min(i + 1, len(a) - 1)] - a[i]) * (x - i)


def ratio(baseline, candidate, field, percentile=None):
    b = {r["rep"]: r for r in baseline}
    c = {r["rep"]: r for r in candidate}
    keys = sorted(b.keys() & c.keys())
    assert keys

    def estimate(ids):
        if percentile is not None:
            return q([v for i in ids for v in c[i][field]], percentile) / q(
                [v for i in ids for v in b[i][field]], percentile
            )
        return st.mean(c[i][field] for i in ids) / st.mean(b[i][field] for i in ids)

    rng = random.Random(160916)
    draws = [estimate(rng.choices(keys, k=len(keys))) for _ in range(2000)]
    return dict(
        ratio=estimate(keys), ci95=[q(draws, 0.025), q(draws, 0.975)], blocks=len(keys)
    )


def export(root, name, rows):
    if not rows:
        return
    fields = sorted(set().union(*(r.keys() for r in rows)))
    with (root / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(
            {
                k: (
                    json.dumps(v, ensure_ascii=False)
                    if isinstance(v, (dict, list))
                    else v
                )
                for k, v in row.items()
            }
            for row in rows
        )


def table(lines, headers, rows):
    lines.extend(
        [
            "",
            "| " + " | ".join(headers) + " |",
            "|" + "|".join("---" for _ in headers) + "|",
        ]
    )
    lines.extend("| " + " | ".join(map(str, row)) + " |" for row in rows)


def rt(value):
    def number(x):
        return f"{x:.4f}" if 0 < abs(x) < 0.01 else f"{x:.2f}"

    return f"{number(value['ratio'])} [{number(value['ci95'][0])}; {number(value['ci95'][1])}]"


def main(root):
    lab = Path(__file__).resolve().parent.parent
    analysis_files = [
        "expanded/report.py",
        "expanded/verify.py",
        "scripts/audit_expanded_sources.py",
        "scripts/verify_expanded_final.py",
        "scripts/finish_expanded.py",
    ]
    (root / "analysis-versions.json").write_text(
        json.dumps(
            {
                name: hashlib.sha256((lab / name).read_bytes()).hexdigest()
                for name in analysis_files
            },
            indent=2,
        )
    )
    summary = {}
    lines = [
        "# Расширенная серия экспериментов Firefly",
        "",
        "Стенд использует отдельные worktree и отдельный Docker Compose-проект. Исходная серия не изменена.",
        "Все времена относятся к общей машине с CPU-лимитами, а не к production SLA. Пилоты исключены из таблиц.",
        "Технические повторы сгруппированы в блоки. 95% интервалы получены парным bootstrap по блокам (2000 выборок). "
        "Отношение меньше 1 означает снижение метрики. Интервалы не скорректированы на множественные сравнения; "
        "они описывают неопределённость на этом стенде, а не гарантируют переносимость на другие серверы.",
        "Сохранены необработанные измерения, план до запуска, хеши исходников, планы SQL и журнал допуска по нагрузке.",
    ]
    audit_path = root / "source-audit.json"
    if audit_path.exists():
        summary["source_audit"] = json.loads(audit_path.read_text())
        if not summary["source_audit"]["passed"]:
            review = json.loads((root / "source-audit-review.json").read_text())
            commits = "; ".join(
                f"{name}: {change['before_head'][:7]} → {change['after_head'][:7]}"
                for name, change in review["changes"].items()
            )
            checked_sources = json.loads((root / "verification.json").read_text())[
                "source_hashes_checked"
            ]
            lines += [
                "",
                f"**Примечание к изоляции:** строгая проверка Git-метаданных не прошла: {commits}. "
                "Проверенные файлы всех четырёх основных каталогов побайтно совпадают со снимком до запуска; "
                f"исходные baseline/candidate worktree и {checked_sources} проверенных файлов измерений сохранены. "
                "Отрицательный результат [строгого аудита](source-audit.json) оставлен как есть; "
                "[разбор изменения метаданных](source-audit-review.json) записан отдельно. Основной checkout не откатывался.",
            ]
    perf = read(root / "h2/h2-performance.jsonl")
    conc = read(root / "h2/h2-concurrent.jsonl")
    checks = read(root / "h2/h2-checks.jsonl")
    export(root, "h2-performance.csv", perf)
    export(root, "h2-concurrent.csv", conc)
    lines += [
        "",
        "## H2: атомарное сохранение и конкурентные редакторы",
        "",
        f"Проверено {len(perf)} сохранений, {len(conc)} конкурентных групп и {len(checks)} условий корректности.",
        "Сильная альтернатива snapshot — атомарный patch с теми же ExerciseUpdate-валидаторами, арендой и CAS версии. "
        "Здесь сравниваются изменения существующих упражнений. Создание/удаление структуры не покрывается patch.",
        "Latency обычного сохранения — сумма времени HTTP-вызовов. Байты — request/response bodies, без заголовков. "
        "Конкурентное время также включает перечитывание и безопасное повторение намерения. "
        "Это HTTP-модель редакторов с одним тестовым пользователем, разными намерениями и одинаковыми либо разными editor session ID; "
        "отдельно пройден regression harness очереди Session.",
        "Размер обмена учитывает контракты ответов: snapshot принимает и возвращает полный снимок, "
        "patch возвращает версию и ID изменённых упражнений. Выигрыш характеризует эти API целиком, "
        "включая объём ответа и серверную обработку. Начальная загрузка и контрольный GET после обычного сохранения "
        "в его latency не входят. Встраивание нового patch в UI Session этой серией не проверяется.",
    ]
    rows = []
    h2stats = []
    for size in (5, 25, 100):
        for edited in (2, (size + 1) // 2):
            selected = [r for r in perf if r["size"] == size and r["edited"] == edited]
            groups = {
                v: [r for r in selected if r["variant"] == v]
                for v in ("crud", "snapshot", "patch")
            }
            item = dict(
                size=size,
                edited=edited,
                means={v: st.mean(r["http_ms"] for r in g) for v, g in groups.items()},
                patch_snapshot_ms=ratio(groups["snapshot"], groups["patch"], "http_ms"),
                patch_snapshot_bytes=ratio(
                    groups["snapshot"], groups["patch"], "bytes"
                ),
            )
            h2stats.append(item)
            rows.append(
                [
                    size,
                    edited,
                    *[f"{item['means'][v]:.1f}" for v in groups],
                    rt(item["patch_snapshot_ms"]),
                    rt(item["patch_snapshot_bytes"]),
                ]
            )
    table(
        lines,
        [
            "Упражнений",
            "Правок",
            "CRUD, мс",
            "Snapshot, мс",
            "Patch, мс",
            "Patch/snapshot latency [CI]",
            "Patch/snapshot bodies [CI]",
        ],
        rows,
    )
    rows = []
    for variant in ("crud", "snapshot", "patch"):
        g = [r for r in conc if r["variant"] == variant]
        rows.append(
            [
                variant,
                len(g),
                sum(r["saved"] for r in g),
                sum(r["field_conflicts"] for r in g),
                sum(r["initial_partial_intents"] for r in g),
                sum(r["version_conflicts_409"] for r in g),
                sum(r["lease_conflicts_423"] for r in g),
            ]
        )
    table(
        lines,
        [
            "Вариант",
            "Групп",
            "Сохранённых намерений",
            "Конфликтов того же поля",
            "Частичных намерений после первой попытки",
            "Ответов 409",
            "Ответов 423",
        ],
        rows,
    )
    lines += [
        "",
        "Обновления разных упражнений повторно применяются после перечитывания; чужое изменение того же поля сохраняется и возвращается конфликт. "
        "409 и 423 разделены: конфликт версии и отказ аренды не считаются одной причиной. Частичность CRUD измеряется между физическими запросами одной логической операции.",
        "Отдельная проверка недопустимой второй правки различает транзакционные границы: "
        "после 400 у CRUD первая длительность остаётся изменённой с 5 на 7, вторая остаётся 5; "
        "у snapshot и patch обе остаются 5 и версия не увеличивается. "
        "passed=true для CRUD в domain_rollback означает, что наблюдалось именно ожидаемое частичное сохранение, а не общий rollback.",
    ]
    if not any(r["initial_partial_intents"] for r in conc):
        lines += [
            "",
            "В данной конкурентной матрице частично применённых намерений не зарегистрировано ни у одного варианта. "
            "Поэтому преимущество атомарности подтверждается проверкой отказа второй правки, "
            "а снижение частичности при этих конкретных конкурентных расписаниях не продемонстрировано.",
        ]
    summary["h2"] = dict(performance=h2stats, groups=len(conc), checks=len(checks))

    transport = read(root / "transport/h1.jsonl")
    browser = read(root / "browser/browser.jsonl")
    export(root, "h1-transport.csv", transport)
    export(root, "h1-browser.csv", browser)
    lines += [
        "",
        "## H1: HTTP-трафик и восстановление настоящего Instructor",
        "",
        f"Протокольный генератор завершил {len(transport)} тренировок; браузерная матрица содержит {len(browser)} случаев.",
        "Байты wire получены из TCP-прокси: HTTP/1.1 заголовки и переданные тела. TCP/IP/TLS не входят. "
        "Лимит скорости действует на каждое соединение; это управляемая модель сети, а не общий физический канал. "
        "Gzip применяется к ответам, если его принимает клиент; запросы не сжимаются. "
        "Текст неоднородный и воспроизводимый, но синтетический. Время доставки включает локальную SQLite-очередь генератора.",
        "Таблица ниже: крупный draft (~16 KiB) и сеть RTT 250 мс / 64 KiB/s; вся матрица доступна в CSV.",
    ]
    rows = []
    h1stats = []
    for compressed in (False, True):
        groups = {
            v: [
                r
                for r in transport
                if r["variant"] == v
                and r["cache_bytes"] == 16384
                and r["rtt_ms"] == 250
                and r["gzip"] == compressed
            ]
            for v in ("split_full", "split_compact", "unified_compact")
        }
        for variant, g in groups.items():
            row = dict(
                gzip=compressed,
                variant=variant,
                wire_bytes=st.mean(r["wire_bytes"] for r in g),
                delivery_ms=st.mean(r["delivery_ms"] for r in g),
                relative_full_ms=ratio(groups["split_full"], g, "delivery_ms"),
                relative_full_bytes=ratio(groups["split_full"], g, "wire_bytes"),
            )
            h1stats.append(row)
            rows.append(
                [
                    compressed,
                    variant,
                    f"{row['wire_bytes']/1024:.1f}",
                    f"{row['delivery_ms']:.1f}",
                    rt(row["relative_full_ms"]),
                    rt(row["relative_full_bytes"]),
                ]
            )
    table(
        lines,
        [
            "Gzip ответов",
            "Вариант",
            "Wire, KiB",
            "Доставка, мс",
            "Время / full [CI]",
            "Wire / full [CI]",
        ],
        rows,
    )
    lines += [
        "",
        "Flutter harness использует реальные TrainingDraftController, TrainingRuntimeController и IndexedDB из Instructor. "
        "Chromium завершается SIGKILL целиком; после повторного входа того же пользователя проверяются локальные данные до включения API. "
        "Это проверка компонентов приложения, а не всего UI и не физических Android/iOS.",
        "**Граница применимости:** основная матрица начинает с идентичности устройства, сохранённой штатным закрытием профиля. "
        "Отдельный отрицательный пилот нового профиля сохранил черновик и три события, но потерял writer ID в secure storage. "
        "Сквозная гарантия для немедленного падения нового профиля поэтому не подтверждена. "
        "[Сохранённые состояния отрицательного пилота](boundary-evidence/r0-lan-offline-1789578891252-states.json).",
    ]
    if browser:
        table(
            lines,
            [
                "Сеть",
                "Исходный сбой",
                "Случаев",
                "Корректно",
                "Медиана восстановления, мс",
                "Попыток submit",
            ],
            [
                [
                    net,
                    fault,
                    len(
                        g := [
                            r
                            for r in browser
                            if r["network"]["id"] == net and r["fault"] == fault
                        ]
                    ),
                    sum(r["correct"] for r in g),
                    f"{st.median(r['recoveryMs'] for r in g):.1f}",
                    sum(r["submitAttempts"] for r in g),
                ]
                for net in ("lan", "rtt80", "rtt250")
                for fault in ("offline", "lost_ack")
            ],
        )
    summary["h1"] = dict(
        transport=h1stats,
        trainings=len(transport),
        browser_cases=len(browser),
        fresh_profile_boundary="writer identity lost in retained pilot",
    )

    lines += [
        "",
        "## H3: исходный SQL, оптимизированный SQL и проекция",
        "",
        "Варианты работают с клонами одного seed в отдельных БД одного PostgreSQL. Оптимизированный SQL использует DISTINCT ON и индексы источника. "
        "Проекция получает те же индексы; её стоимость записи и хранения включена. "
        "Backend перезапускается между блоками, прогрев выполняется до измерений. Это тёплые чтения, не cold-cache benchmark.",
        "Результаты трёх вариантов сверены по восьми фильтрам; текущий и исторический срезы дополнительно проверены независимым арифметическим эталоном.",
        "Генератор создаёт одного оценённого пилота и восемь итоговых оценок на тренировку: "
        "профиль 100000 тренировок содержит 800000 строк final_report. "
        "Это заданная синтетическая структура данных, а не выборка эксплуатационных тренировок.",
        "Исторический срез зафиксирован на 2020-01-02 включительно. Тренировки следуют с минутным шагом с 2020-01-01: "
        "в большом профиле такой срез охватывает первые 2880 тренировок выбранной авиакомпании. "
        "Он характеризует раннюю дату истории; другие доли истории требуют отдельных измерений.",
        "Latency и throughput ниже относятся к успешным ответам. Все запланированные попытки, включая сетевые ошибки, "
        "сохранены без повторной отправки; ошибки показаны отдельно. Первый прерванный запуск H3 не включён в эту таблицу и сохранён в исходном каталоге.",
    ]
    readstats = []
    allread = []
    rows = []
    space = []
    diagnostics = []
    profile_order = (
        "history-1k",
        "history-10k",
        "history-100k",
        "pilots-100",
        "skew-80-10",
        "neighbors-4",
    )
    for p in sorted(
        (root / "reads").glob("*/dataset.json"),
        key=lambda p: profile_order.index(p.parent.name),
    ):
        folder = p.parent
        data = read(folder / "read-series.jsonl")
        for row in data:
            allread.append(dict(profile=folder.name, **row))
        for historical in (False, True):
            for concurrency in (1, 8):
                groups = {
                    v: [
                        r
                        for r in data
                        if r["variant"] == v
                        and bool(r["filters"]) == historical
                        and r["concurrency"] == concurrency
                    ]
                    for v in ("original", "optimized", "projection")
                }
                p95 = {
                    v: q([x for r in g for x in r["latencies_ms"]], 0.95)
                    for v, g in groups.items()
                }
                item = dict(
                    profile=folder.name,
                    historical=historical,
                    concurrency=concurrency,
                    p95=p95,
                    p50={
                        v: q([x for r in g for x in r["latencies_ms"]], 0.50)
                        for v, g in groups.items()
                    },
                    throughput={
                        v: sum(r["successful_requests"] for r in g)
                        / sum(r["seconds"] for r in g)
                        for v, g in groups.items()
                    },
                    errors={v: sum(r["errors"] for r in g) for v, g in groups.items()},
                    optimized_original=ratio(
                        groups["original"], groups["optimized"], "latencies_ms", 0.95
                    ),
                    projection_original=ratio(
                        groups["original"], groups["projection"], "latencies_ms", 0.95
                    ),
                    projection_optimized=ratio(
                        groups["optimized"], groups["projection"], "latencies_ms", 0.95
                    ),
                )
                readstats.append(item)
                rows.append(
                    [
                        folder.name,
                        "2020-01-02" if historical else "current",
                        concurrency,
                        *[f"{p95[v]:.1f}" for v in groups],
                        rt(item["projection_optimized"]),
                    ]
                )
        for v in ("original", "optimized", "projection"):
            plans = json.loads((folder / f"explain-{v}.json").read_text())
            for historical in (False, True):
                selected_plans = [
                    x["plan"][0] for x in plans if bool(x["as_of_date"]) == historical
                ]
                diagnostics.append(
                    dict(
                        profile=folder.name,
                        variant=v,
                        historical=historical,
                        statements=len(selected_plans),
                        execution_ms=sum(x["Execution Time"] for x in selected_plans),
                        **{
                            key: sum(x["Plan"].get(key, 0) for x in selected_plans)
                            for key in (
                                "Shared Hit Blocks",
                                "Shared Read Blocks",
                                "Temp Read Blocks",
                                "Temp Written Blocks",
                            )
                        },
                    )
                )
            s = json.loads((folder / f"storage-{v}.json").read_text())
            total = sum(r["bytes"] for r in s["tables"])
            space.append(
                dict(
                    profile=folder.name,
                    variant=v,
                    total_table_index_bytes=total,
                    projection_bytes=sum(
                        r["bytes"]
                        for r in s["tables"]
                        if r["relname"].startswith("commander_")
                    ),
                    source_index_bytes=sum(
                        r["bytes"]
                        for r in s["extra_source_indexes"]
                        if r["indexrelname"]
                        in {
                            "thesis_assessment_user_training",
                            "thesis_completed_training",
                            "thesis_latest_report",
                        }
                    ),
                )
            )
    table(
        lines,
        [
            "Профиль",
            "Срез",
            "Clients",
            "Original p95, мс",
            "Optimized p95, мс",
            "Projection p95, мс",
            "Projection/optimized p95 [CI]",
        ],
        rows,
    )
    export(root, "h3-read-series.csv", allread)
    export(root, "h3-comparisons.csv", readstats)
    export(root, "h3-storage.csv", space)
    export(root, "h3-sql-diagnostics.csv", diagnostics)
    table(
        lines,
        [
            "Профиль",
            "Ошибки original / попытки",
            "Ошибки optimized / попытки",
            "Ошибки projection / попытки",
        ],
        [
            [
                profile,
                *[
                    f"{sum(r['errors'] for r in allread if r['profile']==profile and r['variant']==v)} / {sum(r['requests'] for r in allread if r['profile']==profile and r['variant']==v)}"
                    for v in ("original", "optimized", "projection")
                ],
            ]
            for profile in profile_order
        ],
    )
    lines += [
        "",
        "Глубина истории и число пилотов варьируются отдельно. `skew-80-10` сосредотачивает 80% истории у 10% пилотов; "
        "`neighbors-4` добавляет четырёх соседних tenants. Полные EXPLAIN (ANALYZE, BUFFERS) сохранены отдельно от latency. "
        "SQL execution time, буферы и WAL в сырых рядах — разности pg_stat_statements по соответствующей БД. CPU backend не включает PostgreSQL.",
        "h3-sql-diagnostics.csv суммирует корневые счётчики девяти отдельно выполненных EXPLAIN для каждого среза. "
        "Их времена диагностические: порядок, нагрузка и состояние кэша отличаются от измеренных HTTP-блоков. "
        "Счётчики страниц характеризуют работу PostgreSQL, а не напрямую физические обращения к диску.",
        "![Сравнение с двумя контрольными вариантами](h3-strong-baselines.png)",
    ]
    summary["h3_reads"] = readstats
    summary["h3_storage"] = space
    table(
        lines,
        [
            "100 тыс. тренировок / 1000 пилотов",
            "Таблицы и индексы, MiB",
            "Индексы источника, MiB",
            "Проекция с индексами, MiB",
        ],
        [
            [
                r["variant"],
                f"{r['total_table_index_bytes']/2**20:.1f}",
                f"{r['source_index_bytes']/2**20:.1f}",
                f"{r['projection_bytes']/2**20:.1f}",
            ]
            for r in space
            if r["profile"] == "history-100k"
        ],
    )
    lines += [
        "",
        "Размеры сняты после установки и первичного заполнения, до смешанной нагрузки. "
        "Столбцы индексов и проекции входят в общий объём, а не добавляются к нему. "
        "Это pg_total_relation_size таблиц пользовательской схемы; WAL и служебные каталоги PostgreSQL не включены. "
        "p50, p95 и throughput каждой ячейки сохранены в h3-comparisons.csv; throughput — успешные ответы / полное время измеренных групп.",
    ]

    folder = root / "mixed/history-100k"
    mixed = read(folder / "mixed-series.jsonl")
    writes = read(folder / "mixed-writes.jsonl")
    reads = read(folder / "mixed-reads.jsonl")
    queue = read(folder / "mixed-queue.jsonl")
    for name, data in [
        ("h3-mixed-series.csv", mixed),
        ("h3-mixed-writes.csv", writes),
        ("h3-mixed-reads.csv", reads),
        ("h3-mixed-queue.csv", queue),
    ]:
        export(root, name, data)
    lines += [
        "",
        "## H3: смешанная нагрузка, свежесть и восстановление",
        "",
        "100000 тренировок / 1000 пилотов, поступление запросов задано на 30 секунд: 4 полных чтения/с и 1 либо 8 записей/с. "
        "Наблюдатели свежести создают дополнительную нагрузку; их количество опубликовано. "
        "Внутри одного случая каждый выбранный пилот изменяется один раз, что позволяет однозначно связать наблюдаемую оценку с записью. "
        "Свежесть измеряется монотонными часами драйвера от подтверждения записи до ответа с ожидаемым значением; "
        "она включает HTTP и дискретный опрос. PostgreSQL timestamps сохранены как дополнительная диагностика.",
        "Три повтора смешанных случаев дают описательную оценку; из двух отдельных аварийных случаев нельзя выводить вероятность безотказности.",
        "Операция записи — лабораторный HTTP endpoint, изменяющий grade, grade_code_snapshot и grade_score_snapshot "
        "одного существующего FinalReport с реальным commit. Метрики записи характеризуют эту корректировку строки, "
        "включая постановку пилота в очередь в варианте проекции. Аналитические чтения выполняются реальным сервисом Commander.",
    ]
    rows = []
    mixstats = []
    for crash in (False, True):
        for rate in (1, 8):
            for variant in (
                ("projection",) if crash else ("original", "optimized", "projection")
            ):

                def select(d):
                    return [
                        r
                        for r in d
                        if r["crash"] == crash
                        and r["write_rate"] == rate
                        and r["variant"] == variant
                    ]

                w = select(writes)
                r = select(reads)
                s = select(mixed)
                qq = select(queue)
                item = dict(
                    variant=variant,
                    rate=rate,
                    crash=crash,
                    writes=len(w),
                    write_errors=sum(x["status"] != 200 for x in w),
                    read_errors=sum(x["read_errors"] for x in s),
                    write_p95=q([x["http_ms"] for x in w], 0.95),
                    read_p95=q([x["http_ms"] for x in r], 0.95),
                    freshness_p95=q(
                        [x["freshness_ms"] for x in w if x["freshness_ms"] is not None],
                        0.95,
                    ),
                    censored=sum(not x["visible"] for x in w),
                    max_queue=max(x["pending"] for x in qq),
                    max_driver_wait_ms=max(x["driver_wait_ms"] for x in w),
                    max_read_driver_wait_ms=max(x["driver_wait_ms"] for x in r),
                    elapsed_seconds=sum(x["elapsed_s"] for x in s),
                    observers=sum(x["observer_requests"] for x in s),
                    backend_cpu_seconds=sum(x["backend_cpu_seconds"] for x in s),
                    sql_execution_ms=sum(x["sql_delta"]["executionMs"] for x in s),
                    sql_shared_hits=sum(x["sql_delta"]["sharedHits"] for x in s),
                    sql_shared_reads=sum(x["sql_delta"]["sharedReads"] for x in s),
                    sql_wal_bytes=sum(x["sql_delta"]["walBytes"] for x in s),
                )
                mixstats.append(item)
                rows.append(
                    [
                        variant,
                        rate,
                        crash,
                        len(w),
                        item["write_errors"],
                        f"{item['write_p95']:.1f}",
                        f"{item['read_p95']:.1f}",
                        f"{item['freshness_p95']:.1f}",
                        item["max_queue"],
                        item["censored"],
                    ]
                )
    table(
        lines,
        [
            "Вариант",
            "Write/s",
            "Crash",
            "Записей",
            "Ошибок записи",
            "Write p95, мс",
            "Read p95, мс",
            "Обнаружение p95, мс",
            "Max queue",
            "Не видно до дедлайна",
        ],
        rows,
    )
    crashes = read(folder / "worker-crashes.jsonl")
    processes = read(folder / "worker-processes.jsonl")
    recovery = []
    for series in mixed:
        if not series["crash"]:
            continue
        samples_for_case = [
            r for r in queue if r["crash"] and r["write_rate"] == series["write_rate"]
        ]
        before = series["worker_before"]
        detected = next(
            (r for r in samples_for_case if r["crashes"] > before["crashes"]), None
        )
        restarted = next(
            (r for r in samples_for_case if r["workerPid"] != before["workerPid"]), None
        )
        empty = next(
            (
                r
                for r in samples_for_case
                if r["workerPid"] != before["workerPid"] and r["pending"] == 0
            ),
            None,
        )
        recovery.append(
            dict(
                write_rate=series["write_rate"],
                observed_restart_ms=(
                    (restarted["offset_s"] - detected["offset_s"]) * 1000
                    if restarted and detected
                    else None
                ),
                observed_empty_queue_ms=(
                    (empty["offset_s"] - detected["offset_s"]) * 1000
                    if empty and detected
                    else None
                ),
            )
        )
    summary["worker_recovery"] = recovery
    table(
        lines,
        [
            "Записей/с",
            "От обнаружения сбоя до новой PID, мс",
            "До первого нуля очереди после рестарта, мс",
        ],
        [
            [
                r["write_rate"],
                (
                    round(r["observed_restart_ms"], 1)
                    if r["observed_restart_ms"] is not None
                    else "не зафиксировано"
                ),
                (
                    round(r["observed_empty_queue_ms"], 1)
                    if r["observed_empty_queue_ms"] is not None
                    else "не зафиксировано"
                ),
            ]
            for r in recovery
        ],
    )
    lines += [
        "",
        f'Сохранено {len(crashes)} аварийных записей worker и {sum(x["exit_code"]==77 for x in processes)} подтверждений exit 77. '
        "Процесс завершается до commit непустого пакета; supervisor ждёт 5 секунд. Для каждого аварийного случая "
        "проверяется рост счётчика, смена PID, опустошение очереди и видимость всех принятых записей.",
        "Время восстановления в таблице определяется по дискретным наблюдениям очереди (плановый интервал 250 мс плюс HTTP), "
        "поэтому это наблюдаемый интервал, а не точная длительность внутренних переходов. "
        "Начальная точка — первое наблюдение выросшего счётчика crashes: worker увеличивает его перед обработкой аварийного пакета, "
        "а фактический exit происходит после обработки, перед commit. Этот интервал включает оставшуюся работу пакета до exit.",
        "Свежесть не является строгой транзакционной согласованностью чтения. Решение о проекции должно учитывать "
        "её выигрыш относительно оптимизированного SQL, дополнительное хранение, стоимость обновления и допустимое устаревание.",
        "![Распределение задержки обнаружения](h3-freshness.png)",
    ]
    summary["h3_mixed"] = mixstats
    case_stats = []
    for case in mixed:
        own = [
            x
            for x in writes
            if all(x[k] == case[k] for k in ("variant", "write_rate", "rep", "crash"))
        ]
        case_stats.append(
            dict(
                **{
                    k: case[k]
                    for k in ("variant", "write_rate", "rep", "crash", "elapsed_s")
                },
                write_p95_ms=q([x["http_ms"] for x in own], 0.95),
                max_driver_wait_ms=max(x["driver_wait_ms"] for x in own),
            )
        )
    export(root, "h3-mixed-case-summary.csv", case_stats)
    summary["h3_mixed_cases"] = case_stats
    for variant in ("original", "optimized", "projection"):
        for rate in (1, 8):
            cases = sorted(
                [
                    x
                    for x in case_stats
                    if not x["crash"]
                    and x["variant"] == variant
                    and x["write_rate"] == rate
                ],
                key=lambda x: x["rep"],
            )
            values = [x["write_p95_ms"] for x in cases]
            if max(values) > 1000 and max(values) > 10 * min(values):
                detail = "; ".join(
                    f"rep={x['rep']}: {x['write_p95_ms']:.1f} мс" for x in cases
                )
                lines += [
                    "",
                    f"**Нестабильный случай сохранён:** {variant}, {rate} запись/с, p95 записи по повторам — {detail}. "
                    "Причина этого разброса не локализована; приписывать выброс архитектуре SQL нельзя. "
                    "Все повторы включены в агрегат. Значения по отдельным случаям и ожидание драйвера доступны в h3-mixed-case-summary.csv.",
                ]
    table(
        lines,
        [
            "Вариант",
            "Write/s задано",
            "Crash",
            "Время случаев, с",
            "Max ожидание записи в драйвере, мс",
            "Max ожидание чтения, мс",
        ],
        [
            [
                r["variant"],
                r["rate"],
                r["crash"],
                f"{r['elapsed_seconds']:.2f}",
                f"{r['max_driver_wait_ms']:.1f}",
                f"{r['max_read_driver_wait_ms']:.1f}",
            ]
            for r in mixstats
        ],
    )
    lines += [
        "",
        "Время случаев — сумма по трём обычным повторам или одному аварийному случаю, "
        "включая завершение запланированных запросов и наблюдателей после окна поступления. "
        "Ожидание в драйвере отсчитывается от запланированного момента до фактической отправки; "
        "HTTP latency начинается после него. Поэтому заданную частоту поступления нельзя считать доказательством устойчивой пропускной способности.",
    ]
    table(
        lines,
        [
            "Вариант",
            "Write/s",
            "Crash",
            "Наблюдений свежести",
            "Ошибок чтения",
            "Backend CPU, с",
            "SQL execution, с",
            "SQL WAL, MiB",
        ],
        [
            [
                r["variant"],
                r["rate"],
                r["crash"],
                r["observers"],
                r["read_errors"],
                f"{r['backend_cpu_seconds']:.2f}",
                f"{r['sql_execution_ms']/1000:.2f}",
                f"{r['sql_wal_bytes']/2**20:.2f}",
            ]
            for r in mixstats
        ],
    )
    batches = read(folder / "worker-batches.jsonl")
    summary["worker_batches"] = dict(
        completed=len(batches),
        items=sum(x["items"] for x in batches),
        processing_cpu_seconds=sum(x["cpu_seconds"] for x in batches),
        elapsed_ms=sum(x["elapsed_ms"] for x in batches),
    )
    lines += [
        "",
        "Ресурсы в таблице суммированы по трём обычным повторам или одному аварийному случаю. "
        "Они включают полный API-трафик измеренного случая, в том числе наблюдение свежести. "
        "SQL-метрики собраны для соответствующей БД и включают обновление проекции worker; execution time не равен CPU PostgreSQL. "
        "Backend CPU не включает CPU worker и БД. "
        f"Отдельно у worker зарегистрировано {len(batches)} завершённых пакетов, "
        f"{sum(x['items'] for x in batches)} обработок пилота и "
        f"{sum(x['cpu_seconds'] for x in batches):.2f} CPU-секунд обработки. "
        "Эта сумма не включает простой, запуск процесса и оборванные до commit пакеты; полная стоимость эксплуатации по ней не определяется.",
    ]
    samples = read(root / "host-samples.jsonl")
    idle = []
    for a, b in zip(samples, samples[1:]):
        if b["ticks"] > a["ticks"]:
            idle.append((b["idle_ticks"] - a["idle_ticks"]) / (b["ticks"] - a["ticks"]))
    summary["host"] = dict(
        samples=len(samples),
        max_load1=max(x["load1"] for x in samples),
        median_idle=st.median(idle),
        min_idle=min(idle),
    )
    lines += [
        "",
        "## Ограничения и интерпретация",
        "",
        f"Записано {len(samples)} отсчётов машины; median idle={st.median(idle):.1%}, max load1={max(x['load1'] for x in samples):.1f}. "
        "До блоков проверялся допуск, но внешняя нагрузка могла меняться внутри блока. Измерения после всплесков не удалялись.",
        "Эта серия расширяет инженерные основания диплома, но не является доказательством универсального превосходства архитектуры. "
        "Синтетические данные, один физический хост, ограниченный набор действий клиента и неизолированные ядра остаются угрозами внешней валидности.",
        "Результат H2 следует формулировать через атомарную границу и сохранение намерений, а выбор snapshot/patch делать по типу изменений. "
        "H3 оценивается прежде всего относительно оптимизированного SQL. H1 ограничивается явно проверенными условиями хранения идентичности.",
    ]
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    fig, (ax, strong) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    sel = [r for r in readstats if not r["historical"] and r["concurrency"] == 1]
    for j, key in enumerate(("optimized_original", "projection_original")):
        xx = [i + (j - 0.5) * 0.2 for i in range(len(sel))]
        yy = [r[key]["ratio"] for r in sel]
        color = f"C{j}"
        low = [r[key]["ci95"][0] for r in sel]
        high = [r[key]["ci95"][1] for r in sel]
        ax.plot(
            xx,
            yy,
            "o",
            color=color,
            label=("Оптимизированный / исходный", "Проекция / исходный")[j],
        )
        # Draw interval endpoints directly: a percentile interval need not contain the point estimate.
        ax.vlines(xx, low, high, color=color)
        ax.plot(xx, low, "_", color=color)
        ax.plot(xx, high, "_", color=color)
    ax.axhline(1, color="gray", ls="--")
    ax.set_xticks(range(len(sel)), [r["profile"] for r in sel], rotation=25)
    ax.set_ylabel("Отношение p95 к исходному SQL\n95% интервал bootstrap по блокам")
    ax.set_title("Сравнение с исходным SQL")
    ax.legend()
    xx = list(range(len(sel)))
    point = [r["projection_optimized"]["ratio"] for r in sel]
    low = [r["projection_optimized"]["ci95"][0] for r in sel]
    high = [r["projection_optimized"]["ci95"][1] for r in sel]
    strong.plot(xx, point, "o", color="C1")
    strong.vlines(xx, low, high, color="C1")
    strong.plot(xx, low, "_", color="C1")
    strong.plot(xx, high, "_", color="C1")
    strong.axhline(1, color="gray", ls="--")
    strong.set_xticks(xx, [r["profile"] for r in sel], rotation=25)
    strong.set_title("Проекция / оптимизированный SQL")
    strong.set_ylabel("Отношение p95; 95% интервал по блокам")
    fig.suptitle("Текущий срез, один клиент; меньше 1 — быстрее")
    fig.tight_layout()
    fig.savefig(root / "h3-strong-baselines.png", dpi=180)
    fig.savefig(root / "h3-strong-baselines.svg")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for v in ("original", "optimized", "projection"):
        vals = sorted(
            x["freshness_ms"]
            for x in writes
            if not x["crash"]
            and x["write_rate"] == 8
            and x["variant"] == v
            and x["freshness_ms"] is not None
        )
        ax.step(
            vals,
            [(i + 1) / len(vals) for i in range(len(vals))],
            where="post",
            label={
                "original": "Исходный SQL",
                "optimized": "Оптимизированный SQL",
                "projection": "Проекция",
            }[v],
        )
    ax.set_xlabel("Обнаружение после подтверждения записи, мс (8 записей/с)")
    ax.set_ylabel("Накопленная доля наблюдений")
    ax.set_title("Без сбоя: 100000 тренировок, 1000 пилотов, три повтора")
    ax.set_xscale("log")
    ax.legend()
    fig.tight_layout()
    fig.savefig(root / "h3-freshness.png", dpi=180)
    fig.savefig(root / "h3-freshness.svg")
    plt.close(fig)
    print("Expanded report written", root)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
