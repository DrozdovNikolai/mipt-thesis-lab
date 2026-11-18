"""Synthetic programmer-labelled examples exercise fitting only, not an NLP benchmark."""

import pytest

from north55_speech.core import SpeechError, settings
from north55_speech.datasets import write_manifest
from north55_speech.training import TrainedEventClassifier, check_training_partitions, train_events
from tests.unit.test_data_gates import sample


def test_training_and_reload_real_estimator(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "model_root", tmp_path / "models")
    examples = [
        ("checklist please", ["CHECKLIST"], True),
        ("flaps fifteen", ["CONFIGURATION_MENTION"], True),
        ("your controls", ["CREW_COORDINATION"], True),
        ("hello everyone", ["OTHER"], False),
    ]
    train = []
    dev = []
    for i, (text, labels, salient) in enumerate(examples):
        for j in range(3):
            s = sample(
                1 if j < 2 else 2,
                sample_id=f"fixture-{i}-{j}",
                audio_sha256=(str(i + 1) if j < 2 else str(i + 5)) * 64,
                session_id=f"s-{i}-{j}",
                recording_id=f"r-{i}-{j}",
                original_utterance_id=f"u-{i}-{j}",
                reference_text=text + (" unique_development_token" if j == 2 else ""),
                labels=labels,
                salient_for_review=salient,
                events_status="human_verified",
                split="train" if j < 2 else "dev",
                group_id=f"g-{i}-{j}",
            )
            (train if j < 2 else dev).append(s)
    train_path = tmp_path / "train.jsonl"
    dev_path = tmp_path / "dev.jsonl"
    write_manifest(train_path, train)
    write_manifest(dev_path, dev)
    report = train_events(
        {"train_manifest": str(train_path), "dev_manifest": str(dev_path), "output": "test-events"}
    )
    assert report["version"] == "tfidf_logreg_v1"
    loaded = TrainedEventClassifier.load("test-events")
    assert loaded.predict("flaps fifteen")["labels"]
    vectorizer = loaded.model.named_steps["features"].transformer_list[0][1]
    assert "unique_development_token" not in vectorizer.vocabulary_
    assert loaded.salience.classes_.tolist() == [False, True]


def test_training_rejects_test_partition():
    with pytest.raises(SpeechError):
        check_training_partitions([sample(1, split="test")], [sample(2, split="dev")])
