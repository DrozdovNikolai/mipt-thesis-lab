"""Execute the follow-up VAD gate on new real Russian and noise inputs on CPU."""

import json
import time
from pathlib import Path

import soundfile as sf

from north55_speech.asr import AsrProvider
from north55_speech.audio import VadProvider
from north55_speech.core import atomic_json, file_hash
from north55_speech.schemas import PipelineConfig, VadConfig
from scripts.additional_asr_experiment import inference_regions


def main():
    plan = json.loads(Path('/reports/additional-sources-v1/asr/plan.json').read_bytes())
    config = PipelineConfig.model_validate(plan['config'] | {'device': 'cpu', 'compute_type': 'int8'})
    started = time.perf_counter()
    provider = AsrProvider(config)
    rows = []
    for cohort in ('general_ru', 'bleriot_b_noise'):
        item = next(i for i in plan['items'] if i['cohort'] == cohort)
        path = Path('/audio') / item['audio_path']
        if file_hash(path) != item['audio_sha256']:
            raise ValueError('Input changed')
        audio, rate = sf.read(path, dtype='float32')
        if rate != 16000 or audio.ndim != 1:
            raise ValueError('Unexpected prepared audio')
        speech = VadProvider().intervals(audio, VadConfig.model_validate(plan['vad']))
        regions = inference_regions(len(audio), speech, 'vad_gate')
        segments = []
        for begin, end in regions:
            segments.extend(provider.transcribe(audio[begin:end], begin, item['input_language'], 'cpu-smoke', lambda: None))
        rows.append({'id': item['id'], 'cohort': cohort, 'audio_sha256': item['audio_sha256'], 'regions': regions,
            'hypothesis': ' '.join(s.raw_asr_text.strip() for s in segments), 'segments': [s.model_dump() for s in segments]})
    result = {'status': 'PASS' if rows[0]['hypothesis'] and provider.model.model.device == 'cpu' else 'FAIL',
        'purpose': 'engineering_smoke_only_not_quality_evidence', 'actual_device': provider.model.model.device,
        'actual_compute_type': provider.model.model.compute_type, 'rows': rows, 'elapsed_sec': time.perf_counter() - started,
        'script_sha256': file_hash(Path(__file__)), 'model': config.model}
    atomic_json(Path('/reports/additional-sources-v1/cpu-smoke.json'), result)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
