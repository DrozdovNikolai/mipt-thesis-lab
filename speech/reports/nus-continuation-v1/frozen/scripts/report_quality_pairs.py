"""Render measured preparation results; no new evaluation or selection."""

import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1] / 'reports/pair-quality-v1'
    pairs = json.loads((root / 'preparation-report.json').read_bytes())
    support = json.loads((root / 'training-support.json').read_bytes())
    verification = json.loads((root / 'verification.json').read_bytes())
    lines = [
        '# Автоматическая подготовка обучающих пар · pair-quality-v1', '',
        'Новая ручная разметка не использовалась. Прежние данные, результаты и требования сохранены.', '',
        '| Набор | Пар | Минут | Основание текста |',
        '|---|---:|---:|---|',
        f'| Прежний BLeRIOT train | {pairs["old_train_pairs"]} | {pairs["old_train_minutes"]:.2f} | Слабая автоматическая привязка сценария |',
        f'| Новый BLeRIOT train | {pairs["accepted_train_pairs"]} | {pairs["accepted_minutes"]:.2f} | Точное lexical-согласие small EN, large auto и сценария; прежний alignment gate |',
        f'| LibriSpeech EN train | {support["languages"]["en"]} | {support["minutes"]["en"]:.2f} | Готовый текст корпуса, CC BY 4.0 |',
        f'| FLEURS RU train | {support["languages"]["ru"]} | {support["minutes"]["ru"]:.2f} | Готовый текст корпуса, CC BY 4.0 |', '',
        f'Обработано {pairs["considered_train_windows"]} фрагментов из девяти чистых train-оригиналов. '
        f'Выполнено {pairs["asr_calls"]} GPU-вызовов ASR. Ошибки: {pairs["asr_failures"]}. '
        f'Новые пары представляют {pairs["accepted_speakers"]} известных дикторов. '
        f'Прежние {pairs["unchanged_dev_pairs"]} dev-пар сохранены побайтно.', '',
        'Данные BLeRIOT остаются weak: истинная точность автоматически отобранных пар неизвестна. '
        'Два Whisper могут ошибаться одинаково. Паузы и таймкоды уменьшают риск обрезанных слов, '
        'но не доказывают их полную сохранность. Числа, отрицания и словоформы не исправлялись.', '',
        'Общие EN/RU данные подготовлены отдельно, без обучения модели. Статус human_verified '
        'в их манифесте относится к человеческим текстам поставщика корпуса, а не к местному '
        'прослушиванию. В provenance явно записано local_manual_verification=false. '
        'NLP labels, сущности и временные события не созданы.', '',
        f'Ограничение разнообразия: EN-подвыборка содержит {support["known_en_speakers"]} известных диктора; '
        'индивидуальные RU speaker IDs отсутствуют. Это стартовый обучающий пакет, не достаточный '
        'набор для доказательства обобщения.', '',
        'Причины отказа пересекаются; суммы ниже не являются числом уникальных отклонённых фрагментов.', '',
        '| Причина | Срабатываний |', '|---|---:|',
    ]
    lines += [f'| {reason} | {count} |' for reason, count in sorted(pairs['rejection_reasons'].items(), key=lambda x: -x[1])]
    lines += ['',
        f'Проверка исполнения: **{verification["status"]}**, {len(verification["checks"])} проверок артефактов; '
        '38 контрактных тестов. Верификация включает исходные хеши, контроль split, '
        'точное согласие принятых текстов, полную популяцию ASR, сетевую изоляцию и отсутствие '
        'дубликатов новых общеречевых WAV среди прежних 661 диагностических входов.', '',
        '### Ограничение следующего обучения', '',
        '**BLOCKED_SEARCH_BUDGET_EXHAUSTED**: предыдущий протокол использовал 16/16 dev-конфигураций. '
        'ACCEPTANCE.yaml требует остановки поиска при исчерпании бюджета. Новая подготовка читала '
        'только train для отбора и добавила ноль dev-конфигураций. Сравнение обучения на старых/новых '
        'парах с выбором checkpoint по dev в этом этапе не выполнялось. Лимит не изменён.', '',
        '**Качество ASR: NEEDS_MORE_DATA.** Улучшение WER, точность критических сущностей и '
        'пригодность нового набора для обучения этим этапом не доказаны. Release не менялся.', '',
        '### Воспроизведение и происхождение', '',
        '[Команды и ограничения](../../docs/quality_pairs.md) · '
        '[Сводка подготовки](preparation-report.json) · [Общие EN/RU пары](training-support.json) · '
        '[Верификация](verification.json).', '',
        'Издатель FLEURS сообщает о разных дикторах train и dev/test; индивидуальные IDs отсутствуют, '
        'поэтому новый RU train объединён в одну консервативную группу. Проверены отсутствие общих '
        'sentence IDs с исходным RU dev и дубликатов декодированного аудио. '
        '[Карточка FLEURS](https://huggingface.co/datasets/google/fleurs/blob/70bb2e84b976b7e960aa89f1c648e09c59f894dd/README.md).', '',
        'LibriSpeech: Panayotov et al., ICASSP 2015. '
        '[OpenSLR 12](https://www.openslr.org/12/). '
        'FLEURS: Conneau et al., 2022, arXiv:2205.12446. Оба корпуса — общая читаемая речь, '
        'не доказательство качества кабинного EN/RU/mixed. BLeRIOT ограничен CC BY-NC 4.0.', '',
        'Авторы FLEURS описывают проверку соответствия каждой записи предложенному тексту '
        'дополнительными проверяющими. Поэтому источник человеческой проверки — корпус, '
        'а не новый просмотр здесь. '
        '[Публикация авторов](https://simran-khanuja.github.io/assets/fleurs_slt.pdf).', '',
    ]
    (root / 'report.md').write_bytes(('\n'.join(lines)+'\n').encode('utf-8'))
    print(root / 'report.md')


if __name__ == '__main__':
    main()
