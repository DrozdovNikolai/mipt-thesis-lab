"""Conservative cross-family weak-label checks, separate from evaluation metrics."""
from __future__ import annotations

import math
import statistics

from north55_speech.metrics import edit_counts
from scripts.publisher_alignment import number_tokens
from scripts.publisher_phrase_support import critical, support
from scripts.publisher_recovery_rules_v3 import normalize, word_list


def compatible(target, other, policy):
    a, b = normalize(target), normalize(other)
    c = edit_counts(a, b)
    limit = 0 if c['N'] < policy['exact_below_words'] else policy['teacher_disagreement']
    return ((c['S']+c['D']+c['I'])/max(1, c['N']) <= limit
        and number_tokens(a) == number_tokens(b) and critical(a) == critical(b))


def timestamp_reasons(words, duration, max_collapsed, require_probability=False, min_probability=.65):
    reasons = []
    if not words:
        return ['missing_words']
    intervals = [(w.get('start_sec', w.get('start')), w.get('end_sec', w.get('end'))) for w in words]
    if any(a is None or b is None or not math.isfinite(a) or not math.isfinite(b)
           or not 0 <= a <= b <= duration+.1 for a, b in intervals):
        reasons.append('invalid_timestamps')
    else:
        if sum(a == b for a, b in intervals)/len(intervals) > max_collapsed:
            reasons.append('collapsed_timestamps')
        if any(b[0] < a[0] or b[1] < a[1] for a, b in zip(intervals, intervals[1:])):
            reasons.append('nonmonotonic_timestamps')
    if require_probability:
        probs = [w.get('probability') for w in words]
        if any(p is None or not math.isfinite(p) or not 0 <= p <= 1 for p in probs):
            reasons.append('invalid_probability')
        elif statistics.median(probs) < min_probability:
            reasons.append('low_probability')
    return reasons


def decision(parakeet, teachers, documents, duration, policy):
    target = parakeet['hypothesis'].strip()
    reasons = []
    n = len(normalize(target).split())
    if parakeet.get('error'):
        reasons.append('parakeet_failure')
    if not 3 <= duration <= 25 or n < policy['minimum_words']:
        reasons.append('length')
    if n/max(duration, .001) > policy['maximum_speech_words_per_second']:
        reasons.append('excessive_word_rate')
    words = parakeet.get('timestamp', {}).get('word', [])
    reasons.extend('parakeet_'+r for r in timestamp_reasons(words, duration, policy['maximum_collapsed_timestamps']))
    teacher_checks = {}
    for name, row in teachers.items():
        issues = []
        if row.get('error'):
            issues.append('runtime_failure')
        if not compatible(target, row['hypothesis'], policy):
            issues.append('text_or_critical_disagreement')
        issues.extend(timestamp_reasons(word_list(row), duration,
            policy['maximum_collapsed_timestamps'], True, policy['whisper_median_probability']))
        teacher_checks[name] = issues
    supporters = [name for name, issues in teacher_checks.items() if not issues]
    if not supporters:
        reasons.append('no_reliable_cross_family_support')
    evidence = []
    for name, doc in documents.items():
        script = '\n'.join(line['text'] for line in doc['lines'] if not line.get('excluded_layout', False))
        evidence.append({'document': name, **support(normalize(target), normalize(script))})
    best = max(evidence, key=lambda e: (e['coverage'], e['critical_supported']))
    if best['coverage'] < policy['publisher_coverage'] or not best['critical_supported']:
        reasons.append('publisher_support')
    return {'accepted': not reasons, 'reasons': reasons, 'target': target, 'supporting_teachers': supporters,
        'teacher_checks': teacher_checks, 'publisher': best, 'human_verified': False}


def interval_union_seconds(intervals):
    end, total = -math.inf, 0.
    for a, b in sorted(intervals):
        if not math.isfinite(a) or not math.isfinite(b) or a < 0 or b <= a:
            raise ValueError('Invalid source interval')
        total += max(0., b-max(a, end))
        end = max(end, b)
    return total
