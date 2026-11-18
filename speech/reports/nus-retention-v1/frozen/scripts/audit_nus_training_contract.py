"""Offline diagnosis of saved NUS training artifacts; never trains or selects a release."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

ROOT = Path('/study')
MODELS = Path('/models')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def checked_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Invalid artifact path')
    return path


def validate_inputs(items):
    allowed = {'id', 'audio_path', 'audio_sha256', 'duration_sec', 'input_language'}
    if len(items) != 275 or len({i['id'] for i in items}) != 275:
        raise ValueError('Expected all 275 distinct training inputs')
    for item in items:
        if set(item) != allowed or item['input_language'] != 'en':
            raise ValueError('Only answer-free English NUS inference inputs are allowed')
        if not item['id'].startswith('nus-clip'):
            raise ValueError('Only the existing NUS training population is allowed')


def validate():
    plan = read(ROOT / 'plan.json')
    if sha(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Frozen inputs changed')
    if sha(Path(__file__)) != plan['script_sha256']:
        raise ValueError('Frozen audit changed')
    items = read(ROOT / 'inputs.json')
    validate_inputs(items)
    return plan, items


def check_files(root, files):
    for name, expected in files.items():
        if sha(checked_path(root, name)) != expected:
            raise ValueError('Artifact checksum mismatch: ' + name)


def contract():
    import gc

    import librosa
    import numpy as np
    import soundfile as sf
    import torch
    from faster_whisper.feature_extractor import FeatureExtractor
    from peft import PeftModel
    from safetensors.torch import load_file
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    plan, items = validate()
    manifest = Path('/train/train.jsonl')
    if sha(manifest) != plan['train_sha256']:
        raise ValueError('Training manifest changed')
    training = read(ROOT / 'training.json')
    if sha(ROOT / 'training.json') != plan['training_report_sha256']:
        raise ValueError('Training report changed')
    samples = [json.loads(line) for line in manifest.read_text(encoding='utf-8').splitlines()]
    if len(samples) != 675 or any(s['split'] != 'train' for s in samples):
        raise ValueError('Only the original training partition is admitted')
    base = MODELS / 'whisper-small-transformers'
    adapted = MODELS / 'whisper-small-nus-v1'
    check_files(base, training['base_manifest']['files'])
    check_files(adapted, {k: v for k, v in training['files'].items()
                          if k.startswith(('adapter/', 'merged/'))})
    processor = WhisperProcessor.from_pretrained(base, local_files_only=True)
    fw_features = FeatureExtractor()
    rows = []
    for index, sample in enumerate(samples):
        path = checked_path(Path('/audio'), sample['audio_path'])
        if sha(path) != sample['audio_sha256']:
            raise ValueError('Training audio changed')
        trained, _ = librosa.load(path, sr=16000, mono=False)
        inferred, rate = sf.read(path, dtype='float32')
        if rate != 16000 or trained.ndim != 1 or inferred.ndim != 1 or sample['channel'] != 0:
            raise ValueError('Unexpected audio contract; audit does not silently downmix')
        if not np.array_equal(trained, inferred) or not np.isfinite(trained).all():
            raise ValueError('Training/inference waveforms differ')
        if abs(len(trained) / 16000 - sample['duration_sec']) > 1 / 16000:
            raise ValueError('Duration differs')
        processor.tokenizer.set_prefix_tokens(language=sample['language'], task='transcribe')
        labels = processor.tokenizer(sample['reference_text']).input_ids
        expected = processor.tokenizer.prefix_tokens
        if labels[:len(expected)] != expected or labels[-1] != processor.tokenizer.eos_token_id:
            raise ValueError('Malformed training language/task/end tokens')
        if len(labels) > 448 or len(trained) > 480000:
            raise ValueError('Silent truncation would occur')
        a = processor.feature_extractor(trained, sampling_rate=16000).input_features[0]
        b = fw_features(inferred, padding=480000)[:, :3000]
        maximum = float(np.max(np.abs(a - b)))
        if a.shape != (80, 3000) or not np.isfinite(a).all() or maximum > 1e-4:
            raise ValueError('Training/inference log-mel features differ')
        rows.append({'id': sample['sample_id'], 'language': sample['language'],
                     'prefix_tokens': expected, 'label_length': len(labels),
                     'samples': len(trained), 'mel_max_abs_difference': maximum})
        if (index + 1) % 100 == 0:
            print('Audio/token/feature checks:', index + 1, flush=True)
    save(Path('/output/audio-tokens.json'), rows)

    # Reconstruct exactly the saved FP32 merge, independently of CT2 conversion.
    model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
    model = PeftModel.from_pretrained(model, adapted / 'adapter', local_files_only=True)
    # Original training merged on CUDA. CPU GEMM differs in the last FP32 bits.
    # Preserve exact equality by repeating the recorded device/precision.
    torch.backends.cuda.matmul.allow_tf32 = False
    model = model.cuda()
    merged = model.merge_and_unload()
    saved = load_file(adapted / 'merged/model.safetensors')
    state = merged.state_dict()
    mismatches = [key for key, tensor in saved.items()
                  if key not in state or not torch.equal(tensor, state[key].cpu())]
    if mismatches:
        raise ValueError('Saved merged tensors differ: ' + repr(mismatches[:5]))
    save(Path('/output/merge.json'), {'status': 'PASS', 'saved_tensors_checked': len(saved),
                                    'mismatches': mismatches, 'exact_FP32_equality': True})
    del model, merged, saved, state
    gc.collect()

    # A deterministic 32-case training diagnostic, never validation or test.
    chosen = sorted(items, key=lambda x: (x['audio_sha256'], x['id']))[:32]
    by_id = {s['sample_id']: s for s in samples}
    features, labels = [], []
    for item in chosen:
        sample = by_id[item['id']]
        waveform, _ = sf.read(checked_path(Path('/audio'), item['audio_path']), dtype='float32')
        features.append(torch.tensor(processor.feature_extractor(
            waveform, sampling_rate=16000).input_features, device='cuda', dtype=torch.float16))
        processor.tokenizer.set_prefix_tokens(language='en', task='transcribe')
        labels.append(torch.tensor([processor.tokenizer(sample['reference_text']).input_ids[1:]],
                                   device='cuda'))
    teacher = []
    for system, location in [('parent', base), ('nus', adapted / 'merged')]:
        model = WhisperForConditionalGeneration.from_pretrained(
            location, local_files_only=True, torch_dtype=torch.float16).cuda().eval()
        with torch.inference_mode():
            for index, item in enumerate(chosen):
                losses = {}
                for kind, value in [('matching_audio', features[index]),
                                    ('different_audio', features[(index + 1) % len(chosen)])]:
                    output = model(input_features=value, labels=labels[index], use_cache=False)
                    losses[kind] = float(output.loss)
                    if not np.isfinite(losses[kind]):
                        raise ValueError('Nonfinite teacher-forced loss')
                teacher.append({'id': item['id'], 'system': system, **losses})
        del model
        gc.collect()
        torch.cuda.empty_cache()
        print('Teacher forcing complete:', system, flush=True)
    save(Path('/output/teacher-forcing.json'), teacher)
    save(Path('/output/contract.json'), {'status': 'PASS', 'audio_token_pairs': len(rows),
         'waveforms_exactly_equal': True, 'maximum_mel_difference': max(r['mel_max_abs_difference'] for r in rows),
         'teacher_forcing_cases': 32, 'teacher_forcing_forward_passes': 128,
         'human_audio_verification': False, 'quality_evidence': False, 'new_training_steps': 0,
         'plan_sha256': sha(ROOT / 'plan.json')})


def infer(system):
    import time

    import numpy as np
    import soundfile as sf

    from north55_speech.asr import AsrProvider
    from north55_speech.schemas import PipelineConfig

    plan, items = validate()
    spec = plan['models'][system]
    check_files(MODELS / spec['name'], spec['manifest']['files'])
    provider = AsrProvider(PipelineConfig.model_validate(plan['configs'][system]))
    if provider.model.model.compute_type != 'float16' or provider.model.model.device != 'cuda':
        raise ValueError('Require CUDA float16 like historical fit inference')
    records = []
    for index, item in enumerate(items):
        options = provider.options(item['input_language']) | {'without_timestamps': True}
        record = dict(item, system=system, hypothesis='', runtime_failure=None,
                      effective_options=options, plan_sha256=sha(ROOT / 'plan.json'))
        started = time.perf_counter()
        try:
            path = checked_path(Path('/audio'), item['audio_path'])
            if sha(path) != item['audio_sha256']:
                raise ValueError('Audio checksum differs')
            waveform, rate = sf.read(path, dtype='float32')
            if rate != 16000 or waveform.ndim != 1 or not np.isfinite(waveform).all():
                raise ValueError('Audio contract differs')
            record['effective_waveform_sha256'] = hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest()
            generator, info = provider.model.transcribe(waveform, **options)
            segments = list(generator)
            record['hypothesis'] = ' '.join(s.text.strip() for s in segments).strip()
            record['segments'] = [asdict(s) for s in segments]
            record['detected_language'] = info.language
        except Exception as error:
            record['runtime_failure'] = type(error).__name__ + ': ' + str(error)
        record['seconds'] = time.perf_counter() - started
        save(Path('/output/predictions') / (item['id'] + '.json'), record)
        records.append(record)
        if (index + 1) % 50 == 0:
            print(system, 'inference:', index + 1, flush=True)
    save(Path('/output/execution.json'), {'system': system, 'records': len(records),
         'runtime_failures': sum(r['runtime_failure'] is not None for r in records),
         'actual_precision': provider.model.model.compute_type, 'actual_device': provider.model.model.device,
         'prediction_sha256': {r['id'] + '.json': sha(Path('/output/predictions') / (r['id'] + '.json')) for r in records},
         'plan_sha256': sha(ROOT / 'plan.json'), 'training_partition_only': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['contract', 'parent', 'nus'])
    args = parser.parse_args()
    contract() if args.stage == 'contract' else infer(args.stage)
