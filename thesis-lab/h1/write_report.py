"""Render the H1 report only from completed, audited and cleaned cloud evidence."""
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


def main(run):
    root = Path(__file__).resolve().parents[1]
    relative = run.relative_to(root).as_posix()
    def read(name):
        return json.loads((run / name).read_text())
    analysis = read('analysis/summary.json')
    audit = read('analysis/archive-audit.json')
    cleanup = read('cleanup.json')
    backup = read('backup-verified.json')
    assert cleanup['complete'] and backup['passed'] and audit['cases'] == 768
    resources = read('analysis/resource-summary.json')
    costs = read('analysis/cost-summary.json')['last']
    dashboard = read('dashboard.json')['url']
    started, ended = read('main-started.json')['at'], read('main-complete.json')['at']
    duration = (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds() / 60
    state = read('resources.json')
    cells = analysis['cells']
    def cell(variant, cache=16384, rtt=250, gzip=True, fault='clean'):
        return next(r for r in cells if r['variant'] == variant and r['cache'] == cache and
                    r['rtt_ms'] == rtt and r['gzip'] == gzip and r['fault'] == fault)
    variants = ('split_full', 'split_compact', 'unified_compact')
    def f(number, digits=3):
        return f'{number:,.{digits}f}'.replace(',', ' ').replace('.', ',')
    def link(name, label):
        return f'[{label}]({relative}/{name})'
    outcome = 'выполнены' if analysis['criteria_met'] and audit['passed'] else 'выполнены не полностью'
    lines = [
        '# H1: устойчивое завершение тренировки — эксперимент в Yandex Cloud', '',
        f'Запуск `{run.name}`. Предварительно объявленные критерии **{outcome}**.',
        f'Основная серия: {started} — {ended} (UTC), {f(duration, 1)} мин.',
        'Московское время: ' + datetime.fromisoformat(started).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M:%S') +
        ' — ' + datetime.fromisoformat(ended).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M:%S') + '.',
        '768 тренировок, 8 технических блоков, по 256 случаев на вариант. '
        'Сырые данные, отрицательные проверки и инфраструктурные журналы сохранены.', '',
        '## Сравнение и измеряемая величина', '',
        '`split_full` отправляет события и полный черновик отдельно; `split_compact` '
        'отправляет события и компактное состояние отдельно; `unified_compact` объединяет '
        'события и компактное состояние в общей транзакции. Во всех вариантах одинаковы '
        'SQLite-очередь, неизменяемое намерение завершения, проверка квитанции и повторы.', '',
        'Измеряется время от начала доставки сохранённой очереди до локального commit '
        'проверенной финальной квитанции. Авторизация, создание fixture и контрольная '
        'сверка БД вынесены за измеряемый интервал. Байты — заголовки и тела HTTP/1.1 '
        'на прокси, включая повторы; TCP/IP/TLS не учитываются. Gzip применяется к ответам.', '',
        'Отсчёт начинается перед запуском Python-процесса доставки, поэтому его запуск '
        'включён во все три варианта, как и восстановление после аварии. Это измерение '
        'полной протокольной цепочки в данном драйвере; скорость интерфейса Flutter '
        'требует отдельного исследования. Браузерные тесты проверяют корректность '
        'восстановления и не входят в сравнительную выборку времени.', '',
        'Рабочая нагрузка: шесть смен экипажа, связанные с событиями наблюдения, шесть '
        'оценочных состояний, терминальное упражнение и финальные оценки двух участников. '
        'Варианты используют FIFO без слияния промежуточных snapshot. Эксперимент '
        'не устанавливает оптимальность относительно всех возможных пакетных протоколов.', '',
        '## Основной профиль', '',
        '16 KiB справочного текста, добавленная RTT 250 мс, 64 KiB/s, gzip ответов, '
        'без сбоя. Этот профиль выбран до основной серии.', '',
        '| Вариант | n | p50, с | p95, с | Средние HTTP-байты | Средние попытки |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for variant in variants:
        r = cell(variant)
        lines.append(f"| `{variant}` | {r['n']} | {f(r['delivery_p50_ms']/1000)} | {f(r['delivery_p95_ms']/1000)} | {f(r['bytes_mean'],0)} | {f(r['requests_mean'],1)} |")
    lines += ['', 'Парное отношение unified/baseline: геометрическое среднее отношений '
              'по восьми блокам; 10 000 bootstrap-выборок, seed 20261004. '
              'Значение < 1 соответствует уменьшению метрики.', '',
              '| Baseline | Метрика | Отношение | 95% CI |', '|---|---|---:|---|']
    for r in analysis['comparisons']:
        if r['cache'] == 16384 and r['rtt_ms'] == 250 and r['gzip'] and r['fault'] == 'clean':
            digits = 5 if r['metric'] == 'wire_bytes' else 4
            lines.append(f"| `{r['baseline']}` | `{r['metric']}` | {f(r['ratio'],digits)} | [{f(r['ci95'][0],digits)}; {f(r['ci95'][1],digits)}] |")
    lines += ['', '## Полная матрица и корректность', '',
              'Без отказа: 2 размера × 3 сети × 2 режима gzip × 3 варианта × 8 блоков = 288. '
              'С отказами: 2 размера × 2 ограниченные сети × 5 отказов × 3 варианта × 8 блоков = 480. '
              'Порядок условий и вариантов рандомизирован, seed 20261004. Все результаты включены.', '',
              '| Вариант | Корректных завершений |', '|---|---:|']
    for variant in variants:
        lines.append(f"| `{variant}` | {analysis['successes'][variant]}/256 |")
    lines += ['', '| Предварительно объявленный критерий | Выполнен |', '|---|---|']
    labels = {'primary_time_reduced':'Уменьшение времени: верхняя граница CI < 1',
              'primary_bytes_reduced':'Уменьшение HTTP-байтов: верхняя граница CI < 1',
              'completion_noninferiority_2pp_conditional':'Допустимое ухудшение доли завершений: 2 п.п.',
              'zero_correctness_failures':'Нет ошибок доменной корректности',
              'all_faults_injected':'Все объявленные отказы действительно сработали'}
    for name, passed in analysis['criteria'].items():
        lines.append(f"| {labels[name]} | {'Да' if passed else 'Нет'} |")
    lines += ['', f"Консервативная нижняя 95% граница разности долей unified − full: **{f(analysis['completion_difference_lower95']*100,2)} п.п.** "
              'Расчёт Clopper–Pearson/Bonferroni условен относительно независимости Bernoulli-испытаний. '
              'Общие ВМ и управляемые отказы ограничивают эту интерпретацию; это не production SLA.', '',
              f"Дополнительная повторная сверка архивов: **{'пройдена' if audit['passed'] else 'не пройдена'}**. "
              'Проверены SQLite integrity, совпадение intent с fixture, квитанция, пустая очередь, '
              'неизменность байтов submit, признаки фактически внесённых отказов и доменные данные. '
              + link('analysis/archive-audit.json','Результат аудита') + '.', '',
              '## Сети и размеры данных без отказов', '',
              'p50 времени, секунды. В каждой клетке восемь наблюдений; p95 такой выборки '
              'используется только как описательная величина.', '',
              '| Текст, KiB | RTT, мс | gzip | split/full | split/compact | unified/compact |',
              '|---:|---:|---|---:|---:|---:|']
    for cache in (1024, 16384):
        for rtt in (0, 80, 250):
            for gzip in (False, True):
                values = ' | '.join(f(cell(v, cache, rtt, gzip)['delivery_p50_ms']/1000) for v in variants)
                lines.append(f"| {cache//1024} | {rtt} | {'Да' if gzip else 'Нет'} | {values} |")
    lines += ['', '## Графики', '']
    for filename, label in [('delivery','Время доставки'),('traffic','HTTP-трафик'),('faults','Завершение при отказах'),('paired-ratios','Парные отношения и интервалы'),('guest-resources','CPU и RAM гостевой ОС'),('native-cpu','Нативные данные YC'),('container-resources','Контейнеры backend и PostgreSQL'),('costs','Расходы в рублях')]:
        lines += [f'![{label}]({relative}/analysis/{filename}.png)', '']
    lines += ['## Инфраструктура и наблюдаемость', '',
              'Сервер: 8 vCPU / 16 GiB / 128 GiB SSD; генератор: 2 vCPU / 4 GiB / 32 GiB SSD. '
              'Ice Lake, 100% гарантированной доли CPU, без прерываемых ВМ. Backend и PostgreSQL '
              'каждый ограничены 2 vCPU / 3 GiB. Генератор расположен на другой ВМ; HTTP-прокси '
              'моделирует задержку и пропускную способность поверх настоящей приватной сети.', '',
              f'[Дашборд H1 в Yandex Monitoring]({dashboard}). Нативная CPU-метрика выгружена '
              'через API YC; RAM и метрики контейнеров собраны гостевым агентом каждые 10 секунд. '
              'Временные ряды описывают ресурсы всего стенда, без точного распределения CPU или '
              'стоимости между отдельными тренировками.', '',
              'Для повторного просмотра дашборда выберите указанный выше временной интервал. '
              'Для диплома сохранены также JSON-выгрузки и графики PNG/SVG: после прекращения '
              'поступления данных метрики Compute удаляются из Monitoring через 7 дней, '
              'обычные метрики — через 30 дней, согласно '
              '[документации YC](https://yandex.cloud/ru/docs/monitoring/qa/all). '
              'Архивные графики не зависят от наличия метрик в облаке.', '',
              '| ВМ | Выборок | Максимальный разрыв, с | CPU p95, % | RAM max, GiB | Ошибок экспорта |',
              '|---|---:|---:|---:|---:|---:|']
    for role, r in resources['roles'].items():
        m = r['whole_window']
        lines.append(f"| {role} | {r['sample_batches']} | {f(r['max_sample_gap_seconds'],1)} | {f(m['host_cpu_percent']['p95'],2)} | {f(m['host_memory_used_bytes']['max']/2**30,2)} | {len(r['export_errors'])} |")
    io = resources['roles']['loadgen']['whole_window']['host_iowait_percent']
    lines += ['', f"На генераторе нагрузки наблюдались пики iowait до {f(io['max'],2)}% "
              f"при p95 {f(io['p95'],2)}%. Соответствующие измерения сохранены без исключений. "
              'Ресурсные графики характеризуют этот стенд и не являются проверкой его предельной пропускной способности.', '',
              f"Плановая оценка ВМ, SSD и IPv4 от создания до удаления: **{f(costs['estimated_compute_disk_ip_rub'],2)} ₽**. "
              f"Предварительный Billing всего каталога за UTC-день: **{f(costs['billing_cost_before_credits_rub'],2)} ₽** до гранта, "
              f"**{f(costs['billing_expense_after_credits_rub'],2)} ₽** после зачёта льгот. "
              'Billing поступает с задержкой, включает другие расходы каталога за этот день '
              'и не является ценой отдельного варианта. Оценка не включает Monitoring и другие услуги. '
              'Снижение трафика не снижает автоматически цену фиксированной ВМ. '
              'Рубли на дашборде передаются в пользовательские метрики из API Billing '
              'и отдельного расчёта по тарифам; они не вычисляются из загрузки CPU.', '',
              '## Сохранность и ограничения вывода', '',
              'До серии проверено реальное выключение и повторный запуск генератора. '
              f"Предельное выключение было задано на {state['deadline']}. "
              'Дамп PostgreSQL восстановлен в отдельную пустую БД; сверены семь таблиц. '
              'Файлы скопированы с обеих ВМ и сверены по SHA-256. После этого удалены временные '
              'ВМ, диски, сеть, security groups и служебный аккаунт. Дашборд сохранён.', '',
              'Изменения приложений сделаны в отдельных worktree. Проверки целостности '
              'основных checkout и совпадения исходников на ВМ до/после основной серии сохранены. '
              'Локальные Chromium/Flutter-проверки описаны в '
              '[отдельном отчёте](H1_LOCAL_READINESS_20261004.md); они не входят в 768 облачных тренировок.', '',
              'Ограничения: один набор ВМ, синтетические данные, последовательная доставка, '
              'технические повторы и выбранные точки отказа. Авария процесса не равна потере '
              'питания. Android/iOS, очистка всего браузерного хранилища, конкурентная нагрузка '
              'и устойчивость OAuth-сессии этим экспериментом не проверены. Вывод относится '
              'к исследованным вариантам, нагрузке и сетевым профилям.', '',
              '## Артефакты', '',
              '- ' + link('H1_PLAN.md','План и критерии до основной серии'),
              '- ' + link('analysis/summary.json','Полные результаты и доверительные интервалы'),
              '- ' + link('analysis/cells.csv','Таблица всех клеток матрицы'),
              '- ' + link('artifacts/loadgen/main','Сырые случаи, SQLite-журналы и сетевые трассы'),
              '- ' + link('artifacts/server/backups/restore-check.json','Проверка восстановления PostgreSQL'),
              '- ' + link('cleanup.json','Удаление временных ресурсов'),
              '- ' + link('main-source-after.json','Сверка основных checkout'),
              '- ' + link('SHA256SUMS','Контрольные суммы архива'), '',
              'Контрольные суммы пакета исходников и образов: '
              '`dc155413955b2a16a43d195aa8eacd2a97c6092196e3635a8790521a264d70ea` '
              '(SHA-256 файла SHA256SUMS пакета `yc-h1-bundle-20261004-v2`).', '']
    text = '\n'.join(lines)
    path = root / 'YANDEX_CLOUD_H1_DURABLE_20261004.md'
    with path.open('x') as stream:
        stream.write(text)
    (run / 'REPORT.md').write_text(text.replace(relative + '/', '').replace('(H1_LOCAL_READINESS_20261004.md)', '(../../H1_LOCAL_READINESS_20261004.md)'))
    print(path)


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
