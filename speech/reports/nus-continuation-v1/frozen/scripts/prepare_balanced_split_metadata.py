"""Copy known development split metadata while removing reference answers."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / 'reports/balanced-v1/split-metadata'


def unchanged_or_create(path, text):
    # Preserve the initial Windows copies byte-for-byte on either platform.
    raw = text.replace('\n', '\r\n').encode('utf-8')
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Existing split metadata differs; preserve it')
    else:
        path.write_bytes(raw)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan = json.loads((REPO / 'data/curated/clean-controls-v1/plan.json').read_bytes())
    unchanged_or_create(OUTPUT / 'clean-plan.json', json.dumps({
        'items': [{'speaker_id': row['speaker_id']} for row in plan['items']]}, indent=2))
    rows = [json.loads(line) for line in (REPO / 'data/curated/reviewed-pilot-v2/dev.jsonl').read_text(encoding='utf-8').splitlines()]
    fields = ('reference_text', 'labels', 'critical_entities', 'events', 'salient_for_review')
    statuses = ('transcript_status', 'events_status', 'entities_status', 'temporal_status')
    for row in rows:
        row.update({**dict.fromkeys(fields), **dict.fromkeys(statuses, 'missing'),
                    'unintelligible': [], 'annotation_provenance': {'method': 'split_metadata_only'}})
    unchanged_or_create(OUTPUT / 'reviewed-dev.jsonl', ''.join(json.dumps(row)+'\n' for row in rows))
    print('Known split metadata verified; no reference answers in the preparation copies')


if __name__ == '__main__':
    try:
        main()
    except PermissionError:
        if '--in-container' in sys.argv:
            raise
        args = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python']
        for local, target, ro in [
            (Path(__file__).resolve(), '/app/scripts/prepare_balanced_split_metadata.py', True),
            (REPO / 'data/curated/clean-controls-v1/plan.json', '/app/data/curated/clean-controls-v1/plan.json', True),
            (REPO / 'data/curated/reviewed-pilot-v2/dev.jsonl', '/app/data/curated/reviewed-pilot-v2/dev.jsonl', True),
            (OUTPUT, '/app/reports/balanced-v1/split-metadata', False),
        ]:
            args += ['-v', f'{local.as_posix()}:{target}' + (':ro' if ro else '')]
        args += ['north55-speech-gpu:0.1.0', '/app/scripts/prepare_balanced_split_metadata.py', '--in-container']
        raise SystemExit(subprocess.run(args, check=False).returncode) from None
