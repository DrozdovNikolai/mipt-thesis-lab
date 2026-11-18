"""Actual offline large-v3 CPU smoke; separate from the GPU accuracy comparison."""

import json
import time
from pathlib import Path

import soundfile as sf

from north55_speech.asr import AsrProvider
from north55_speech.core import atomic_json, file_hash, now
from north55_speech.schemas import PipelineConfig

ROOT = Path('/reports/language-large-v1')


def main():
    plan = json.loads((ROOT / 'plan.json').read_bytes())
    if file_hash(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Input snapshot changed')
    items = json.loads((ROOT / 'inputs.json').read_bytes())
    selected = [next(i for i in items if i['cohort'] == c) for c in ('partial_human_dev', 'general_ru', 'bleriot_b_noise')]
    config = PipelineConfig.model_validate(plan['configs']['large_known'] | {'device': 'cpu', 'compute_type': 'int8'})
    started = time.perf_counter()
    provider = AsrProvider(config)
    rows = []
    for item in selected:
        path = Path('/audio') / item['audio_path']
        if file_hash(path) != item['audio_sha256']:
            raise ValueError('Audio changed')
        waveform, rate = sf.read(path, dtype='float32')
        if rate != 16000 or waveform.ndim != 1:
            raise ValueError('Invalid frozen input')
        begin = time.perf_counter()
        segments = provider.transcribe(waveform, 0, item['input_language'], item['id'], lambda: None)
        rows.append({'id': item['id'], 'cohort': item['cohort'], 'audio_sha256': item['audio_sha256'],
            'effective_options': provider.options(item['input_language']), 'hypothesis': ' '.join(s.raw_asr_text.strip() for s in segments),
            'segments': [s.model_dump() for s in segments], 'asr_elapsed_sec': time.perf_counter() - begin})
    passed = all(r['hypothesis'] for r in rows[:2]) and provider.model.model.device == 'cpu'
    result = {'status': 'PASS' if passed else 'FAIL', 'purpose': 'offline_engineering_smoke_not_quality_comparison',
        'actual_device': provider.model.model.device, 'actual_compute_type': provider.model.model.compute_type,
        'requested_compute_type': config.compute_type, 'model_manifest': provider.manifest,
        'plan_sha256': file_hash(ROOT / 'plan.json'), 'script_sha256': file_hash(Path(__file__)),
        'completed_at': now().isoformat(), 'total_sec': time.perf_counter() - started,
        'initialization_sec': provider.initialization_sec, 'rows': rows}
    atomic_json(ROOT / 'cpu-smoke.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'rows', 'model_manifest'}}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
