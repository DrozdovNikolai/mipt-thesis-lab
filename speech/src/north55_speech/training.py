from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import MultiLabelBinarizer

from north55_speech.core import SpeechError, atomic_json, confined, file_hash, settings
from north55_speech.datasets import Sample, load_manifest
from north55_speech.metrics import multilabel_score, salience_score
from north55_speech.nlp import EventClassifier
from north55_speech.schemas import LABELS


def check_training_partitions(train: list[Sample], dev: list[Sample]) -> None:
    if not train or not dev:
        raise SpeechError(
            "MISSING_TRAIN_DEV_DATA", "Independent train and development sets are required"
        )
    if any(s.split != "train" for s in train) or any(s.split != "dev" for s in dev):
        raise SpeechError("TEST_ACCESS_FORBIDDEN", "Training accepts only train and dev partitions")
    for key in (
        "group_id",
        "session_id",
        "recording_id",
        "original_utterance_id",
        "audio_sha256",
        "decoded_audio_sha256",
    ):
        a, b = {getattr(s, key) for s in train} - {None}, {getattr(s, key) for s in dev} - {None}
        if a & b:
            raise SpeechError("SPLIT_LEAKAGE", f"Train/dev share {key}")
    if {v for s in train for v in s.speaker_ids} & {v for s in dev for v in s.speaker_ids}:
        raise SpeechError("SPLIT_LEAKAGE", "Train/dev share speaker identities")


def features():
    return FeatureUnion(
        [
            ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1
                ),
            ),
        ]
    )


class TrainedEventClassifier:
    version = "tfidf_logreg_v1"

    def __init__(self, model, salience, manifest):
        self.model, self.salience, self.manifest = model, salience, manifest

    def predict(self, text: str, role: str = "unknown") -> dict:
        probabilities = self.model.predict_proba([text])[0]
        labels = [
            label
            for i, label in enumerate(LABELS)
            if probabilities[i] >= self.manifest["thresholds"][label]
        ]
        if "OTHER" in labels and len(labels) > 1:
            labels.remove("OTHER")
        salience = float(self.salience.predict_proba([text])[0, 1])
        return {
            "labels": labels or ["OTHER"],
            "label_scores": dict(zip(LABELS, map(float, probabilities), strict=True)),
            "salient_for_review": salience >= self.manifest["salience_threshold"],
            "classifier_version": self.version,
        }

    @classmethod
    def load(cls, artifact: str | None):
        if not artifact:
            raise SpeechError(
                "CLASSIFIER_NOT_AVAILABLE", "No trusted classifier artifact configured"
            )
        root = confined(settings.model_root, artifact, must_exist=False)
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise SpeechError("CLASSIFIER_NOT_AVAILABLE", "Train an event classifier first")
        manifest = json.loads(manifest_path.read_text())
        import skops.io as sio

        trusted = ["sklearn.multiclass._ConstantPredictor"]
        for name in ("events.skops", "salience.skops"):
            if file_hash(root / name) != manifest["files"][name]:
                raise SpeechError(
                    "CLASSIFIER_CHECKSUM_MISMATCH", "Classifier artifact was modified"
                )
            if set(sio.get_untrusted_types(file=root / name)) - set(trusted):
                raise SpeechError(
                    "UNTRUSTED_MODEL_TYPE",
                    "Classifier contains types outside the safe sklearn format",
                )
        return cls(
            sio.load(root / "events.skops", trusted=trusted),
            sio.load(root / "salience.skops", trusted=trusted),
            manifest,
        )


def train_events(config: dict) -> dict:
    train_path, dev_path = Path(config["train_manifest"]), Path(config["dev_manifest"])
    if not train_path.is_file() or not dev_path.is_file():
        raise SpeechError(
            "MISSING_EVENT_LABELS", "Supply lawful train/dev human event and salience annotations"
        )
    train, dev = load_manifest(train_path), load_manifest(dev_path)
    check_training_partitions(train, dev)
    if any(
        s.reference_text is None
        or s.labels is None
        or s.salient_for_review is None
        or s.events_status not in {"human_verified", "weak"}
        for s in train
    ):
        raise SpeechError(
            "MISSING_EVENT_LABELS",
            "Training needs texts, explicit event labels and separate salience labels",
        )
    if any(
        s.events_status != "human_verified" or s.labels is None or s.salient_for_review is None
        for s in dev
    ):
        raise SpeechError(
            "MISSING_HUMAN_DEV_LABELS",
            "Threshold selection requires human-verified development labels",
        )
    if len({s.salient_for_review for s in train}) < 2:
        raise SpeechError("MISSING_SALIENCE_CLASS", "Both salience classes are required in train")
    output = confined(settings.model_root, config.get("output", "events-v1"), must_exist=False)
    if (output / "manifest.json").exists():
        raise SpeechError("MODEL_VERSION_EXISTS", "Use a new immutable classifier version")
    texts = [s.reference_text for s in train]
    y = MultiLabelBinarizer(classes=LABELS).fit_transform([s.labels for s in train])
    model = Pipeline(
        [
            ("features", features()),
            (
                "classifier",
                OneVsRestClassifier(
                    LogisticRegression(
                        C=float(config.get("C", 1.0)),
                        class_weight="balanced",
                        max_iter=1000,
                        random_state=55,
                    )
                ),
            ),
        ]
    )
    salience = Pipeline(
        [
            ("features", features()),
            (
                "classifier",
                LogisticRegression(
                    C=float(config.get("C", 1.0)),
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=55,
                ),
            ),
        ]
    )
    # No dev/test vectorizer fitting. Separate salience target is never derived from rules.
    model.fit(texts, y)
    salience.fit(texts, [s.salient_for_review for s in train])
    thresholds = {label: 0.5 for label in LABELS}
    probabilities = model.predict_proba([s.reference_text for s in dev])
    grid = config.get("threshold_grid", [0.35, 0.5, 0.65])
    if len(grid) > 5:
        raise SpeechError("SEARCH_BUDGET", "At most five threshold values per class")
    for index, label in enumerate(LABELS):
        gold = np.array([label in (s.labels or []) for s in dev])
        if not gold.any():
            continue
        scores = []
        for threshold in grid:
            pred = probabilities[:, index] >= threshold
            tp, fp, fn = int(sum(pred & gold)), int(sum(pred & ~gold)), int(sum(~pred & gold))
            scores.append((2 * tp / max(1, 2 * tp + fp + fn), -abs(threshold - 0.5), threshold))
        thresholds[label] = max(scores)[2]
    manifest = {
        "version": "tfidf_logreg_v1",
        "ontology_version": "1.0",
        "seed": 55,
        "train_sha256": file_hash(train_path),
        "dev_sha256": file_hash(dev_path),
        "train_groups": sorted({s.group_id for s in train if s.group_id}),
        "dev_groups": sorted({s.group_id for s in dev if s.group_id}),
        "thresholds": thresholds,
        "salience_threshold": 0.5,
        "weak_train_count": sum(s.events_status == "weak" for s in train),
        "support": {label: int(y[:, i].sum()) for i, label in enumerate(LABELS)},
    }
    output.mkdir(parents=True, exist_ok=True)
    import skops.io as sio

    sio.dump(model, output / "events.skops")
    sio.dump(salience, output / "salience.skops")
    manifest["files"] = {
        name: file_hash(output / name) for name in ("events.skops", "salience.skops")
    }
    candidate = TrainedEventClassifier(model, salience, manifest)
    manifest["development"] = evaluate_events(dev, candidate)
    atomic_json(output / "manifest.json", manifest)
    return manifest


def evaluate_events(
    samples: list[Sample], classifier: TrainedEventClassifier, asr_predictions: dict | None = None
) -> dict:
    if any(
        s.events_status != "human_verified" or s.labels is None or s.reference_text is None
        for s in samples
    ):
        raise SpeechError(
            "MISSING_HUMAN_EVENT_LABELS", "Evaluation cannot use automatic rule labels as truth"
        )
    gold = [cast(list[str], s.labels) for s in samples]
    texts = [cast(str, s.reference_text) for s in samples]
    rules = EventClassifier()
    candidate = [classifier.predict(text) for text in texts]
    baseline = [rules.predict(text) for text in texts]
    report = {
        "task": "utterance_classification",
        "temporal_detection": "NEEDS_MORE_DATA",
        "rules_human_text": multilabel_score(gold, [p["labels"] for p in baseline], LABELS),
        "candidate_human_text": multilabel_score(gold, [p["labels"] for p in candidate], LABELS),
        "salience_human_text": salience_score(
            [cast(bool, s.salient_for_review) for s in samples],
            [p["salient_for_review"] for p in candidate],
        )
        if all(s.salient_for_review is not None for s in samples)
        else None,
        "end_to_end": None,
    }
    if asr_predictions is not None:
        asr_texts = [asr_predictions.get(s.sample_id, "") for s in samples]
        predicted = [classifier.predict(text) for text in asr_texts]
        report["end_to_end"] = {
            "rules": multilabel_score(
                gold, [rules.predict(text)["labels"] for text in asr_texts], LABELS
            ),
            "candidate": multilabel_score(gold, [p["labels"] for p in predicted], LABELS),
            "salience": salience_score(
                [cast(bool, s.salient_for_review) for s in samples],
                [p["salient_for_review"] for p in predicted],
            )
            if all(s.salient_for_review is not None for s in samples)
            else None,
        }
    return report
