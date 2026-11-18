"""A factual report of the short live node-pool API probe."""
from datetime import datetime
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main(root):
    read = lambda p: json.loads((root / p).read_text())
    status = read('status.json')
    if status['phase'] not in ('completed', 'failed'):
        raise ValueError('Wait for the probe and cleanup to finish')
    if status['phase'] != 'completed' or not (root / 'result.json').exists():
        completed = []
        for name in ('down-1', 'up-1', 'down-2'):
            if (root / (name + '.json')).exists():
                step = read(name + '.json')
                completed.append(f"- `{name}`: подтверждено {step['count']} узлов через "
                    f"{step['request_to_observed_state_seconds_upper']:.1f} с после запроса.")
        (root / 'RESULTS.md').write_text('# Короткая проверка scale-to-zero\n\n'
            'Полный цикл проверки не завершён успешно. Подробности сохранены в '
            '`failure.json`, `cleanup-failure.json` (при наличии) и `status.json`.\n\n'
            + ('Подтверждённые этапы:\n\n' + '\n'.join(completed) + '\n\n' if completed else '')
            + f"Ошибка: {status.get('error') or status.get('cleanup_error')}.\n\n"
            + f"Исходному управляющему процессу отправлено возобновление: "
            + f"{status.get('original_writer_resumed', False)}.\n")
        return
    result = read('result.json')
    assert result['passed'] and read('cleanup.json')['probe_pool_deleted']
    observations = [json.loads(x) for x in (root / 'observations.jsonl').read_text().splitlines()]
    original = read('plan.json')['borrowed_original_run']
    phases = [read(name + '.json') for name in ('down-1', 'up-1', 'down-2')]
    # All durations were measured with the monotonic clock. Use the same clock
    # in the figure; UTC on this WSL host can be corrected during a run.
    previous = read('initial-ready.json')['monotonic']
    phase_starts, resource_release = [], []
    for row in phases:
        samples = [x for x in observations if previous < x['monotonic'] <= row['final']['monotonic']]
        if row['count'] == 0:
            first = next(x for x in samples if not x['vms'] and not x['disks'] and not x['ready_nodes'])
        else:
            first = next(x for x in samples if len(x['vms']) == len(x['disks']) == len(x['ready_nodes']) == 1
                         and all(v['state'] == 'running' for v in x['vms']))
        start = first['monotonic'] - row['request_to_observed_state_seconds_upper']
        phase_starts.append(start)
        if row['count'] == 0:
            released = next(x for x in samples if not x['vms'] and not x['disks'])
            resource_release.append(released['monotonic'] - start)
        previous = row['final']['monotonic']
    times = [x['monotonic'] for x in observations]
    origin = times[0]
    fig, ax = plt.subplots(figsize=(10, 4.5), layout='constrained')
    for key, label, color, style in [('vms', 'ВМ в Compute', '#2563eb', '-'),
        ('disks', 'SSD в Compute', '#ea580c', '--'), ('ready_nodes', 'Готовые узлы Kubernetes', '#0f766e', ':')]:
        ax.step([(t-origin)/60 for t in times], [len(x[key]) for x in observations],
                where='post', label=label, color=color, linestyle=style, linewidth=2)
    for start, label in zip(phase_starts, ('Уменьшить до 0', 'Вернуть 1 узел', 'Повторно до 0')):
        x = (start-origin)/60
        ax.axvline(x, color='#64748b', alpha=.5, linewidth=1)
        ax.text(x + .05, 1.1, label, rotation=20, fontsize=9)
    ax.set_ylim(-.08, 1.4)
    ax.set_yticks([0, 1])
    ax.set_xlabel('Минуты после первого наблюдения группы')
    ax.set_ylabel('Количество ресурсов')
    ax.set_title('Cloud.ru: реальный цикл одной группы 1 → 0 → 1 → 0')
    ax.legend(loc='center', bbox_to_anchor=(.5, .45))
    ax.grid(alpha=.15)
    for ext in ('png', 'pdf'):
        fig.savefig(root / ('resource-cycle.' + ext), dpi=170)
    plt.close(fig)
    d1, d2 = result['down_seconds']
    up = result['up_seconds']
    elapsed = phases[-1]['final']['monotonic'] - phase_starts[0]
    (root / 'timing-analysis.json').write_text(json.dumps({
        'clock': 'time.monotonic', 'down_vm_and_disk_absence_seconds_upper': resource_release,
        'full_cycle_seconds': elapsed,
        'wall_clock_elapsed_diagnostic_seconds': (datetime.fromisoformat(observations[-1]['at'])
            - datetime.fromisoformat(observations[0]['at'])).total_seconds(),
        'monotonic_elapsed_seconds': times[-1] - times[0],
        'note': 'Figure and durations use the monotonic clock, independently of UTC corrections.'
    }, indent=2) + '\n')
    (root / 'RESULTS.md').write_text(f'''# Cloud.ru: короткая проверка быстрого освобождения узлов

**Проверка прошла:** одна и та же группа узлов выполнила цикл **1 → 0 → 1 → 0**.

| Действие | От запроса API до подтверждённого состояния |
|---|---:|
| Первое уменьшение до нуля: ВМ и SSD отсутствуют, готовых узлов 0 | {d1:.1f} с |
| Возврат одного узла: новая ВМ работает, Kubernetes Node Ready | {up:.1f} с |
| Повторное уменьшение до нуля: ВМ и SSD отсутствуют, готовых узлов 0 | {d2:.1f} с |

Сам цикл после подготовки первой ВМ занял {elapsed / 60:.1f} минуты.
Исчезновение ВМ и SSD из Compute подтверждено ещё раньше: через
{resource_release[0]:.1f} и {resource_release[1]:.1f} с соответственно.
Основной показатель дополнительно ждёт отсутствия готового узла Kubernetes.

Проверялись реальные инвентаризации Compute и готовность узлов Kubernetes,
а также обратное чтение `fixedScale.count`. В группе не осталось оплачиваемого
диска после исчезновения ВМ. Времена ограничены частотой успешного опроса;
в `down-1.json`, `up-1.json`, `down-2.json` отдельно сохранено завершение
облачной операции, которое может происходить позднее исчезновения ресурсов.
Длительности и горизонтальная ось графика используют монотонные часы,
поэтому коррекции календарного времени WSL на них не влияют.

![Фактический жизненный цикл](resource-cycle.png)

Проверка выполнялась на отдельной группе с одной ВМ 2 vCPU / 4 GB и SSD 40 GB.
Группа не удалялась между изменениями размера; после проверки пустая группа
удалена. Группа работала в режиме `fixedScale`: число узлов изменялось нашим
скриптом через API. Автомасштабирование провайдера в этой группе не включалось.

Последний старый контроль полностью завершился, его данные и ресурсы были
сохранены и освобождены до начала проверки. Его управляющий процесс временно
приостановлен только на этапе перед окончательным удалением кластера и
возобновлён после проверки. Исходный аварийный срок остановки сохранён.
Дополнительное время master/system относится к этой проверке, а не к стоимости
основных пар предыдущей серии. Исходный сеанс: `{original}`.

Этот результат подтверждает инфраструктурный механизм быстрого освобождения
и повторного запуска. ASR-нагрузки в этом тесте не было. Процент экономии,
устойчивость при повторных поступлениях и работу контроллера с активной
очередью нужно измерять отдельно. Многочасовая серия для проверки самого
механизма выключения не требуется.

Артефакты: [результат](result.json), [наблюдения](observations.jsonl),
[передача управления](handoff.json), [очистка](cleanup.json),
[состояние завершения](status.json). Скрипт запуска сохранён рядом с отчётом.
''')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
