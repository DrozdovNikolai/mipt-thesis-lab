"""Conservative agreement of independent ASR candidates, without reference text."""
from __future__ import annotations

from rapidfuzz.distance import Levenshtein

from north55_speech.metrics import lexical_normalizer_v1


def proposals(base: list[str], candidate: list[str]) -> set[tuple]:
    return {(op.src_start, op.src_end, tuple(candidate[op.dest_start:op.dest_end]))
        for op in Levenshtein.opcodes(base, candidate) if op.tag != 'equal'}


def select_consensus(base: str, parakeet: str | None, canary: str | None,
                     language: str, severe: bool) -> dict:
    result = {'utterance': base, 'edits': base, 'accepted_edits': [], 'utterance_changed': False}
    if language != 'en' or severe or not base.strip() or not parakeet or not canary:
        return result
    b, p, c = [lexical_normalizer_v1(t).split() for t in (base, parakeet, canary)]
    if not b or not p or not c:
        return result
    if p == c and p != b:
        result['utterance'] = parakeet
        result['utterance_changed'] = True
    agreed = sorted(proposals(b, p) & proposals(b, c))
    if not agreed:
        return result
    words, end = [], 0
    for start, stop, replacement in agreed:
        assert end <= start <= stop <= len(b)
        words.extend(b[end:start])
        words.extend(replacement)
        result['accepted_edits'].append({'start_token': start, 'end_token': stop,
            'before': b[start:stop], 'replacement': list(replacement)})
        end = stop
    words.extend(b[end:])
    result['edits'] = ' '.join(words)
    return result
