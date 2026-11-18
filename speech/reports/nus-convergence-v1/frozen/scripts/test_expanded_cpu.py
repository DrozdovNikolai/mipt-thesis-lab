"""Real offline CPU inference of the newly converted checkpoint; engineering only."""

import json
import time
from pathlib import Path

import soundfile as sf

from north55_speech.asr import AsrProvider
from north55_speech.core import atomic_json, file_hash, read_yaml, settings
from north55_speech.schemas import PipelineConfig


def main():
    config = PipelineConfig.model_validate(read_yaml(Path('/app/configs/baseline.yaml')))
    config.model = 'whisper-small-publisher-expanded-v1-ct2'
    config.device, config.compute_type = 'cpu', 'int8'
    item = json.loads(Path('/clean-controls/plan.json').read_text())['items'][0]
    path = settings.audio_root / item['audio_path']
    if file_hash(path) != item['audio_sha256']:
        raise ValueError('Frozen control audio changed')
    started = time.perf_counter()
    provider = AsrProvider(config)
    audio, rate = sf.read(path, dtype='float32')
    if rate != 16000 or audio.ndim != 1:
        raise ValueError('Unexpected control audio format')
    segments = provider.transcribe(audio, 0, 'en', 'cpu-smoke', lambda: None)
    result = {'status': 'PASS' if any(s.raw_asr_text.strip() for s in segments) else 'FAIL',
              'purpose': 'engineering_CPU_checkpoint_execution_only', 'config': config.model_dump(),
              'actual_device': provider.model.model.device, 'actual_compute_type': provider.model.model.compute_type,
              'sample_id': item['id'], 'audio_sha256': file_hash(path),
              'model_manifest_sha256': file_hash(settings.model_root / config.model / 'manifest.json'),
              'script_sha256': file_hash(Path(__file__)), 'segments': [s.model_dump() for s in segments],
              'elapsed_including_model_load_sec': time.perf_counter() - started, 'quality_evidence': False}
    atomic_json(Path('/reports/all-sources-v1/cpu-smoke.json'), result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'segments', 'config'}}, indent=2))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
