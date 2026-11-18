"""Fixed candidate inference and delay-safe native DeepFilterNet processing."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def deep_filter(x: np.ndarray, binary: Path) -> tuple[np.ndarray, dict]:
    """Start a fresh model per clip and flush its delayed tail before trimming."""
    if x.ndim != 1 or not np.isfinite(x).all() or len(x) < 400:
        raise ValueError('Expected finite mono float audio of at least 25 ms')
    high = resample_poly(x, 3, 1).astype('float32')
    # Full hops plus one second of flush padding: larger than the model delay.
    padded_size = ((len(high)+479)//480)*480+48000
    padded = np.pad(high, (0, padded_size-len(high)))
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, out = root/'input.wav', root/'out'
        sf.write(source, padded, 48000, subtype='FLOAT')
        command = [str(binary), '-v', '--compensate-delay', '--atten-lim-db', '100',
            '--min-db-thresh=-15', '--max-db-erb-thresh', '35',
            '--max-db-df-thresh', '35', '--output-dir', str(out), str(source)]
        run = subprocess.run(command, capture_output=True, text=True,
            timeout=180, env={**os.environ, 'RUST_LOG': 'debug'})
        if run.returncode:
            raise RuntimeError(f'DeepFilterNet failed ({run.returncode}): {run.stderr}')
        files = list(out.glob('*.wav'))
        assert len(files) == 1, files
        y, rate = sf.read(files[0], dtype='float32')
        info = sf.info(files[0])
        assert rate == 48000 and y.ndim == 1 and len(y) >= len(high)
        # The official native binary writes PCM16 even for a FLOAT input.
        assert info.subtype == 'PCM_16', info
        result = resample_poly(y[:len(high)], 1, 3).astype('float32')
        assert len(result) == len(x) and np.isfinite(result).all()
        return result, {'input_samples_16k': len(x), 'padded_samples_48k': padded_size,
            'native_output_samples_48k': len(y), 'removed_delay_samples_48k': padded_size-len(y),
            'output_samples_16k': len(result), 'subtype': info.subtype,
            'native_clipped_samples': int(np.sum((y >= 32767/32768) | (y <= -1))),
            'stdout': run.stdout, 'stderr': run.stderr,
            'fresh_process_per_clip': True, 'attenuation_limit_db': 100}


def speech_present(x: np.ndarray) -> bool:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    return bool(get_speech_timestamps(x, VadOptions(threshold=.5, min_speech_duration_ms=100,
        min_silence_duration_ms=400, speech_pad_ms=200, max_speech_duration_s=30),
        sampling_rate=16000))


def load_canary(snapshot: str):
    import torch
    from nemo.collections.speechlm2.models import SALM
    from safetensors.torch import load_model
    torch.set_num_threads(4)
    torch.manual_seed(55)
    folder = Path(snapshot)
    cfg = json.loads((folder/'config.json').read_bytes())
    assert cfg['pretrained_weights'] is False
    # Resolve the tokenizer/config to a pinned local snapshot; no mutable main alias.
    cfg['pretrained_llm'] = str(folder.parents[2]/'models--Qwen--Qwen3-1.7B'/'snapshots'/
        '70d244cc86ccca08cf5af4e1e306ecf908b1ad5e')
    model = SALM(cfg)
    missing, unexpected = load_model(model, str(folder/'model.safetensors'), strict=True)
    assert not missing and not unexpected
    model = model.to(device='cuda:0', dtype=torch.bfloat16).eval()
    # STFT/mel extraction remains float32; neural layers use checkpoint precision.
    model.perception.preprocessor.float()
    return model


def transcribe_canary(model, x: np.ndarray) -> dict:
    import torch
    from transformers import GenerationConfig
    generation = GenerationConfig(do_sample=False, num_beams=1, max_new_tokens=256,
        bos_token_id=model.text_bos_id, eos_token_id=model.text_eos_id,
        pad_token_id=model.text_pad_id)
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
        ids = model.generate(prompts=[[{'role': 'user',
            'content': f'Transcribe the following: {model.audio_locator_tag}'}]],
            audios=torch.from_numpy(x.copy())[None].to('cuda:0'),
            audio_lens=torch.tensor([len(x)], device='cuda:0'), generation_config=generation)[0].cpu()
    values = ids.tolist()
    eos = model.text_eos_id
    eos_ids = eos if isinstance(eos, list) else [eos]
    return {'hypothesis': model.tokenizer.ids_to_text(ids), 'token_ids': values,
        'generated_tokens': len(values), 'eos_reached': any(i in eos_ids for i in values),
        'token_limit_reached': len(values) >= 256 and not any(i in eos_ids for i in values)}


def compose_candidates(item: dict, prior: dict, vad: bool | None,
                       canary: str | None, filtered: str | None) -> dict:
    """Selection uses language, original audio VAD and the frozen v9 noise route."""
    old = prior['hypothesis']
    if item['language'] == 'ru':
        return {k: old for k in ('v9', 'guarded_v9', 'canary', 'canary_guarded',
            'canary_router', 'dfn_parakeet')}
    assert canary is not None and vad is not None
    para_empty = not item['parakeet'].strip()
    suppress = para_empty and not vad
    guarded = item['whisper'] if para_empty and vad else old
    severe = prior['selected'] == 'parakeet' and not para_empty
    if severe:
        assert filtered is not None
    candidate = '' if suppress else canary
    return {'v9': old, 'guarded_v9': guarded, 'canary': canary,
        'canary_guarded': candidate, 'canary_router': old if severe else candidate,
        'dfn_parakeet': filtered if severe else guarded}
