"""Record the single pre-inference runtime repair without rewriting the training plan."""
from pathlib import Path
from scripts.soteria_training_v15 import read, sha, save

workspace = Path(__file__).resolve().parents[1]
study = workspace/'reports/soteria-training-v15'
original = study/'frozen/scripts/soteria_training_v15.py'
updated = workspace/'scripts/soteria_training_v15.py'
old = original.read_text(encoding='utf-8')
new = updated.read_text(encoding='utf-8')
assert new == old.replace('        provider.config = config\n', '        provider.config = config\n        provider.model = model\n')
assert not list((study/'predictions').rglob('*.json'))
assert read(study/'run-train.json')['exit_code'] == read(study/'run-convert.json')['exit_code'] == 0
target = study/'runtime/soteria_training_v15.py'
target.parent.mkdir(parents=True)
with target.open('xb') as stream:
    stream.write(updated.read_bytes())
save(study/'inference-runtime-fix.json', {
    'reason':'AsrProvider.options inspects model.transcribe; attach the existing WhisperModel to the options helper',
    'diff':'one assignment: provider.model = model',
    'original_sha256':sha(original),'runtime_sha256':sha(target),
    'original_plan_sha256':sha(study/'plan.json'), 'fix_script_sha256':sha(Path(__file__)),
    'existing_ASR_predictions':0,'training_and_models_changed':False,
    'ASR_options_changed':False,'original_failure_preserved':'failed-infer-small.json',
})
print('Recorded inference-only repair; training plan and checkpoints unchanged.')
