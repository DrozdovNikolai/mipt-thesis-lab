"""Hard admission trusts teacher agreement, not student correctness or document fills."""

import copy

from scripts.cockpit_hard_v4 import disagreement, overlaps, teacher_decision


def prediction(text):
    return {'hypothesis': text, 'error': None, 'words': [{'word': word, 'start': i*.3,
        'end': i*.3+.2, 'probability': .95} for i, word in enumerate(text.split())]}


def documents(text):
    return {'checklist.pdf': {'lines': [{'text': text}]}}


def test_hard_student_does_not_veto_agreeing_teachers():
    text = 'parking brake set thrust levers idle engine masters off'
    teacher = prediction(text)
    assert disagreement(text, 'marking break sit trust levels idol engine masters of')['errors'] >= 2
    assert teacher_decision(teacher, copy.deepcopy(teacher), documents(text), 5.)['accepted']


def test_document_cannot_override_teacher_number_disagreement():
    medium = prediction('set minimum altitude 3000 feet')
    large = prediction('set minimum altitude 300 feet')
    result = teacher_decision(medium, large, documents(medium['hypothesis']), 5.)
    assert not result['accepted']
    assert 'numeric_disagreement' in result['reasons']


def test_agreed_but_unsupported_numeric_fill_still_needs_review():
    teacher = prediction('set minimum altitude 3000 feet')
    result = teacher_decision(teacher, teacher, documents('set minimum altitude blank feet'), 5.)
    assert not result['accepted']
    assert 'publisher_support' in result['reasons']


def test_negation_mismatch_and_invalid_probability_rejected():
    medium = prediction('engine masters off parking brake set')
    large = prediction('engine masters on parking brake set')
    assert 'state_or_negation_disagreement' in teacher_decision(medium, large, documents(medium['hypothesis']), 5.)['reasons']
    large = copy.deepcopy(medium)
    large['words'][0]['probability'] = None
    assert 'large_confidence' in teacher_decision(medium, large, documents(medium['hypothesis']), 5.)['reasons']


def test_touching_intervals_are_not_duplicate_audio():
    assert not overlaps((1, 2), (2, 3))
    assert overlaps((1, 2.01), (2, 3))
