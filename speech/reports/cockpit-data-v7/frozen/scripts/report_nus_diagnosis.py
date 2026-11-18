"""Create a compact report from completed, immutable diagnostic measurements."""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
D = REPO / 'reports/nus-diagnosis-v1'
A = REPO / 'reports/nus-lora-ablation-v1'


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def main():
    diagnosis, components = read(D / 'comparison.json'), read(A / 'comparison.json')
    fit = read(D / 'fit-audit/summary.json')
    checks = {}
    for root, result in ((D, diagnosis), (A, components)):
        label = root.name
        checks[label + '_scorer_checks'] = result['artifact_status'] == 'PASS' and all(result['checks'].values())
        checks[label + '_plan'] = result['plan_sha256'] == sha(root / 'plan.json')
        checks[label + '_frozen_sources'] = all(sha(root / 'frozen' / name) == expected
                                      for name, expected in read(root / 'frozen-files.json').items())
        checks[label + '_no_promotion_or_test'] = result['test_accessed'] is False and result['release_promoted'] is False
        for name in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml'):
            checks[label + '_' + name] = sha(REPO / name) == sha(root / 'frozen' / name)
        snapshots = [read(p) for p in root.glob('north55-*.json')]
        runs = [r for r in snapshots if r['command'][:3] in (
            ['-u', '-m', 'scripts.nus_failure_diagnosis'], ['-u', '-m', 'scripts.nus_lora_ablation'])
            and r['command'][3] in ('trace', 'fit', 'context', 'control', 'cpu')]
        checks[label + '_offline_inference'] = bool(runs) and all(r['network_mode'] == 'none' for r in runs)
        checks[label + '_reference_isolation'] = all(not any(m['Destination'] in ('/study', '/scoring')
                                                   for m in r['mounts']) for r in runs)
        checks[label + '_readonly_models_audio'] = all(not m['RW'] for r in runs for m in r['mounts']
                                                     if m['Destination'] in ('/models', '/audio'))
        amendment = read(root/'scoring-amendment.json')
        checks[label + '_scoring_amendment'] = result['scoring_amendment_sha256'] == sha(root/'scoring-amendment.json') and all(
            sha(root/'scoring-repair'/name) == expected for name, expected in amendment['files'].items())
    checks['fit_audit_details_hash'] = sha(D / 'fit-audit/details.json') == fit['details_sha256']
    checks['fit_audit_unchanged_refs'] = fit['references_changed'] is False and fit['pairs_excluded'] == 0
    checks['fit_audit_primary_matches'] = fit['lexical'] == diagnosis['fit']['scores']
    test_suites = [suite for path in (D/'tests/results.xml', A/'tests/results.xml', D/'tests/legacy-audio.xml')
                   for suite in ET.parse(path).getroot().iter('testsuite')]
    test_counts = {key: sum(int(suite.attrib.get(key, 0)) for suite in test_suites)
                   for key in ('tests', 'failures', 'errors', 'skipped')}
    checks['unit_tests_passed'] = test_counts['tests'] == 22 and all(test_counts[k] == 0 for k in ('failures', 'errors', 'skipped'))
    key = 'reviewed-291ebb141aa4e7a7ba94ccf8d18002fb'
    record = read(D / 'trace-nus_on/predictions' / (key + '.json'))
    off = read(D / 'trace-nus_off/predictions' / (key + '.json'))
    checks['dominant_repeat_first_call_no_context'] = len(record['trace']) == 1 and record['trace'][0]['previous_token_count'] == 0
    checks['dominant_repeat_unchanged_without_context'] = record['hypothesis'] == off['hypothesis']
    replay = read(D/'cross-platform-replay.json')
    checks['Linux_replay_byte_identical'] = replay['status'] == 'PASS' and all(replay['byte_identical'].values()) and all(
        sha(REPO / name) == expected for name, expected in replay['after'].items())
    verification = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
                    'unit_tests': test_counts,
                    'scope': 'Artifact/execution verification only, not ASR quality approval.',
                    'diagnosis_comparison_sha256': sha(D/'comparison.json'),
                    'component_comparison_sha256': sha(A/'comparison.json')}
    save(D / 'verification.json', verification)
    summaries = components['cohorts']
    table = []
    for stage, cohort, title in (
        ('fit', 'nus_training_fit', 'NUS train, 275 пар (только fitting)'),
        ('control', 'partial_human_dev', 'Кабинный human dev, 5 фрагментов'),
        ('control', 'general_clean', 'General EN, 50 фрагментов'),
        ('control', 'general_ru', 'General RU, 50 фрагментов'),
        ('control', 'quiet_partial_human_dev', 'Тихие копии кабинного dev')):
        scores = summaries[stage][cohort]['scores']
        values = ['%.2f' % (100*scores[s]['wer_lexical_corpus']) for s in ('parent_on', 'nus_on', 'encoder_on', 'decoder_on')]
        table.append('| ' + title + ' | ' + ' | '.join(values) + ' |')
    context_lines = []
    if diagnosis['context']['status'] == 'EXECUTED':
        for cohort in ('partial_human_dev', 'quiet_partial_human_dev', 'general_clean', 'general_ru'):
            c = diagnosis['context']['cohorts'][cohort]
            values = ['%.2f' % (100*c['scores'][s]['wer_lexical_corpus']) for s in ('parent_on', 'parent_off', 'nus_on', 'nus_off')]
            context_lines.append('| ' + cohort + ' | ' + ' | '.join(values) + ' |')
    context_table = '\n'.join(context_lines)
    total_gpu = diagnosis['new_GPU_predictions'] + components['new_GPU_predictions']
    total_cpu = diagnosis['new_CPU_predictions'] + components['new_CPU_predictions']
    scope = {
        'implementation': 'implemented', 'GPU_diagnostics': 'executed', 'CPU_smokes': 'executed',
        'artifact_verification': 'verified' if verification['status'] == 'PASS' else 'FAIL',
        'new_GPU_predictions': total_gpu, 'new_CPU_predictions': total_cpu,
        'quality_fix': 'FAIL', 'independent_quality': 'NEEDS_MORE_DATA',
        'release_promoted': False, 'new_training_steps': 0, 'test_accessed': False,
        'component_gates': components['gates'], 'runtime_selection': read(D/'application-runtime.json')}
    save(D/'status.json', scope)
    report = f'''# NUS: диагностика и проверка исправлений

Статус исправления качества: **FAIL**. Новые варианты не продвинуты.
Проверка артефактов: **{verification['status']}**, проверок: {len(checks)}.

## Что выполнено

- Записаны реальные вызовы генерации, prompt tokens, seek и выравнивание слов.
  Исходные ответы с инструментированием совпали с историческими.
- Проверены context=True/False на обеих моделях: 40 ответов для пяти human dev
  фрагментов и их тихих копий, затем 1350 ответов на всех прежних 675 dev/controls.
- Все 275 NUS train-пар распознаны исходной и полной обученной моделями: 550 ответов.
- Сохранённый адаптер разделён на encoder-only и decoder-only без новых шагов
  обучения. Проверены обе версии на 275 train и 159 controls: 868 ответов.
- Всего **{total_gpu} GPU-ответов**, **{total_cpu} CPU smoke**;
  подробный runtime-статус содержится в verification/comparison, не выводится из числа вызовов.
- {test_counts['tests']} теста проверили восстановление диагностических hooks, отсутствие
  изменения исходных tensors, точное отключение выбранного вклада LoRA и
  совместимость доказательств идентичности аудио с историческими результатами.
- Аудио, эталоны, baseline, ACCEPTANCE и пользовательские ревизии не менялись.

## Результаты lexical WER, %

| Набор | Parent | Полная NUS LoRA | Только encoder | Только decoder |
|---|---:|---:|---:|---:|
{chr(10).join(table)}

Fitting на train — измерение усвоения виденных слабых текстов, не подтверждение
качества на новых данных. Здесь одна консервативная NUS-группа. На полном NUS
адаптере улучшился 61 пример, ухудшились 14, не изменились 200; точных по lexical
scorer ответов стало 89 -> 116. Secondary canonical WER: parent
{100*fit['secondary_canonical_not_primary_WER']['parent_on']['wer_lexical_corpus']:.2f}% -> NUS
{100*fit['secondary_canonical_not_primary_WER']['nus_on']['wer_lexical_corpus']:.2f}%.
Формат чисел объясняет небольшую часть расхождения, не заменяет primary WER.

## Проверка предыдущего текста

| Набор | Parent on | Parent off | NUS on | NUS off |
|---|---:|---:|---:|---:|
{context_table}

В `reviewed-291ebb141aa4e7a7ba94ccf8d18002fb` весь повтор NUS возникает в одном
вызове генерации с нулём previous tokens. Отключение context не меняет этот
ответ. Повторная обработка хвоста/перенос prompt не объясняет именно этот случай.
Наличие повторов в аудио не установлено данным анализом: нельзя объявить текст
галлюцинацией или переписать человеческий эталон по ответу модели.

## Аудио и данные

Для всех 275 NUS проверены hashes, finite mono 16kHz, peak/RMS и локальный Silero
VAD. Нулевого сигнала и клипов без обнаруженной VAD речи: 0. Это технический
скрининг, а не подтверждение точности текстов, области речи или происхождения.
Никакие пары не удалены по несогласию ASR/VAD. Подробности сохранены локально в
fit-audit/details.json; сводка — [fit-audit/summary.json](fit-audit/summary.json).

## Gate и ограничения

```json
{json.dumps(components['gates'], ensure_ascii=False, indent=2)}
```

Все проверки используют открытый dev и train, final test не использован.
Пять human dev клипов / 115 слов / три группы не удовлетворяют ACCEPTANCE;
human critical entities, независимые NLP/temporal labels и подтверждение
качества RU/mixed cockpit speech отсутствуют. Пороги не ослаблены.
Изолированные части совместно обученного адаптера — абляция; их неудача не
доказывает, что отдельное обучение encoder всегда неработоспособно.

## Статусы и воспроизведение

Scoring потребовал отдельной [поправки совместимости](scoring-amendment.json):
у старых ответов parent нет runtime PCM hash. Их исходный file hash и параметры
сохранены; совпадение проверено через исходный файл и явно записанную
реконструкцию. Историческое измерение PCM не приписывается старому запуску.
Frozen код, слова, метрики и пороги сохранены; repair-код хранится отдельно.
Для запуска scorer по пути /repair явно установлен PYTHONPATH=/app:/app/src.
Linux resume переиспользовал 285 ответов без новых ASR-вызовов. Оба comparison
и оба файла legacy-аудита совпали побайтно с PowerShell:
[cross-platform-replay.json](cross-platform-replay.json).

Implemented: инструменты трассировки, fitting, разделения адаптера и проверки.
Executed: реальные offline GPU/CPU прогоны, scoring, технический аудит пар.
Verified: только перечисленные артефакты/контракты при PASS verification.
ML improvement: не подтверждён; release остаётся на исходном baseline.

Команды: [docs/nus_diagnosis.md](../../docs/nus_diagnosis.md).
Исходные frozen протоколы не изменялись после запуска: [diagnosis](protocol.md),
[components](../nus-lora-ablation-v1/protocol.md).
Измерения: [comparison.json](comparison.json),
[component comparison](../nus-lora-ablation-v1/comparison.json),
[verification.json](verification.json), [status.json](status.json).
'''
    (D/'report.md').write_text(report, encoding='utf-8', newline='\n')
    print(json.dumps({'verification': verification['status'], 'checks': len(checks), 'GPU': total_gpu, 'CPU': total_cpu,
                      'quality_fix': scope['quality_fix'], 'release_promoted': False}))
    if verification['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
