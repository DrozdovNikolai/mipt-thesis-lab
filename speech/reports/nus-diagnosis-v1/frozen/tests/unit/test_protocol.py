import json
from pathlib import Path

import pytest

from north55_speech.benchmark import assert_same_model, summarize
from north55_speech.core import SpeechError
from north55_speech.datasets import (
    inference_projection,
    prepare_splits,
    validate_groups,
    verify_partition_proof,
    write_manifest,
)
from north55_speech.gates import load_acceptance, temporal_gate
from north55_speech.metrics import apply_scoring_masks, canonical_normalizer_v1, diarization_score
from north55_speech.schemas import PipelineConfig
from tests.unit.test_data_gates import sample


def test_manifest_projection_has_no_sealed_answers(tmp_path):
    path = tmp_path / "input.jsonl"
    samples = [
        sample(i, reference_text="private fixture", decoded_audio_sha256=str(i) * 64)
        for i in range(1, 9)
    ]
    write_manifest(path, samples)
    prepare_splits(path, tmp_path / "manifests")
    assert not (tmp_path / "manifests/full-manifest.jsonl").exists()
    assert (tmp_path / "sealed/full-manifest.jsonl").exists()
    assert "private fixture" not in (tmp_path / "manifests/test-inference/test.jsonl").read_text()
    proof = json.loads((tmp_path / "manifests/protocol/partition-proof.json").read_text())
    verify_partition_proof(proof)
    proof["partitions"]["test"][0]["session"] = proof["partitions"]["train"][0]["session"]
    with pytest.raises(SpeechError):
        verify_partition_proof(proof)


def test_comparison_model_precision_invariant():
    with pytest.raises(SpeechError):
        assert_same_model(PipelineConfig(), PipelineConfig(model="large-v3"))
    with pytest.raises(SpeechError):
        assert_same_model(PipelineConfig(), PipelineConfig(compute_type="float16"))


def test_selected_audio_channel_is_runtime_metadata():
    request = inference_projection(sample(1, channel=1))
    assert request.audio_channel == 1 and request.channel_mode == "separate_channels"
    assert "reference_text" not in request.model_dump()


def test_augmentation_cannot_create_new_independent_group():
    original = sample(1, split="train")
    validate_groups([original])
    previous = original.group_id
    variant = original.model_copy(deep=True)
    variant.sample_id = "variant"
    variant.variant_of = original.sample_id
    variant.audio_sha256 = "a" * 64
    report = validate_groups([original, variant])
    assert report["independent_groups"] == 1
    assert original.group_id == variant.group_id == previous


def test_scorer_keeps_failure_and_review_samples():
    s = sample(1, reference_text="a b c", primary=False)
    fail = {s.sample_id: {"status": "FAILED", "result": None}}
    report, rows = summarize([s], fail, fail, load_acceptance(Path("configs/acceptance.yaml")))
    assert len(rows) == 1 and rows[0]["candidate"]["D"] == 3
    assert report["unhandled_runtime_failures"] == 2


def test_canonical_is_secondary_and_conservative():
    assert canonical_normalizer_v1("flaps fifteen") == "flaps 15"
    assert canonical_normalizer_v1("flaps fifty") == "flaps 50"
    assert canonical_normalizer_v1("one sixty") == "one sixty"


def test_explicit_scoring_mask():
    masks = [{"start_sec": 1, "end_sec": 2, "reference_start_token": 1, "reference_end_token": 2}]
    segments = [
        {
            "raw_asr_text": "a noise c",
            "words": [
                {"word": "a", "start_sec": 0, "end_sec": 0.5},
                {"word": "noise", "start_sec": 1, "end_sec": 2},
                {"word": "c", "start_sec": 2, "end_sec": 3},
            ],
        }
    ]
    assert apply_scoring_masks("a unintelligible c", segments, masks) == ("a c", "a c")


def test_diarization_mapping_and_temporal_gate():
    a = [{"start_sec": 0, "end_sec": 2, "speaker_id": "a"}]
    b = [{"start_sec": 0, "end_sec": 2, "speaker_id": "anonymous"}]
    result = diarization_score(a, b, collar=0)
    assert result["der"] == 0 and result["jer"] == 0
    assert diarization_score(a, [], collar=0)["der"] == 1
    acceptance = load_acceptance(Path("configs/acceptance.yaml"))
    assert temporal_gate({}, acceptance)["status"] == "NEEDS_MORE_DATA"
