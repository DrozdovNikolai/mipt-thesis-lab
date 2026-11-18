"""Render the completed short optimization pilot, keeping evidence types distinct."""
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    return json.loads(path.read_text())


def main(output):
    local = output / 'local-asr-v2'
    runs, summary = read(local / 'runs.json'), read(local / 'summary.json')
    trace = read(output / 'traces/analysis.json')
    parity = read(local / 'local-parity.json')
    idle = read(output / 'idle-simulation-v2/simulation.json')
    assert summary['completed'] and parity['same_local_baseline'] == parity['measured_tasks'] == 36
    assert all(run['cpu_max'] == '150000 100000' for run in runs)
    for name, expected in read(local / 'plan.json')['source_sha256'].items():
        assert hashlib.sha256((local / 'sources' / name).read_bytes()).hexdigest() == expected
    # Retain actual metadata, never docker Config.Env or other project settings.
    hardware = json.loads(subprocess.check_output(['lscpu', '--json']))['lscpu']
    metadata = {x['field']: x['data'] for x in hardware if x['field'] in
                ('Architecture:', 'CPU(s):', 'Model name:', 'Vendor ID:', 'Thread(s) per core:')}
    metadata['docker_server_version'] = subprocess.check_output(
        ['docker', 'version', '--format', '{{.Server.Version}}'], text=True).strip()
    (output / 'local-hardware.json').write_text(json.dumps(metadata, indent=2) + '\n')
    figures = output / 'figures'
    figures.mkdir(exist_ok=True)
    names = ('default', 'threads1', 'threads2')
    labels = ('По умолчанию: 4', '1 поток', '2 потока')
    colors = ('#64748b', '#2563eb', '#0f766e')
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), layout='constrained')
    for ax, duration in zip(axes, (30, 180, 900)):
        for i, name in enumerate(names):
            data = summary['variants'][name]['by_audio_seconds'][str(duration)]
            ax.bar(i, data['median_seconds'], color=colors[i], alpha=.8)
            xs = [i - .12 + .08 * j for j in range(len(data['samples_seconds']))]
            ax.scatter(xs, data['samples_seconds'], color='#172554', s=18, zorder=3)
            ax.text(i, max(data['samples_seconds']) * 1.06, f"{data['median_seconds']:.2f} с", ha='center')
        ax.set_xticks(range(3), labels, rotation=12)
        ax.set_title(f'Запись {duration} с')
        ax.set_ylabel('Время обработки, секунды')
        ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
        ax.grid(axis='y', alpha=.15)
    fig.suptitle('Реальный локальный ASR · одинаковые 1,5 CPU / 2 GiB · медианы и все повторы')
    for ext in ('png', 'pdf'):
        fig.savefig(figures / ('asr-thread-pilot.' + ext), dpi=170)
    plt.close(fig)
    group = trace['resource_cost_counterfactual']['work']
    fig, ax = plt.subplots(figsize=(9, 4), layout='constrained')
    amounts = [group['upper'], group['hypothetical_180s'], group['hypothetical_120s']]
    bars = ax.barh(['Измеренные интервалы жизни ресурсов', 'Если удаление через 3 минуты',
                   'Если удаление через 2 минуты'], amounts, color=['#64748b', '#bfdbfe', '#93c5fd'])
    for i, (bar, value) in enumerate(zip(bars, amounts)):
        if i:
            bar.set_hatch('//')
        ax.text(value + .4, i, f'{value:.2f} ₽', va='center')
    ax.invert_yaxis()
    ax.set_xlim(0, max(amounts) * 1.2)
    ax.set_xlabel('Расчётные ВМ + SSD, ₽; постоянные расходы кластера не включены')
    ax.set_title('Сокращение простоя рабочих узлов\nШтриховка — расчётный сценарий')
    for ext in ('png', 'pdf'):
        fig.savefig(figures / ('retirement-potential.' + ext), dpi=170)
    plt.close(fig)
    cleanup = { (r['source'], r['trial']): r for r in trace['cleanup_latency_observations'] }
    for row in read(output / 'new-cleanup-observations.json'):
        cleanup[(row['source'], row['trial'])] = row
    cleanup = list(cleanup.values())
    delays = [r['request_to_last_resource_absence_seconds_upper'] for r in cleanup]
    lines = []
    for d in (30, 180, 900):
        base = summary['variants']['default']['by_audio_seconds'][str(d)]['median_seconds']
        one = summary['variants']['threads1']['by_audio_seconds'][str(d)]['median_seconds']
        two = summary['variants']['threads2']['by_audio_seconds'][str(d)]['median_seconds']
        lines.append(f'| {d} с | {base:.3f} с | {one:.3f} с (−{100*(1-one/base):.1f}%) | '
                     f'{two:.3f} с (−{100*(1-two/base):.1f}%) |')
    lean = trace['configs']['lean_margin_probe']
    service = sum(c['fixed_seconds'] + c['seconds_per_audio_second'] * 900 for c in lean['costs'].values())
    stress = {'basis': 'deterministic_forecast_stress_not_cloud_performance', 'workers': 2,
        'tasks': 24, 'task_seconds': service, 'cold_seconds': 600, 'slo_seconds': 900,
        'predicted_on_time': sum(600 + (i // 2 + 1) * service <= 900 for i in range(24)),
        'last_completion_seconds': 600 + 12 * service}
    (output / 'lean-margin-stress.json').write_text(json.dumps(stress, indent=2) + '\n')
    text = f'''# H2: короткий пилот оптимизаций, 16 октября 2026

Потенциал есть. Для дальнейшей облачной проверки выбраны управление простоем
рабочих узлов и настройка числа CPU-потоков. Одна коррекция калибровки не
устраняет третью ВМ на длинных задачах. Полная новая облачная серия не запускалась.

## Реальное выполнение ASR

36 измеренных задач и 6 прогревочных, 6 отдельных контейнеров, один за раз.
Каждый вариант выполнен дважды: порядок 4→1→2, затем 2→1→4; порядок шести
аудиофайлов во втором проходе обратный. В каждом варианте одинаковые 1,5 CPU,
2 GiB RAM, запрет swap, тот же готовый образ и настройки качества tiny.en.
Меняется только `ASR_CPU_THREADS`; OMP/MKL/OpenBLAS остаются равными 3.
Продолжительность этой части — {summary['elapsed_seconds'] / 60:.1f} минуты.

| Длительность аудио | 4 потока, исходный вариант | 1 поток | 2 потока |
|---|---:|---:|---:|
{chr(10).join(lines)}

Все 36 результатов побитово совпали с локальным исходным вариантом после
исключения служебных идентификаторов. Это проверка неизменности результата
при настройке потоков на этом компьютере. С историческим облачным эталоном
совпали 6/36 результатов; отличия есть уже у исходного варианта с четырьмя
потоками. Отдельный запуск неизменённого образа подтвердил различия в тексте,
а не только в формате JSON. Причина различий окружений здесь не установлена;
совпадение с облачными эталонами надо проверить на облачной ВМ.

Артефактный HTTP-транспорт заменён одинаковым локальным транспортом во всех
вариантах. Это измерения обработки на локальном CPU, а не облачного времени
задачи или экономии счёта. 1 и 2 потока дают близкий результат; двух повторов
недостаточно, чтобы объявить один из них окончательно лучшим.

![Реальные времена ASR](figures/asr-thread-pilot.png)

## Прогноз нагрузки

Новая линейная верхняя граница построена только по прежним шести пилотным
измерениям. Она покрывает каждое из них, исправляет завышенную экстраполяцию
предобработки и не обучает ML-модель. Оценка предобработки 900-секундной записи
уменьшается с 3,747 до 0,421 с, общая оценка с запасом — с 46,852 до 40,780 с.
Однако при прежнем холодном старте 572 с и запасе 20% выбор на пакете из
24 длинных задач остаётся **3 ВМ**.

Пробный вариант без множителя 1,2 и с холодным стартом {lean['cold_start_seconds']} с
выбирает 2 ВМ. Но при стрессовом старте 600 с он прогнозирует лишь
{stress['predicted_on_time']}/24 задач в SLO 900 с; последняя заканчивается через
{stress['last_completion_seconds']:.1f} с. Уменьшать запас ради желаемого количества
ВМ по этому пилоту не рекомендовано. Этот вариант не развёрнут.

## Освобождение рабочих ресурсов

Из журналов сохранённых облачных запусков и завершившегося во время пилота
дополнительного long-fixed получено **{len(delays)} операций** удаления групп,
при которых ресурсы ещё были видны после запроса. От запроса API до первого
подтверждённого отсутствия всех таких ВМ/SSD проходило **{min(delays):.1f}–{max(delays):.1f} с**,
медиана **{statistics.median(delays):.1f} с**. Это реальные интервалы, ограниченные
частотой опроса. Они относятся к обычной очистке группы; автоматический
контроллер с уменьшением сохранённой группы до нуля и обратным запуском
ещё не измерен.

При неизменных временах выполнения задач и условном удалении всех рабочих
ВМ/SSD через 2–3 минуты после завершения пакета их суммарная стоимость Work
изменилась бы с {group['lower']:.2f}–{group['upper']:.2f} ₽ до
{group['hypothetical_120s']:.2f}–{group['hypothetical_180s']:.2f} ₽: потенциал
{group['conditional_saving_180s_percent']:.1f}–{group['conditional_saving_120s_percent']:.1f}%
относительно текущей реализации. Это расчёт по 12 прежним Work-прогонам,
не новое измерение экономии. Count также выигрывает от ускоренного удаления.
Master и системный узел в эти суммы не входят.

![Расчёт потенциала](figures/retirement-potential.png)

## Повторные поступления

Отдельная имитация одного воркера: восемь задач по 30 с обработки, интервалы
между поступлениями 150/300/600/800/1200 с, запуск 450/600 с, ожидание удаления
660 или 120 с. Сохранены все десять сочетаний, включая невыгодные.
При интервале 800 с и запуске 600 с быстрое выключение даёт восемь запусков
вместо четырёх и увеличивает модельное время выделения узлов на 0,7%.
При редких поступлениях выигрыш существенно больше. Во всех этих простых
сценариях задачи укладываются в 900 с, но частые холодные старты увеличивают
среднее ожидание. Политика с известным расписанием использует объявленные
будущие поступления и не выдаётся за готовое предсказание произвольного трафика.

## Решение после пилота

1. Проверять контроллер жизненного цикла отдельной ASR-группы: один владелец
   числа узлов, сохранённая очередь, отсутствие активных задач перед уходом
   в ноль, обработка нового поступления во время уменьшения и запуск из нуля.
   На готовом кластере достаточно двух коротких циклов до большой серии.
2. На той же облачной ВМ сравнить 4/1/2 потока и облачные эталоны. Улучшенный
   исполнитель затем использовать одинаково в Count и Work, чтобы не
   приписывать эффект настройки CPU алгоритму масштабирования.
3. Сравнивать быструю очистку для обеих стратегий, отдельно показывая выгоду
   всей новой конфигурации относительно старой. Включить одиночный пакет,
   близкие повторные всплески и длительный простой.
4. Уточнённую калибровку сохранить, агрессивное сокращение запаса пока отложить.

## Воспроизводимость

- [План и порядок ASR](local-asr-v2/plan.json), [сырые результаты](local-asr-v2/runs.json),
  [сравнение локальных результатов](local-asr-v2/local-parity.json),
  [проверка отличий от облачного эталона](reference-check.json).
- [Калибровка и ресурсные интервалы](traces/analysis.json),
  [новые интервалы очистки](new-cleanup-observations.json),
  [стресс прогноза](lean-margin-stress.json),
  [все сценарии повторных поступлений](idle-simulation-v2/simulation.json).
- [9 проверок моделей расчёта](tests.xml). Первоначальный запуск контейнера
  остановился до ASR из-за отсутствия `/app` в пути импорта; сохранён в
  `local-asr/`. Рабочий запуск отдельно хранится в `local-asr-v2/`.
- Изменение backend находится в отдельном worktree `h2-cost-pilot`, ветка
  `thesis/20261016-h2-cost-pilot`. Основные репозитории и 24 замороженных
  исходника текущей облачной серии не изменялись. Новые облачные ресурсы
  в этом коротком пилоте не создавались; прежняя контрольная серия продолжалась.

Сформировано {datetime.now(UTC).isoformat()}.
'''
    (output / 'RESULTS.md').write_text(text)
    (output / 'retirement-observations.json').write_text(json.dumps(cleanup, indent=2) + '\n')
    print(str(output / 'RESULTS.md'))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
