"""Read-only audit of saved weights, optimizer steps and physical training waveforms."""
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from safetensors.torch import load_file

ROOT = Path('/study')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


plan = read(ROOT/'plan.json')
training = read(ROOT/'training.json')
samples = read(ROOT/'train.json')
schedule = read(ROOT/'schedule.json')
contracts = {r['id']: r for r in read(ROOT/'audio-contracts.json')}
inputs = read(ROOT/'inputs.json')
assert len(samples) == len(contracts) == 310
assert not {r['id'] for r in samples} & {r['id'] for r in inputs}
assert not {r['audio_sha256'] for r in samples} & {r['audio_sha256'] for r in inputs}
assert training['plan_sha256'] == sha(ROOT/'plan.json')
repair = read(ROOT/'inference-runtime-fix.json')
assert sha(ROOT/'runtime/soteria_training_v15.py') == repair['runtime_sha256']
assert repair['original_plan_sha256'] == sha(ROOT/'plan.json')
original_text = (ROOT/'frozen/scripts/soteria_training_v15.py').read_text(encoding='utf-8')
repaired_text = (ROOT/'runtime/soteria_training_v15.py').read_text(encoding='utf-8')
assert repaired_text == original_text.replace('        provider.config = config\n', '        provider.config = config\n        provider.model = model\n')
for name, expected in plan['inputs'].items():
    assert sha(ROOT/name) == expected, name
for name, expected in plan['code'].items():
    assert sha(ROOT/'frozen'/name) == expected, name
origins = {r['id']:r['origin'] for r in samples}
for row in samples:
    root = Path('/soteria') if row['origin']=='soteria' else Path('/legacy')
    path = (root/row['audio_path']).resolve()
    assert path.is_relative_to(root) and sha(path) == row['audio_sha256']
    wave, rate = sf.read(path, dtype='float32', always_2d=True)
    wave = wave[:,row['channel']].copy()
    assert rate == 16000 and np.isfinite(wave).all()
    assert hashlib.sha256(wave.astype('<f4').tobytes()).hexdigest() == contracts[row['id']]['pcm_sha256']
    assert hashlib.sha256(row['target'].encode()).hexdigest() == contracts[row['id']]['target_sha256']
    assert len(wave) == contracts[row['id']]['samples']
assert set(schedule['replay_control']) == {r['id'] for r in samples if r['origin']=='replay'}
assert set(schedule['soteria_mix']) == {r['id'] for r in samples}
for step in range(160):
    control = schedule['replay_control'][4*step:4*step+4]
    mixed = schedule['soteria_mix'][4*step:4*step+4]
    assert control[:2] == mixed[:2]
    assert [origins[k] for k in control] == ['replay']*4
    assert [origins[k] for k in mixed] == ['replay','replay','soteria','soteria']
adapters = {}
for arm in plan['policy']['arms']:
    folder = ROOT/'models'/arm
    for name, expected in training['arms'][arm]['files'].items():
        assert sha(folder/'adapter'/name) == expected
    optimizer = torch.load(folder/'adapter/optimizer.pt', map_location='cpu', weights_only=True)
    assert len(optimizer['state']) == 96
    assert {int(v['step']) for v in optimizer['state'].values()} == {160}
    assert all(torch.isfinite(v[key]).all() for v in optimizer['state'].values() for key in ('exp_avg','exp_avg_sq'))
    adapter = load_file(str(folder/'adapter/adapter_model.safetensors'))
    assert len(adapter) == 96 and all(torch.isfinite(v).all() for v in adapter.values())
    assert all('.decoder.layers.' in name and '.lora_' in name for name in adapter)
    assert sum(float(v.abs().sum()) for name,v in adapter.items() if '.lora_B.' in name) > 0
    manifest = read(folder/'ct2/manifest.json')
    for name, expected in manifest['files'].items():
        assert sha(folder/'ct2'/name) == expected
    assert manifest['files']['model.bin'] != plan['v14_models']['small']['files']['model.bin']
    adapters[arm] = sha(folder/'adapter/adapter_model.safetensors')
assert len(set(adapters.values())) == 2
print(json.dumps({'status':'PASS','audit_script_sha256':sha(Path(__file__)),
    'waveforms_and_targets_reverified':len(samples),'schedule_updates_per_arm':160,
    'saved_optimizer_tensors_per_arm':96,'finite_trained_adapters':adapters,
    'inference_only_repair_verified':True,
    'training_evaluation_audio_disjoint':True,'human_annotations_created':0,
    'closed_test_accessed':False},indent=2))
