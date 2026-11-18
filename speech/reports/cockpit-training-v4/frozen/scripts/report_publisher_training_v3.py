"""Verify saved experiment evidence and write its complete before/after report."""

import ast
import json
from pathlib import Path

from scripts.audit_nus_training_contract import read, save, sha

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/publisher-training-v3'


class WithoutTyping(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        return None if node.module == 'typing' else node

    def visit_AnnAssign(self, node):
        return ast.Assign(targets=[node.target], value=node.value) if node.value else None


def main():
    plan, training, result = (read(ROOT / filename) for filename in ('plan.json', 'training.json', 'comparison.json'))
    plan_hash = sha(ROOT / 'plan.json')
    if any(r['plan_sha256'] != plan_hash for r in (training, result, read(ROOT / 'conversion.json'))):
        raise ValueError('Experiment identity differs')
    for name, expected in plan['implementation_sha256'].items():
        if sha(ROOT / 'frozen' / name) != expected:
            raise ValueError('Frozen implementation changed')
    for name in ('train', 'dev'):
        if sha(REPO / 'data/curated/publisher-recovery-v3' / (name + '.jsonl')) != plan[name + '_sha256']:
            raise ValueError('Source dataset changed')
    if sha(ROOT / 'protocol.md') != plan['protocol_sha256'] or sha(ROOT / 'scoring/references.json') != plan['references_sha256']:
        raise ValueError('Protocol or references changed')
    if sha(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Evaluation population changed')
    arm = training['arms']['240']
    if (arm['actual_updates'] != 240 or set(arm['coverage']) != set(plan['selected_ids'])
            or sum(arm['coverage'].values()) != 960 or not arm['encoder_unchanged']
            or not arm['frozen_base_unchanged'] or arm['teacher_before_sha256'] != arm['teacher_after_sha256']):
        raise ValueError('Training update, coverage, or frozen-weight verification failed')
    executions = {}
    items = read(ROOT / 'inputs.json')
    for system in ('baseline', 'candidate', 'cpu'):
        execution = read(ROOT / ('io-' + system) / 'execution.json')
        expected_ids = {i['id'] for i in items} if system != 'cpu' else {
            next(i['id'] for i in items if i['cohort'] == c) for c in ('partial_human_dev', 'general_ru')}
        if (execution['plan_sha256'] != plan_hash or execution['runtime_failures']
                or set(execution['prediction_sha256']) != {i + '.json' for i in expected_ids}):
            raise ValueError('Execution incomplete')
        for name, expected in execution['prediction_sha256'].items():
            path = ROOT / ('io-' + system) / 'predictions' / name
            record = read(path)
            if sha(path) != expected or record['runtime_failure'] is not None or record['plan_sha256'] != plan_hash:
                raise ValueError('Prediction evidence changed')
        executions[system] = {k: execution[k] for k in ('records', 'new_ASR_calls', 'actual_device', 'actual_precision')}
    old = read(REPO / 'reports/nus-lora-ablation-v1/scoring/parent_on.json')
    controls = [i for i in items if i['cohort'] not in ('training_fit', 'publisher_weak_dev')]
    changed = [i['id'] for i in controls if read(ROOT / 'io-baseline/predictions' / (i['id'] + '.json'))['hypothesis'] != old[i['id']]['hypothesis']]
    source = 'scripts/publisher_training_v3.py'
    trees = [ast.dump(WithoutTyping().visit(ast.parse(p.read_text(encoding='utf-8'))))
             for p in (REPO / source, ROOT / 'frozen' / source)]
    if trees[0] != trees[1]:
        raise ValueError('Current source differs from measured source beyond type annotations')
    verification = {'status': 'PASS', 'plan_sha256': plan_hash, 'actual_updates': arm['actual_updates'],
        'unique_train_examples': len(arm['coverage']), 'training_presentations': sum(arm['coverage'].values()),
        'frozen_encoder_and_base_unchanged': True, 'teacher_unchanged': True,
        'executions': executions, 'historical_baseline_compared': len(controls),
        'historical_baseline_hypothesis_differences': changed,
        'source_after_freeze': 'type annotations only; runtime AST equal after removing typing',
        'measured_worker_sha256': sha(ROOT / 'frozen' / source), 'current_worker_sha256': sha(REPO / source),
        'quality_evidence': False, 'test_accessed': False, 'release_promoted': False}
    if (ROOT / 'verification.json').exists():
        if read(ROOT / 'verification.json') != verification:
            raise ValueError('Do not overwrite differing verification evidence')
    else:
        save(ROOT / 'verification.json', verification)
    titles = {'training_fit': 'Обучающие фрагменты (подгонка)', 'publisher_weak_dev': 'Отложенные чек-листы, слабая разметка',
        'partial_human_dev': 'Кабинная речь, частичная ручная проверка', 'general_clean': 'Обычная английская речь',
        'general_ru': 'Обычная русская речь', 'quiet_general_clean': 'Тихие версии английской речи',
        'quiet_partial_human_dev': 'Тихие версии кабинной речи'}
    text = ['# Результат обучения на publisher-recovery-v3', '',
        '**Уверенного улучшения кабинной речи не получено; рабочая модель не заменена.**',
        'На 35 слабых dev-примерах WER изменился с 22.87% до 22.53%, на пяти частично проверенных вручную —',
        'с 13.91% до 15.65% (16 → 18 ошибок на 115 слов). На обоих наборах шума ложных слов стало больше.', '',
        'Обучение и проверка завершены. Один новый адаптер обучен на **221 фрагменте / 25.44 минуты / 9 дикторах**.',
        'Выполнены **240 реальных обновлений**, 960 предъявлений (по 4–5 раз на фрагмент).',
        'Исходный Whisper-small, decoder LoRA rank 8, learning rate 2e-5, BF16, KL к исходной модели: вес 1, температура 2.',
        'Выбран заранее последний checkpoint. Кодировщик и исходные веса проверены по хешам и не изменились.', '',
        '## Что получилось', '', 'WER — доля ошибок по словам; меньше лучше. Дельта — процентные пункты.', '',
        '| Набор | Фрагментов | Исходная | После обучения | Дельта |', '|---|---:|---:|---:|---:|']
    for name, title in titles.items():
        row = result['cohorts'][name]
        a, b = [row['scores'][s]['wer_lexical_corpus']*100 for s in ('baseline', 'candidate')]
        text.append(f'| {title} | {row["samples"]} | {a:.2f}% | {b:.2f}% | {b-a:+.2f} |')
    text += ['', '| Только шум | Фрагментов | Слов/мин, исходная | Слов/мин, новая |', '|---|---:|---:|---:|']
    for name in ('noise_only', 'bleriot_b_noise'):
        row = result['cohorts'][name]
        values = row['inserted_words_per_minute']
        text.append(f'| {name} | {row["samples"]} | {values["baseline"]:.2f} | {values["candidate"]:.2f} |')
    text += ['', '## Проверки и ограничения', '',
        f'Диагностические проверки: **{result["diagnostic_status"]}**. Рабочая модель не заменена.',
        f'Проверки: `{json.dumps(result["checks"], ensure_ascii=False)}`.',
        'Выполнены 830 новых распознаваний GPU float16 и 2 CPU int8_float32; ошибок исполнения нет.',
        'Автоматические проверки: 482 теста пройдены, 9 исключены как требующие отдельной инфраструктуры;',
        '26 целевых тестов замороженного опыта и 6 тестов после добавления типов также прошли. Ruff и mypy: PASS.',
        '95% парный интервал дельты WER для слабого dev: от −0.68 до +1.44 п.п. (2 группы);',
        'для частично ручного dev: от 0.00 до +4.35 п.п. (3 группы). Преимущество не подтверждено.',
        f'Свежий baseline совпал с историческим текстом в {len(controls)-len(changed)} из {len(controls)} контрольных случаев.',
        '35 отложенных чек-листов имеют машинную, а не независимую ручную разметку. Пять вручную проверенных',
        'фрагментов размечены частично с доступом к подсказкам ASR и уже использовались в прошлых экспериментах.',
        'Тихие версии не являются независимыми записями. Часть кабинных проверок может покрывать одни исходные записи.',
        'Падение WER на train показывает подгонку к обучающим текстам и само по себе не доказывает перенос.',
        'Held-out test не открывался. Качество спонтанной кабинной речи и критических чисел этим опытом не подтверждается.', '',
        '## Артефакты и повторение', '',
        f'Модель: `{plan["model_name"]}` в Docker volume `north55-speech_publisher_training_v3`, каталог `models/`.',
        'Адаптер: `training/checkpoint-240/`, объединённые Transformers-веса: `merged/` в том же томе.',
        '`comparison.json` содержит метрики, интервалы и проверки; `verification.json` — проверку целостности;',
        '`training.json` — историю обучения, реальные счётчики оптимизатора и покрытие; `scoring/examples.json` — тексты.',
        'Код, выполнивший опыт, сохранён в `frozen/`. После запуска в текущий worker добавлены только аннотации типов;',
        'верификатор проверяет равенство AST без этих аннотаций. Замороженная копия не менялась.',
        'Команды: `python -m scripts.run_publisher_training_v3 STAGE`, где стадии: freeze, init, tests, train,',
        'convert, baseline, candidate, cpu, score. Существующие train/convert сохраняются; повторный запуск inference',
        'проверяет идентичность и переиспользует готовые ответы. Затем `python -m scripts.report_publisher_training_v3`.', '']
    (ROOT / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    print(json.dumps(verification, indent=2))


if __name__ == '__main__':
    main()
