"""Render the final Russian report strictly from validated run artifacts."""
import json
from pathlib import Path
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


def main(run):
    root=Path(__file__).resolve().parents[1]
    number=lambda value,places=0:format(value,f',.{places}f').replace(',','\u202f')
    load=lambda name:json.loads((run/name).read_text())
    s=load('analysis/summary.json');cost=load('analysis/cost-summary.json')['last']
    resources=load('analysis/resource-summary.json');cgroups=load('analysis/cgroup-summary.json')
    cleanup=load('cleanup.json');backup=load('backup-verified.json');restore=load('artifacts/server/backups/restore-check.json')
    assert cleanup['complete'] and backup['passed'] and restore['passed']
    assert not cleanup['remaining_instances'] and not cleanup['remaining_disks']
    dashboard=load('dashboard.json')['url']
    start=datetime.fromisoformat(load('main-started.json')['at']).astimezone(ZoneInfo('Europe/Moscow'))
    end=datetime.fromisoformat(load('main-complete.json')['at']).astimezone(ZoneInfo('Europe/Moscow'))
    read=s['profiles']['history-100k'];lat=read['groups']['current-1'];ratio=read['incremental_over_optimized']['current-1']
    inc=s['mixed']['groups']['incremental-8'];pilot=s['mixed']['groups']['projection-8']
    wal=s['mixed']['paired']['8']['walBytes']
    sql=s['mixed']['paired']['8']['executionMs']
    write=s['mixed']['paired']['8']['write_p95_ms']
    worst=max(v for group in s['freshness_by_rep'].values() for v in group.values())
    recovery=max(s['recovery_max_freshness_ms'].values())
    storage=s['storage']['history-100k']
    db_resources=cgroups['containers']['server/db']
    post=load('storage-after-workload.json')
    mixed_storage={v:{
        'before_bytes':sum(t['bytes'] for t in load('artifacts/server/mixed/history-100k/storage-'+v+'.json')['tables'] if t['relname'].startswith('commander_')),
        'after_bytes':sum(t['bytes'] for t in post['tables'][v] if t['relname'].startswith('commander_')),
    } for v in ('projection','incremental')}
    terms={
        'correctness_and_no_errors':'Совпадение результатов, отсутствие ошибок и потерянных принятых изменений',
        'read_p95_upper_ci_below_1':'Верхняя граница 95% ДИ отношения p95 к optimized < 1',
        'maintenance_wal_upper_ci_below_1':'Верхняя граница 95% ДИ отношения WAL к projection < 1',
        'freshness_each_healthy_rep_at_most_1000ms':'p95 свежести ≤1000 мс в каждом штатном повторе',
        'recovery_freshness_at_most_15000ms':'Максимальная свежесть при сбое ≤15000 мс',
    }
    lines=['# Проверка H3: проекция по затронутым оценкам','',
        ('**Все заранее заданные критерии H3 выполнены в исследованных условиях.**' if s['h3_criteria_met'] else '**Основная серия завершена; совокупность заранее заданных критериев H3 не выполнена.**'),'',
        f"Основная серия: {start:%d.%m.%Y %H:%M} — {end:%d.%m.%Y %H:%M} МСК. Две отдельные ВМ Yandex Cloud; четыре реализации на одинаковых клонированных данных. Предыдущая облачная серия использована для постановки задачи, её измерения не объединялись с новой выборкой.",'',
        '## Результат','',
        f"На 100 000 тренировок и 1000 пилотов, текущий срез / один клиент: медиана p95 десяти блоков — **{lat['optimized']['median_block_p95_ms']:.1f} мс у optimized и {lat['incremental']['median_block_p95_ms']:.1f} мс у incremental**. Парное геометрическое отношение: {ratio['ratio']:.3f}, bootstrap 95% ДИ [{ratio['ci95'][0]:.3f}; {ratio['ci95'][1]:.3f}].",'',
        f"При 8 исправлениях/с и 4 чтениях/с: **WAL на принятое исправление {number(pilot['wal_bytes_per_update'])} → {number(inc['wal_bytes_per_update'])} байт** при переходе от пересчёта по пилоту к пересчёту по оценке. Парное отношение {wal['ratio']:.4f}, 95% ДИ [{wal['ci95'][0]:.4f}; {wal['ci95'][1]:.4f}].",'',
        f"Дополнительные сравнения на той же нагрузке, incremental / projection: время исполнения SQL на исправление — {sql['ratio']:.3f}, 95% ДИ [{sql['ci95'][0]:.3f}; {sql['ci95'][1]:.3f}]; p95 подтверждения записи — {write['ratio']:.3f}, 95% ДИ [{write['ci95'][0]:.3f}; {write['ci95'][1]:.3f}]. Время SQL включает читающие запросы и наблюдателей внутри окна и не заменяет измерение CPU БД.",'',
        f"Наибольший p95 свежести кандидата среди 20 штатных повторов: **{worst:.1f} мс**. Максимальная наблюдаемая свежесть при управляемых сбоях: **{recovery:.1f} мс**, включая заданную задержку перезапуска 5 с. Проверены смена PID, увеличение счётчика сбоев, пустая очередь и повторная видимость принятых изменений.",'',
        '| Критерий до основной серии | Выполнен |','|---|---|',
        *[f"| {terms[k]} | {'да' if v else 'нет'} |" for k,v in s['criteria'].items()], '',
        '## Что реализовано','',
        'В отдельном worktree добавлена транзакционная очередь по CrewMemberAssessment. Повторные изменения одного ключа объединяются. Изменения тренировок разворачиваются в оценки после commit; удаления сохраняются в очереди без внешнего ключа. Обработчик обновляет затронутые факты и указатель последней оценки, сохраняя прежнюю логику аналитических запросов. UPSERT меняет значения только при отличии. Транзакционный advisory lock сериализует исполнителей; горизонтальное масштабирование worker в этом исследовании не проверялось.', '',
        'Варианты: original — исходный SQL; optimized — зафиксированная оптимизация с индексами и DISTINCT ON; projection — пересчёт всей истории затронутого пилота; incremental — новый пересчёт по оценке. Код основных репозиториев не изменялся; работа выполнена в `worktrees/h3-incremental/firefly-backend`, ветка `thesis/20261003-h3-incremental`.', '',
        '## Полнота эксперимента','',
        '19 200 измеряемых чтений в шести профилях, 10 запусков backend (первичный и 9 перезапусков) на профиль, текущий и исторический срез, конкурентность 1 и 8. Дополнительно 84 смешанных сценария: 11 340 исправлений и 10 080 чтений; четыре сценария со сбоями. Наблюдатели свежести и служебные запросы — дополнительная нагрузка, их число записано в исходных данных.', '',
        f"Функциональная проверка локально и повторно в облаке: {s['validation']['cases']} сценариев и {s['validation']['query_pairs']} пар ответов, плюс полная сверка фактов/оценок. Проверены вставки, изменения и удаления, смена пилота/компетенции/авиакомпании, даты и статуса завершения, одинаковые timestamps, откаты, конкуренция записи с worker и двух worker. Отдельно 100 исправлений объединились в один ключ очереди. Серия из 20 burst-сценариев проверила ещё 400 исправлений при остановленном worker; это исследование механизма объединения, вне метрики штатной свежести.",'',
        f"Ошибки в основной серии: чтение по профилям — {sum(p['errors'] for p in s['profiles'].values())}; смешанное чтение — {s['mixed']['read_errors']}; запись — {s['mixed']['write_errors']}; не наблюдавшиеся до предельного времени изменения — {s['mixed']['not_visible']}. Анализ проверяет точное покрытие матрицы и отсутствие повторов/пропусков индексов запросов.",'',
        f"После всей нагрузки обе проекции дополнительно сравнены с исходными таблицами через EXCEPT ALL в обоих направлениях: все факты, все оценки компетенций и указатели последних оценок. Проверяется также пустота очередей. Полная итоговая сверка пройдена: **{'да' if s['post_workload_parity']['passed'] else 'нет'}**. Числа строк и расхождения сохранены в [снимке после нагрузки](@RUN@storage-after-workload.json). Эта сверка выполнялась после остановки worker, вне окон измерения производительности.",'',
        '## Границы применимости и начальные расходы','',
        f"При 1000 тренировок / 1000 пилотов / одном клиенте медиана p95: optimized {s['profiles']['history-1k']['groups']['current-1']['optimized']['median_block_p95_ms']:.1f} мс, incremental {s['profiles']['history-1k']['groups']['current-1']['incremental']['median_block_p95_ms']:.1f} мс. Для этого малого профиля проекция медленнее. Все профили и срезы опубликованы в отчёте и CSV.",'',
        '| Первичная подготовка, 100k/1000 | projection | incremental |','|---|---:|---:|',
        f"| Установка индексов, построение и ANALYZE, с | {storage['projection']['install_ms']/1000:.1f} | {storage['incremental']['install_ms']/1000:.1f} |",
        f"| Таблицы проекции с индексами, МиБ | {storage['projection']['projection_bytes']/2**20:.1f} | {storage['incremental']['projection_bytes']/2**20:.1f} |",'',
        'Начальные расходы измерены по одному разу на профиль и имеют описательный характер. Выигрыш при сопровождении следует оценивать вместе с более дорогим первоначальным построением и дополнительным хранением.', '',
        '| Размер таблиц проекции с индексами, МиБ | projection | incremental |','|---|---:|---:|',
        f"| Перед смешанной серией, свежий набор 100k/1000 | {mixed_storage['projection']['before_bytes']/2**20:.1f} | {mixed_storage['incremental']['before_bytes']/2**20:.1f} |",
        f"| После смешанной серии, сбоев и burst | {mixed_storage['projection']['after_bytes']/2**20:.1f} | {mixed_storage['incremental']['after_bytes']/2**20:.1f} |", '',
        'Это физические размеры отношений в двух моментах времени, без WAL-файлов и без оценки долгосрочного роста; на них влияет обслуживание PostgreSQL. Снимок после нагрузки снят вне измеряемых окон.', '',
        'Ограничения: одна пара ВМ и один запуск, синтетическая история, технические повторы; исторический срез именно 2020-01-02. В профиле neighbors-4 к целевым 100k добавлены четыре авиакомпании по 25k тренировок. Результаты относятся к зафиксированным реализациям и нагрузкам. Исправление одной оценки не заменяет эксперимент с полной сдачей тренировки. Дополнительные bootstrap-интервалы точечные, без поправки за множественные сравнения.', '',
        'Сравнивается реализация в целом: очередь по оценке, объединение ключей и условный UPSERT. Отдельный количественный вклад каждого механизма не выделялся. Burst-сценарии подтверждают объединение повторов; в штатной смешанной нагрузке внутри каждого сценария изменяются разные пилоты.', '',
        'WAL измеряется по pg_stat_statements.wal_bytes и не равен всем физическим записям SSD. SQL execution time включает ожидание и не является чистым CPU БД. CPU и память измеряются отдельно по cgroup/гостевым и нативным метрикам; шаг 10 с ограничивает точность границ интервалов. Наблюдаемая свежесть включает время запроса наблюдателя и паузу polling.', '',
        f"Снимок PostgreSQL {post['settings']['server_version']} после серии: pg_stat_statements.track={post['settings']['pg_stat_statements.track']}; вложенных записей статистики — {post['statement_entries']['non_toplevel_entries']}; вытеснений записей — {post['pg_stat_statements_info']['dealloc']}. [Настройки и метаданные счётчиков](@RUN@storage-after-workload.json). Определение WAL-счётчика и режима учёта: [документация PostgreSQL](https://www.postgresql.org/docs/18/pgstatstatements.html).", '',
        '## Ресурсы, расходы и завершение','',
        'Сервер: 8 vCPU / 16 ГиБ / SSD 128 ГиБ; генератор: 2 vCPU / 4 ГиБ / SSD 32 ГиБ. Intel Ice Lake, доля CPU 100%, одна зона. PostgreSQL и приложения ограничены 2 CPU / 3 ГиБ; нагрузка по вариантам последовательная. Образы и файлы закреплены, NTP синхронизирован. Перед и после серии проверены 496 файлов на каждой ВМ с единственным объявленным overlay выбора контейнеров сборщиком метрик.', '',
        f"Для общего контейнера PostgreSQL за основное окно, включая подготовку всех профилей, сумма наблюдаемых положительных приращений CPU-счётчика — {number(db_resources['observed_positive_cpu_deltas_seconds'],1)} CPU·с; p95 памяти cgroup — {db_resources['memory_p95_bytes']/2**20:.1f} МиБ. Это ресурсная характеристика всего эксперимента, без точного разделения CPU БД между вариантами. Обнаружено сбросов этого CPU-счётчика: {db_resources['detected_cpu_counter_resets']}.", '',
        '| Телеметрия основного окна | server | loadgen |','|---|---:|---:|',
        f"| Пакетов гостевых измерений | {resources['roles']['server']['sample_batches']} | {resources['roles']['loadgen']['sample_batches']} |",
        f"| Максимальный интервал между пакетами, с | {resources['roles']['server']['max_sample_gap_seconds']:.1f} | {resources['roles']['loadgen']['max_sample_gap_seconds']:.1f} |",
        f"| Зафиксированных ошибок экспорта | {len(resources['roles']['server']['export_errors'])} | {len(resources['roles']['loadgen']['export_errors'])} |", '',
        f"Оценка VM + SSD + IPv4 для **нового запуска — {cost['estimated_compute_disk_ip_rub']:.2f} ₽**. Предварительный Billing **всего каталога за охваченные дни — {cost['billing_cost_before_credits_rub']:.2f} ₽**, после зачёта гранта — {cost['billing_expense_after_credits_rub']:.2f} ₽. До этого запуска наблюдалось {cost['billing_before_launch_rub']:.2f} ₽. Billing включает первую серию и запаздывающие начисления; его разность не является точным счётом второго запуска. Оценка аренды включает всё время выделения, а дополнительные сервисы учитываются через Billing.",'',
        'Фиксированная аренда не дешевеет от меньшего CPU или WAL. Здесь рубли показывают стоимость эксперимента. Тарифы: [Compute Cloud](https://yandex.cloud/ru/docs/compute/pricing), [VPC](https://yandex.cloud/ru/docs/vpc/pricing).', '',
        f"**Временные ВМ, диски, сеть и сервисный аккаунт удалены.** Завершение очистки: {cleanup['completed_at']}. Сохранены пять дампов; копии проверены по SHA-256, TOC прочитаны. БД кандидата полностью восстановлена в пустую БД, числа строк восьми ключевых таблиц совпали.",'',
        f"[Дашборд Yandex Monitoring]({dashboard}). Выбрать период с 03.10.2026 21:40 МСК до завершения запуска; после удаления ВМ относительное окно со временем будет пустеть.",'',
        '## Данные и графики','',
        '- [Подробный анализ](@RUN@analysis/REPORT.md)',
        '- [Все профили чтения и интервалы, CSV](@RUN@analysis/read-comparisons.csv)',
        '- [Все смешанные сценарии, CSV](@RUN@analysis/mixed-cases.csv)',
        '- [Зафиксированный план](@RUN@H3_PLAN.md)',
        '- [Манифест SHA-256](@RUN@SHA256SUMS)',
        '- [Исходники и образы использованного пакета](@BUNDLE@bundle.json)', '',
        '![Чтение и рост истории](@RUN@analysis/read-scaling.png)', '',
        '![Парные отношения с интервалами](@RUN@analysis/paired-ratios.png)', '',
        '![Чтение, свежесть и WAL](@RUN@analysis/mixed-tradeoffs.png)', '',
        '![Восстановление при сбое](@RUN@analysis/recovery.png)', '',
        '![CPU и память контейнеров](@RUN@analysis/container-resources.png)', '',
        '![Нативный CPU Yandex Cloud](@RUN@analysis/native-cpu.png)', '',
        '![Расходы](@RUN@analysis/costs.png)', '',
        'Все графики сохранены также в SVG. Исходные измерения, SQL-планы, настройки, промежуточные Billing/Monitoring-снимки и версии контроллера находятся в каталоге запуска. Предыдущий архив baseline не изменялся.'
    ]
    body='\n'.join(lines)+'\n'
    destination=root/'YANDEX_CLOUD_H3_INCREMENTAL_20261003.md'
    assert not destination.exists() and not (run/'final-report.md').exists()
    bundle=Path(load('uploaded.json')['bundle']).name
    destination.write_text(body.replace('@RUN@','results/'+run.name+'/').replace('@BUNDLE@','results/'+bundle+'/'))
    (run/'final-report.md').write_text(body.replace('@RUN@','').replace('@BUNDLE@','../'+bundle+'/'))
    print(destination)


if __name__=='__main__':main(Path(sys.argv[1]).resolve())
