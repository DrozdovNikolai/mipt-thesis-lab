"""Generate optional ASR assistance without creating human annotation revisions."""

import argparse
import json
import time
from pathlib import Path

import soundfile as sf

from north55_speech.asr import AsrProvider
from north55_speech.core import atomic_json, confined, digest, file_hash, now, settings
from north55_speech.datasets import load_manifest
from north55_speech.schemas import PipelineConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--split', choices=['train', 'dev'], required=True)
    parser.add_argument('--allow-control-drafts', action='store_true')
    args = parser.parse_args()
    manifest = args.packet / f'{args.split}.jsonl'
    manifest_hash = file_hash(manifest)
    samples = load_manifest(manifest)
    if any(s.split != args.split for s in samples):
        raise ValueError('Packet split mismatch')
    controls = [s.sample_id for s in samples if s.annotation_provenance.get('draft_available') is False]
    if controls and not args.allow_control_drafts:
        raise ValueError('Explicit authorization required to offer drafts on control clips')
    config = PipelineConfig(model='whisper-large-v3-systran-ct2', device='cuda',
                            compute_type='float16', condition_on_previous_text=False)
    provider = AsrProvider(config)
    started = time.perf_counter()
    hashes = {}
    for index, sample in enumerate(samples):
        directory = 'assisted-drafts' if sample.sample_id in controls else 'drafts'
        path = args.packet / directory / f'{sample.sample_id}.json'
        identity = {'sample_id': sample.sample_id, 'audio_sha256': sample.audio_sha256,
                    'model': config.model, 'model_manifest_sha256': digest(provider.manifest),
                    'config_hash': config.config_hash, 'language_mode': 'auto'}
        if path.exists():
            previous = json.loads(path.read_text(encoding='utf-8'))
            if any(previous.get(k) != v for k, v in identity.items()):
                raise ValueError('Preserve existing differing draft: ' + sample.sample_id)
        else:
            audio_path = confined(settings.audio_root, sample.audio_path)
            if file_hash(audio_path) != sample.audio_sha256:
                raise ValueError('Audio changed')
            audio, rate = sf.read(audio_path, dtype='float32')
            if rate != 16000 or audio.ndim != 1 or abs(len(audio)/rate-sample.duration_sec) > .001:
                raise ValueError('Expected original 16 kHz mono clip')
            segments = provider.transcribe(audio, 0, 'auto', sample.sample_id, lambda: None)
            atomic_json(path, {**identity, 'text': ' '.join(s.raw_asr_text.strip() for s in segments),
                              'segments': [s.model_dump(mode='json') for s in segments],
                              'created_at': now(), 'status': 'machine', 'human_verified': False})
        hashes[sample.sample_id] = file_hash(path)
        print(json.dumps({'ready': index+1, 'total': len(samples)}), flush=True)
    if file_hash(manifest) != manifest_hash:
        raise ValueError('Manifest changed during preparation')
    policy = {'version': 1, 'enabled_sample_ids': controls,
              'manifest_sha256': {f'{args.split}.jsonl': manifest_hash},
              'draft_sha256': hashes, 'requested_by': 'user',
              'reason': 'User requested machine drafts for manual listening and correction',
              'evaluation_note': 'Revealed drafts require assisted-reference reporting, not blind-reference claims'}
    policy_path = args.packet / 'draft-policy.json'
    if policy_path.exists() and json.loads(policy_path.read_text(encoding='utf-8')) != policy:
        raise ValueError('Preserve differing draft policy')
    atomic_json(policy_path, policy)
    atomic_json(args.packet / 'draft-generation.json', {
        'model': config.model, 'ready': len(hashes), 'seconds': time.perf_counter()-started,
        'generated_at': now(), 'manifest_sha256': manifest_hash, 'policy_sha256': file_hash(policy_path),
        'human_labels_created': 0, 'test_accessed': False, 'purpose': 'annotation_assistance'})


if __name__ == '__main__':
    main()
