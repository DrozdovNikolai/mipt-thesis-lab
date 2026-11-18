"""Assemble frozen inference with group validation on the derived population.

The original inference driver is retained byte-for-byte for resume/hash verification.
Stored group IDs from the original population cannot be reused as hashes of clips.
"""
import json
from collections import Counter
from pathlib import Path

import soundfile as sf

from north55_speech.asr import load_model
from north55_speech.core import atomic_json, digest, file_hash, settings
from north55_speech.datasets import (
    decoded_audio_hash,
    load_manifest,
    validate_groups,
    write_manifest,
)
from north55_speech.lora import validate_references
from scripts.expand_publisher_pairs import FAMILIES
from scripts.prepare_quality_pairs import (
    MODELS,
    OLD,
    POLICY,
    REPORT,
    ROOT,
    agreement_reasons,
    read,
    validate,
)
from scripts.publisher_alignment import align, locate


def checked_groups(train, dev):
    # Recompute train group hashes for these clips. Do not mutate the frozen dev rows.
    for row in train:
        row.group_id = None
    if train:
        validate_groups(train)
    combined = [row.model_copy(deep=True, update={'group_id': None}) for row in train + dev]
    return validate_groups(combined)


def assemble():
    from north55_speech.datasets import Sample

    plan = validate()
    for name, key in [('sources.json', 'sources_sha256'), ('documents.json', 'documents_file_sha256')]:
        if file_hash(ROOT / name) != plan[key]:
            raise ValueError('Frozen source metadata changed')
    sources = {k: Sample.model_validate(v) for k, v in read(ROOT / 'sources.json').items()}
    documents = read(ROOT / 'documents.json')
    executions = {s: read(ROOT / s / 'execution.json') for s in MODELS}
    for execution in executions.values():
        if execution['plan_sha256'] != file_hash(ROOT / 'plan.json') or len(execution['prediction_sha256']) != len(plan['items']):
            raise ValueError('Incomplete frozen inference population')
    model = None
    accepted, diagnostics = [], []
    for item in plan['items']:
        responses = {}
        for system in MODELS:
            path = ROOT / system / 'predictions' / f'{item["id"]}.json'
            if file_hash(path) != executions[system]['prediction_sha256'][path.name]:
                raise ValueError('Frozen prediction changed')
            responses[system] = read(path)
        small, large = responses['small'], responses['large']
        document = max((documents[f'{n}.json'] for n in FAMILIES[item['family']]),
                       key=lambda d: locate(small['hypothesis'], d)['matched_tokens'])
        proposal = locate(small['hypothesis'], document)
        reasons = agreement_reasons(small, large, proposal['text'], item['duration_sec'])
        if not reasons:
            if model is None:
                model = load_model('small', 'cuda', 'float16', digest(plan['models']['small']))
            audio_path = settings.audio_root / item['audio_path']
            if file_hash(audio_path) != item['audio_sha256']:
                raise ValueError('Alignment audio changed')
            audio, _ = sf.read(audio_path, dtype='float32')
            proposal = align(model, audio, document, small['hypothesis'], item['original_start_sec'])
            reasons += proposal['reasons']
        proposal.update(selection_method=POLICY['version'], extra_reasons=reasons, item=item)
        path = ROOT / 'proposals' / f'{item["id"]}.json'
        if path.exists() and read(path) != proposal:
            raise ValueError('Immutable proposal changed')
        atomic_json(path, proposal)
        diagnostics.append({'id': item['id'], 'source': item['source'], 'eligible': not reasons, 'reasons': reasons})
        if reasons:
            continue
        parent = sources[item['source']]
        row = parent.model_dump() | {
            'sample_id': item['id'], 'audio_path': item['audio_path'], 'audio_sha256': item['audio_sha256'],
            'decoded_audio_sha256': decoded_audio_hash([settings.audio_root / item['audio_path']]),
            'duration_sec': item['duration_sec'], 'channel': 0, 'variant_of': None,
            'original_utterance_id': f'{parent.original_utterance_id}@{item["start_sample"]}:{item["end_sample"]}',
            'language': 'en', 'reference_text': proposal['text'], 'transcript_status': 'weak',
            'scope': 'read_cockpit', 'scope_verified': False, 'primary': False, 'clean_control': False,
            'entities_status': 'missing', 'events_status': 'missing', 'temporal_status': 'missing',
            'diarization_status': 'missing', 'critical_entities': None, 'events': None,
            'labels': None, 'salient_for_review': None, 'unintelligible': [],
            'annotation_provenance': {
                'method': proposal['method'], 'selection_method': POLICY['version'],
                'publisher_transcript': True, 'reviewed_audio': False, 'annotator': None,
                'source_file': proposal['source_file'], 'source_sha256': proposal['source_sha256'],
                'alignment_sha256': file_hash(path), 'preparation_plan_sha256': file_hash(ROOT / 'plan.json'),
                'automatic_training_eligible': True, 'eligibility_reasons': [],
                'source_sample_id': parent.sample_id, 'original_start_sec': item['original_start_sec'],
                'original_end_sec': item['original_end_sec'],
                'language_basis': 'English document + small EN / large unforced consensus; not human verification'},
        }
        accepted.append(Sample.model_validate(row))
    dev_path = OLD / 'training/dev.jsonl'
    dev = load_manifest(dev_path)
    groups = checked_groups(accepted, dev)
    if accepted:
        validate_references(accepted, dev, {'reference_policy': 'publisher_weak_exploratory_v1',
                                          'quality_evidence': False, 'selection_allowed': False, 'max_steps': 40})
    write_manifest(ROOT / 'training/train.jsonl', accepted)
    target_dev = ROOT / 'training/dev.jsonl'
    if target_dev.exists() and target_dev.read_bytes() != dev_path.read_bytes():
        raise ValueError('Existing development manifest changed')
    target_dev.write_bytes(dev_path.read_bytes())
    old_train = load_manifest(OLD / 'training/train.jsonl')
    result = {'status': 'READY_WEAK_PAIRS' if accepted else 'NEEDS_MORE_DATA',
              'plan_sha256': file_hash(ROOT / 'plan.json'), 'policy': POLICY,
              'assembler_sha256': file_hash(Path(__file__)),
              'considered_train_windows': len(plan['items']), 'accepted_train_pairs': len(accepted),
              'accepted_minutes': sum(s.duration_sec for s in accepted)/60,
              'accepted_speakers': len({v for s in accepted for v in s.speaker_ids}),
              'old_train_pairs': len(old_train), 'old_train_minutes': sum(s.duration_sec for s in old_train)/60,
              'unchanged_dev_pairs': len(dev), 'dev_sha256': file_hash(target_dev), 'groups': groups,
              'rejection_reasons': dict(Counter(r for d in diagnostics for r in d['reasons'])),
              'items': diagnostics, 'asr_calls': len(plan['items'])*2,
              'asr_failures': {s: sum(read(ROOT / s / 'predictions' / f'{i["id"]}.json')['error'] is not None for i in plan['items']) for s in MODELS},
              'true_pair_accuracy': None, 'human_verified_pairs': 0, 'quality_gate': 'NEEDS_MORE_DATA',
              'training_comparison': plan['dev_search_budget']['training_comparison'],
              'test_accessed': False, 'release_promoted': False, 'limitations': plan['limitations']}
    atomic_json(ROOT / 'preparation-report.json', result)
    atomic_json(REPORT / 'preparation-report.json', {k: v for k, v in result.items() if k != 'items'})
    print(json.dumps({k: v for k, v in result.items() if k not in {'items', 'limitations', 'groups'}}, indent=2))


if __name__ == "__main__":
    assemble()
