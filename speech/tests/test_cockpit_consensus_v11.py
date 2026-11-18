from north55_speech.cockpit_consensus_v11 import select_consensus


def test_only_same_edit_from_both_other_models_is_accepted():
    row = select_consensus('flops thirty lights on', 'flaps thirty lights on',
        'flaps thirty lights off', 'en', False)
    assert row['edits'] == 'flaps thirty lights on'
    assert row['utterance'] == 'flops thirty lights on'
    assert row['accepted_edits'] == [{'start_token': 0, 'end_token': 1,
        'before': ['flops'], 'replacement': ['flaps']}]


def test_single_model_deletion_cannot_remove_repetition():
    row = select_consensus('no amber no amber', 'no amber', 'no amber no amber', 'en', False)
    assert row['edits'] == 'no amber no amber'
    assert row['accepted_edits'] == []


def test_insertion_requires_same_boundary_and_words():
    row = select_consensus('flight on lights', 'flight director on lights',
        'flight on landing lights', 'en', False)
    assert row['edits'] == 'flight on lights'
    row = select_consensus('flight on', 'flight director on', 'Flight director on.', 'en', False)
    assert row['edits'] == 'flight director on' and row['utterance_changed']


def test_two_agreeing_changes_and_deletion():
    row = select_consensus('flops thirty extra lights on', 'flaps thirty lights off',
        'flaps thirty lights off', 'en', False)
    assert row['edits'] == 'flaps thirty lights off'
    assert len(row['accepted_edits']) == 3


def test_severe_noise_russian_and_silence_are_preserved():
    for base, language, severe in [('', 'en', False), ('исходный ответ', 'ru', False),
        ('noisy speech', 'en', True)]:
        row = select_consensus(base, 'different', 'different', language, severe)
        assert row['edits'] == row['utterance'] == base


def test_empty_independent_decoder_is_not_a_deletion_vote():
    row = select_consensus('flight director on', '', '', 'en', False)
    assert row['edits'] == 'flight director on'
