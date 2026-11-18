import copy

import pytest

from north55_speech.convergence import convergence_decision, select_training_subset


def population():
    return [{'source_dataset': 'NUS-SIA/CDE4301-VR-401', 'sample_id': f'clip-{i}',
             'audio_sha256': f'{i:064x}', 'decoded_audio_sha256': f'{i:064x}',
             'split': 'train', 'transcript_status': 'weak', 'reference_text': 'ready',
             'rights_confirmed': True, 'language': 'en', 'input_language': 'en',
             'primary': False, 'scope_verified': False, 'speaker_ids': [],
             'annotation_provenance': {'source_reference_conflict': False, 'radio_text_indicator': False}}
            for i in range(275)]


def test_selection_ignores_text_and_source_row_order():
    original = population()
    changed = copy.deepcopy(original)[::-1]
    for sample in changed:
        sample['reference_text'] = 'a different source transcript'
    assert [s['sample_id'] for s in select_training_subset(original)] == [s['sample_id'] for s in select_training_subset(changed)]


@pytest.mark.parametrize('field,value', [('split', 'test'), ('rights_confirmed', False),
                                        ('transcript_status', 'human_verified'), ('primary', True)])
def test_subset_rejects_changed_admission(field, value):
    items = population()
    items[0][field] = value
    with pytest.raises(ValueError):
        select_training_subset(items)


def test_duplicate_audio_rejected():
    items = population()
    items[-1]['decoded_audio_sha256'] = items[0]['decoded_audio_sha256']
    with pytest.raises(ValueError):
        select_training_subset(items)


def curve():
    return {step: {'runtime_failures': 0, 'N': 100, 'wer_lexical_corpus': .05} for step in (0, 40, 120, 240)}


def test_early_good_fit_cannot_select_checkpoint_or_release():
    values = curve()
    values[240]['wer_lexical_corpus'] = .20
    decision = convergence_decision(values)
    assert not decision['run_transfer'] and not decision['release_allowed']
    values[240]['wer_lexical_corpus'] = .10
    decision = convergence_decision(values)
    assert decision['run_transfer'] and not decision['release_allowed']


def test_failure_or_incomplete_curve_cannot_pass():
    values = curve()
    values[40]['runtime_failures'] = 1
    assert not convergence_decision(values)['run_transfer']
    del values[40]
    with pytest.raises(ValueError):
        convergence_decision(values)
