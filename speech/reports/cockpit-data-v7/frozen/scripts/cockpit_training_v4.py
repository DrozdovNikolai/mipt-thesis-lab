"""Three matched regimes on exactly the same hard and noisy aviation training data."""

import argparse
import gc
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from north55_speech.core import file_hash
from north55_speech.hard_adaptation import ARMS, TRAINING
from scripts import nus_convergence as worker
from scripts import publisher_training_v3 as evaluation

ROOT = Path('/study')
EXP = Path('/experiment')
read = worker.read
save_new = worker.save_new


def validate():
    plan = worker.validate()
    if plan['training'] != TRAINING:
        raise ValueError('Training regime or selection protocol changed')
    if any(plan.get(k) is not False for k in ('quality_evidence', 'selection_allowed', 'test_accessed', 'release_promoted')):
        raise ValueError('Diagnostic cannot authorize release')
    return plan


def train():
    import librosa
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, set_seed
    from transformers.modeling_outputs import BaseModelOutput

    from north55_speech.datasets import load_manifest
    from north55_speech.decoder_adaptation import (
        tensor_hashes,
        verify_trainable_decoder,
    )
    from north55_speech.hard_adaptation import ARMS, targets, validate_population
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
    if len(samples) != plan['train_rows'] or [s.sample_id for s in samples] != plan['selected_ids'] or any(s.split != 'train' for s in samples):
        raise ValueError('Only the frozen complete hard/noisy training population is admitted')
    validate_population(samples, load_manifest(Path('/train/dev.jsonl')))
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
        cached.append((states, labels, features.cpu()))
        contracts.append({'id': sample.sample_id, 'language': sample.language, 'prefix': tokens[:4],
            'tokens': len(tokens), 'samples': len(waveform),
            'waveform_sha256': hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest(),
            'encoder_state_sha256': hashlib.sha256(states.view(torch.uint8).numpy().tobytes()).hexdigest()})
        if (index + 1) % 100 == 0:
            print('Cached train audio', index + 1, '/', len(samples), flush=True)
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
    set_seed(55)
    initial_base = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
    initial_model = get_peft_model(initial_base, LoraConfig(r=8, lora_alpha=16,
        target_modules=targets(initial_base, True), lora_dropout=.05, bias='none'))
    shared_initial = {n: p.detach().clone() for n, p in initial_model.named_parameters() if p.requires_grad}
    del initial_model, initial_base
    gc.collect()
    checkpoints, arms = {}, {}
    for arm, options in ARMS.items():
        weight = options['kl_weight']
        set_seed(55)
        original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        original.config.use_cache = False
        model: Any = get_peft_model(original, LoraConfig(r=8, lora_alpha=16,
            target_modules=targets(original, options['encoder_lora']), lora_dropout=.05, bias='none')).cuda()
        trainable = [n for n, p in model.named_parameters() if p.requires_grad]
        if not options['encoder_lora']:
            verify_trainable_decoder(model)
        else:
            model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        with torch.no_grad():
            for name, value in model.named_parameters():
                if value.requires_grad:
                    value.copy_(shared_initial[name].to(value.device))
        set_seed(55)
        initial_adapter = {n: p.detach().cpu().clone() for n, p in model.named_parameters() if p.requires_grad}
        initial_hash = hashlib.sha256(b''.join(p.numpy().tobytes() for p in initial_adapter.values())).hexdigest()
        decoder_initial_sha = hashlib.sha256(b''.join(p.numpy().tobytes() for n, p in initial_adapter.items() if '.decoder.' in n)).hexdigest()
        params = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(params, lr=phase['learning_rate'], weight_decay=0., fused=True)
        optimizer.zero_grad(set_to_none=True)
        seen: Counter[str]
        seen, logs = Counter(), []
        ce_sum = kl_sum = 0.
        started = time.perf_counter()
        model.train()
        probe_states, probe_labels, _ = cached[0]
        probe = {'encoder_outputs': BaseModelOutput(last_hidden_state=probe_states.cuda()), 'labels': probe_labels.cuda()}
        with torch.autocast('cuda', dtype=torch.bfloat16):
            teacher_before = base_teacher_logits(model, **probe)
        teacher_hash_before = hashlib.sha256(teacher_before.cpu().view(torch.uint8).numpy().tobytes()).hexdigest()
        del teacher_before
        for update in range(1, phase['updates'] + 1):
            for index in schedule[(update - 1)*4:update*4]:
                states, labels, features = cached[index]
                batch = ({'input_features': features.cuda(), 'labels': labels.cuda()} if options['encoder_lora'] else
                         {'encoder_outputs': BaseModelOutput(last_hidden_state=states.cuda()), 'labels': labels.cuda()})
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
        if not options['encoder_lora']:
            verify_trainable_decoder(model)
        encoder_after = tensor_hashes(model.get_base_model().model.encoder)
        if not options['encoder_lora'] and encoder_after != encoder_before:
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
            'encoder_unchanged': not options['encoder_lora'], 'frozen_base_unchanged': True,
            'encoder_lora': options['encoder_lora'], 'decoder_initial_sha256': decoder_initial_sha,
            'teacher_before_sha256': teacher_hash_before, 'teacher_after_sha256': teacher_hash_after}
        worker.save_new(destination / f'arm-{arm}.json', arms[arm])
        del model, original, optimizer, params, probe, teacher_after, initial_adapter
        gc.collect()
        torch.cuda.empty_cache()
    if len({v['decoder_initial_sha256'] for v in arms.values()}) != 1:
        raise ValueError('Initial adapter identity differs')
    worker.save_new(Path('/output') / 'training.json', {
        'plan_sha256': worker.file_hash(worker.ROOT / 'plan.json'), 'arms': arms, 'checkpoints': checkpoints,
        'encoder_before': encoder_before, 'frozen_base_before': frozen_base_before,
        'cache_seconds': cache_seconds, 'audio_label_contract': contracts, 'schedule_sha256': schedule_hash,
        'GPU': torch.cuda.get_device_name(0), 'training_precision': 'bfloat16', 'test_accessed': False,
        'dev_used_for_optimization': False, 'dev_accessed_for_admission_only': True, 'quality_evidence': False})


def convert():
    import torch
    from ctranslate2.converters import TransformersConverter
    from peft import PeftModel
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, WhisperTokenizerFast

    from north55_speech.decoder_adaptation import tensor_hashes

    plan, training = validate(), read(ROOT / 'training.json')
    if training['plan_sha256'] != file_hash(ROOT / 'plan.json'):
        raise ValueError('Training identity differs')
    base = Path('/models/whisper-small-transformers')
    worker.verify_files(base, plan['base_manifest']['files'])
    torch.set_num_threads(4)
    conversions = {}
    for arm, options in ARMS.items():
        checkpoint = EXP / 'training' / ('checkpoint-' + arm)
        worker.verify_files(checkpoint, training['checkpoints'][arm])
        merged_dir, output = EXP / 'merged' / arm, EXP / 'models' / plan['model_names'][arm]
        if merged_dir.exists() or output.exists():
            raise ValueError('Preserve existing converted arm')
        base_model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        adapted = PeftModel.from_pretrained(base_model, checkpoint, local_files_only=True).cuda()
        merged = adapted.merge_and_unload()
        if not options['encoder_lora'] and tensor_hashes(merged.model.encoder) != training['encoder_before']:
            raise ValueError('Frozen encoder changed during conversion')
        merged.save_pretrained(merged_dir, safe_serialization=True)
        WhisperProcessor.from_pretrained(base, local_files_only=True).save_pretrained(merged_dir)
        WhisperTokenizerFast.from_pretrained(base, local_files_only=True).save_pretrained(merged_dir)
        del base_model, adapted, merged
        gc.collect()
        torch.cuda.empty_cache()
        TransformersConverter(str(merged_dir), copy_files=['tokenizer.json', 'preprocessor_config.json']).convert(str(output), quantization='float16')
        manifest = {'model': output.name, 'repo': 'local_hard_aviation_regime_comparison_v4',
            'revision': file_hash(checkpoint / 'adapter_model.safetensors'), 'actual_updates': 240,
            'arm': arm, 'regime': options, 'train_sha256': plan['train_sha256'], 'base_manifest': plan['base_manifest'],
            'quality_evidence': False, 'release_allowed': False, 'selection_allowed': False,
            'license': 'inherited_base_and_existing_noncommercial_research_source_restrictions',
            'files': {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}
        save_new(output / 'manifest.json', manifest)
        conversion = {'plan_sha256': file_hash(ROOT / 'plan.json'), 'model': manifest}
        save_new(Path('/output/conversions') / (arm + '.json'), conversion)
        conversions[arm] = manifest
        print('Converted', arm, flush=True)
    save_new(Path('/output/conversion.json'), {'plan_sha256': file_hash(ROOT / 'plan.json'), 'models': conversions})


def score():
    from north55_speech.metrics import corpus_counts, paired_cluster_bootstrap

    plan = validate()
    if file_hash(ROOT / 'scoring/references.json') != plan['references_sha256']:
        raise ValueError('References changed')
    refs, items = read(ROOT / 'scoring/references.json'), read(ROOT / 'inputs.json')
    systems = ['baseline', *ARMS]
    executions = {s: read(ROOT / ('io-' + s) / 'execution.json') for s in systems}
    if any(e['plan_sha256'] != file_hash(ROOT / 'plan.json') or e['runtime_failures'] for e in executions.values()):
        raise ValueError('Runtime failure or mismatched execution')
    counts: dict[str, Any]
    counts, examples = {}, []
    for item in items:
        records = {}
        for system in systems:
            path = ROOT / ('io-' + system) / 'predictions' / (item['id'] + '.json')
            if file_hash(path) != executions[system]['prediction_sha256'][path.name]:
                raise ValueError('Prediction changed')
            records[system] = read(path)
            if records[system]['plan_sha256'] != file_hash(ROOT / 'plan.json'):
                raise ValueError('Prediction plan differs')
        counts[item['id']] = {}
        for arm in ARMS:
            pair = evaluation.compare_records(item, refs[item['reference_id']], records['baseline'], records[arm])
            counts[item['id']].update(baseline=pair['baseline'])
            counts[item['id']][arm] = pair['candidate']
        if item['cohort'] == 'partial_human_dev':
            examples.append({'id': item['id'], 'reference': refs[item['reference_id']],
                'hypotheses': {s: r['hypothesis'] for s, r in records.items()}, 'counts': counts[item['id']]})
    cohorts: dict[str, Any] = {}
    for cohort in sorted({i['cohort'] for i in items}):
        group = [i for i in items if i['cohort'] == cohort]
        scores = {s: corpus_counts([counts[i['id']][s] for i in group]) for s in systems}
        row: dict[str, Any] = {'samples': len(group), 'groups': len({i['group_id'] for i in group}), 'scores': scores}
        comparisons = {}
        for left, right in [('baseline', a) for a in ARMS] + [('decoder-kl', 'decoder-ce'), ('decoder-ce', 'full-ce')]:
            a, b = (scores[s]['wer_lexical_corpus'] for s in (left, right))
            change = {'wer_delta': b-a if a is not None and b is not None else None,
                'relative_reduction': (a-b)/a if a else None}
            if not cohort.startswith('train_') and cohort not in ('noise_only', 'bleriot_b_noise'):
                change['bootstrap'] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                    'baseline': counts[i['id']][left], 'candidate': counts[i['id']][right]} for i in group],
                    resamples=2000, seed=55, confidence=.95)
            comparisons[right + '_vs_' + left] = change
        row['comparisons'] = comparisons
        if cohort in ('noise_only', 'bleriot_b_noise'):
            minutes = sum(i['duration_sec'] for i in group)/60
            row['inserted_words_per_minute'] = {s: scores[s]['I']/minutes for s in systems}
        cohorts[cohort] = row
    checks = {}
    for arm in ARMS:
        key = arm + '_vs_baseline'
        human = cohorts['partial_human_dev']['comparisons'][key]
        checks[arm] = {'human_point': human['relative_reduction'] >= .1, 'human_CI': human['bootstrap']['upper'] < 0,
            'general_EN': cohorts['general_clean']['comparisons'][key]['wer_delta'] <= .01,
            'general_RU': cohorts['general_ru']['comparisons'][key]['wer_delta'] <= .01,
            'noise': all(cohorts[c]['inserted_words_per_minute'][arm] <= cohorts[c]['inserted_words_per_minute']['baseline']
                         for c in ('noise_only', 'bleriot_b_noise')), 'runtime': True}
    result = {'plan_sha256': file_hash(ROOT / 'plan.json'), 'cohorts': cohorts, 'checks': checks,
        'fixed_candidate': 'full-ce', 'diagnostic_status': 'FAIL' if not all(checks['full-ce'].values()) else 'NEEDS_MORE_DATA',
        'new_GPU_ASR': sum(e['new_ASR_calls'] for e in executions.values()), 'new_blind_dev_scored': False,
        'quality_evidence': False, 'selection_allowed': False, 'test_accessed': False, 'release_promoted': False}
    save_new(ROOT / 'comparison.json', result)
    save_new(ROOT / 'scored-counts.json', counts)
    save_new(ROOT / 'scoring/human-examples.json', examples)
    print(json.dumps({'WER': {c: {s: v['wer_lexical_corpus'] for s, v in r['scores'].items()} for c, r in cohorts.items()},
        'checks': checks}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['train', 'convert', 'baseline', 'candidate', 'cpu', 'score'])
    args = parser.parse_args()
    if args.stage in ('baseline', 'candidate', 'cpu'):
        evaluation.validate = validate
        evaluation.infer(args.stage)
    else:
        {'train': train, 'convert': convert, 'score': score}[args.stage]()


