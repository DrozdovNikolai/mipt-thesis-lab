"""Import human source-native CVR safety-voice labels, with sealed case holdout.

No project event, salience, entity or temporal labels are synthesized. This source
is text-only and cannot establish ASR quality or continuous event detection.
"""

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path


def partition(case):
    value = int(hashlib.sha256(('55:noort:' + case).encode()).hexdigest()[:8], 16) % 100
    return 'train' if value < 70 else 'dev' if value < 85 else 'test'


def eligibility(row):
    if row['analysis_data'] != '1' or row['coding_row_type'] != '1':
        return 'not_publisher_analysis_conversation'
    if row['cvr_audio_source'].strip().upper() != 'CVR':
        return 'not_explicit_CVR_source'
    # Channel markers come from the human source transcript, not voice identity.
    channel = row['cvr_speaker_source'].strip().upper().rstrip(':')
    if not re.fullmatch(r'(?:CAM|HOT|INT)(?:[- ](?:\d+|\?))?', channel):
        return 'radio_or_unestablished_cabin_channel'
    role = row['cvr_turn_speaker_raw'].strip()
    if not re.fullmatch(r'(?:Captain|First Officer|Flight Engineer)(?:-\d+)?', role, flags=re.I):
        return 'not_explicit_core_flight_crew'
    if re.search(r'ATC|TOWER|GROUND CONTROL|APPROACH|DEPARTURE', row['cvr_addressee'], flags=re.I):
        return 'explicit_radio_addressee'
    if row['coding_safety_voice'] not in {'0', '1'}:
        return 'missing_human_label'
    if not row['cvr_message'].strip():
        return 'empty_text'
    return None


def main():
    source = Path('data/input/cvr-noort-v1')
    destination = Path('data/curated/cvr-native-v1')
    if (destination / 'preparation.json').exists():
        raise ValueError('Preserve the prepared version')
    plan = json.loads((source / 'case-partition.json').read_text())
    with zipfile.ZipFile(source / 'supplementary.zip') as archive:
        raw = archive.read('mmc2.csv')
        if hashlib.sha256(raw).hexdigest() != plan['source_sha256']:
            raise ValueError('Source changed after partition freeze')
        rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline='')))
        if set(plan['assignments']) != {r['case_id'] for r in rows} or any(partition(c) != s for c, s in plan['assignments'].items()):
            raise ValueError('Case assignment changed')
        destination.mkdir(parents=True, exist_ok=True)
        for name in ('mmc1.csv', 'mmc3.csv'):
            (destination / name).write_bytes(archive.read(name))
    selected = {s: [] for s in ('train', 'dev', 'test')}
    exclusions = Counter()
    ids = set()
    for row in rows:
        reason = eligibility(row)
        if reason:
            exclusions[reason] += 1
            continue
        case = row['case_id']
        identifier = f"noort-{case}-{row['cvr_row_rawnumber']}"
        if identifier in ids:
            raise ValueError('Duplicate case/turn')
        ids.add(identifier)
        selected[partition(case)].append({'id': identifier, 'case_id': case, 'group_id': f'noort-case-{case}',
            'text': row['cvr_message'], 'label': int(row['coding_safety_voice']),
            'label_name': 'source_native_safety_voice', 'human_label_field': 'coding_safety_voice',
            'channel': row['cvr_speaker_source'], 'role_provenance': 'publisher human transcript metadata',
            'original_source_url': row['case_source_URL'], 'source_row': row['Sorting_row'],
            'scope_basis': 'CVR + CAM/HOT/INT + explicitly coded crew + no explicit radio addressee',
            'scope_independently_verified': False, 'project_labels': None, 'project_salience': None, 'temporal_events': None})
    def write(name, records):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
        return hashlib.sha256(path.read_bytes()).hexdigest()
    files = {}
    for split in ('train', 'dev'):
        files[f'train-dev/{split}.jsonl'] = write(f'train-dev/{split}.jsonl', selected[split])
    files['sealed/test-inputs.jsonl'] = write('sealed/test-inputs.jsonl', [{k: r[k] for k in ('id', 'group_id', 'text')} for r in selected['test']])
    files['sealed/test-references.jsonl'] = write('sealed/test-references.jsonl', [{k: r[k] for k in ('id', 'group_id', 'label')} for r in selected['test']])
    report = {'source': 'Noort, Reader & Gillespie (2021), doi:10.1016/j.dib.2021.107602', 'license': 'CC-BY-4.0',
        'raw_rows': len(rows), 'case_partition_sha256': hashlib.sha256((source / 'case-partition.json').read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'files': files, 'exclusions': dict(exclusions),
        'splits': {s: {'rows': len(rs), 'cases': len({r['case_id'] for r in rs})} for s, rs in selected.items()},
        'train_dev_label_counts': {s: dict(Counter(str(r['label']) for r in selected[s])) for s in ('train', 'dev')},
        'test_labels_inspected_by_model': False, 'asr_quality_evidence': False, 'project_event_quality_evidence': False,
        'limitations': ['Source-native human safety-voice labels are not project event or salience labels.',
            'Accident-only, possibly translated transcripts; no paired source audio.',
            'Case partition; known speaker identity cannot be linked across cases.',
            'Channel-metadata screening is not independent human scope adjudication.']}
    (destination / 'preparation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    output = Path('reports/additional-sources-v1')
    (output / 'cvr-preparation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
