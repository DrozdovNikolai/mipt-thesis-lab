"""Prepare and execute the single frozen, user-authorized NUS ASR experiment."""

import argparse
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from north55_speech.asr import local_model_manifest
from north55_speech.core import atomic_json, file_hash, now, settings
from north55_speech.datasets import Sample, decoded_audio_hash, load_manifest, write_manifest
from north55_speech.lora import train_asr, validate_references
from north55_speech.nus_training import GROUP, REVISION, RIGHTS, SOURCE, select_nus_rows
from scripts import decoding_diagnostics as decoder
from scripts.assemble_quality_pairs import checked_groups
from scripts.retrain_asr import EXPECTED

STUDY, DATA = Path('/study'), Path('/dataset')
MODEL = 'whisper-small-nus-v1'
SYSTEMS = ('parent', 'balanced', 'nus')


def read(path):
    return json.loads(path.read_bytes())


def identity():
    decoder.ROOT = STUDY
    return decoder.identity() | {'experiment_driver_sha256': file_hash(Path(__file__)),
        'training_implementation_sha256': file_hash(Path('/app/src/north55_speech/lora.py'))}


def prepare():
    if (STUDY / 'plan.json').exists():
        raise ValueError('Preserve the frozen study')
    for name, expected in EXPECTED.items():
        if file_hash(Path('/app') / name) != expected:
            raise ValueError('Original contract changed')
    permission = read(STUDY / 'permission.json')
    if permission['user_statement'] != 'можно можно обучать, делай' or permission['basis'] != 'explicit_user_confirmation':
        raise ValueError('Expected recorded user confirmation')
    permission_sha = file_hash(STUDY / 'permission.json')
    old = read(Path('/old/plan.json'))
    if file_hash(Path('/old/train.jsonl')) != old['train_sha256'] or file_hash(Path('/old/dev.jsonl')) != old['dev_sha256']:
        raise ValueError('Previous training data changed')
    originals, dev = load_manifest(Path('/old/train.jsonl')), load_manifest(Path('/old/dev.jsonl'))
    support = [sample.model_copy(deep=True) for sample in originals if sample.scope == 'general_control']
    if len(support) != 400 or len(dev) != 35 or len(originals) != 433:
        raise ValueError('Unexpected prior composition')
    inspection = read(Path('/source-audit/inspection-final.json'))
    acquisition_path = Path('/source-audit/acquisition.json')
    index = Path('/source/inspection-index-final.json')
    if (file_hash(index) != inspection['private_index_sha256'] or
            file_hash(acquisition_path) != inspection['acquisition_sha256']):
        raise ValueError('Inspected data identity changed')
    acquisition = read(acquisition_path)
    tables, entries = {}, {}
    for entry in acquisition['files']:
        path = Path('/source') / entry['name']
        if file_hash(path) != entry['sha256']:
            raise ValueError('Acquired Parquet changed')
        tables[entry['name']] = pq.read_table(path)
        entries[entry['name']] = entry
    chosen, excluded = select_nus_rows(read(index)['records'])
    if not chosen or len(chosen) > 302:
        raise ValueError('Unexpected deduplicated NUS population')
    items = read(Path('/old/inputs.json'))
    if len(items) != 675 or file_hash(Path('/old/inputs.json')) != old['inputs_sha256']:
        raise ValueError('Diagnostic audio population changed')
    excluded_pcm = {sample.decoded_audio_sha256 for sample in support + dev}
    for item in items:
        path = settings.audio_root / item['audio_path']
        if file_hash(path) != item['audio_sha256']:
            raise ValueError('Existing evaluation audio changed')
        excluded_pcm.add(decoded_audio_hash([path]))
    imported = []
    for row in chosen:
        source_row = tables[row['file']].slice(row['row_index'], 1).to_pylist()[0]
        if source_row['text'] != row['source_reference_text'] or source_row['id'] != row['source_id']:
            raise ValueError('Source row/index mismatch')
        payload = source_row['audio']['bytes']
        import hashlib
        if hashlib.sha256(payload).hexdigest() != row['audio_sha256']:
            raise ValueError('Embedded waveform changed')
        name = 'nus-' + row['source_id']
        path = settings.audio_root / 'nus-training-v1' / (name + '.wav')
        # IDs from the publisher cannot create arbitrary output paths.
        import re
        if not re.fullmatch(r'nus-clip\d+_\d+', name):
            raise ValueError('Unexpected source clip ID')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if file_hash(path) != row['audio_sha256']:
                raise ValueError('Preserve existing different audio')
        else:
            with path.open('xb') as stream:
                stream.write(payload)
        pcm = decoded_audio_hash([path])
        if pcm in excluded_pcm:
            raise ValueError('New source overlaps training/dev/diagnostic audio')
        excluded_pcm.add(pcm)
        imported.append(Sample(sample_id=name, audio_path=str(path.relative_to(settings.audio_root)),
            audio_sha256=file_hash(path), decoded_audio_sha256=pcm, source_dataset=SOURCE,
            source_version=REVISION, recording_id=GROUP, session_id=GROUP,
            original_utterance_id=name, speaker_ids=[], language='en', input_language='en',
            scope='unknown', scope_verified=False, speech_origin='recorded_human',
            duration_sec=row['duration_sec'], license_id=RIGHTS, rights_confirmed=True,
            transcript_status='weak', reference_text=source_row['text'], split='train',
            primary=False, clean_control=False,
            provenance='https://github.com/wangyubo013-blip/CDE4301-VR-401-Final-Report/tree/'+REVISION,
            annotation_provenance={'method': 'nus_source_reference_import_v1',
                'source_row_id': row['row_id'], 'source_parquet_sha256': entries[row['file']]['sha256'],
                'acquisition_sha256': file_hash(acquisition_path), 'private_index_sha256': file_hash(index),
                'permission_evidence_sha256': permission_sha, 'rights_basis': 'explicit_user_confirmation',
                'public_license_found': False, 'reviewed_audio': False,
                'source_interval_known': False, 'source_start_sec': None, 'source_end_sec': None,
                'source_reference_conflict': False, 'radio_text_indicator': False,
                'scope_screening': 'conservative_text_indicator_only_not_audio_verification',
                'language_verified': False, 'source_report_claims_human_recording': True,
                'independent_speaker_session_ids_known': False}))
    train = support + imported
    groups = checked_groups(train, dev)
    checked_groups([sample.model_copy(deep=True) for sample in train], load_manifest(Path('/old/reviewed-dev.jsonl')))
    config = old['config'] | {'output': MODEL, 'reference_policy': 'nus_sources_exploratory_v1',
        'max_steps': 240, 'eval_steps': 240, 'learning_rate': 0.00005,
        'permission_evidence_sha256': permission_sha}
    validate_references(train, dev, config)
    for sample in train + dev:
        path = settings.audio_root / sample.audio_path
        if file_hash(path) != sample.audio_sha256 or decoded_audio_hash([path]) != sample.decoded_audio_sha256:
            raise ValueError('Training audio contract changed')
    DATA.mkdir(exist_ok=True)
    write_manifest(DATA / 'train.jsonl', train)
    (DATA / 'dev.jsonl').write_bytes(Path('/old/dev.jsonl').read_bytes())
    (STUDY / 'inputs.json').write_bytes(Path('/old/inputs.json').read_bytes())
    atomic_json(STUDY / 'exclusions.json', excluded)
    report = {'NUS_unique_before_filter': 313, 'NUS_selected': len(imported),
        'NUS_minutes': sum(sample.duration_sec for sample in imported)/60,
        'excluded_unique': len(excluded),
        'exclusion_reason_counts': dict(Counter(reason for row in excluded for reason in row['reasons'])),
        'pairs': len(train), 'minutes': sum(sample.duration_sec for sample in train)/60,
        'general_EN': sum(sample.language == 'en' for sample in support),
        'general_RU': sum(sample.language == 'ru' for sample in support),
        'prior_weak_train_removed': 33, 'known_EN_support_speakers': len({v for s in support if s.language == 'en' for v in s.speaker_ids}),
        'NUS_conservative_groups': 1, 'NUS_human_verified': 0, 'dev_count': len(dev),
        'groups': groups, 'test_accessed': False, 'audio_scope_verified': False}
    atomic_json(STUDY / 'preparation.json', report)
    atomic_json(STUDY / 'plan.json', {**identity(), 'frozen_at': now().isoformat(), 'config': config,
        'train_sha256': file_hash(DATA / 'train.jsonl'), 'dev_sha256': file_hash(DATA / 'dev.jsonl'),
        'inputs_sha256': file_hash(STUDY / 'inputs.json'), 'references_sha256': old['references_sha256'],
        'base_manifest': old['base_manifest'], 'inference_template': old['inference_template'],
        'preparation_sha256': file_hash(STUDY / 'preparation.json'), 'data': report,
        'permission_sha256': permission_sha, 'previous_training_plan_sha256': file_hash(Path('/old/plan.json')),
        'budget': {'new_training_arms': 1, 'steps': 240, 'seed': 55},
        'selection_allowed': False, 'quality_evidence': False, 'release_promoted': False})
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def validate_training():
    plan = read(STUDY / 'plan.json')
    if any(plan[key] != value for key, value in identity().items()):
        raise ValueError('Frozen code or contract changed')
    for filename, key in [('train.jsonl', 'train_sha256'), ('dev.jsonl', 'dev_sha256')]:
        if file_hash(DATA / filename) != plan[key]:
            raise ValueError('Frozen training manifest changed')
    if file_hash(STUDY / 'permission.json') != plan['permission_sha256']:
        raise ValueError('Source permission evidence changed')
    return plan


def train():
    plan = validate_training()
    result = train_asr(plan['config'])
    atomic_json(STUDY / 'training.json', result)
    coverage = result['training_coverage']
    if coverage['unique_samples_loaded'] != plan['data']['pairs'] or coverage['global_optimizer_steps'] != 240:
        raise ValueError('Incomplete declared training')
    print(json.dumps({'coverage': {k: v for k, v in coverage.items() if k != 'sample_load_counts'},
                      'loss': result['train_metrics'], 'converted_inference': result['converted_inference']}), flush=True)


def freeze_eval():
    plan, trained = validate_training(), read(STUDY / 'training.json')
    output = STUDY / 'evaluation'
    if (output / 'plan.json').exists():
        raise ValueError('Evaluation already frozen')
    names = {'parent': 'whisper-small-publisher-base-ct2',
             'balanced': 'whisper-small-balanced-v1-ct2', 'nus': MODEL+'-ct2'}
    models = {system: {'name': name, 'manifest': local_model_manifest(name),
              'manifest_sha256': file_hash(settings.model_root / name / 'manifest.json')} for system, name in names.items()}
    if trained['converted_model'] != models['nus']['manifest'] or trained['config'] != plan['config']:
        raise ValueError('Saved checkpoint identity differs')
    previous = read(Path('/previous-eval/plan.json'))
    for system in ('parent', 'balanced'):
        if models[system] != previous['models'][system]:
            raise ValueError('Historical checkpoint changed')
    parent = Path('/previous-eval/historical/parent.json')
    if file_hash(parent) != previous['historical_sha256']['parent']:
        raise ValueError('Historical parent answers changed')
    items = read(STUDY / 'inputs.json')
    if file_hash(STUDY / 'inputs.json') != previous['inputs_sha256']:
        raise ValueError('Historical input population differs')
    records = read(parent)
    atomic_json(output / 'historical/parent.json', records)
    execution = read(Path('/previous-eval/balanced/execution.json'))
    if execution['plan_sha256'] != file_hash(Path('/previous-eval/plan.json')):
        raise ValueError('Historical execution plan differs')
    records = {}
    for item in items:
        path = Path('/previous-eval/balanced/predictions') / (item['id']+'.json')
        if file_hash(path) != execution['prediction_sha256'][path.name]:
            raise ValueError('Historical balanced response changed')
        records[item['id']] = read(path)
    atomic_json(output / 'historical/balanced.json', records)
    (output / 'inputs.json').write_bytes((STUDY / 'inputs.json').read_bytes())
    (output / 'protocol.md').write_bytes((STUDY / 'protocol.md').read_bytes())
    atomic_json(output / 'plan.json', {**identity(), 'frozen_at': now().isoformat(),
        'models': models, 'systems': list(SYSTEMS),
        'configs': {system: plan['inference_template'] | {'model': name} for system, name in names.items()},
        'options_overrides': {system: {'without_timestamps': False} for system in SYSTEMS},
        'inputs_sha256': plan['inputs_sha256'], 'references_sha256': plan['references_sha256'],
        'training_plan_sha256': file_hash(STUDY / 'plan.json'),
        'historical_sha256': {s: file_hash(output / 'historical' / (s+'.json')) for s in ('parent', 'balanced')},
        'test_accessed': False, 'release_promoted': False})
    print('Frozen evaluation: 675 new predictions, 1350 historical reference responses', flush=True)


def infer(cpu=False):
    decoder.ROOT = Path('/eval')
    plan = decoder.validate()
    if plan['experiment_driver_sha256'] != file_hash(Path(__file__)):
        raise ValueError('Frozen experiment driver changed')
    decoder.infer('nus', cpu=cpu)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'train', 'freeze-eval', 'infer', 'cpu'))
    stage = parser.parse_args().stage
    {'prepare': prepare, 'train': train, 'freeze-eval': freeze_eval,
     'infer': infer, 'cpu': lambda: infer(cpu=True)}[stage]()
