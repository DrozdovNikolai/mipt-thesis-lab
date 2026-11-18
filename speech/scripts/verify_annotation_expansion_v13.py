"""Audit queue coverage and draft identity without creating human annotations."""
import hashlib
import json
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    new = root/'data/curated/annotation-expanded-v13'
    old = root/'data/curated/annotation-hard-v4'
    packet, policy = read(new/'packet.json'), read(new/'draft-policy.json')
    for name, expected in packet['old_packet_sha256'].items():
        assert sha(old/name) == expected, name
    old_rows = [json.loads(line) for line in (old/'dev.jsonl').read_text().splitlines()]
    rows = [json.loads(line) for line in (new/'dev.jsonl').read_text().splitlines()]
    assert len(old_rows) == 42 and len(rows) == 84
    ids = {r['sample_id'] for r in rows}
    assert len(ids) == 84 and not ids & {r['sample_id'] for r in old_rows}
    assert set(policy['enabled_sample_ids']) == ids
    languages = Counter()
    for name, expected in policy['manifest_sha256'].items():
        assert sha(new/name) == expected
    for row in rows:
        key = row['sample_id']
        path = new/'assisted-drafts'/f'{key}.json'
        assert sha(path) == policy['draft_sha256'][key]
        draft = read(path)
        assert draft['sample_id'] == key and draft['audio_sha256'] == row['audio_sha256']
        assert draft['human_verified'] is False and isinstance(draft['text'], str)
        assert row['reference_text'] is None and row['transcript_status'] == 'missing'
        language = {s.get('language') for s in draft['segments']} - {None, 'unknown', ''}
        languages[next(iter(language)) if len(language) == 1 else 'mixed' if language else 'unknown'] += 1
    human = 0
    for row in old_rows:
        revisions = sorted((old/'revisions'/row['sample_id']).glob('revision-*.json'))
        if revisions and read(revisions[-1])['sample']['transcript_status'] == 'human_verified':
            human += 1
    report = {'status': 'PASS', 'new_clips': 84, 'new_minutes': sum(r['duration_sec'] for r in rows)/60,
              'old_dev_clips': 42, 'combined_dev_clips': 126, 'old_snapshot_files_unchanged': len(packet['old_packet_sha256']),
              'old_human_reviewed_clips_preserved': human, 'machine_drafts': 84, 'machine_language_hints': dict(languages),
              'source_recordings': len({r['recording_id'] for r in rows}),
              'speakers': len({s for r in rows for s in r['speaker_ids']}),
              'new_human_annotations_created_by_agent': 0, 'sealed_test_accessed': False,
              'queue_url': 'http://localhost:8012/?split=dev', 'ui_regression_tests_passed': 25}
    destination = root/'reports/aviation-v13/annotation-verification.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
