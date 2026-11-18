"""Post-run diagnosis from existing artifacts; no model calls, relabeling or tuning."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'reports/retraining-v1'


def read(path):
    return json.loads(path.read_bytes())


def main():
    source = STUDY / 'evaluation/scored-rows.json'
    rows = read(source)
    lookup = {(r['system'], r['id']): r for r in rows if r['cohort'] == 'partial_human_dev'}
    ids = sorted({key[1] for key in lookup})
    totals = {system: {kind: sum(lookup[system, i]['score'][kind] for i in ids)
                       for kind in ('S', 'D', 'I', 'N')} for system in ('parent', 'control', 'augmented')}
    details = []
    for sample_id in ids:
        before, after = (lookup[s, sample_id]['score'] for s in ('parent', 'augmented'))
        details.append({'id': sample_id, 'baseline': before, 'augmented': after,
                        'error_delta': sum(after[k] - before[k] for k in ('S', 'D', 'I'))})
    train = [json.loads(line) for line in (ROOT / 'data/curated/retraining-v1/augmented/train.jsonl').read_text(encoding='utf-8').splitlines()]
    result = {
        'kind': 'post_run_failure_diagnosis_not_new_quality_trial',
        'scored_rows_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'human_dev_totals': totals, 'human_dev_fragments': details,
        'training_composition': {
            'sources': dict(Counter(s['source_dataset'] for s in train)),
            'conditions': dict(Counter(s['acoustic_condition'] for s in train)),
            'empty_transcript_examples': sum(not s['reference_text'].strip() for s in train),
            'weak_cockpit_pairs': sum(s['transcript_status'] == 'weak' for s in train),
            'publisher_general_pairs': sum(s['scope'] == 'general_control' for s in train),
        },
        'verified_training_tokenizer_prefix': ['<|startoftranscript|>', '<|en|>', '<|transcribe|>', '<|notimestamps|>'],
        'tokenizer_check': 'Actual local WhisperTokenizerFast from the training image; offline, no ASR calls.',
        'inference_without_timestamps': False,
        'hypotheses_not_established_causes': [
            'Text-only training versus timestamp-generating inference can be tested as a decoding-format mismatch.',
            'Additional words may include generation loops, real spoken repetitions missing in references, or fragment-boundary words.',
            'Almost all training examples are unaugmented speech; this does not establish adaptation to cabin acoustics or non-speech rejection.',
        ],
        'next_experiment_proposal': [
            'Compare timestamp decoding modes on the same frozen parent and augmented weights; preserve word/original timing through alignment.',
            'Separately compare conservative speech segmentation, measuring short-command deletions as well as noise insertions.',
            'Only then define a new acoustic-adaptation training experiment with train-only noise, unchanged source transcripts and clean replay.',
        ],
        'new_ASR_calls': 0, 'new_training_runs': 0, 'reference_edits': 0,
        'release_promoted': False, 'existing_quality_gate_unchanged': 'NEEDS_MORE_DATA',
        'sources': [
            'https://huggingface.co/docs/transformers/en/model_doc/whisper',
            'https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py',
        ],
    }
    (STUDY / 'failure-audit-v1.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    text = '''# Разбор неудачного переобучения

Это анализ сохранённых результатов, не новый подбор параметров. Исходные метрики,
эталоны, веса и пороги не изменены. Новых ASR-вызовов и обучений: 0.

## Что установлено

- На пяти dev-фрагментах: исходная модель — 10 замен, 1 пропуск, 5 вставок;
  дополненная — 9 замен, 0 пропусков, 17 вставок. Всего 16 → 26 ошибок на 115 словах.
- Рост целиком приходится на два фрагмента: +3 и +7 ошибок. В остальных трёх
  число ошибок не изменилось. Это маленькая диагностика, не независимый test.
- В одном фрагменте дополненная версия повторяет `annunciator panel` и
  `no amber or red`. Эталон содержит эту последовательность один раз.
  Само расхождение не доказывает, что повторов нет в аудио: требуется сверка.
- В train 33 слабые кабинные пары и 400 общих EN/RU пар. 432 записи помечены
  original, одна — publisher CVR simulation. Примеров с пустым текстом нет.
- Локальный tokenizer реально формирует `<|notimestamps|>` при обучении;
  текущий inference использует `without_timestamps=False`. Это проверяемое
  различие режимов, пока не доказанная причина ухудшения.

## Следующие проверки в порядке приоритета

1. Сопоставить форматы декодирования на уже сохранённых весах. Не обучать новую
   модель до этой проверки. Выравнивание слов должно сохранять исходные таймкоды.
2. Отдельно проверить сегментацию речи и тишины. Измерять как ложные вставки,
   так и удаление тихих/коротких команд. Не удалять повторы просто по тексту.
3. Если понадобится новое обучение, готовить акустические варианты существующих
   train-пар с прежними текстами, независимыми train-шумами и контролем слышимости.
   Не использовать dev/test шумовые оригиналы. Общую чистую речь оставить как
   защиту от ухудшения, а не выдавать её за кабинный корпус.
4. Независимый кабинный quality gate сохраняет дефицит данных и сущностей.
   Автоматические привязки и собственные ASR-ответы не могут заменить этот эталон.

Документация: [Whisper tokenizer](https://huggingface.co/docs/transformers/en/model_doc/whisper),
[faster-whisper decoding](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py).
'''
    (STUDY / 'failure-audit-v1.md').write_text(text, encoding='utf-8', newline='\n')
    print(json.dumps({'totals': totals, 'deltas': [r['error_delta'] for r in details],
                      'new_ASR_calls': 0, 'new_training_runs': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
