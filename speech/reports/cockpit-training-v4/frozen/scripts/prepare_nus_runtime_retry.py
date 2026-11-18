"""Preserve failed CUDA evaluation and clone the identical protocol to a new attempt."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path('reports/nus-training-v1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    original, retry = ROOT / 'evaluation', ROOT / 'evaluation-v2'
    if retry.exists():
        raise ValueError('Preserve retry directory')
    failures = [json.loads(path.read_bytes()) for path in (original / 'nus/predictions').glob('*.json')]
    expected = {'type': 'RuntimeError', 'message': 'Library libcublas.so.12 is not found or cannot be loaded'}
    if len(failures) != 675 or any(row['runtime_failure'] != expected or row['hypothesis'] for row in failures):
        raise ValueError('Unexpected first-attempt failures; inspect before retry')
    retry.mkdir()
    for name in ('plan.json', 'inputs.json', 'protocol.md'):
        shutil.copyfile(original / name, retry / name)
    shutil.copytree(original / 'historical', retry / 'historical')
    shutil.copytree(original / 'cpu-nus', retry / 'cpu-nus')
    (retry / 'nus').mkdir()
    report = {'recorded_at': datetime.now(UTC).isoformat(), 'reason': expected,
        'failed_prediction_count': 675, 'failed_comparison_sha256': sha(original / 'comparison.json'),
        'preserved_original_hashes': {path.relative_to(original).as_posix(): sha(path)
                                    for path in original.rglob('*') if path.is_file()},
        'original_plan_sha256': sha(original / 'plan.json'), 'retry_plan_sha256': sha(retry / 'plan.json'),
        'identical_protocol_inputs_and_references': True, 'training_repeated': False,
        'scorer_or_weights_modified': False, 'successful_CPU_records_reused': 4,
        'correction': 'Explicit LD_LIBRARY_PATH for installed cuBLAS and cuDNN; same paths as prior GPU image',
        'retry_directory': retry.as_posix()}
    (ROOT / 'cuda-runtime-retry.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'preserved_original_hashes'}, indent=2))


if __name__ == '__main__':
    main()
