"""Deterministic speaker-balanced selection of already eligible train records."""

import hashlib
from collections import defaultdict, deque


def balanced_selection(rows, count=200, seed=55):
    if count < 1:
        raise ValueError('A positive sample count is required')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate sample IDs')
    if any(r.get('split') != 'train' or not r.get('speaker_id') for r in rows):
        raise ValueError('Selection requires train records with known speakers')
    if len(rows) < count:
        raise ValueError('Insufficient eligible records; do not silently shrink the experiment')

    def key(value):
        return hashlib.sha256(f'{seed}:{value}'.encode()).hexdigest()

    groups = defaultdict(list)
    for row in rows:
        groups[str(row['speaker_id'])].append(row)
    queues = {speaker: deque(sorted(group, key=lambda r: (key(r['id']), r['id'])))
              for speaker, group in groups.items()}
    speakers = sorted(queues, key=lambda s: (key(s), s))
    selected = []
    while len(selected) < count:
        for speaker in speakers:
            if queues[speaker]:
                selected.append(queues[speaker].popleft())
                if len(selected) == count:
                    break
    return selected
