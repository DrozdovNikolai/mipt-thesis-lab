"""Finish the report from completed frozen comparisons and the independent artifact audit."""
from pathlib import Path
from scripts.soteria_training_v15 import read, sha, save

workspace = Path(__file__).resolve().parents[1]
study = workspace/'reports/soteria-training-v15'
result = read(study/'comparison.json')
plan = read(study/'plan.json')
assert read(study/'artifact-audit.json')['status'] == 'PASS'
assert read(study/'verification.json')['status'] == 'PASS'
for name, expected in plan['sources'].items():
    assert sha(workspace/name) == expected, name
for stage in ('tests','train','convert','infer-small','infer-large','infer-replay_control','infer-soteria_mix','score'):
    assert read(study/f'run-{stage}.json')['exit_code'] == 0
assert result['new_ASR_calls'] == 470
human = result['human_cockpit']['all_16']
counts = {name: value['lexical']['errors'] for name,value in human.items()}
comparisons = {}
for baseline in ('small','replay_control','previous_v9'):
    deltas = []
    for row in result['per_clip']:
        def errors(name):
            return sum(row['models'][name]['lexical'][k] for k in ('S','D','I'))
        deltas.append({'id':row['id'], 'error_change':errors('soteria_mix')-errors(baseline)})
    comparisons[baseline] = {'errors_change':sum(r['error_change'] for r in deltas),
        'improved_clips':sum(r['error_change']<0 for r in deltas),
        'worsened_clips':sum(r['error_change']>0 for r in deltas),
        'unchanged_clips':sum(r['error_change']==0 for r in deltas), 'per_clip':deltas}
best = min(counts.values())
decision = {'completed':True, 'candidate_errors':counts['soteria_mix'],
    'reference_words':human['soteria_mix']['lexical']['N'], 'all_model_errors':counts,
    'lowest_error_systems':[k for k,v in counts.items() if v==best],
    'candidate_deltas':comparisons, 'SOTERIA_specific_human_accuracy_measured':False,
    'promotion_performed':False, 'comparison_sha256':sha(study/'comparison.json'),
    'artifact_audit_sha256':sha(study/'artifact-audit.json'),
    'reporting_script_sha256':sha(Path(__file__))}
save(study/'decision.json',decision)
delta = comparisons['replay_control']['errors_change']
effect = 'уменьшило' if delta < 0 else 'увеличило' if delta > 0 else 'не изменило'
text = '\n## Результат опыта\n\n'
text += f"Добавление SOTERIA {effect} число ошибок по сравнению с контролем: {counts['replay_control']} → {counts['soteria_mix']} на 203 словах. "
text += f"Прежний v9: {counts['previous_v9']} ошибок; large-v3 без обучения: {counts['large']}.\n\n"
change = comparisons['replay_control']
text += f"Относительно контроля кандидат улучшил {change['improved_clips']} фрагментов, ухудшил {change['worsened_clips']}, "
text += f"не изменил число ошибок в {change['unchanged_clips']}. "
text += 'Это точечный результат на уже использованной небольшой dev-выборке, без доказательства переноса на всю кабинную речь.\n\n'
text += 'Независимый аудит заново прочитал все 310 обучающих аудио и целей, проверил сохранённые состояния AdamW '
text += '(96 тензоров, по 160 обновлений) и оба обученных адаптера. Все проверки прошли. '
text += 'Исходные данные и пользовательские эталоны сохранили свои хеши.\n\n'
text += 'Перед первым распознаванием исправлена одна строка инициализации помощника параметров. '
text += 'Исходный сбой, исправление и хеши сохранены в `inference-runtime-fix.json`; обучение и параметры ASR не менялись.\n'
with (study/'report.md').open('a', encoding='utf-8') as stream:
    stream.write(text)
print(__import__('json').dumps(decision,ensure_ascii=False,indent=2))
