"""Offline training and paired evaluation of the recovered publisher population."""

import argparse
import gc
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from north55_speech.core import file_hash, settings
from scripts import nus_convergence as worker

ROOT = Path('/study')
EXP = Path('/experiment')
read = worker.read
save_new = worker.save_new


def validate():
    plan = worker.validate()
    expected = {'updates': 240, 'accumulation': 4, 'learning_rate': 2e-5,
        'kl_weight': 1.0, 'temperature': 2.0, 'rank': 8, 'alpha': 16, 'dropout': .05,
        'seed': 55, 'precision': 'bfloat16', 'encoder_frozen': True}
    if plan['training'] != expected or len(set(plan['selected_ids'])) != 221:
        raise ValueError('Training protocol changed')
    if any(plan.get(k) is not False for k in ('quality_evidence', 'selection_allowed', 'test_accessed', 'release_promoted')):
        raise ValueError('Exploratory training cannot authorize release')
    return plan


def convert():
    import torch
    from ctranslate2.converters import TransformersConverter
    from peft import PeftModel
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, WhisperTokenizerFast

    from north55_speech.decoder_adaptation import tensor_hashes

    plan = validate()
    training = read(ROOT / 'training.json')
    if training['plan_sha256'] != file_hash(ROOT / 'plan.json'):
        raise ValueError('Training identity differs')
    base = Path('/models/whisper-small-transformers')
    worker.verify_files(base, plan['base_manifest']['files'])
    checkpoint = EXP / 'training/checkpoint-240'
    worker.verify_files(checkpoint, training['checkpoints']['240'])
    merged_dir, output = EXP / 'merged', EXP / 'models' / plan['model_name']
    if merged_dir.exists() or output.exists():
        raise ValueError('Preserve existing conversion')
    torch.set_num_threads(4)
    model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
    adapted = PeftModel.from_pretrained(model, checkpoint, local_files_only=True).cuda()
    merged = adapted.merge_and_unload()
    if tensor_hashes(merged.model.encoder) != training['encoder_before']:
        raise ValueError('Merged encoder changed')
    merged.save_pretrained(merged_dir, safe_serialization=True)
    WhisperProcessor.from_pretrained(base, local_files_only=True).save_pretrained(merged_dir)
    WhisperTokenizerFast.from_pretrained(base, local_files_only=True).save_pretrained(merged_dir)
    del model, adapted, merged
    gc.collect()
    torch.cuda.empty_cache()
    TransformersConverter(str(merged_dir), copy_files=['tokenizer.json', 'preprocessor_config.json']).convert(
        str(output), quantization='float16')
    manifest = {'model': output.name, 'repo': 'local_publisher_recovery_v3_decoder_lora',
        'revision': file_hash(checkpoint / 'adapter_model.safetensors'), 'actual_updates': 240,
        'train_sha256': plan['train_sha256'], 'reference_policy': plan['admission']['reference_policy'],
        'base_manifest': plan['base_manifest'], 'encoder_unchanged': True,
        'quality_evidence': False, 'selection_allowed': False, 'release_allowed': False,
        'license': 'inherited_base_and_existing_project_noncommercial_research_source_restrictions',
        'files': {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}
    save_new(output / 'manifest.json', manifest)
    save_new(Path('/output/conversion.json'), {'plan_sha256': file_hash(ROOT / 'plan.json'), 'model': manifest})
    print('Converted fixed final checkpoint:', output, flush=True)


def infer(system):
    import numpy as np

    from north55_speech.asr import AsrProvider
    from north55_speech.schemas import PipelineConfig
    from scripts.decoding_diagnostics import load_audio

    plan = validate()
    cpu = system == 'cpu'
    if system == 'baseline':
        settings.model_root = Path('/models')
        manifest = plan['baseline_model']['manifest']
        name = plan['baseline_model']['name']
        if file_hash(settings.model_root / name / 'manifest.json') != plan['baseline_model']['manifest_sha256']:
            raise ValueError('Baseline manifest changed')
    else:
        conversion = read(ROOT / 'conversion.json')
        if conversion['plan_sha256'] != file_hash(ROOT / 'plan.json'):
            raise ValueError('Conversion identity differs')
        manifest = conversion['model']
        name = manifest['model']
        settings.model_root = EXP / 'models'
    if read(settings.model_root / name / 'manifest.json') != manifest:
        raise ValueError('Model manifest changed')
    config = PipelineConfig.model_validate(plan['config'] | {'model': name})
    items = read(ROOT / 'inputs.json')
    if cpu:
        config = config.model_copy(update={'device': 'cpu', 'compute_type': 'int8'})
        items = [next(i for i in items if i['cohort'] == c) for c in ('partial_human_dev', 'general_ru')]
    provider = AsrProvider(config)
    device, precision = provider.model.model.device, provider.model.model.compute_type
    if not cpu and (device, precision) != ('cuda', 'float16'):
        raise ValueError('Require actual CUDA float16')
    hashes, failed, resumed = {}, [], 0
    for index, item in enumerate(items):
        path = Path('/output/predictions') / (item['id'] + '.json')
        identity = dict(item, system=system, plan_sha256=file_hash(ROOT / 'plan.json'),
            config=config.model_dump(), effective_options=provider.options(item['input_language']),
            model_manifest_sha256=file_hash(settings.model_root / name / 'manifest.json'))
        if path.exists():
            record = read(path)
            if any(record.get(k) != v for k, v in identity.items()) or record['runtime_failure'] is not None:
                raise ValueError('Existing prediction identity differs or failed')
            resumed += 1
        else:
            started = time.perf_counter()
            record = dict(identity, hypothesis='', runtime_failure=None, actual_device=device, actual_precision=precision)
            try:
                waveform = load_audio(item)
                if not np.isfinite(waveform).all():
                    raise ValueError('Nonfinite audio')
                record['effective_waveform_sha256'] = hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest()
                segments, info = provider.model.transcribe(waveform, **identity['effective_options'])
                segments = list(segments)
                record.update(hypothesis=' '.join(s.text.strip() for s in segments).strip(),
                    language=info.language, segments=[asdict(s) for s in segments])
            except Exception as error:
                record['runtime_failure'] = type(error).__name__ + ': ' + str(error)
            record['seconds'] = time.perf_counter() - started
            save_new(path, record)
        if record['runtime_failure'] is not None:
            failed.append(item['id'])
        hashes[path.name] = file_hash(path)
        if (index + 1) % 25 == 0:
            print(system, index + 1, '/', len(items), flush=True)
    execution = {'plan_sha256': file_hash(ROOT / 'plan.json'), 'records': len(items),
        'runtime_failures': failed, 'prediction_sha256': hashes, 'actual_device': device,
        'actual_precision': precision, 'new_ASR_calls': len(items)-resumed, 'resumed': resumed}
    out = Path('/output/execution.json')
    save_new(out if not out.exists() else Path('/output') / f'replay-{time.time_ns()}.json', execution)
    print(json.dumps({k: v for k, v in execution.items() if k != 'prediction_sha256'}), flush=True)


def compare_records(item, reference, baseline, candidate):
    from north55_speech.metrics import edit_counts

    for record in (baseline, candidate):
        if any(record.get(k) != v for k, v in item.items()):
            raise ValueError('Prediction population changed')
        if record['runtime_failure'] is not None:
            raise ValueError('Runtime failure cannot be scored as successful inference')
    for key in ('effective_options', 'effective_waveform_sha256'):
        if not baseline.get(key) or baseline[key] != candidate.get(key):
            raise ValueError('Comparison options or waveforms differ')
    if reference is None:
        raise ValueError('Reference is missing')
    return {name: edit_counts(reference, record['hypothesis']) for name, record in
            [('baseline', baseline), ('candidate', candidate)]}


def score():
    from north55_speech.metrics import corpus_counts, paired_cluster_bootstrap

    plan = validate()
    if file_hash(ROOT / 'scoring/references.json') != plan['references_sha256']:
        raise ValueError('References changed')
    refs, items = read(ROOT / 'scoring/references.json'), read(ROOT / 'inputs.json')
    executions = {s: read(ROOT / ('io-' + s) / 'execution.json') for s in ('baseline', 'candidate', 'cpu')}
    if any(e['plan_sha256'] != file_hash(ROOT / 'plan.json') or e['runtime_failures'] for e in executions.values()):
        raise ValueError('Incomplete execution')
    counts, changes = {}, []
    for item in items:
        records = {}
        for system in ('baseline', 'candidate'):
            path = ROOT / ('io-' + system) / 'predictions' / (item['id'] + '.json')
            if file_hash(path) != executions[system]['prediction_sha256'][path.name]:
                raise ValueError('Prediction changed')
            record = read(path)
            if record['plan_sha256'] != file_hash(ROOT / 'plan.json') or record['system'] != system:
                raise ValueError('Prediction run changed')
            records[system] = record
        counts[item['id']] = compare_records(item, refs[item['reference_id']], **records)
        if item['cohort'] in ('partial_human_dev', 'publisher_weak_dev'):
            changes.append({'id': item['id'], 'cohort': item['cohort'], 'reference': refs[item['reference_id']],
                **{s: r['hypothesis'] for s, r in records.items()}, 'counts': counts[item['id']]})
    cohorts: dict[str, Any] = {}
    for cohort in sorted({i['cohort'] for i in items}):
        group = [i for i in items if i['cohort'] == cohort]
        scores = {s: corpus_counts([counts[i['id']][s] for i in group]) for s in ('baseline', 'candidate')}
        a, b = (scores[s]['wer_lexical_corpus'] for s in ('baseline', 'candidate'))
        row = {'samples': len(group), 'groups': len({i['group_id'] for i in group}), 'scores': scores,
            'wer_delta': b-a if a is not None and b is not None else None,
            'relative_reduction': (a-b)/a if a else None}
        if cohort in ('noise_only', 'bleriot_b_noise'):
            minutes = sum(i['duration_sec'] for i in group)/60
            row['inserted_words_per_minute'] = {s: scores[s]['I']/minutes for s in scores}
        elif cohort != 'training_fit':
            row['bootstrap'] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                **counts[i['id']]} for i in group], resamples=2000, seed=55, confidence=.95)
        cohorts[cohort] = row
    human = cohorts['partial_human_dev']
    checks = {'human_point': human['relative_reduction'] >= .1,
        'human_CI': human['bootstrap']['upper'] < 0,
        'general_EN': cohorts['general_clean']['wer_delta'] <= .01,
        'general_RU': cohorts['general_ru']['wer_delta'] <= .01,
        'noise': all(cohorts[c]['inserted_words_per_minute']['candidate'] <= cohorts[c]['inserted_words_per_minute']['baseline']
                     for c in ('noise_only', 'bleriot_b_noise')), 'runtime': True}
    result = {'plan_sha256': file_hash(ROOT / 'plan.json'), 'cohorts': cohorts, 'checks': checks,
        'diagnostic_status': 'FAIL' if not all(checks.values()) else 'NEEDS_MORE_DATA',
        'GPU_ASR': sum(executions[s]['new_ASR_calls'] for s in ('baseline', 'candidate')),
        'CPU_ASR': executions['cpu']['new_ASR_calls'], 'quality_evidence': False,
        'selection_allowed': False, 'test_accessed': False, 'release_promoted': False}
    save_new(ROOT / 'comparison.json', result)
    save_new(ROOT / 'scored-counts.json', counts)
    save_new(ROOT / 'scoring/examples.json', changes)
    print(json.dumps({'WER': {c: {s: v['wer_lexical_corpus'] for s, v in row['scores'].items()} for c, row in cohorts.items()},
                      'checks': checks}, indent=2), flush=True)


# The training loop below reuses the verified BF16 decoder/teacher recipe from
# nus_retention, with this experiment's own data admission and fixed update count.


def train():
    import librosa
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, set_seed
    from transformers.modeling_outputs import BaseModelOutput

    from north55_speech.datasets import load_manifest
    from north55_speech.decoder_adaptation import (
        decoder_targets,
        tensor_hashes,
        verify_trainable_decoder,
    )
    from north55_speech.publisher_pairs import validate_phrase_references
    from north55_speech.retention import (
        base_teacher_logits,
        masked_teacher_kl,
    )

    plan = validate()
    phase = plan['training']
    manifest = Path('/train/train.jsonl')
    if worker.file_hash(manifest) != plan['train_sha256']:
        raise ValueError('Training manifest changed')
    samples = load_manifest(manifest)
    if len(samples) != 221 or [s.sample_id for s in samples] != plan['selected_ids'] or any(s.split != 'train' for s in samples):
        raise ValueError('Only the complete recovered 221 train pairs are admitted')
    validate_phrase_references(samples, [], plan['admission'])
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1 or not torch.cuda.is_bf16_supported():
        raise ValueError('Require one BF16 capable CUDA GPU')
    base = Path('/models/whisper-small-transformers')
    worker.verify_files(base, plan['base_manifest']['files'])
    destination = worker.EXP / 'training'
    if destination.exists():
        raise ValueError('Preserve previous training artifacts; never silently restart an arm')
    destination.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    set_seed(55)
    processor: Any = WhisperProcessor.from_pretrained(base, local_files_only=True)
    original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True).cuda().eval()
    encoder_before = tensor_hashes(original.model.encoder)
    frozen_base_before = tensor_hashes(original)
    cached, contracts = [], []
    started = time.perf_counter()
    # Encoder is immutable with dropout disabled; cache only audio-derived states.
    for index, sample in enumerate(samples):
        path = (Path('/audio') / sample.audio_path).resolve()
        if not path.is_relative_to(Path('/audio')) or worker.file_hash(path) != sample.audio_sha256:
            raise ValueError('Training waveform changed')
        waveform, _ = librosa.load(path, sr=16000, mono=False)
        if waveform.ndim == 2:
            waveform = waveform[sample.channel]
        elif sample.channel != 0:
            raise ValueError('Invalid mono channel')
        if not 0 < len(waveform) <= 480000:
            raise ValueError('Empty/truncated waveform is forbidden')
        processor.tokenizer.set_prefix_tokens(language=sample.language, task='transcribe')
        tokens = processor.tokenizer(sample.reference_text).input_ids
        if not sample.reference_text or len(tokens) > 448 or tokens[0] != original.config.decoder_start_token_id:
            raise ValueError('Empty/truncated/misaligned target')
        features = processor.feature_extractor(waveform, sampling_rate=16000, return_tensors='pt').input_features.cuda()
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
            states = original.model.encoder(features).last_hidden_state.cpu()
        labels = torch.tensor([tokens[1:]], dtype=torch.long)
        cached.append((states, labels))
        contracts.append({'id': sample.sample_id, 'language': sample.language, 'prefix': tokens[:4],
            'tokens': len(tokens), 'samples': len(waveform),
            'waveform_sha256': hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest(),
            'encoder_state_sha256': hashlib.sha256(states.view(torch.uint8).numpy().tobytes()).hexdigest()})
        if (index + 1) % 100 == 0:
            print('Cached train audio', index + 1, '/221', flush=True)
    cache_seconds = time.perf_counter() - started
    del original, features, states
    gc.collect()
    torch.cuda.empty_cache()
    # The schedule is generated once, independent of labels, outputs and arm.
    generator = torch.Generator().manual_seed(55)
    schedule: list[int] = []
    while len(schedule) < phase['updates'] * phase['accumulation']:
        schedule.extend(torch.randperm(len(samples), generator=generator).tolist())
    schedule = schedule[:phase['updates'] * phase['accumulation']]
    schedule_ids = [samples[i].sample_id for i in schedule]
    schedule_hash = hashlib.sha256('\n'.join(schedule_ids).encode()).hexdigest()
    checkpoints, arms = {}, {}
    for arm, weight in [('240', phase['kl_weight'])]:
        set_seed(55)
        original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        original.config.use_cache = False
        model: Any = get_peft_model(original, LoraConfig(r=8, lora_alpha=16,
            target_modules=decoder_targets(original), lora_dropout=.05, bias='none')).cuda()
        trainable = verify_trainable_decoder(model)
        initial_adapter = {n: p.detach().cpu().clone() for n, p in model.named_parameters() if p.requires_grad}
        initial_hash = hashlib.sha256(b''.join(p.numpy().tobytes() for p in initial_adapter.values())).hexdigest()
        params = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(params, lr=phase['learning_rate'], weight_decay=0., fused=True)
        optimizer.zero_grad(set_to_none=True)
        seen: Counter[str]
        seen, logs = Counter(), []
        ce_sum = kl_sum = 0.
        started = time.perf_counter()
        model.train()
        probe_states, probe_labels = cached[0]
        probe = {'encoder_outputs': BaseModelOutput(last_hidden_state=probe_states.cuda()), 'labels': probe_labels.cuda()}
        with torch.autocast('cuda', dtype=torch.bfloat16):
            teacher_before = base_teacher_logits(model, **probe)
        teacher_hash_before = hashlib.sha256(teacher_before.cpu().view(torch.uint8).numpy().tobytes()).hexdigest()
        del teacher_before
        for update in range(1, phase['updates'] + 1):
            for index in schedule[(update - 1)*4:update*4]:
                states, labels = cached[index]
                batch = {'encoder_outputs': BaseModelOutput(last_hidden_state=states.cuda()), 'labels': labels.cuda()}
                with torch.autocast('cuda', dtype=torch.bfloat16):
                    teacher = base_teacher_logits(model, **batch) if weight else None
                    output = model(**batch)
                    kl = masked_teacher_kl(output.logits, teacher, batch['labels'], phase['temperature']) if weight else output.loss.new_zeros(())
                    loss = output.loss + weight * kl
                if not torch.isfinite(loss):
                    raise ValueError('Nonfinite loss; preserve failure without skipped updates')
                (loss / 4).backward()
                ce_sum += float(output.loss.detach())
                kl_sum += float(kl.detach())
                seen[samples[index].sample_id] += 1
                del batch, output, teacher, loss, kl
            grad_norm = torch.nn.utils.clip_grad_norm_(params, 1., error_if_nonfinite=True)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            if update % 20 == 0:
                record = {'updates': update, 'ce': ce_sum/80, 'kl': kl_sum/80,
                    'grad_norm': float(grad_norm), 'seconds': time.perf_counter()-started}
                logs.append(record)
                print('arm', arm, worker.json.dumps(record), flush=True)
                ce_sum = kl_sum = 0.
        actual = sorted({int(v['step'].item()) for v in optimizer.state.values()})
        if actual != [240] or len(optimizer.state) != len(trainable) or set(seen) != set(plan['selected_ids']):
            raise ValueError('Actual optimizer updates/coverage failed')
        verify_trainable_decoder(model)
        encoder_after = tensor_hashes(model.get_base_model().model.encoder)
        if encoder_after != encoder_before:
            raise ValueError('Encoder changed')
        # Strip PEFT wrappers from all frozen base parameters to compare to original.
        frozen_after = {}
        for name, value in model.get_base_model().state_dict().items():
            if '.lora_' not in name:
                frozen_after[name.replace('.base_layer.', '.')] = hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest()
        if frozen_after != frozen_base_before:
            raise ValueError('Frozen teacher/base weights changed')
        with torch.autocast('cuda', dtype=torch.bfloat16):
            teacher_after = base_teacher_logits(model, **probe)
        teacher_hash_after = hashlib.sha256(teacher_after.cpu().view(torch.uint8).numpy().tobytes()).hexdigest()
        if teacher_hash_before != teacher_hash_after:
            raise ValueError('Teacher output changed after adaptation')
        folder = destination / f'checkpoint-{arm}'
        model.save_pretrained(folder, safe_serialization=True)
        torch.save(optimizer.state_dict(), folder / 'optimizer.pt')
        torch.save({'cpu': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state()}, folder / 'rng.pt')
        checkpoints[arm] = {p.name: worker.file_hash(p) for p in folder.iterdir() if p.is_file()}
        arms[arm] = {'kl_weight': weight, 'actual_updates': actual[0], 'optimizer_tensors': len(optimizer.state),
            'training_seconds': time.perf_counter()-started, 'coverage': dict(seen), 'schedule_sha256': schedule_hash,
            'initial_adapter_sha256': initial_hash, 'trainable_tensors': trainable, 'history': logs,
            'encoder_unchanged': True, 'frozen_base_unchanged': True,
            'teacher_before_sha256': teacher_hash_before, 'teacher_after_sha256': teacher_hash_after}
        worker.save_new(destination / f'arm-{arm}.json', arms[arm])
        del model, original, optimizer, params, probe, teacher_after, initial_adapter
        gc.collect()
        torch.cuda.empty_cache()
    if len({v['initial_adapter_sha256'] for v in arms.values()}) != 1:
        raise ValueError('Initial adapter identity differs')
    worker.save_new(Path('/output') / 'training.json', {
        'plan_sha256': worker.file_hash(worker.ROOT / 'plan.json'), 'arms': arms, 'checkpoints': checkpoints,
        'encoder_before': encoder_before, 'frozen_base_before': frozen_base_before,
        'cache_seconds': cache_seconds, 'audio_label_contract': contracts, 'schedule_sha256': schedule_hash,
        'GPU': torch.cuda.get_device_name(0), 'training_precision': 'bfloat16', 'test_accessed': False,
        'dev_accessed': False, 'quality_evidence': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['train', 'convert', 'baseline', 'candidate', 'cpu', 'score'])
    args = parser.parse_args()
    if args.stage in ('baseline', 'candidate', 'cpu'):
        infer(args.stage)
    else:
        {'train': train, 'convert': convert, 'score': score}[args.stage]()
