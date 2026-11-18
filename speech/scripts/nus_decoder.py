"""Train a fresh decoder adapter on all existing NUS/EN/RU pairs, then score controls."""

import argparse
import hashlib
import os
from collections import Counter
from pathlib import Path

from scripts import nus_convergence as worker

worker.STEPS = (240, 1200)


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

    from north55_speech.datasets import load_manifest
    from north55_speech.decoder_adaptation import (
        decoder_targets,
        learning_rate_multiplier,
        tensor_hashes,
        validate_decoder_plan,
        verify_trainable_decoder,
    )
    from north55_speech.nus_training import validate_nus_pair_population

    plan = worker.validate()
    phase = validate_decoder_plan(plan)
    manifest = Path('/train/subset.jsonl')  # Launcher compatibility; this is the full 675-row file.
    if worker.file_hash(manifest) != plan['subset_sha256']:
        raise ValueError('Full training manifest changed')
    samples = load_manifest(manifest)
    if len(samples) != 675 or [s.sample_id for s in samples] != plan['selected_ids'] or any(s.split != 'train' for s in samples):
        raise ValueError('Only the original full 675-pair training population is admitted')
    validate_nus_pair_population(samples, [], plan['permission_evidence_sha256'])
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError('Expose exactly one CUDA GPU')
    base = Path('/models/whisper-small-transformers')
    worker.verify_files(base, plan['base_manifest']['files'])
    destination = worker.EXP / 'training'
    if destination.exists():
        raise ValueError('Preserve the existing training version')
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    set_seed(55)
    processor = WhisperProcessor.from_pretrained(base, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
    model.config.use_cache = False
    before = tensor_hashes(model.model.encoder)
    targets = decoder_targets(model)
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, target_modules=targets,
                                            lora_dropout=.05, bias='none'))
    trainable = verify_trainable_decoder(model)
    features, contracts = [], []
    for sample in samples:
        path = (Path('/audio') / sample.audio_path).resolve()
        if not path.is_relative_to(Path('/audio')) or worker.file_hash(path) != sample.audio_sha256:
            raise ValueError('Training waveform identity changed')
        waveform, _ = librosa.load(path, sr=16000, mono=False)
        if waveform.ndim == 2:
            waveform = waveform[sample.channel]
        elif sample.channel != 0:
            raise ValueError('Mono audio has only channel zero')
        if len(waveform) > 480000:
            raise ValueError('No implicit waveform truncation is allowed')
        processor.tokenizer.set_prefix_tokens(language=sample.language, task='transcribe')
        labels = processor.tokenizer(sample.reference_text).input_ids
        if len(labels) > 448 or not sample.reference_text:
            raise ValueError('No empty/truncated reference is admitted')
        feature = processor.feature_extractor(waveform, sampling_rate=16000).input_features[0]
        features.append({'input_features': feature, 'labels': labels})
        contracts.append({'id': sample.sample_id, 'language': sample.language, 'prefix': labels[:4],
            'label_length': len(labels), 'samples': len(waveform),
            'waveform_sha256': hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest()})
    seen = Counter()

    class Dataset(torch.utils.data.Dataset):
        def __len__(self):
            return len(features)

        def __getitem__(self, index):
            seen[samples[index].sample_id] += 1
            return features[index]

    def collate(items):
        inputs = processor.feature_extractor.pad(
            [{'input_features': i['input_features']} for i in items], return_tensors='pt')
        labels = processor.tokenizer.pad([{'input_ids': i['labels']} for i in items], return_tensors='pt')
        targets = labels.input_ids.masked_fill(labels.attention_mask.ne(1), -100)
        if not (targets[:, 0] == model.config.decoder_start_token_id).all().item():
            raise ValueError('Decoder start token missing')
        inputs['labels'] = targets[:, 1:]
        return inputs

    milestone_audit = {}

    class Milestones(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):
            control.should_save = state.global_step in worker.STEPS
            if control.should_save:
                if tensor_hashes(model.get_base_model().model.encoder) != before:
                    raise ValueError('Encoder weights changed during decoder-only training')
                verify_trainable_decoder(model)
                milestone_audit[str(state.global_step)] = {'encoder_unchanged': True,
                    'optimizer_steps': sorted({float(v['step']) for v in kwargs['optimizer'].state.values()}),
                    'train_visits': sum(seen.values())}
            return control

    args = Seq2SeqTrainingArguments(output_dir=str(destination), max_steps=phase['max_steps'],
        per_device_train_batch_size=1, gradient_accumulation_steps=4, learning_rate=5e-5,
        optim='adamw_torch_fused', lr_scheduler_type='constant', warmup_steps=0, weight_decay=0.,
        fp16=True, tf32=False, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={'use_reentrant': False}, eval_strategy='no', save_strategy='no',
        logging_steps=40, disable_tqdm=True, save_total_limit=None, load_best_model_at_end=False,
        remove_unused_columns=False, label_names=['labels'], report_to=[], seed=55,
        dataloader_num_workers=0, predict_with_generate=False)
    trainer = Seq2SeqTrainer(model=model, args=args, train_dataset=Dataset(), data_collator=collate,
                             callbacks=[Milestones()])
    trainer.create_optimizer()
    trainer.lr_scheduler = torch.optim.lr_scheduler.LambdaLR(trainer.optimizer, learning_rate_multiplier)
    result = trainer.train()
    after = tensor_hashes(model.get_base_model().model.encoder)
    if after != before or set(seen) != set(plan['selected_ids']) or trainer.state.global_step != 1200:
        raise ValueError('Training integrity or coverage failed')
    checkpoints = {str(s): {p.name: worker.file_hash(p) for p in (destination / f'checkpoint-{s}').iterdir() if p.is_file()}
                   for s in worker.STEPS}
    worker.save_new(Path(os.environ.get('NORTH55_DIAGNOSTIC_OUTPUT', '/study')) / 'training.json', {
        'plan_sha256': worker.file_hash(worker.ROOT / 'plan.json'), 'global_steps': trainer.state.global_step,
        'metrics': result.metrics, 'history': trainer.state.log_history, 'coverage': dict(seen),
        'checkpoints': checkpoints, 'milestones': milestone_audit, 'encoder_before': before, 'encoder_after': after,
        'trainable_tensors': trainable, 'target_modules': targets, 'audio_label_contract': contracts,
        'parameters': {'total': sum(p.numel() for p in model.parameters()),
            'trainable': sum(p.numel() for p in model.parameters() if p.requires_grad)},
        'arguments': args.to_dict(), 'actual_scheduler': 'LambdaLR: linear_first_240_then_constant',
        'GPU': torch.cuda.get_device_name(0), 'dev_accessed': False, 'test_accessed': False,
        'quality_evidence': False})
    print('Completed fresh decoder-only trajectory; encoder hashes unchanged.', flush=True)


def score():
    from north55_speech.metrics import corpus_counts, edit_counts, paired_cluster_bootstrap
    from scripts.research_audio_evidence import same_waveform, write_legacy_evidence

    plan = worker.validate()
    from north55_speech.decoder_adaptation import validate_decoder_plan
    validate_decoder_plan(plan)
    inputs = worker.read(worker.ROOT / 'inputs.json')
    refs = worker.read(worker.ROOT / 'scoring/references.json')
    joint = worker.read(worker.ROOT / 'scoring/joint.json')
    results, counts = {}, {}
    for step in worker.STEPS:
        step_counts, failures = {}, {}
        for stage in ('fit', 'transfer'):
            parent_counts, candidate_counts, failed = worker.scored(stage, step)
            failures[stage] = failed
            for item in inputs[stage]:
                key = item['id']
                prediction = worker.read(worker.ROOT / f'{stage}-{step}/predictions' / (key + '.json'))
                historical = joint[key]
                if historical['runtime_failure'] is not None or historical['effective_options'] != prediction['effective_options']:
                    raise ValueError('Historical joint model runtime/options differ')
                if not same_waveform(item, historical, prediction['effective_waveform_sha256']):
                    raise ValueError('Historical joint waveform differs')
                step_counts[key] = {'parent': parent_counts[key], 'candidate': candidate_counts[key],
                    'joint240': edit_counts(refs[item['reference_id']], historical['hypothesis'])}
        groups = {'nus_training_fit': inputs['fit']}
        groups.update({c: [i for i in inputs['transfer'] if i['cohort'] == c] for c in {i['cohort'] for i in inputs['transfer']}})
        cohorts = {}
        for cohort, items in sorted(groups.items()):
            scores = {system: corpus_counts([step_counts[i['id']][system] for i in items])
                      for system in ('parent', 'joint240', 'candidate')}
            entry = {'samples': len(items), 'groups': len({i['group_id'] for i in items}), 'scores': scores}
            comparisons = {}
            for base in ('parent', 'joint240'):
                a, b = scores[base]['wer_lexical_corpus'], scores['candidate']['wer_lexical_corpus']
                comparison = {'wer_delta': b-a if a is not None and b is not None else None,
                    'relative_reduction': (a-b)/a if a else None}
                if cohort not in ('nus_training_fit', 'noise_only', 'bleriot_b_noise'):
                    comparison['bootstrap'] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                        'baseline': step_counts[i['id']][base], 'candidate': step_counts[i['id']]['candidate']} for i in items],
                        resamples=2000, seed=55, confidence=.95)
                    comparison['independent_confirmation'] = False
                comparisons['candidate_vs_' + base] = comparison
            entry['comparisons'] = comparisons
            if cohort in ('noise_only', 'bleriot_b_noise'):
                minutes = sum(i['duration_sec'] for i in items) / 60
                entry.update(minutes=minutes, inserted_words_per_minute={s: v['I']/minutes for s, v in scores.items()})
            cohorts[cohort] = entry
        human = cohorts['partial_human_dev']['comparisons']['candidate_vs_parent']
        checks = {'human_dev_point': human['relative_reduction'] >= .10,
            'human_dev_CI': human['bootstrap']['upper'] < 0,
            'clean_EN': cohorts['general_clean']['comparisons']['candidate_vs_parent']['wer_delta'] <= .01,
            'general_RU': cohorts['general_ru']['comparisons']['candidate_vs_parent']['wer_delta'] <= .01,
            'noise': all(cohorts[c]['inserted_words_per_minute']['candidate'] <= cohorts[c]['inserted_words_per_minute']['parent']
                         for c in ('noise_only', 'bleriot_b_noise')), 'runtime': not any(failures.values())}
        results[str(step)] = {'cohorts': cohorts, 'checks': checks, 'failures': failures,
            'release': 'FAIL' if not all(checks[k] for k in ('human_dev_point', 'clean_EN', 'general_RU', 'noise', 'runtime')) else 'NEEDS_MORE_DATA'}
        counts[str(step)] = step_counts
    comparison = {'plan_sha256': worker.file_hash(worker.ROOT / 'plan.json'), 'checkpoints': results,
        'fixed_final_step': 1200, 'release': results['1200']['release'], 'independent_quality': 'NEEDS_MORE_DATA',
        'quality_evidence': False, 'test_accessed': False, 'release_promoted': False}
    worker.save_new(worker.ROOT / 'comparison.json', comparison)
    worker.save_new(worker.ROOT / 'scored-counts.json', counts)
    write_legacy_evidence(worker.ROOT / 'legacy-waveform-evidence.json')
    print(worker.json.dumps({'release': comparison['release'], 'checkpoints': {s: {
        'WER': {c: {k: v['wer_lexical_corpus'] for k, v in e['scores'].items()} for c, e in r['cohorts'].items()},
        'checks': r['checks']} for s, r in results.items()}}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['train', 'convert', 'fit', 'transfer', 'cpu', 'score-transfer'])
    parser.add_argument('step', nargs='?', type=int, choices=[240, 1200])
    args = parser.parse_args()
    if args.stage in ('fit', 'transfer', 'cpu'):
        if args.step is None:
            parser.error('step is required')
        worker.infer('fit' if args.stage == 'cpu' else args.stage, args.step, cpu=args.stage == 'cpu')
    else:
        {'train': train, 'convert': worker.convert, 'score-transfer': score}[args.stage]()
