"""Identify the actual draft model used for the fixed human evaluation references."""
from pathlib import Path
from scripts.soteria_training_v15 import read, sha, save

workspace = Path(__file__).resolve().parents[1]
study = workspace/'reports/soteria-training-v15'
packet = workspace/'data/curated/annotation-hard-v4/assisted-drafts'
references = read(study/'scoring/references.json')
records = []
for row in references:
    path = packet/(row['sample_id']+'.json')
    draft = read(path)
    exposure = row['annotation_provenance']
    assert exposure['machine_draft_exposed'] is True
    assert sha(path) in exposure['machine_draft_sha256']
    assert draft['audio_sha256'] == row['audio_sha256']
    records.append({'id':row['sample_id'], 'draft_sha256':sha(path), 'model':draft['model'],
                    'model_manifest_sha256':draft['model_manifest_sha256'], 'language_mode':draft['language_mode']})
assert len(records) == 16
assert {r['model'] for r in records} == {'whisper-large-v3-systran-ct2'}
result = {'status':'PASS','references':records,'all_16_references_corrected_from_large_v3_drafts':True,
    'interpretation':'Observed large-v3 WER may benefit from anchoring to its own drafts; not a blind independent comparison',
    'human_edits_are_preserved':True,'reference_sha256':sha(study/'scoring/references.json'),
    'audit_script_sha256':sha(Path(__file__))}
save(study/'reference-exposure-audit.json',result)
with (study/'report.md').open('a',encoding='utf-8') as stream:
    stream.write('\n## Ограничение сравнения с large-v3\n\n'
        'По хешам фактически показанных черновиков подтверждено: все 16 человеческих эталонов исправлялись '
        'из ответов того же Whisper large-v3. Это может давать модели преимущество из-за влияния подсказки '
        'на разметку. 8,37% WER — измеренная диагностика на исправленных пользователем текстах, '
        'а не доказательство независимого превосходства над v9. Человеческие правки и все эталоны сохранены. '
        'Подробности: `reference-exposure-audit.json`.\n')
print('Verified: all 16 human references were corrected from large-v3 drafts; comparison caveat recorded.')
