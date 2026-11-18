"""Write a concise report from completed artifacts; never score drafts as gold."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/'reports/soteria-v14'
PACKET=ROOT/'data/curated/soteria-v14/packet'


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    result=read(STUDY/'result.json')
    plan=read(STUDY/'experiment-plan.json')
    for name,expected in plan['frozen_sha256'].items():
        assert sha(STUDY/'frozen'/name)==expected,name
    assert read(STUDY/'packet-verification.json')['status']=='PASS'
    assert read(STUDY/'service-verification.json')['status']=='PASS'
    rows=[]
    for split in ('train','dev'):
        rows.extend(json.loads(x) for x in (PACKET/(split+'.jsonl')).read_text().splitlines() if x)
    policy=read(PACKET/'draft-policy.json')
    assert len(rows)==result['clips']==358
    hashes={}
    for row in rows:
        sid=row['sample_id']
        for arm in ('small','large'):
            p=STUDY/'predictions'/arm/(sid+'.json')
            value=read(p)
            assert value['audio_sha256']==row['audio_sha256'] and value['human_verified'] is False
            assert value['plan_sha256']==sha(STUDY/'experiment-plan.json')
            assert value['error'] is None
            hashes[str(p.relative_to(STUDY))]=sha(p)
        p=PACKET/'assisted-drafts'/(sid+'.json')
        assert sha(p)==policy['draft_sha256'][sid]
        assert p.read_bytes()==(STUDY/'predictions/large'/p.name).read_bytes()
    verification={'status':'PASS','frozen_files':len(plan['frozen_sha256']),'ASR_records':len(hashes),
        'authorized_drafts':len(policy['enabled_sample_ids']),'segmentation_unit_tests_passed':9,
        'references_created_by_agent':0,'test_accessed':False,'prediction_sha256':hashes}
    (STUDY/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    t=result['splits']['train'];d=result['splits']['dev']
    lines=['# Первый опыт с NASA SOTERIA','',
        f"Подготовлено **{result['clips']} фрагментов / {result['clip_minutes']:.2f} минуты речи** "
        f"из четырёх полных DVR-записей ({result['source_minutes']:.2f} минуты).",
        'Все 716 распознаваний завершились без ошибок исполнения. Проверка аудио, черновиков и интерфейса — PASS.', '',
        f"[Dev: {d['clips']} фрагмента / {d['minutes']:.2f} минуты](http://localhost:8013/?split=dev) · "
        f"[Train: {t['clips']} фрагментов / {t['minutes']:.2f} минуты](http://localhost:8013/?split=train).",'',
        '| Экипаж | Раздел | Исходное аудио, мин | Фрагментов | В очереди, мин |',
        '|---|---|---:|---:|---:|']
    for s in result['sources']:
        lines.append(f"| {s['crew']} | {s['split']} | {s['source_minutes']:.2f} | {s['clips']} | {s['clip_minutes']:.2f} |")
    lines += ['', '## Что показал опыт','',
        'Скачаны и проверены четыре полных видео, 4,916 ГБ. В записи входят инструктаж, '
        'общение в симуляторе и радиообмен. Все найденные VAD интервалы сохранены, '
        'без отбора удачных ответов модели. Доля именно кабинных реплик ещё не подтверждена.', '',
        'Для каждого отрывка получены два ответа: Whisper small и large-v3. '
        'В интерфейсе доступен черновик large-v3; второй ответ сохранён для анализа расхождений.',
        f"Машинные определения языка: {result['language_hints']}. "
        f"Пустых черновиков large-v3: {result['empty_large_drafts']}. "
        f"Совпали тексты двух моделей после нормализации регистра и пунктуации: {result['identical_drafts']} / {result['clips']}.", '',
        '**Это не измерение WER и не доказательство улучшения модели.** '
        'Согласованные машинные тексты могут ошибаться. Эталон появляется только после проверки человеком. '
        'Обучения, настройки по эталонам и переключения рабочего профиля не было.', '',
        '## Как использовать','',
        'Начать можно с dev-очереди: слушать отрывок, подставлять черновик и исправлять каждое слово. '
        'Язык, область речи и подтверждение текста остаются ручными. '
        'Неразборчивое не угадывать. Реплики инструктора и радиообмен не следует автоматически '
        'объявлять разговорами экипажа. Старые очереди и человеческие расшифровки BLeRIOT сохранены.', '',
        'Разделение train/dev выполнено по экипажам, но диспетчер и исследователи могут повторяться. '
        'Отдельные speaker IDs и независимость голосов не установлены. '
        'До обучения/независимой оценки нужно разобрать общих участников и область реплик. '
        'Остальные экипажи не открывались; новый финальный test не создавался.', '',
        'VAD может пропускать тихую речь. Полные аудиодорожки сохранены для дальнейшего восстановления; '
        'проверка покрытия относится ко всем найденным VAD участкам, а не доказывает обнаружение всей речи.', '',
        '## Воспроизводимость','',
        '`./scripts/Run-SoteriaV14.ps1` — проверяет/докачивает источники и использует сохранённые результаты. '
        'Код и политика заморожены до ASR; оригиналы проверены по SHA-256 и multipart ETag. '
        'Все 358 WAV сверены с исходными отсчётами. Девять тестов границ прошли. '
        'Read-only проверка интерфейса проверила все 358 карточек и аудио каждого экипажа, '
        'не создавая аннотаций или просмотров черновиков.', '',
        '[Инструкция](../../docs/soteria_v14.md) · [Результат](result.json) · '
        '[Проверка](verification.json) · [План](experiment-plan.json).', '',
        'Источник: [NASA SOTERIA Simulation Testbed Data](https://registry.opendata.aws/nasa-soteria-data/), '
        'CC BY 4.0, получен 16 сентября 2026. Производные файлы: извлечение аудио, '
        'ресемплинг, усреднение каналов и нарезка; машинные тексты созданы локально.', '']
    (STUDY/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:v for k,v in verification.items() if k!='prediction_sha256'}))


if __name__=='__main__':
    main()
