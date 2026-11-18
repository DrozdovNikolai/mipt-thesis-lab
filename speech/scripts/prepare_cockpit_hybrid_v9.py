"""Package the tested router with fixed ASR settings and four audio-only smoke inputs."""
import os
import shutil
from pathlib import Path

import soundfile as sf

from north55_speech.core import file_hash
from scripts.cockpit_cross_asr_v6 import pcm, read, save


def main():
    work = Path('/app')
    root = work/'reports/cockpit-noise-router-v9'
    assert read(root/'verification.json')['status'] == 'PASS'
    package = root/'local-runtime'
    assert not package.exists()
    frozen = package/'frozen'
    shutil.copytree(work/'src', frozen/'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (frozen/'scripts').mkdir()
    shutil.copyfile(work/'scripts/transcribe_cockpit_hybrid_v9.py', frozen/'scripts/transcribe_cockpit_hybrid_v9.py')
    code = {p.relative_to(frozen).as_posix(): file_hash(p) for p in sorted(frozen.rglob('*.py'))}
    prior = work/'reports/cockpit-robust-v5'
    p5 = read(prior/'plan.json')
    conversion = read(prior/'io-convert/conversions/balanced.json')
    assert conversion['plan_sha256'] == file_hash(prior/'plan.json')
    model = conversion['model']['model']
    assert read(Path('/robust/models')/model/'manifest.json') == conversion['model']
    cross = read(work/'reports/cockpit-cross-asr-v6/model-manifest.json')
    training = read(root/'io-train/training.json')
    config = {'implementation_sha256': code, 'training_sha256': file_hash(root/'io-train/training.json'),
        'router_sha256': training['files']['router.joblib'],
        'whisper_config': {**p5['config'], 'model': model},
        'whisper_manifest_sha256': file_hash(Path('/robust/models')/model/'manifest.json'),
        'parakeet_sha256': cross['files']['parakeet-tdt-0.6b-v2.nemo']['sha256'],
        'prior_router_plan_sha256': file_hash(root/'plan.json'), 'experimental': True,
        'smoke_rule': 'first id sorted in each of train_retained_fit, train_noisy_fit, noise_only, quiet_general_clean'}
    save(package/'runtime.json', config)
    items = read(root/'inputs.json')
    refs = read(root/'scoring/references.json')
    decisions = {r['id']: r for r in read(root/'io-infer/decisions.json')}
    expected = []
    smoke = root/'smoke-audio'
    smoke.mkdir()
    for name, cohort in [('clean', 'train_retained_fit'), ('noisy', 'train_noisy_fit'),
        ('empty', 'noise_only'), ('quiet', 'quiet_general_clean')]:
        item = sorted([i for i in items if refs[i['id']]['cohort'] == cohort], key=lambda i: i['id'])[0]
        source = Path('/cross')/item['audio_path']
        assert file_hash(source) == item['audio_sha256']
        path = smoke/(name+'.wav')
        shutil.copyfile(source, path)
        x, rate = sf.read(path, dtype='float32')
        assert rate == 16000 and pcm(x) == item['pcm_sha256']
        expected.append({'file': path.name, 'id': item['id'], 'pcm_sha256': item['pcm_sha256'],
            'route': decisions[item['id']]['selected'], 'whisper': item['whisper'], 'parakeet': item['parakeet'],
            'hypothesis': decisions[item['id']]['hypothesis'], 'original_language': item['original_input_language']})
    save(root/'live-smoke-expected.json', expected)
    output = root/'local-output'
    output.mkdir()
    for folder in (package, smoke, output):
        for path in [folder, *folder.rglob('*')]:
            os.chown(path, 10001, 10001)
    print({'runtime_sha256': file_hash(package/'runtime.json'), 'smoke_files': [r['file'] for r in expected]}, flush=True)


if __name__ == '__main__':
    main()
