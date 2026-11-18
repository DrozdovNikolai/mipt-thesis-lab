"""One bounded NUS training-fit experiment, with isolated generation and scoring."""

import argparse
import gc
import hashlib
import json
import os
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from north55_speech.convergence import convergence_decision
from north55_speech.core import atomic_json, file_hash, settings

ROOT = Path('/study')
EXP = Path('/experiment')
STEPS = (40, 120, 240)


def read(path):
    return json.loads(path.read_bytes())


def save_new(path, value):
    if path.exists():
        raise ValueError('Preserve existing result: ' + str(path))
    atomic_json(path, value)


def validate():
    plan = read(ROOT / 'plan.json')
    for name, expected in plan['implementation_sha256'].items():
        if file_hash(Path('/app') / name) != expected:
            raise ValueError('Frozen implementation changed: ' + name)
    if file_hash(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Frozen inputs changed')
    return plan


def verify_files(root, files):
    for relative, expected in files.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != expected:
            raise ValueError('Model artifact changed: ' + relative)


def train():
    import librosa
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (
        Seq2SeqTrainer,
        Seq2SeqTrainingArguments,
        TrainerCallback,
        WhisperForConditionalGeneration,
        WhisperProcessor,
        set_seed,
    )

    plan = validate()
    phase = None
    if plan.get('continuation'):
        from north55_speech.continuation import validate_continuation
        phase = validate_continuation(plan)
    max_steps = phase['additional_steps'] if phase else 240
    path = Path('/train/subset.jsonl')
    if file_hash(path) != plan['subset_sha256']:
        raise ValueError('Training subset changed')
    samples = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    if [s['sample_id'] for s in samples] != plan['selected_ids'] or any(s['split'] != 'train' for s in samples):
        raise ValueError('Only the frozen training subset is admitted')
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError('Expose exactly one CUDA training GPU')
    base = Path('/models/whisper-small-transformers')
    verify_files(base, plan['base_manifest']['files'])
    destination = EXP / 'training'
    if destination.exists():
        raise ValueError('Preserve existing training version')
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    set_seed(55)
    processor = WhisperProcessor.from_pretrained(base, local_files_only=True)
    processor.tokenizer.set_prefix_tokens(language='en', task='transcribe')
    model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
    model.config.use_cache = False
    if phase:
        from peft import PeftModel
        source_checkpoint = Path('/source_experiment/training/checkpoint-240')
        verify_files(source_checkpoint, phase['source_checkpoint_files'])
        model = PeftModel.from_pretrained(model, source_checkpoint, local_files_only=True, is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, target_modules=['q_proj', 'v_proj'],
                                               lora_dropout=.05, bias='none'))
    # Cache only the deterministic preprocessing used by the original training.
    features = []
    for sample in samples:
        audio = (Path('/audio') / sample['audio_path']).resolve()
        if not audio.is_relative_to(Path('/audio')) or file_hash(audio) != sample['audio_sha256']:
            raise ValueError('Training audio changed')
        waveform, _ = librosa.load(audio, sr=16000, mono=False)
        if waveform.ndim != 1 or sample['channel'] != 0 or len(waveform) > 480000:
            raise ValueError('Unexpected training audio contract')
        labels = processor.tokenizer(sample['reference_text']).input_ids
        if len(labels) > 448:
            raise ValueError('Training labels would be truncated')
        features.append({'input_features': processor.feature_extractor(
            waveform, sampling_rate=16000).input_features[0], 'labels': labels})
    seen = Counter()

    class Dataset(torch.utils.data.Dataset):
        def __len__(self):
            return len(features)

        def __getitem__(self, index):
            seen[samples[index]['sample_id']] += 1
            return features[index]

    def collate(items):
        inputs = processor.feature_extractor.pad(
            [{'input_features': item['input_features']} for item in items], return_tensors='pt')
        labels = processor.tokenizer.pad([{'input_ids': item['labels']} for item in items], return_tensors='pt')
        targets = labels.input_ids.masked_fill(labels.attention_mask.ne(1), -100)
        if not (targets[:, 0] == model.config.decoder_start_token_id).all().item():
            raise ValueError('Missing decoder start token')
        inputs['labels'] = targets[:, 1:]
        return inputs

    class Milestones(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):
            control.should_save = state.global_step in STEPS
            return control

    args = Seq2SeqTrainingArguments(output_dir=str(destination), max_steps=max_steps,
        per_device_train_batch_size=1, gradient_accumulation_steps=4,
        learning_rate=phase['learning_rate'] if phase else 5e-5, optim='adamw_torch_fused',
        lr_scheduler_type=phase['schedule'] if phase else 'linear', warmup_steps=0,
        weight_decay=0., fp16=True, tf32=False, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={'use_reentrant': False}, eval_strategy='no',
        save_strategy='no', logging_steps=10, save_total_limit=None, load_best_model_at_end=False,
        remove_unused_columns=False, label_names=['labels'], report_to=[], seed=55,
        dataloader_num_workers=0, predict_with_generate=False)
    trainer = Seq2SeqTrainer(model=model, args=args, train_dataset=Dataset(), data_collator=collate,
                             callbacks=[Milestones()])
    optimizer_audit = None
    if phase:
        from north55_speech.continuation import restart_learning_rate
        trainer.create_optimizer()
        source_optimizer = torch.load(source_checkpoint / 'optimizer.pt', map_location='cpu', weights_only=True)
        trainer.optimizer.load_state_dict(source_optimizer)
        restart_learning_rate(trainer.optimizer, phase['learning_rate'])
        if trainer.accelerator.scaler is None:
            raise ValueError('Expected AMP scaler to restore')
        trainer.accelerator.scaler.load_state_dict(torch.load(source_checkpoint / 'scaler.pt', map_location='cpu', weights_only=True))
        optimizer_audit = {'source_state_count': len(source_optimizer['state']),
            'source_steps': sorted({float(v['step']) for v in source_optimizer['state'].values()}),
            'restored_steps': sorted({float(v['step']) for v in trainer.optimizer.state.values()}),
            'source_learning_rates': [g['lr'] for g in source_optimizer['param_groups']],
            'restarted_learning_rates': [g['lr'] for g in trainer.optimizer.param_groups],
            'scaler_restored': True, 'rng_policy': 'new phase seeded 55; original dataset order restarts'}
    result = trainer.train()
    if optimizer_audit is not None:
        optimizer_audit['final_steps'] = sorted({float(v['step']) for v in trainer.optimizer.state.values()})
    checkpoints = {}
    for step in STEPS:
        folder = destination / f'checkpoint-{step}'
        if not (folder / 'adapter_model.safetensors').is_file():
            raise ValueError('Missing prespecified adapter checkpoint')
        checkpoints[str(step)] = {p.name: file_hash(p) for p in folder.iterdir() if p.is_file()}
    if trainer.state.global_step != max_steps or set(seen) != set(plan['selected_ids']):
        raise ValueError('Incomplete training coverage')
    save_new(Path(os.environ.get('NORTH55_DIAGNOSTIC_OUTPUT', '/study')) / 'training.json', {'plan_sha256': file_hash(ROOT / 'plan.json'),
        'global_steps': trainer.state.global_step, 'metrics': result.metrics, 'history': trainer.state.log_history,
        'coverage': dict(seen), 'checkpoints': checkpoints, 'GPU': torch.cuda.get_device_name(0),
        'parameters': {'total': sum(p.numel() for p in model.parameters()),
                       'trainable': sum(p.numel() for p in model.parameters() if p.requires_grad)},
        'arguments': args.to_dict(), 'reference_policy': 'train_only_convergence_diagnostic',
        'optimizer_continuation': optimizer_audit,
        'dev_accessed': False, 'test_accessed': False, 'quality_evidence': False})
    print('Saved fixed checkpoints', STEPS, ';', len(seen), 'training originals loaded.', flush=True)


def convert():
    import torch
    from ctranslate2.converters import TransformersConverter
    from peft import PeftModel
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, WhisperTokenizerFast

    plan = validate()
    training = read(ROOT / 'training.json')
    if training['plan_sha256'] != file_hash(ROOT / 'plan.json'):
        raise ValueError('Training identity differs')
    base = Path('/models/whisper-small-transformers')
    verify_files(base, plan['base_manifest']['files'])
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    manifests = {'0': plan['source_model']} if plan.get('continuation') else {}
    for step in STEPS:
        checkpoint = EXP / 'training' / f'checkpoint-{step}'
        verify_files(checkpoint, training['checkpoints'][str(step)])
        merged_dir = EXP / 'merged' / f'step-{step}'
        output = EXP / 'models' / plan['model_names'][str(step)]
        if merged_dir.exists() or output.exists():
            raise ValueError('Preserve existing converted checkpoint')
        model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        adapted = PeftModel.from_pretrained(model, checkpoint, local_files_only=True).cuda()
        merged = adapted.merge_and_unload()
        if plan.get('decoder_training') or plan.get('retention_training'):
            from north55_speech.decoder_adaptation import tensor_hashes
            if tensor_hashes(merged.model.encoder) != training['encoder_before']:
                raise ValueError('Converted encoder differs from the original base')
        merged.save_pretrained(merged_dir, safe_serialization=True)
        WhisperProcessor.from_pretrained(base, local_files_only=True).save_pretrained(merged_dir)
        WhisperTokenizerFast.from_pretrained(base, local_files_only=True).save_pretrained(merged_dir)
        del model, adapted, merged
        gc.collect()
        torch.cuda.empty_cache()
        TransformersConverter(str(merged_dir), copy_files=['tokenizer.json', 'preprocessor_config.json']).convert(
            str(output), quantization='float16')
        manifest = {'model': output.name, 'repo': 'local_train_only_convergence_diagnostic',
            'revision': file_hash(checkpoint / 'adapter_model.safetensors'), 'step': step,
            'subset_sha256': plan['subset_sha256'], 'base_manifest': plan['base_manifest'],
            'quality_evidence': False, 'selection_allowed': False, 'release_allowed': False,
            'license': 'inherited_base_and_existing_project_research_source_restrictions',
            'files': {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}
        if plan.get('decoder_training') or plan.get('retention_training'):
            manifest.update(repo='local_fresh_decoder_only_adaptation', encoder_unchanged=True,
                            source_train_manifest_sha256=plan['subset_sha256'])
        if plan.get('retention_training'):
            manifest.update(repo='local_retention_diagnostic', arm_id=step,
                            actual_updates=training['arms'][str(step)]['actual_updates'],
                            kl_weight=plan['retention_training']['arms'][str(step)])
        save_new(output / 'manifest.json', manifest)
        manifests[str(step)] = manifest
        print('Converted step', step, 'to CT2 float16.', flush=True)
    save_new(Path(os.environ.get('NORTH55_DIAGNOSTIC_OUTPUT', '/study')) / 'conversion.json', {'plan_sha256': file_hash(ROOT / 'plan.json'), 'models': manifests})


def infer(stage, step, cpu=False):
    import numpy as np

    from north55_speech.asr import AsrProvider
    from north55_speech.schemas import PipelineConfig
    from scripts.decoding_diagnostics import load_audio

    plan = validate()
    if stage == 'transfer' and not any(plan.get(k) for k in ('continuation', 'decoder_training', 'retention_training')) and not read(ROOT / 'fit-decision.json')['run_transfer']:
        raise ValueError('Prespecified training criterion has not passed')
    from north55_speech.continuation import permitted_transfer_steps
    allowed_steps = permitted_transfer_steps(plan)
    if plan.get('decoder_training'):
        from north55_speech.decoder_adaptation import validate_decoder_plan
        allowed_steps = validate_decoder_plan(plan)['milestones']
    if plan.get('retention_training'):
        from north55_speech.retention import validate_retention_plan
        allowed_steps = [int(k) for k in validate_retention_plan(plan)['arms']]
    if stage == 'transfer' and step not in allowed_steps:
        raise ValueError('Only prespecified source/final checkpoints may be assessed on other audio')
    conversion = read(ROOT / 'conversion.json')
    if conversion['plan_sha256'] != file_hash(ROOT / 'plan.json'):
        raise ValueError('Conversion identity differs')
    manifest = conversion['models'][str(step)]
    settings.model_root = Path('/source_experiment/models') if plan.get('continuation') and step == 0 else EXP / 'models'
    if read(settings.model_root / manifest['model'] / 'manifest.json') != manifest:
        raise ValueError('Saved model identity differs')
    config = PipelineConfig.model_validate(plan['config'] | {'model': manifest['model']})
    items = read(ROOT / 'inputs.json')[stage]
    if cpu:
        config = config.model_copy(update={'device': 'cpu', 'compute_type': 'int8'})
        items = read(ROOT / 'inputs.json')['cpu'] if plan.get('cpu_inputs') else items[:1]
    provider = AsrProvider(config)
    actual = provider.model.model.compute_type
    if not cpu and (provider.model.model.device != 'cuda' or actual != 'float16'):
        raise ValueError('Require CUDA float16 matching parent')
    out = ROOT / (('cpu-' if cpu else '') + stage + f'-{step}')
    hashes, failed, resumed = {}, [], 0
    for index, item in enumerate(items):
        destination = out / 'predictions' / (item['id'] + '.json')
        identity = dict(item, step=step, plan_sha256=file_hash(ROOT / 'plan.json'),
                        config=config.model_dump(), effective_options=provider.options(item['input_language']),
                        model_manifest_sha256=file_hash(settings.model_root / manifest['model'] / 'manifest.json'))
        if destination.exists():
            record = read(destination)
            if any(record.get(k) != v for k, v in identity.items()) or record['runtime_failure'] is not None:
                raise ValueError('Existing result cannot be silently replaced')
            resumed += 1
        else:
            started = time.perf_counter()
            record = dict(identity, hypothesis='', runtime_failure=None, actual_device=provider.model.model.device,
                          actual_precision=actual)
            try:
                waveform = load_audio(item)
                record['effective_waveform_sha256'] = hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest()
                generator, info = provider.model.transcribe(waveform, **identity['effective_options'])
                segments = list(generator)
                record['hypothesis'] = ' '.join(s.text.strip() for s in segments).strip()
                record['segments'] = [asdict(s) for s in segments]
                record['language'] = info.language
                if not np.isfinite(record.get('seconds', 0.)):
                    raise ValueError('Nonfinite timing')
            except Exception as error:
                record['runtime_failure'] = type(error).__name__ + ': ' + str(error)
            record['seconds'] = time.perf_counter() - started
            save_new(destination, record)
        if record['runtime_failure'] is not None:
            failed.append(item['id'])
        hashes[destination.name] = file_hash(destination)
        if (index + 1) % 25 == 0:
            print(stage, step, index + 1, '/', len(items), flush=True)
    execution = {'plan_sha256': file_hash(ROOT / 'plan.json'), 'step': step, 'records': len(items),
        'runtime_failures': failed, 'prediction_sha256': hashes, 'actual_device': provider.model.model.device,
        'actual_precision': actual, 'new_ASR_calls': len(items) - resumed, 'resumed': resumed}
    # Resumption writes a separate observation, preserving the first execution record.
    save_new(out / ('execution.json' if not (out / 'execution.json').exists() else f'replay-{time.time_ns()}.json'), execution)
    print(json.dumps({k: v for k, v in execution.items() if k != 'prediction_sha256'}), flush=True)


def scored(stage, step):
    from north55_speech.metrics import edit_counts
    from scripts.research_audio_evidence import same_waveform

    plan = validate()
    for name, expected in plan['scoring_sha256'].items():
        if file_hash(ROOT / 'scoring' / name) != expected:
            raise ValueError('Frozen references or baseline changed')
    refs = read(ROOT / 'scoring/references.json')
    baseline = read(ROOT / 'scoring/parent.json')
    items = read(ROOT / 'inputs.json')[stage]
    out = ROOT / f'{stage}-{step}'
    execution = read(out / 'execution.json')
    if execution['plan_sha256'] != file_hash(ROOT / 'plan.json'):
        raise ValueError('Inference identity differs')
    a, b, failed = {}, {}, []
    for item in items:
        path = out / 'predictions' / (item['id'] + '.json')
        if file_hash(path) != execution['prediction_sha256'][path.name]:
            raise ValueError('Prediction changed')
        current, old = read(path), baseline[item['id']]
        if current['effective_options'] != old['effective_options']:
            raise ValueError('Decoder options differ')
        if not same_waveform(item, old, current['effective_waveform_sha256']):
            raise ValueError('Parent and candidate audio differ')
        if current['runtime_failure'] is not None:
            failed.append(item['id'])
        ref = refs[item['reference_id']]
        if ref is None:
            raise ValueError('Missing diagnostic reference')
        a[item['id']] = edit_counts(ref, old['hypothesis'])
        b[item['id']] = edit_counts(ref, current['hypothesis'] if current['runtime_failure'] is None else '')
    return a, b, failed


def score_fit():
    from north55_speech.metrics import corpus_counts

    validate()
    curve, counts = {}, {}
    for step in STEPS:
        a, b, failed = scored('fit', step)
        curve.setdefault(0, dict(corpus_counts(list(a.values())), runtime_failures=0))
        curve[step] = dict(corpus_counts(list(b.values())), runtime_failures=len(failed))
        counts[str(step)] = b
    decision = convergence_decision(curve)
    save_new(ROOT / 'fit-comparison.json', {'plan_sha256': file_hash(ROOT / 'plan.json'),
        'curve': curve, 'counts': counts, 'decision': decision, 'training_only': True, 'quality_evidence': False})
    save_new(ROOT / 'fit-decision.json', decision)
    print(json.dumps({'curve': curve, 'decision': decision}, indent=2), flush=True)


def score_transfer():
    from north55_speech.metrics import corpus_counts, paired_cluster_bootstrap
    from scripts.research_audio_evidence import write_legacy_evidence

    plan = validate()
    a, b, failed = scored('transfer', 240)
    items = read(ROOT / 'inputs.json')['transfer']
    cohorts = {}
    for cohort in sorted({i['cohort'] for i in items}):
        group = [i for i in items if i['cohort'] == cohort]
        aa, bb = (corpus_counts([values[i['id']] for i in group]) for values in (a, b))
        first, last = aa['wer_lexical_corpus'], bb['wer_lexical_corpus']
        value = {'samples': len(group), 'groups': len({i['group_id'] for i in group}),
                 'parent': aa, 'final': bb, 'relative_reduction': (first-last)/first if first else None}
        if cohort in ('noise_only', 'bleriot_b_noise'):
            minutes = sum(i['duration_sec'] for i in group)/60
            value.update(minutes=minutes, parent_insertions_per_minute=aa['I']/minutes,
                         final_insertions_per_minute=bb['I']/minutes)
        elif cohort != 'nus_same_source_nonfit':
            value['bootstrap'] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                'baseline': a[i['id']], 'candidate': b[i['id']]} for i in group], resamples=2000, seed=55, confidence=.95)
        cohorts[cohort] = value
    human = cohorts['partial_human_dev']
    checks = {'human_dev_point': human['relative_reduction'] is not None and human['relative_reduction'] >= .10,
              'clean_EN': cohorts['general_clean']['final']['wer_lexical_corpus']-cohorts['general_clean']['parent']['wer_lexical_corpus'] <= .01,
              'general_RU': cohorts['general_ru']['final']['wer_lexical_corpus']-cohorts['general_ru']['parent']['wer_lexical_corpus'] <= .01,
              'noise': all(cohorts[c]['final_insertions_per_minute'] <= cohorts[c]['parent_insertions_per_minute'] for c in ('noise_only', 'bleriot_b_noise')),
              'runtime': not failed}
    save_new(ROOT / 'transfer-comparison.json', {'plan_sha256': file_hash(ROOT / 'plan.json'),
        'cohorts': cohorts, 'checks': checks, 'runtime_failures': failed,
        'release': 'FAIL' if not all(checks.values()) else 'NEEDS_MORE_DATA',
        'independent_quality': 'NEEDS_MORE_DATA', 'test_accessed': False, 'release_promoted': False,
        'conditional_protocol': plan['transfer_condition']})
    write_legacy_evidence(ROOT / 'legacy-waveform-evidence.json')
    print(json.dumps({'checks': checks, 'cohorts': {c: {'parent_WER': v['parent']['wer_lexical_corpus'],
        'final_WER': v['final']['wer_lexical_corpus']} for c, v in cohorts.items()}}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['train', 'convert', 'fit', 'transfer', 'cpu', 'score-fit', 'score-transfer'])
    parser.add_argument('step', nargs='?', type=int, choices=STEPS)
    args = parser.parse_args()
    if args.stage in ('fit', 'transfer', 'cpu'):
        if args.step is None:
            parser.error('step is required')
        infer('fit' if args.stage == 'cpu' else args.stage, args.step, cpu=args.stage == 'cpu')
    else:
        {'train': train, 'convert': convert, 'score-fit': score_fit, 'score-transfer': score_transfer}[args.stage]()
