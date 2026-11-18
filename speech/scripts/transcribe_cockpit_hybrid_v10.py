"""Fresh local inference with the tested empty-result guard and optional denoising."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import joblib
import soundfile as sf
from transcribe_cockpit_hybrid_v9 import load_wave, plain, read

from north55_speech.acoustic_noise_router import audio_features
from north55_speech.asr import AsrProvider
from north55_speech.cockpit_candidates_v10 import deep_filter, speech_present
from north55_speech.core import file_hash, settings
from north55_speech.schemas import PipelineConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', nargs='+', type=Path)
    parser.add_argument('--language', choices=['en', 'ru', 'auto'], default='en')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output filename')
    config = read('/profile/runtime.json')
    for path, digest in config['implementation_sha256'].items():
        assert file_hash(Path('/app')/path) == digest
    assert config['candidate'] in ('guarded_v9', 'dfn_parakeet')
    assert file_hash(Path('/trained/training.json')) == config['training_sha256']
    assert file_hash(Path('/trained/router.joblib')) == config['router_sha256']
    if config['candidate'] == 'dfn_parakeet':
        assert file_hash(Path('/models/deep-filter')) == config['deep_filter_binary_sha256']
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
        parakeet = ASRModel.restore_from(str(path), map_location=torch.device('cuda:0')).eval()
        cfg = parakeet.cfg.decoding
        cfg.strategy = 'greedy_batch'
        parakeet.change_decoding_strategy(cfg)
        assert str(next(parakeet.parameters()).dtype) == 'torch.float32'
    outputs, calls = [], {'whisper': 0, 'parakeet': 0, 'dfn_parakeet': 0}

    def recognize(wave):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'input.wav'
            sf.write(path, wave, 16000, subtype='FLOAT')
            with torch.inference_mode():
                response = parakeet.transcribe([str(path)], batch_size=1,
                    return_hypotheses=True, timestamps=True, verbose=False)
        if isinstance(response, tuple):
            response = response[0]
        assert len(response) == 1
        return response[0].text, plain(response[0].timestamp)

    for input_path in args.audio:
        x = load_wave(input_path)
        probability = para_text = whisper_text = filtered_text = vad = None
        para_timestamps = whisper_segments = filtered_timestamps = dfn = None
        if parakeet is not None:
            para_text, para_timestamps = recognize(x)
            calls['parakeet'] += 1
            if para_text.strip():
                probability = float(router.predict_proba(audio_features(x)[None])[0, 1])
            else:
                vad = speech_present(x)
        need_whisper = args.language == 'ru' or (
            bool(para_text.strip()) and probability < threshold) or vad is True
        if need_whisper:
            if whisper is None:
                manifest = settings.model_root/config['whisper_config']['model']/'manifest.json'
                assert file_hash(manifest) == config['whisper_manifest_sha256']
                whisper = AsrProvider(PipelineConfig.model_validate(config['whisper_config']))
                assert whisper.model.model.device == 'cuda' and whisper.model.model.compute_type == 'float16'
            segments, _ = whisper.model.transcribe(x, **whisper.options(args.language))
            segments = list(segments)
            whisper_text = ' '.join(s.text.strip() for s in segments).strip()
            whisper_segments = [asdict(s) for s in segments]
            calls['whisper'] += 1
            selected, text = 'whisper', whisper_text
            reason = 'speech_after_empty_decoder' if vad else 'keep_whisper'
        elif para_text.strip():
            selected, text, reason = 'parakeet', para_text, 'severe_noise'
            if config['candidate'] == 'dfn_parakeet':
                y, dfn = deep_filter(x, Path('/models/deep-filter'))
                dfn['pcm_sha256'] = hashlib.sha256(y.astype('<f4').tobytes()).hexdigest()
                filtered_text, filtered_timestamps = recognize(y)
                calls['dfn_parakeet'] += 1
                selected, text, reason = 'dfn_parakeet', filtered_text, 'severe_noise_denoised'
        else:
            selected, text, reason = 'parakeet', '', 'empty_decoder_and_no_speech'
        outputs.append({'input_path': str(input_path), 'input_sha256': file_hash(input_path),
            'pcm_sha256': hashlib.sha256(x.astype('<f4').tobytes()).hexdigest(), 'duration_sec': len(x)/16000,
            'language_profile': args.language, 'selected': selected, 'hypothesis': text, 'reason': reason,
            'severe_probability': probability, 'threshold': threshold, 'vad_on_empty': vad,
            'whisper': whisper_text, 'parakeet': para_text, 'dfn_parakeet': filtered_text,
            'whisper_segments': whisper_segments, 'parakeet_timestamps': para_timestamps,
            'dfn_parakeet_timestamps': filtered_timestamps, 'denoising': dfn})
    result = {'runtime_sha256': file_hash(Path('/profile/runtime.json')), 'candidate': config['candidate'],
        'actual_ASR_calls': calls, 'device': 'cuda', 'seconds': time.perf_counter()-started,
        'records': outputs, 'experimental': True, 'serving_replaced': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'output': str(args.output), 'calls': calls,
        'results': [{'input': r['input_path'], 'text': r['hypothesis']} for r in outputs]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
