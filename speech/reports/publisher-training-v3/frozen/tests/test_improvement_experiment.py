import numpy as np
import soundfile as sf

from north55_speech.core import file_hash
from scripts.improvement_experiment import glossary_from_train, load_input, select_fleurs


def test_fleurs_excludes_entire_exposed_and_training_sentences():
    rows = [["train", "a"], ["old", "b"], ["new", "c"], ["new", "d"]]
    chosen = select_fleurs(rows, {"train"}, {"old"})
    assert {r[0] for r, _ in chosen} == {"new"}
    assert sum(primary for _, primary in chosen) == 1
    assert dict((r[1], p) for r, p in chosen) == dict((r[1], p) for r, p in select_fleurs(list(reversed(rows)), {"train"}, {"old"}))


def test_glossary_has_no_numeric_answers_and_downweights_general_words():
    domain = [{"reference_text": "gear gear flaps flaps other other 1016 1016"}]
    general = [{"reference_text": "other " * 20}]
    glossary = glossary_from_train(domain, general)
    assert glossary == "flaps, gear, other"
    assert "1016" not in glossary


def test_quiet_control_really_attenuates_audio(tmp_path):
    path = tmp_path / "clip.wav"
    waveform = np.full(16000, .5, dtype=np.float32)
    sf.write(path, waveform, 16000, subtype="FLOAT")
    item = {"audio_path": str(path), "audio_sha256": file_hash(path), "duration_sec": 1, "gain_db": -12}
    np.testing.assert_array_equal(load_input(item), waveform * np.float32(10 ** (-12 / 20)))
