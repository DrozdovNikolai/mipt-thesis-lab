from copy import deepcopy
import pytest
from scripts.soteria_training_v15 import admission, schedules, POLICY, distance


def example():
    row = {'split':'train','sample_id':'a','audio_sha256':'b','duration_sec':5.}
    prediction = {'sample_id':'a','audio_sha256':'b','human_verified':False,'status':'machine',
        'error':None,'text':'Climb to 9000 feet and turn right.',
        'segments':[{'language':'en','avg_logprob':-.2,'words':[{'probability':.9}]}]}
    return row, prediction, deepcopy(prediction)


def test_accept_weak_pair_without_attesting_human():
    result = admission(*example())
    assert result['accepted'] and result['human_verified'] is False


@pytest.mark.parametrize('split',['dev','test'])
def test_no_heldout_admission(split):
    row,large,small = example()
    row['split'] = split
    with pytest.raises(ValueError):
        admission(row,large,small)


def test_audio_mismatch_fails():
    row,large,small = example()
    small['audio_sha256'] = 'different'
    with pytest.raises(ValueError):
        admission(row,large,small)


def test_explicit_numeric_conflict_rejected():
    row,large,small = example()
    small['text'] = small['text'].replace('9000','8000')
    assert 'explicit_number_conflict' in admission(row,large,small)['reasons']


def test_numeric_separator_only_is_allowed():
    row,large,small = example()
    small['text'] = small['text'].replace('9000','9,000')
    assert 'explicit_number_conflict' not in admission(row,large,small)['reasons']


def test_missing_words_low_confidence_rejected():
    row,large,small = example()
    large['segments'][0]['words'] = []
    assert 'low_teacher_confidence' in admission(row,large,small)['reasons']


def test_hallucinated_repetition_rejected():
    row,large,small = example()
    large['text'] = small['text'] = 'hello to you hello to you hello to you'
    assert 'repeated_trigram' in admission(row,large,small)['reasons']


def test_matched_replay_and_complete_training_coverage():
    old = [f'old-{i}' for i in range(247)]
    new = [f'new-{i}' for i in range(155)]
    value = schedules(old,new)
    assert value == schedules(old,new)
    assert set(value['replay_control']) == set(old)
    assert set(value['soteria_mix']) == set(old+new)
    for i in range(POLICY['updates']):
        control,mixed = (value[a][i*4:i*4+4] for a in POLICY['arms'])
        assert control[:2] == mixed[:2]
        assert all(k.startswith('new-') for k in mixed[2:])
        assert all(k.startswith('old-') for k in control)


def test_edit_distance_edges():
    assert distance([],['a']) == 1
    assert distance(['a'],[]) == 1
    assert distance(['a','b'],['a','c']) == 1
