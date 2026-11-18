"""Independent artifact checks and report for the hard-example training comparison."""

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.audit_nus_training_contract import read, save, sha

REPO = Path('/workspace') if Path('/workspace').is_dir() else Path(__file__).resolve().parents[1]
PREP = REPO / 'reports/cockpit-hard-v4'
RUN = REPO / 'reports/cockpit-training-v4'
DATA = REPO / 'data/curated/cockpit-hard-v4'
PACKET = REPO / 'data/curated/annotation-hard-v4'


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def preserve(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError('Verification evidence changed: ' + str(path))
    else:
        save(path, value)


def data_audit():
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    from north55_speech.datasets import load_manifest
    from north55_speech.hard_adaptation import validate_population
    from scripts.cockpit_hard_v4 import overlaps, teacher_decision
    from scripts.expand_publisher_pairs import FAMILIES

    plan, result = read(PREP / 'inference/plan.json'), read(PREP / 'result.json')
    for name, expected in plan['code_sha256'].items():
        if sha(REPO / name) != expected:
            raise ValueError('Hard-example preparation code changed')
    train, dev = (load_manifest(DATA / (s + '.jsonl')) for s in ('train', 'dev'))
    validate_population(train, dev)
    if sha(DATA / 'train.jsonl') != result['train_sha256'] or sha(DATA / 'dev.jsonl') != plan['old_dev_sha256']:
        raise ValueError('Training/dev manifest changed')
    for name, expected in plan['scoring_sha256'].items():
        if sha(PREP / 'scoring' / name) != expected:
            raise ValueError('Cached scoring evidence changed')
    docs, cached = read(PREP / 'scoring/documents.json'), read(PREP / 'scoring/cached.json')
    execution = read(PREP / 'predictions/execution.json')
    selected = set()
    for item in read(PREP / 'inference/inputs.json'):
        path = PREP / 'predictions' / (item['id'] + '.json')
        if sha(path) != execution['prediction_sha256'][path.name]:
            raise ValueError('Teacher result changed')
        documents = {k: v for k, v in docs.items() if Path(k).stem in FAMILIES[item['family']]}
        decision = teacher_decision(cached[item['id']]['medium'], read(path), documents, item['duration_sec'])
        if decision['accepted']:
            selected.add(item['id'])
    hard = [s for s in train if s.annotation_provenance['method'] == 'cockpit_hard_teacher_consensus_v4']
    if selected != {s.annotation_provenance['original_item_id'] for s in hard}:
        raise ValueError('Hard membership differs from frozen rules')
    for sample in hard:
        p = sample.annotation_provenance
        if sample.reference_text != cached[p['original_item_id']]['medium']['hypothesis'].strip():
            raise ValueError('Hard label was rewritten')
    old = {s['sample_id']: s for s in rows(REPO / 'data/curated/publisher-recovery-v3/train.jsonl')}
    clean = [s for s in train if not s.variant_of]
    for sample in clean:
        if sample.sample_id in old:
            previous = old[sample.sample_id]
            if sample.reference_text != previous['reference_text'] or sample.audio_sha256 != previous['audio_sha256']:
                raise ValueError('Retained pair changed')
    for index, a in enumerate(clean):
        p = a.annotation_provenance
        for b in clean[index+1:]:
            q = b.annotation_provenance
            if p['source_sample_id'] == q['source_sample_id'] and overlaps(
                    (p['original_start_sec'], p['original_end_sec']), (q['original_start_sec'], q['original_end_sec'])):
                raise ValueError('Duplicate overlapping training intervals')
    for sample in train:
        if sha(Path('/audio') / sample.audio_path) != sample.audio_sha256:
            raise ValueError('Training waveform changed')
    raw = {s['sample_id']: s for split in ('train', 'dev') for s in rows(
        REPO / 'data/curated/bleriot-v2/manifests/train-dev' / (split + '.jsonl'))}
    packet_rows = rows(PACKET / 'train.jsonl') + rows(PACKET / 'dev.jsonl')
    if any(s['reference_text'] is not None or s['transcript_status'] != 'missing' or s['annotation_provenance']['reviewed_audio'] for s in packet_rows):
        raise ValueError('Initial review packet must not invent human references')
    dev_rows = [s for s in packet_rows if s['split'] == 'dev']
    if {sp for s in train for sp in s.speaker_ids} & {sp for s in dev_rows for sp in s['speaker_ids']}:
        raise ValueError('Blind dev speakers overlap training')
    held = rows(DATA / 'dev.jsonl') + rows(REPO / 'data/curated/annotation-packet-v1/dev.jsonl')
    for sample in dev_rows:
        p = sample['annotation_provenance']
        for old_sample in held:
            q = old_sample['annotation_provenance']
            if p['source_sample_id'] == q['source_sample_id'] and overlaps(
                    (p['original_start_sec'], p['original_end_sec']), (q['original_start_sec'], q['original_end_sec'])):
                raise ValueError('Blind dev overlaps earlier checked intervals')
    checked_crops = 0
    derived = [(s.audio_path, s.annotation_provenance, s.augmentation['noisy_source_sample_id'])
               for s in train if s.variant_of]
    derived += [(s['audio_path'], s['annotation_provenance'], s['annotation_provenance']['source_sample_id']) for s in dev_rows]
    for audio_path, p, source in derived:
        parent = raw[source]
        path = Path('/audio') / parent['audio_path']
        if sha(path) != parent['audio_sha256']:
            raise ValueError('Original source changed')
        with sf.SoundFile(path) as stream:
            rate = stream.samplerate
            start, end = round(p['original_start_sec']*rate), round(p['original_end_sec']*rate)
            stream.seek(start)
            wave = stream.read(end-start, dtype='float32', always_2d=True)[:, parent['channel']]
        import math
        common = math.gcd(rate, 16000)
        expected = resample_poly(wave, 16000//common, rate//common).astype('float32')
        actual, actual_rate = sf.read(Path('/audio') / audio_path, dtype='float32')
        if actual_rate != 16000 or not np.array_equal(actual, expected):
            raise ValueError('Derived waveform does not equal its original-source crop')
        checked_crops += 1
    value = {'status': 'PASS', 'train_pairs': len(train), 'hard_rules_replayed': len(cached),
        'hard_targets_unmodified': len(hard), 'retained_targets_unmodified': len(clean)-len(hard),
        'training_original_intervals_nonoverlapping': True, 'exact_original_crop_checks': checked_crops,
        'review_train': len(packet_rows)-len(dev_rows), 'blind_dev': len(dev_rows),
        'blind_dev_speakers_disjoint': True, 'human_references_fabricated': 0,
        'train_sha256': sha(DATA / 'train.jsonl'), 'test_accessed': False, 'quality_evidence': False}
    preserve(PREP / 'verification.json', value)
    print(json.dumps(value, indent=2), flush=True)


def models_audit():
    import torch
    from safetensors.torch import load_file

    plan, training = read(RUN / 'plan.json'), read(RUN / 'training.json')
    if training['plan_sha256'] != sha(RUN / 'plan.json'):
        raise ValueError('Training plan changed')
    initial, schedules, result = set(), set(), {}
    for arm, details in training['arms'].items():
        if (details['actual_updates'] != 240 or sum(details['coverage'].values()) != 960
                or set(details['coverage']) != set(plan['selected_ids']) or not details['frozen_base_unchanged']
                or details['teacher_before_sha256'] != details['teacher_after_sha256']):
            raise ValueError('Actual training counters or frozen teacher differ')
        initial.add(details['decoder_initial_sha256'])
        schedules.add(details['schedule_sha256'])
        folder = Path('/experiment/training') / ('checkpoint-' + arm)
        for name, expected in training['checkpoints'][arm].items():
            if sha(folder / name) != expected:
                raise ValueError('Saved checkpoint changed')
        tensors = load_file(folder / 'adapter_model.safetensors')
        optimizer = torch.load(folder / 'optimizer.pt', map_location='cpu', weights_only=True)
        if (len(optimizer['state']) != (144 if arm == 'full-ce' else 96)
                or {int(v['step']) for v in optimizer['state'].values()} != {240}):
            raise ValueError('Saved AdamW state does not contain the claimed real updates')
        encoder = [v for k, v in tensors.items() if '.encoder.' in k and '.lora_B.' in k]
        decoder = [v for k, v in tensors.items() if '.decoder.' in k and '.lora_B.' in k]
        if len(decoder) != 48 or not all(bool(v.abs().sum() > 0) for v in decoder):
            raise ValueError('Decoder did not receive actual adaptation')
        if arm == 'full-ce':
            if len(encoder) != 24 or not all(bool(v.abs().sum() > 0) for v in encoder):
                raise ValueError('Encoder adaptation was not actually learned')
        elif encoder:
            raise ValueError('Decoder-only arm includes encoder adaptation')
        conversion = read(RUN / 'io-convert/conversions' / (arm + '.json'))
        manifest = conversion['model']
        root = Path('/experiment/models') / manifest['model']
        if read(root / 'manifest.json') != manifest:
            raise ValueError('Converted model identity changed')
        for name, expected in manifest['files'].items():
            if sha(root / name) != expected:
                raise ValueError('Converted model bytes changed')
        result[arm] = {'actual_updates': 240, 'coverage': dict(Counter(details['coverage'].values())),
            'nonzero_decoder_B_tensors': len(decoder), 'nonzero_encoder_B_tensors': len(encoder),
            'frozen_base_unchanged': True, 'model': manifest['model']}
    if len(initial) != 1 or len(schedules) != 1:
        raise ValueError('Common initialization or sample schedules differ')
    value = {'status': 'PASS', 'common_decoder_initialization_identical': True,
        'sample_schedules_identical': True, 'arms': result, 'plan_sha256': sha(RUN / 'plan.json')}
    preserve(RUN / 'model-verification.json', value)
    print(json.dumps(value, indent=2), flush=True)


def report():
    plan, result, prep = read(RUN / 'plan.json'), read(RUN / 'comparison.json'), read(PREP / 'result.json')
    for directory, name in [(PREP, 'verification.json'), (RUN, 'model-verification.json')]:
        if read(directory / name)['status'] != 'PASS':
            raise ValueError('Artifact verification incomplete')
    if result['plan_sha256'] != sha(RUN / 'plan.json'):
        raise ValueError('Comparison identity differs')
    for name, expected in plan['implementation_sha256'].items():
        if sha(RUN / 'frozen' / name) != expected:
            raise ValueError('Frozen implementation changed')
    systems = ['baseline', 'decoder-kl', 'decoder-ce', 'full-ce']
    execution = {}
    for system in systems + ['cpu-' + a for a in systems[1:]]:
        root = RUN / ('io-' + system)
        e = read(root / 'execution.json')
        if e['plan_sha256'] != sha(RUN / 'plan.json') or e['runtime_failures']:
            raise ValueError('Execution failed')
        for name, expected in e['prediction_sha256'].items():
            if sha(root / 'predictions' / name) != expected:
                raise ValueError('Prediction artifact changed')
            record = read(root / 'predictions' / name)
            model = plan['baseline_model']['name'] if system == 'baseline' else plan['model_names'][system.removeprefix('cpu-')]
            if record['config']['model'] != model or record['plan_sha256'] != sha(RUN / 'plan.json'):
                raise ValueError('Candidate label or inference plan differs')
        execution[system] = {k: e[k] for k in ('records', 'new_ASR_calls', 'actual_device', 'actual_precision')}
    preserve(RUN / 'execution-verification.json', {'status': 'PASS', 'executions': execution,
        'plan_sha256': sha(RUN / 'plan.json'), 'human_verified_new_dev': False})
    labels = {'publisher_weak_dev': 'Чек-листы dev, слабая разметка', 'partial_human_dev': 'Частично ручной dev',
        'general_clean': 'Обычная английская речь', 'general_ru': 'Обычная русская речь',
        'quiet_general_clean': 'Тихий английский', 'quiet_partial_human_dev': 'Тихие версии ручного dev',
        'train_retained_fit': 'Train: сохранённые фрагменты', 'train_hard_fit': 'Train: новые сложные',
        'train_noisy_fit': 'Train: шумовые копии'}
    text = ['# Сложные фрагменты и сравнение режимов обучения', '',
        f'Подготовка, три обучения и сравнение завершены. Диагностический статус фиксированного full-ce: **{result["diagnostic_status"]}**.',
        'Рабочая модель не заменена. Новые человеческие эталоны автоматически не создавались.', '',
        '## Данные и очередь проверки', '',
        f'Проверены {prep["hard_candidates"]} сложных кандидатов; выполнено 377 новых large-v3/EN распознаваний.',
        f'Приняты **{prep["accepted_hard"]} слабых пар / {prep["hard_minutes"]:.2f} минуты**, где small ошибается относительно',
        'согласованного текста medium.en и large-v3 с поддержкой документа. Согласие моделей остаётся слабой разметкой.',
        f'Сохранены {prep["retained_old"]} прежних пар; {prep["replaced_old_overlaps"]} старых нарезок заменены из-за пересечения.',
        f'Добавлены {prep["noisy_pairs"]} шумовых копий Beech/TBM940 ({prep["noisy_minutes"]:.2f} минуты), с проверкой источника и локального акустического сходства.',
        f'Итого **{prep["train_pairs"]} пар / {prep["train_minutes"]:.2f} минуты**, из них {prep["unique_clean_minutes"]:.2f} минуты оригинальных интервалов, 9 дикторов.',
        f'Очередь: **{prep["review_train"]} спорных train + {prep["review_dev"]} новых dev**, всего {prep["review_minutes"]:.2f} минуты аудио.',
        'Новые dev: 7 записей, 3 диктора, без машинных черновиков; выбранные интервалы не перекрывают прежние 35 weak-dev и старый пакет разметки.',
        'Новых независимых голосов эти интервалы не добавляют. До ручной расшифровки они не участвуют в подсчёте WER.',
        '[Открыть очередь разметки](http://localhost:8011). Вход с прежним ключом; сначала полезно разметить 42 dev (7 минут аудио).',
        'Для dev: прослушать, записать слышимые слова, отметить язык и подтверждение расшифровки. Неразборчивое не угадывать.',
        'Для train: сравнить три черновика с аудио, особенно числа, on/off, отрицания; автоматически проверенным текст не становится.', '',
        '## Сравнение', '',
        'Все варианты: один train, одинаковый порядок 960 предъявлений, 240 реальных обновлений, одинаковая инициализация общего адаптера.',
        'Decoder+KL — прежний осторожный режим; decoder CE снимает KL; full CE дополнительно обучает адаптер кодировщика звука.',
        'Последний checkpoint каждого режима задан заранее. Набор обучения не позволяет отдельно приписать эффект только новым парам.',
        'WER в процентах, меньше лучше. Train-строки показывают подгонку, а не качество на новых записях.', '',
        '| Набор | N | Исходная | Decoder+KL | Decoder CE | Full CE |', '|---|---:|---:|---:|---:|---:|']
    for name, label in labels.items():
        row = result['cohorts'][name]
        values = ' | '.join(f'{row["scores"][s]["wer_lexical_corpus"]*100:.2f}' for s in systems)
        text.append(f'| {label} | {row["samples"]} | {values} |')
    text += ['', 'Ложные слова на шуме, слов/мин:', '', '| Набор | Исходная | Decoder+KL | Decoder CE | Full CE |', '|---|---:|---:|---:|---:|']
    for name in ('noise_only', 'bleriot_b_noise'):
        values = ' | '.join(f'{result["cohorts"][name]["inserted_words_per_minute"][s]:.2f}' for s in systems)
        text.append(f'| {name} | {values} |')
    human = result['cohorts']['partial_human_dev']
    weak = result['cohorts']['publisher_weak_dev']
    human_ci = human['comparisons']['full-ce_vs_baseline']['bootstrap']
    weak_ci = weak['comparisons']['full-ce_vs_baseline']['bootstrap']
    text += ['', '## Что показал опыт', '',
        'На пяти частично ручных фрагментах decoder CE и full CE дали 15 ошибок вместо 16 на 115 словах:',
        'относительное снижение 6.25%, ниже заданных 10%. Decoder+KL остался на 16 ошибках.',
        f'95% групповой интервал изменения WER full CE: [{human_ci["lower"]*100:.2f}; {human_ci["upper"]*100:.2f}] п.п.;',
        'нулевой эффект не исключён, независимых групп всего три.',
        'Чистое уменьшение счётчика связано с одним фрагментом и заменой `both` на `pause`, совпадающей с прежним частичным эталоном.',
        'Повторной человеческой проверки этого слова в данном опыте не было. В другом фрагменте исправление `of` → `off`',
        'компенсируется дополнительным вставленным словом. `No amber or red` по-прежнему распознаётся как `November in red`.', '',
        'На 35 слабых dev full CE дал 190 ошибок вместо 201 на 879 словах (WER 22.87% → 21.62%).',
        f'95% групповой интервал дельты: [{weak_ci["lower"]*100:.2f}; {weak_ci["upper"]*100:.2f}] п.п., всего две группы.',
        'Улучшение WER сопровождается ухудшением CER: 11.53% → 11.76%. Эти тексты не дают независимого подтверждения качества.', '',
        'Снятие KL заметно меняет подгонку шумового train: 259 → 125 ошибок; добавление encoder LoRA — 125 → 118.',
        'Большая часть снижения — сокращение вставок, 163 → 35 → 30. Даже у full CE WER на этих обучающих копиях 92.91%.',
        'Значения WER выше 100% допустимы при большом числе вставок; это не доля неправильно распознанных фрагментов.',
        'На новых сложных train WER падает с 22.31% до 11.85%, но это совпадение со слабыми целевыми текстами на обучении.', '',
        'Обучение энкодера не добавило выигрыша на пяти исходных dev по сравнению с decoder CE и ухудшило их тихие версии:',
        '17 → 20 ошибок. На отдельном noise-only контроле все адаптеры вставляют больше слов, чем исходная модель:',
        '6.8 → 36.8 / 24.0 / 24.4 слова в минуту. На BLeRIOT-B у CE-вариантов есть небольшой сдвиг 4.59 → 4.19.',
        'Ни один режим не прошёл все диагностические проверки. Выбирать или заменять рабочую модель по этим результатам оснований нет.', '',
        'Практический недостаток данных сохраняется: автоматически добавлено лишь 4.14 минуты сложной речи и 1.46 минуты',
        'шумовых копий двух дикторов; 352 спорных кандидата не получили надёжных текстов. Следующий подготовленный шаг —',
        'человеческая расшифровка 42 новых контрольных интервалов и исправление 60 приоритетных train в очереди.',
        'Разметку новых dev нужно закончить до просмотра ответов моделей; для дальнейшего расширения нужны дополнительные записи и голоса.']
    text += ['', '## Проверки и ограничения', '',
        'Числа, состояния и неподдержанные документом значения при расхождении учителей отправлялись в проверку.',
        'Файлы и источники сверены по хешам; производные шумовые и blind-dev аудио воспроизведены точно из оригиналов.',
        'В каждом режиме подтверждены реальные счётчики AdamW и ненулевые обученные матрицы адаптера.',
        'Все исходные базовые веса сохранены; у full-ce реально обучены 24 encoder LoRA B-матрицы.',
        f'Сравнение: {result["new_GPU_ASR"]} новых GPU-распознаваний, 6 CPU-проверок запуска; с подготовкой — {result["new_GPU_ASR"]+377} GPU-вызовов.',
        'Полный набор тестов перед последней правкой интерфейса: 494 passed, 9 deselected. После правки blind-dev: 21 UI/API тест passed; Ruff пройден.',
        'Локальный интерфейс проверен с авторизацией и выдачей WAV; запрос подсказки для blind-dev отклоняется без записи ложной экспозиции.',
        'Проверки по режимам: `' + json.dumps(result['checks'], ensure_ascii=False) + '`.',
        '35 прежних dev имеют слабые тексты и только 2 группы; 5 частично ручных — 115 слов и 3 группы.',
        'Они уже использовались в прошлых опытах. Положительная точечная дельта не означает независимого подтверждения.',
        'Для этих 35 слабых dev нет подходящих пар BLeRIOT-C; дополнение noisy-dev в этот опыт не попало.',
        'Новый blind-dev пока ожидает человека. Sealed test не открывался; старые бюджеты и критерии не менялись.', '',
        '## Артефакты', '',
        '`data/curated/cockpit-hard-v4/`: train, clean, hard, noisy и неизменённый dev.',
        '`data/curated/annotation-hard-v4/`: очередь, аудиоссылки, скрытые train-черновики и ревизии пользователя.',
        '`reports/cockpit-hard-v4/`: правила, решения, проверка учителей и аудио.',
        '`reports/cockpit-training-v4/`: frozen, plan, training, conversion, comparison, scored-counts и проверки.',
        'Модели в Docker volume `north55-speech_cockpit_training_v4`: `models/whisper-small-cockpit-hard-v4-{decoder-kl,decoder-ce,full-ce}`.',
        'Запуск этапов: `python -m scripts.run_cockpit_training_v4 STAGE [ARM]`; существующие обучения и конвертации защищены от перезаписи.', '']
    (RUN / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    print('Report and execution verification written:', RUN / 'report.md')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['data', 'models', 'report'])
    args = parser.parse_args()
    {'data': data_audit, 'models': models_audit, 'report': report}[args.stage]()
