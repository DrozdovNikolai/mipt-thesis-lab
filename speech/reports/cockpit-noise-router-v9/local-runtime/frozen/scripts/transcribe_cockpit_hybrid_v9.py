"""Run the experimental English cockpit router on local clips, without cached ASR."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import joblib
import numpy as np
import soundfile as sf

from north55_speech.acoustic_noise_router import audio_features, choose_by_noise
from north55_speech.asr import AsrProvider
from north55_speech.core import file_hash, settings
from north55_speech.schemas import PipelineConfig


def read(path):
    return json.loads(Path(path).read_bytes())


def plain(value):
    from enum import Enum
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, 'detach'):
        return value.detach().cpu().tolist()
    return value


def load_wave(path):
    try:
        x, rate = sf.read(path, dtype='float32')
        if x.ndim == 2:
            x = x.mean(axis=1)
        if rate != 16000:
            from math import gcd

            from scipy.signal import resample_poly
            divisor = gcd(rate, 16000)
            x = resample_poly(x, 16000//divisor, rate//divisor).astype('float32')
    except sf.LibsndfileError:
        from faster_whisper.audio import decode_audio
        x = decode_audio(str(path), sampling_rate=16000)
    if x.ndim != 1 or not np.isfinite(x).all() or not 400 <= len(x) <= 480000:
        raise ValueError('Provide a finite audio clip from 0.025 to 30 seconds; no automatic trimming')
    return x


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', nargs='+', type=Path)
    parser.add_argument('--language', choices=['en', 'ru', 'auto'], default='en',
        help='auto uses the English router and lets Whisper detect language; ru bypasses Parakeet')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output filename')
    config = read('/profile/runtime.json')
    for path, digest in config['implementation_sha256'].items():
        assert file_hash(Path('/app')/path) == digest
    assert file_hash(Path('/trained/training.json')) == config['training_sha256']
    assert file_hash(Path('/trained/router.joblib')) == config['router_sha256']
    router = joblib.load('/trained/router.joblib')
    threshold = read('/trained/training.json')['threshold']
    settings.model_root = Path('/whisper-models')
    whisper = parakeet = None
    started = time.perf_counter()
    if args.language != 'ru':
        import torch
        from nemo.collections.asr.models import ASRModel
        torch.set_num_threads(4)
        path = Path('/parakeet/parakeet-tdt-0.6b-v2.nemo')
        assert file_hash(path) == config['parakeet_sha256']
        parakeet = ASRModel.restore_from(str(path), map_location=torch.device('cuda:0'))
        parakeet.eval()
        cfg = parakeet.cfg.decoding
        cfg.strategy = 'greedy_batch'
        parakeet.change_decoding_strategy(cfg)
        assert str(next(parakeet.parameters()).dtype) == 'torch.float32'
    outputs, calls = [], {'whisper': 0, 'parakeet': 0}
    for input_path in args.audio:
        x = load_wave(input_path)
        probability = parakeet_text = whisper_text = None
        para_timestamps = whisper_segments = None
        if parakeet is not None:
            with tempfile.TemporaryDirectory() as temporary:
                wav = Path(temporary)/'input.wav'
                sf.write(wav, x, 16000, subtype='FLOAT')
                with torch.inference_mode():
                    response = parakeet.transcribe([str(wav)], batch_size=1,
                        return_hypotheses=True, timestamps=True, verbose=False)
            if isinstance(response, tuple):
                response = response[0]
            assert len(response) == 1
            parakeet_text = response[0].text
            para_timestamps = plain(response[0].timestamp)
            calls['parakeet'] += 1
            if parakeet_text.strip():
                probability = float(router.predict_proba(audio_features(x)[None])[0, 1])
        needs_whisper = args.language == 'ru' or (bool(parakeet_text.strip()) and probability < threshold)
        if needs_whisper:
            if whisper is None:
                assert file_hash(settings.model_root/config['whisper_config']['model']/'manifest.json') == config['whisper_manifest_sha256']
                whisper = AsrProvider(PipelineConfig.model_validate(config['whisper_config']))
                assert whisper.model.model.device == 'cuda' and whisper.model.model.compute_type == 'float16'
            segments, _ = whisper.model.transcribe(x, **whisper.options(args.language))
            segments = list(segments)
            whisper_text = ' '.join(s.text.strip() for s in segments).strip()
            whisper_segments = [asdict(s) for s in segments]
            calls['whisper'] += 1
        route = choose_by_noise(whisper_text or '', parakeet_text,
            'ru' if args.language == 'ru' else 'en', probability, threshold)
        outputs.append({'input_path': str(input_path), 'input_sha256': file_hash(input_path),
            'pcm_sha256': hashlib.sha256(x.astype('<f4').tobytes()).hexdigest(), 'duration_sec': len(x)/16000,
            'language_profile': args.language, **route, 'severe_probability': probability, 'threshold': threshold,
            'whisper': whisper_text, 'parakeet': parakeet_text, 'whisper_segments': whisper_segments,
            'parakeet_timestamps': para_timestamps})
    result = {'runtime_sha256': file_hash(Path('/profile/runtime.json')), 'actual_ASR_calls': calls,
        'device': 'cuda', 'seconds': time.perf_counter()-started, 'records': outputs,
        'experimental': True, 'serving_replaced': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'output': str(args.output), 'ASR_calls': calls,
        'results': [{'input': r['input_path'], 'selected': r['selected'], 'text': r['hypothesis']} for r in outputs]},
        ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
