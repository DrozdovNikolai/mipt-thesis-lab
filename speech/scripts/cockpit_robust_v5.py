"""Frozen balanced acoustic/silence experiment; all previous runs are read-only."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from north55_speech.core import file_hash
from north55_speech.robust_adaptation import ARMS, TRAINING
from scripts import nus_convergence as worker
from scripts import publisher_training_v3 as evaluation

ROOT, EXP = Path('/study'), Path('/experiment')
read, save_new = worker.read, worker.save_new


def validate():
    p = worker.validate()
    if p['training'] != TRAINING or file_hash(ROOT/'schedule.json') != p['schedule_sha256']:
        raise ValueError('Frozen training recipe changed')
    return p


def pcm(x):
    return hashlib.sha256(x.astype('<f4').tobytes()).hexdigest()


def load_audio(item):
    import soundfile as sf

    from scripts.decoding_diagnostics import load_audio as original_loader
    if not item.get('synthetic_v5'):
        return original_loader(item)
    path = (EXP / 'eval-audio' / (item['id']+'.wav')).resolve()
    if not path.is_relative_to(EXP / 'eval-audio') or file_hash(path) != item['audio_sha256']:
        raise ValueError('Synthetic evaluation waveform changed')
    x, rate = sf.read(path, dtype='float32')
    if rate != 16000 or x.ndim != 1 or pcm(x) != item['effective_waveform_sha256']:
        raise ValueError('Synthetic evaluation signal differs')
    return x


def train():
    import librosa
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, set_seed
    from transformers.modeling_outputs import BaseModelOutput

    from north55_speech.datasets import load_manifest
    from north55_speech.decoder_adaptation import tensor_hashes, verify_trainable_decoder
    from north55_speech.hard_adaptation import targets, validate_population
    from north55_speech.robust_adaptation import augment_waveform, mask_features, negative_waveform

    plan = validate()
    for split in ('train', 'dev'):
        if file_hash(Path('/train')/(split+'.jsonl')) != plan[split+'_sha256']:
            raise ValueError('Training partition changed')
    samples, dev = (load_manifest(Path('/train')/(s+'.jsonl')) for s in ('train', 'dev'))
    validate_population(samples, dev)
    if [s.sample_id for s in samples] != plan['selected_ids']:
        raise ValueError('Unexpected training population')
    schedule = read(ROOT/'schedule.json')
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1 or not torch.cuda.is_bf16_supported():
        raise ValueError('Require one BF16-capable GPU')
    base, destination = Path('/models/whisper-small-transformers'), EXP/'training'
    worker.verify_files(base, plan['base_manifest']['files'])
    if destination.exists():
        raise ValueError('Preserve previous training')
    destination.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    set_seed(55)
    processor = WhisperProcessor.from_pretrained(base, local_files_only=True)
    processor.tokenizer.set_prefix_tokens(language='en', task='transcribe')
    original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True).cuda().eval()
    encoder_before, base_before = tensor_hashes(original.model.encoder), tensor_hashes(original)
    sot, eos = original.config.decoder_start_token_id, processor.tokenizer.eos_token_id
    nonspeech = processor.tokenizer.convert_tokens_to_ids('<|nocaptions|>')
    from faster_whisper.tokenizer import Tokenizer
    backend = Tokenizer(processor.tokenizer.backend_tokenizer, True, task='transcribe', language='en')
    if nonspeech != backend.no_speech or nonspeech in (sot, eos):
        raise ValueError('Wrong nonspeech target token')
    waves, labels, cache, contracts = {}, {}, {}, []
    for sample in samples:
        path = (Path('/audio')/sample.audio_path).resolve()
        if not path.is_relative_to(Path('/audio')) or file_hash(path) != sample.audio_sha256:
            raise ValueError('Training source audio changed')
        x, _ = librosa.load(path, sr=16000, mono=False)
        if x.ndim == 2:
            x = x[sample.channel]
        elif sample.channel != 0:
            raise ValueError('Invalid channel')
        tokens = processor.tokenizer(sample.reference_text).input_ids
        if not sample.reference_text or tokens[0] != sot or len(tokens) > 448:
            raise ValueError('Invalid weak speech target')
        waves[sample.sample_id] = x
        labels[sample.sample_id] = torch.tensor([tokens[1:]], dtype=torch.long)
    negative_labels = torch.tensor([[nonspeech, eos]], dtype=torch.long)

    def encode(key, x, target, meta, mask_seed=None, encoder_model=original):
        features = processor.feature_extractor(x, sampling_rate=16000, return_tensors='pt').input_features
        if mask_seed is not None:
            features, masking = mask_features(features, len(x), mask_seed)
            meta = meta | {'specaugment': masking}
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
            states = encoder_model.model.encoder(features.cuda()).last_hidden_state.cpu()
        cache[key] = (states, target)
        contracts.append({'key': key, 'audio_samples': len(x), 'waveform_sha256': pcm(x),
            'encoder_state_sha256': hashlib.sha256(states.view(torch.uint8).numpy().tobytes()).hexdigest(),
            'label_sha256': hashlib.sha256(target.numpy().tobytes()).hexdigest(), 'metadata': meta})
        if len(contracts) % 100 == 0:
            print('Encoded scheduled input', len(contracts), flush=True)

    started = time.perf_counter()
    for key, x in waves.items():
        encode(key, x, labels[key], {'original_train_parent': key})
    balanced_keys = []
    for index, entry in enumerate(schedule['balanced']):
        parent = entry['parent']
        key = parent
        if entry['augmented']:
            key = 'aug-'+str(index)
            x, meta = augment_waveform(waves[parent], entry['seed'])
            encode(key, x, labels[parent], meta | {'original_train_parent': parent}, entry['seed']+23)
        balanced_keys.append(key)
    negatives = []
    for entry in schedule['negative']:
        key = 'negative-'+str(entry['index'])
        x, meta = negative_waveform(**entry)
        encode(key, x, negative_labels, meta)
        negatives.append(key)
    if len(contracts) != 907 or len(negatives) != 240:
        raise ValueError('Missing scheduled acoustic variants or nonspeech examples')
    cache_seconds = time.perf_counter()-started
    save_new(Path('/output/audio-contracts.json'), contracts)
    del encode, original, waves, labels, x
    gc.collect()
    torch.cuda.empty_cache()
    # Same full adapter construction as v4, then copy only the common decoder tensors.
    set_seed(55)
    initial_base = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
    initial_model = get_peft_model(initial_base, LoraConfig(r=8, lora_alpha=16,
        target_modules=targets(initial_base, True), lora_dropout=.05, bias='none'))
    shared = {n: p.detach().clone() for n, p in initial_model.named_parameters() if p.requires_grad and '.decoder.' in n}
    del initial_model, initial_base
    gc.collect()
    arms, checkpoints = {}, {}
    for arm, options in ARMS.items():
        set_seed(55)
        base_model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        base_model.config.use_cache = False
        model = get_peft_model(base_model, LoraConfig(r=8, lora_alpha=16,
            target_modules=targets(base_model, False), lora_dropout=.05, bias='none')).cuda()
        verify_trainable_decoder(model)
        with torch.no_grad():
            for name, p in model.named_parameters():
                if p.requires_grad:
                    p.copy_(shared[name].to(p.device))
        initial_hash = hashlib.sha256(b''.join(p.detach().cpu().numpy().tobytes()
            for p in model.parameters() if p.requires_grad)).hexdigest()
        set_seed(55)
        params = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(params, lr=2e-5, weight_decay=0., fused=True)
        optimizer.zero_grad(set_to_none=True)
        keys = balanced_keys if options['balanced'] else [e['parent'] for e in schedule['uniform']]
        speech_hash = hashlib.sha256('\n'.join(keys).encode()).hexdigest()
        seen, logs = Counter(), []
        speech_sum = negative_sum = 0.
        started = time.perf_counter()
        model.train()

        def loss_for(key, current_model=model):
            states, target = cache[key]
            with torch.autocast('cuda', dtype=torch.bfloat16):
                loss = current_model(encoder_outputs=BaseModelOutput(last_hidden_state=states.cuda()), labels=target.cuda()).loss
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite loss; no skipped updates allowed')
            return loss

        for update in range(240):
            for key in keys[4*update:4*update+4]:
                loss = loss_for(key)
                (loss/4).backward()
                speech_sum += float(loss.detach())
                seen[key] += 1
            if options['negative_weight']:
                # Nonspeech dropout must not change the matched speech dropout stream.
                with torch.random.fork_rng(devices=[0]):
                    loss = loss_for(negatives[update])
                    (options['negative_weight']*loss).backward()
                    negative_sum += float(loss.detach())
                    seen[negatives[update]] += 1
            grad = torch.nn.utils.clip_grad_norm_(params, 1., error_if_nonfinite=True)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            if (update+1) % 20 == 0:
                log = {'updates': update+1, 'speech_ce': speech_sum/80,
                       'negative_ce': negative_sum/20, 'gradient_norm': float(grad),
                       'seconds': time.perf_counter()-started}
                print(arm, json.dumps(log), flush=True)
                logs.append(log)
                speech_sum = negative_sum = 0.
        if {int(s['step']) for s in optimizer.state.values()} != {240} or len(optimizer.state) != 96:
            raise ValueError('Real optimizer steps/tensors differ')
        verify_trainable_decoder(model)
        if tensor_hashes(model.get_base_model().model.encoder) != encoder_before:
            raise ValueError('Frozen encoder changed')
        frozen_after = {n.replace('.base_layer.', '.'): hashlib.sha256(p.detach().cpu().contiguous().numpy().tobytes()).hexdigest()
            for n, p in model.get_base_model().state_dict().items() if '.lora_' not in n}
        if frozen_after != base_before:
            raise ValueError('Original base weights changed')
        folder = destination/('checkpoint-'+arm)
        model.save_pretrained(folder, safe_serialization=True)
        torch.save(optimizer.state_dict(), folder/'optimizer.pt')
        torch.save({'cpu': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state()}, folder/'rng.pt')
        checkpoints[arm] = {p.name: file_hash(p) for p in folder.iterdir() if p.is_file()}
        arms[arm] = {'actual_updates': 240, 'optimizer_tensors': 96, 'initial_adapter_sha256': initial_hash,
            'speech_schedule_sha256': speech_hash, 'speech_presentations': 960,
            'negative_presentations': 240 if options['negative_weight'] else 0,
            'coverage': dict(seen), 'history': logs, 'encoder_unchanged': True, 'frozen_base_unchanged': True}
        save_new(destination/('arm-'+arm+'.json'), arms[arm])
        del loss_for, model, base_model, optimizer, params, loss
        gc.collect()
        torch.cuda.empty_cache()
    if len({a['initial_adapter_sha256'] for a in arms.values()}) != 1:
        raise ValueError('Initial decoder adapters differ')
    if arms['balanced']['speech_schedule_sha256'] != arms['balanced-silence']['speech_schedule_sha256']:
        raise ValueError('Balanced speech order differs')
    save_new(Path('/output/training.json'), {'plan_sha256': file_hash(ROOT/'plan.json'), 'arms': arms,
        'checkpoints': checkpoints, 'encoder_before': encoder_before, 'frozen_base_before': base_before,
        'audio_contracts_sha256': file_hash(Path('/output/audio-contracts.json')), 'cache_seconds': cache_seconds,
        'nonspeech_labels': [nonspeech, eos], 'decoder_start_token_id': sot,
        'training_precision': 'bfloat16', 'GPU': torch.cuda.get_device_name(0), 'quality_evidence': False})


def convert():
    from scripts import cockpit_training_v4 as conversion
    conversion.ARMS, conversion.validate = ARMS, validate
    conversion.convert()


def infer(stage):
    from scripts import decoding_diagnostics
    original = decoding_diagnostics.load_audio
    # Bind legacy loader separately to avoid recursion for existing inputs.
    def selected_loader(item):
        return load_audio(item) if item.get('synthetic_v5') else original(item)
    decoding_diagnostics.load_audio = selected_loader
    evaluation.validate = validate
    if stage == 'baseline':
        plan = validate()
        old_execution = read(Path('/prior/io-baseline/execution.json'))
        if old_execution['plan_sha256'] != plan['prior_plan_sha256'] or file_hash(Path('/prior/plan.json')) != plan['prior_plan_sha256']:
            raise ValueError('Historical execution identity differs')
        for item in read(ROOT/'inputs.json'):
            if item.get('synthetic_v5'):
                continue
            source = Path('/prior/io-baseline/predictions')/(item['id']+'.json')
            target = Path('/output/predictions')/source.name
            if target.exists():
                continue
            if file_hash(source) != old_execution['prediction_sha256'][source.name]:
                raise ValueError('Reuse source changed')
            record = read(source)
            if any(record.get(k) != v for k, v in item.items()) or record['runtime_failure']:
                raise ValueError('Baseline reuse population changed')
            if pcm(original(item)) != record['effective_waveform_sha256']:
                raise ValueError('Baseline reuse waveform differs')
            if record['model_manifest_sha256'] != plan['baseline_model']['manifest_sha256']:
                raise ValueError('Baseline reuse model differs')
            record.update(plan_sha256=file_hash(ROOT/'plan.json'), reused_from_plan=record['plan_sha256'],
                          reused_from_sha256=file_hash(source))
            save_new(target, record)
    evaluation.infer(stage)


def vad():
    from north55_speech.audio import VadProvider
    from north55_speech.schemas import VadConfig
    validate()
    rows = []
    provider = VadProvider()
    for item in read(ROOT/'inputs.json'):
        x = load_audio(item)
        intervals = provider.intervals(x, VadConfig(enabled=True, mode='gate'))
        rows.append({'id': item['id'], 'pcm_sha256': pcm(x), 'keep': bool(intervals)})
    save_new(Path('/output/vad.json'), {'plan_sha256': file_hash(ROOT/'plan.json'), 'rows': rows,
        'settings': VadConfig(enabled=True, mode='gate').model_dump()})
    print('VAD complete', len(rows), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['train', 'convert', 'baseline', 'candidate', 'cpu', 'vad'])
    args = parser.parse_args()
    if args.stage in ('baseline', 'candidate', 'cpu'):
        infer(args.stage)
    else:
        {'train': train, 'convert': convert, 'vad': vad}[args.stage]()
