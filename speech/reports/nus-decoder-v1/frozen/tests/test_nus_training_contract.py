import pytest

from scripts.audit_nus_training_contract import checked_path, save, validate_inputs


def inputs():
    return [{'id': f'nus-clip01_{i:04d}', 'audio_path': f'{i}.wav', 'audio_sha256': 'a' * 64,
             'duration_sec': 2., 'input_language': 'en'} for i in range(275)]


def test_generation_manifest_rejects_answers_and_nontrain_population():
    items = inputs()
    validate_inputs(items)
    items[0]['reference_text'] = 'Do not pass gold to generation'
    with pytest.raises(ValueError):
        validate_inputs(items)
    del items[0]['reference_text']
    items[0]['id'] = 'human-dev'
    with pytest.raises(ValueError):
        validate_inputs(items)


def test_generation_manifest_rejects_duplicates():
    items = inputs()
    items[-1] = items[0]
    with pytest.raises(ValueError):
        validate_inputs(items)


def test_artifact_path_must_stay_inside_root(tmp_path):
    outside = tmp_path / 'outside.wav'
    outside.write_bytes(b'original')
    inside = tmp_path / 'root'
    inside.mkdir()
    with pytest.raises(ValueError):
        checked_path(inside, '../outside.wav')


def test_existing_measurements_are_preserved(tmp_path):
    target = tmp_path / 'result.json'
    save(target, {'value': 1})
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        save(target, {'value': 2})
    assert target.read_bytes() == original
