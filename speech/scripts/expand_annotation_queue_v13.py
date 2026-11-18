"""Materialize every remaining time-grid dev candidate without modifying prior reviews."""
import hashlib
import json
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import load_manifest, validate_groups, write_manifest
from scripts.cockpit_hard_v4 import clipped, overlaps


def main():
    work, packet = Path('/workspace'), Path('/packet')
    old = work/'data/curated/annotation-hard-v4'
    if (packet/'dev.jsonl').exists():
        raise ValueError('Preserve existing expanded queue')
    raw_path = work/'data/curated/bleriot-v2/manifests/train-dev/dev.jsonl'
    raw = load_manifest(raw_path)
    held = load_manifest(work/'data/curated/publisher-recovery-v3/dev.jsonl')
    held += load_manifest(work/'data/curated/annotation-packet-v1/dev.jsonl')
    previous = load_manifest(old/'dev.jsonl')
    templates = {s.annotation_provenance['source_sample_id']: s for s in previous}
    snapshot = {str(p.relative_to(old)): file_hash(p) for p in old.rglob('*') if p.is_file()}
    samples, coverage = [], []
    for parent in [s for s in raw if not s.variant_of]:
        excluded = [(s.annotation_provenance['original_start_sec'], s.annotation_provenance['original_end_sec'])
                    for s in held+previous if s.annotation_provenance['source_sample_id'] == parent.sample_id]
        candidates = [(float(a), float(a+10)) for a in range(5, int(parent.duration_sec)-10, 15)
                      if not any(overlaps((a, a+10), span) for span in excluded)]
        coverage.append({'source': parent.sample_id, 'added': len(candidates)})
        for start, end in candidates:
            key = hashlib.sha256(f'expanded-dev-v13:{parent.sample_id}:{start}:{end}'.encode()).hexdigest()[:32]
            crop = clipped(parent, key, start, end, 'cockpit-expanded-review-v13')
            template = templates[parent.sample_id]
            row = template.model_copy(deep=True, update={**crop, 'group_id': None,
                'original_utterance_id': parent.original_utterance_id+f'@expanded-dev-v13:{start}:{end}',
                'annotation_provenance': {**template.annotation_provenance,
                    'original_start_sec': start, 'original_end_sec': end, 'queue': 'expanded_dev_v13',
                    'selection': 'all_remaining_nonoverlapping_ten_second_windows_on_fifteen_second_grid',
                    'draft_available': False}})
            samples.append(row)
    assert len(samples) == 84
    validate_groups(samples)
    # Check the full cross-packet split graph without rewriting the historical group IDs.
    all_rows = load_manifest(old/'train.jsonl')+previous+samples
    validate_groups([s.model_copy(deep=True, update={'group_id': None}) for s in all_rows])
    packet.mkdir(parents=True, exist_ok=True)
    write_manifest(packet/'train.jsonl', [])
    write_manifest(packet/'dev.jsonl', samples)
    assert all(file_hash(old/name) == value for name, value in snapshot.items())
    atomic_json(packet/'packet.json', {'items': len(samples), 'old_dev_items': len(previous),
        'combined_dev_items': len(samples)+len(previous), 'coverage': coverage,
        'source_manifest_sha256': file_hash(raw_path), 'old_packet_sha256': snapshot,
        'human_labels_created': 0, 'new_speakers': 0, 'test_accessed': False})
    print(json.dumps({'added': len(samples), 'combined_dev': len(samples)+len(previous),
                      'old_files_unchanged': len(snapshot)}), flush=True)


if __name__ == '__main__':
    main()
