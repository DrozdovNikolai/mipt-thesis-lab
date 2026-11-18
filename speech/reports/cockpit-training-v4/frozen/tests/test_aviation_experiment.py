import copy
from pathlib import Path

import pytest

from north55_speech.local_transcription import config_for_language
from scripts.aviation_experiment import candidate_decision, source_identity


def test_original_source_identity_requires_matching_speaker_and_valid_recording():
    metadata = {"zf2_04_010": {"speaker_id": "zf2", "recording_id": "001_0001", "recording_corrupt": "0"}}
    assert source_identity("atcosim_zf2_04_010_000000_000200", metadata) == ("zf2_04_010", "zf2", "001_0001")
    with pytest.raises(ValueError, match="Unverifiable"):
        source_identity("atcosim_zf2_04_011_000000_000200", metadata)
    metadata["zf2_04_010"]["speaker_id"] = "zf1"
    with pytest.raises(ValueError, match="speaker mismatch"):
        source_identity("atcosim_zf2_04_010_000000_000200", metadata)


def test_formatting_only_gain_is_not_enough_and_gate_must_preserve_speech():
    def summary(wer, canonical=None, insertions=0):
        return {"lexical": {"wer_lexical_corpus": wer, "I": insertions},
                "canonical": {"wer_lexical_corpus": wer if canonical is None else canonical}, "failures": 0}
    data = {"atcosim": {"small": summary(.6), "medium": summary(.5, .2),
                         "atc": summary(.1, .1), "atc_gate": summary(.1, .1)},
            "noise_only": {"small": summary(0, insertions=5), "atc": summary(0, insertions=9), "atc_gate": summary(0)},
            "bleriot_b_noise": {"small": summary(0, insertions=3), "atc": summary(0, insertions=8), "atc_gate": summary(0)}}
    assert candidate_decision(data)["selected"] == "atc_gate"
    formatting_only = copy.deepcopy(data)
    formatting_only["atcosim"]["atc"]["canonical"]["wer_lexical_corpus"] = .2
    assert candidate_decision(formatting_only)["selected"] is None
    speech_deleted = copy.deepcopy(data)
    speech_deleted["atcosim"]["atc_gate"]["lexical"]["wer_lexical_corpus"] = .11
    assert candidate_decision(speech_deleted)["selected"] == "atc"


@pytest.mark.parametrize("language", ["auto", "ru", "mixed"])
def test_english_atc_profile_cannot_silently_replace_other_language_routes(language):
    with pytest.raises(ValueError, match="explicit language"):
        config_for_language({"schema_version": "1.0", "allowed_languages": ["en"]}, language)


def test_aviation_contract_changes_scope_without_relaxing_targets():
    from north55_speech.gates import load_acceptance

    original = load_acceptance(Path("configs/acceptance.yaml"))
    aviation = load_acceptance(Path("configs/aviation_acceptance.yaml"))
    expected = copy.deepcopy(original)
    expected["created_at"] = "2026-09-14"
    expected["protocol_id"] = "aviation_quality_v1"
    expected["scope"]["task"] = "aviation_speech"
    expected["scope"]["permitted_primary_scopes"].append("atc")
    expected["scope"]["forbidden_primary_scopes"].remove("atc")
    assert aviation == expected


def test_aviation_contract_rejects_modified_targets(tmp_path):
    from north55_speech.core import SpeechError
    from north55_speech.gates import load_acceptance

    original = Path("configs/aviation_acceptance.yaml").read_text()
    changed = original.replace("freeze_before_final_test: true", "freeze_before_final_test: false")
    assert changed != original
    target = tmp_path / "relaxed.yaml"
    target.write_text(changed)
    with pytest.raises(SpeechError, match="Normative acceptance bytes differ"):
        load_acceptance(target)
