"""Audit prepared pairs, immutable inputs and real no-network execution artifacts."""

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, digest, file_hash, settings
from north55_speech.datasets import decoded_audio_hash, load_manifest, validate_groups
from north55_speech.training import check_training_partitions
from scripts.prepare_quality_pairs import agreement_reasons, options

ROOT = Path('/pairs')
REPORT = Path('/study')


def read(path):
    return json.loads(path.read_bytes())


def main():
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)

    plan = read(ROOT / 'plan.json')
    preparation = read(ROOT / 'preparation-report.json')
    check('executed_assembler_hash', file_hash(Path('/app/scripts/assemble_quality_pairs.py')) == preparation['assembler_sha256'])
    check('675_planned_train_windows', len(plan['items']) == 675)
    check('frozen_protocol', file_hash(REPORT / 'protocol.md') == plan['protocol_sha256'])
    check('frozen_source_snapshot', all(file_hash(REPORT / 'frozen' / name) == sha for name, sha in plan['code_sha256'].items()))
    check('no_new_dev_configurations', plan['dev_search_budget']['new_configurations'] == 0
          and plan['dev_search_budget']['previous_used'] == plan['dev_search_budget']['limit'] == 16)
    check('training_comparison_honestly_blocked', preparation['training_comparison'] == 'BLOCKED_SEARCH_BUDGET_EXHAUSTED')
    sources = read(ROOT / 'sources.json')
    check('only_nine_clean_train_originals', len(sources) == 9 and all(s['split'] == 'train' and s['variant_of'] is None for s in sources.values()))
    check('source_audio_unchanged', all(file_hash(settings.audio_root / s['audio_path']) == s['audio_sha256'] for s in sources.values()))
    check('every_prepared_clip_hash', all(file_hash(settings.audio_root / i['audio_path']) == i['audio_sha256'] for i in plan['items']))
    timelines = {}
    for item in plan['items']:
        timelines.setdefault(item['source'], []).append(item)
    check('original_timeline_and_nonoverlap', all(
        all(0 <= r['start_sample'] < r['end_sample'] and r['duration_sec'] == (r['end_sample']-r['start_sample'])/16000
            and r['original_start_sec'] == r['start_sample']/16000 and r['original_end_sec'] == r['end_sample']/16000 for r in rows)
        and all(a['end_sample'] <= b['start_sample'] for a, b in zip(rows, rows[1:], strict=False)) for rows in timelines.values()))
    lookup = {}
    for system in ('small', 'large'):
        execution = read(ROOT / system / 'execution.json')
        check(f'{system}_all_records_hashed', len(execution['prediction_sha256']) == 675
              and all(file_hash(ROOT / system / 'predictions' / name) == sha for name, sha in execution['prediction_sha256'].items()))
        for item in plan['items']:
            record = read(ROOT / system / 'predictions' / f'{item["id"]}.json')
            expected = digest({'item': item, 'plan': file_hash(ROOT / 'plan.json'), 'system': system, 'options': options(system)})
            if record['request_sha256'] != expected:
                raise ValueError('Request identity mismatch')
            lookup[system, item['id']] = record
        check(f'{system}_no_ASR_failures', all(lookup[system, i['id']]['error'] is None for i in plan['items']))
        snapshot = read(REPORT / f'north55-quality-pairs-{system}-v1.json')
        check(f'{system}_network_none_exit_zero', snapshot['network_mode'] == 'none' and snapshot['state']['ExitCode'] == 0)
        check(f'{system}_no_reference_or_test_mount', all(m['Destination'] not in {'/old', '/source-train.jsonl', '/pairs/documents.json'}
              and 'test' not in m['Destination'].lower().replace('/app/tests', '') for m in snapshot['mounts']))
    train = load_manifest(ROOT / 'training/train.jsonl')
    dev = load_manifest(ROOT / 'training/dev.jsonl')
    if train:
        check_training_partitions(train, dev)
        validate_groups(train)
    check('unchanged_dev_manifest_bytes', (ROOT / 'training/dev.jsonl').read_bytes() == Path('/old/training/dev.jsonl').read_bytes())
    check('train_count_matches_report', len(train) == preparation['accepted_train_pairs'])
    check('no_fabricated_human_or_event_labels', all(s.transcript_status == 'weak' and not s.scope_verified and not s.primary
          and s.labels is None and s.critical_entities is None and s.events is None and s.salient_for_review is None for s in train))
    check('all_accepted_three_way_agree', all(not agreement_reasons(lookup['small', s.sample_id], lookup['large', s.sample_id], s.reference_text, s.duration_sec) for s in train))
    check('all_accepted_original_alignment_pass', all(read(ROOT / 'proposals' / f'{s.sample_id}.json')['eligible_for_exploratory_training'] for s in train))
    check('all_accepted_audio_decoded_hashes', all(decoded_audio_hash([settings.audio_root / s.audio_path]) == s.decoded_audio_sha256 for s in train))
    check('all_rejections_preserved', len(preparation['items']) == len(plan['items'])
          and Counter(r for i in preparation['items'] for r in i['reasons']) == preparation['rejection_reasons'])
    support = load_manifest(Path('/prepared/train.jsonl'))
    support_report = read(Path('/prepared/report.json'))
    check('executed_support_importer_hash', file_hash(Path('/app/scripts/import_training_support.py')) == support_report['script_sha256'])
    check('400_source_labelled_train_pairs', len(support) == 400 and Counter(s.language for s in support) == {'en': 200, 'ru': 200})
    check('support_manifest_hash', file_hash(Path('/prepared/train.jsonl')) == support_report['manifest_sha256'])
    check('support_no_local_review_or_cabin_claim', all(s.split == 'train' and not s.primary and not s.clean_control
          and not s.annotation_provenance['local_manual_verification'] and s.license_id == 'CC-BY-4.0' for s in support))
    validate_groups(support)
    check('support_audio_and_decoded_hashes', all(file_hash(settings.audio_root / s.audio_path) == s.audio_sha256
          and decoded_audio_hash([settings.audio_root / s.audio_path]) == s.decoded_audio_sha256 for s in support))
    # Compare raw decoded waveform hashes against every existing diagnostic input;
    # do not load diagnostic transcripts or use them for selection.
    controls = read(Path('/diagnostic-inputs.json'))
    seen = set()
    for item in controls:
        audio, rate = sf.read(settings.audio_root / item['audio_path'], dtype='float32')
        if rate != 16000 or audio.ndim != 1:
            raise ValueError('Unexpected diagnostic audio format')
        seen.add(hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest())
    check('no_support_waveform_duplicates_in_existing_diagnostics', all(
        hashlib.sha256(sf.read(settings.audio_root / s.audio_path, dtype='float32')[0].astype('<f4').tobytes()).hexdigest() not in seen for s in support))
    check('support_finite_nonempty_audio', all(np.isfinite(sf.read(settings.audio_root / s.audio_path, dtype='float32')[0]).all() for s in support))
    tests = ET.parse(REPORT / 'contracts-v3.xml').getroot()
    suites = list(tests.iter('testsuite'))
    check('38_contract_tests_passed', sum(int(s.get('tests', 0)) for s in suites) == 38
          and all(int(s.get('failures', 0)) == int(s.get('errors', 0)) == 0 for s in suites))
    preservation = read(REPORT / 'preservation-before.json')['files']
    changed = [name for name, sha in preservation.items() if file_hash(Path('/workspace') / name) != sha]
    check('809_previous_files_unchanged', len(preservation) == 809 and not changed)
    check('primary_quality_and_release_not_claimed', preparation['quality_gate'] == 'NEEDS_MORE_DATA'
          and not preparation['release_promoted'] and preparation['true_pair_accuracy'] is None)
    result = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
              'accepted_machine_pairs': len(train), 'accepted_pair_checks_applicable': bool(train),
              'changed_old_files': changed, 'accepted_pair_accuracy': 'UNKNOWN_WITHOUT_INDEPENDENT_REFERENCE',
              'quality_gate': 'NEEDS_MORE_DATA', 'training_comparison': preparation['training_comparison'],
              'test_accessed': False, 'release_promoted': False}
    result['hashes'] = {'preparation_report': file_hash(REPORT / 'preparation-report.json'),
                        'support_report': file_hash(REPORT / 'training-support.json'),
                        'cockpit_train_manifest': file_hash(ROOT / 'training/train.jsonl'),
                        'general_train_manifest': file_hash(Path('/prepared/train.jsonl'))}
    atomic_json(REPORT / 'verification.json', result)
    print(json.dumps(result, indent=2))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
