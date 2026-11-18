"""Read-only audit of already acquired train metadata; no ASR or new admission."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    source, output = Path('/sources'), Path('/study')
    acquisition_path = source / 'training-support-acquisition.json'
    acquisition = json.loads(acquisition_path.read_bytes())
    if acquisition['status'] != 'ACQUIRED' or acquisition['license'] != 'CC-BY-4.0':
        raise ValueError('Expected previously verified acquisition')
    checks = {entry['local']: sha(source / entry['local']) == entry['actual_sha256']
              for entry in acquisition['files']}
    if not all(checks.values()):
        raise ValueError('Acquired files changed')
    rows = pq.read_table(source / 'librispeech-0000.parquet',
                         columns=['id', 'speaker_id', 'chapter_id']).to_pylist()
    speakers = Counter(str(row['speaker_id']) for row in rows)
    chapters = Counter((str(row['speaker_id']), str(row['chapter_id'])) for row in rows)
    controls = json.loads(Path('/clean-plan.json').read_bytes())['items']
    excluded = {str(row['speaker_id']) for row in controls}
    old = [json.loads(line) for line in Path('/old-train.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    en = [row for row in old if row['language'] == 'en']
    with (source / 'fleurs-train.tsv').open(encoding='utf-8', newline='') as stream:
        ru = list(csv.reader(stream, delimiter='\t', quoting=csv.QUOTE_NONE))
    if any(len(row) != 7 for row in ru):
        raise ValueError('Unexpected publisher TSV format')
    result = {
        'status': 'EXECUTED_METADATA_AUDIT', 'source_checksums': checks,
        'acquisition_sha256': sha(acquisition_path), 'audit_script_sha256': sha(Path(__file__)),
        'existing_train_manifest_sha256': sha(Path('/old-train.jsonl')),
        'librispeech_downloaded': {'records': len(rows), 'speakers': len(speakers),
            'chapters': len(chapters), 'records_per_speaker': dict(sorted(speakers.items())),
            'known_dev_speaker_overlap': sorted(set(speakers) & excluded)},
        'librispeech_previously_imported': {'records': len(en),
            'speakers': len({speaker for row in en for speaker in row['speaker_ids']})},
        'fleurs_downloaded': {'rows': len(ru), 'distinct_sentence_ids': len({row[0] for row in ru}),
            'individual_speaker_ids': 'UNAVAILABLE'},
        'new_training_admitted': 0, 'ASR_calls': 0, 'training_runs': 0, 'test_accessed': False,
        'limitations': ['Metadata inventory is not a validated training manifest.',
            'New selection still needs duration, audio duplicates, transcript and group checks.',
            'General speech does not provide independent cockpit quality evidence.',
            'Two-speaker sampling is a limitation, not a proven causal explanation of LoRA degradation.']}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
