from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

import jiwer
import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import multilabel_confusion_matrix, precision_recall_fscore_support


def lexical_normalizer_v1(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold()
    chars = []
    for i, char in enumerate(text):
        category = unicodedata.category(char)
        decimal = (
            char in ".,"
            and 0 < i < len(text) - 1
            and text[i - 1].isdigit()
            and text[i + 1].isdigit()
        )
        apostrophe = (
            char in "'’"
            and 0 < i < len(text) - 1
            and text[i - 1].isalpha()
            and text[i + 1].isalpha()
        )
        chars.append(char if not category.startswith("P") or decimal or apostrophe else " ")
    return re.sub(r"\s+", " ", "".join(chars)).strip()


def edit_counts(reference: str, hypothesis: str) -> dict[str, Any]:
    reference, hypothesis = lexical_normalizer_v1(reference), lexical_normalizer_v1(hypothesis)
    scored = jiwer.process_words(reference, hypothesis)
    characters = jiwer.process_characters(reference, hypothesis)
    n = len(reference.split())
    return {
        "S": scored.substitutions,
        "D": scored.deletions,
        "I": scored.insertions,
        "N": n,
        "H": scored.hits,
        "wer": scored.wer if n else None,
        "character_errors": characters.substitutions + characters.deletions + characters.insertions,
        "reference_characters": len(reference),
        "cer": characters.cer if reference else None,
    }


def canonical_normalizer_v1(text: str) -> str:
    """Secondary symmetric numeric representation; never substitutes lexical WER."""
    from north55_speech.nlp import NUMBERS, SCALES, parse_number

    words = lexical_normalizer_v1(text).split()
    output, index = [], 0
    while index < len(words):
        end = index
        while end < len(words) and (words[end] in NUMBERS or words[end] in SCALES):
            end += 1
        if end > index:
            value, _ = parse_number(" ".join(words[index:end]))
            output.append(str(value) if value is not None else " ".join(words[index:end]))
            index = end
        else:
            output.append(words[index])
            index += 1
    return " ".join(output)


def apply_scoring_masks(reference: str, segments: list[dict], masks: list[dict]) -> tuple[str, str]:
    """Pre-annotated reference lexical token spans and original audio intervals only."""
    from north55_speech.core import SpeechError

    tokens = lexical_normalizer_v1(reference).split()
    excluded: set[int] = set()
    for mask in masks:
        required = {"start_sec", "end_sec", "reference_start_token", "reference_end_token"}
        if not required <= set(mask):
            raise SpeechError(
                "INVALID_SCORING_MASK",
                "Mask needs original time and lexical reference token interval",
            )
        start, end = mask["reference_start_token"], mask["reference_end_token"]
        if not 0 <= start <= end <= len(tokens) or mask["start_sec"] >= mask["end_sec"]:
            raise SpeechError("INVALID_SCORING_MASK", "Scoring mask boundaries are invalid")
        excluded.update(range(start, end))
    words = []
    for segment in segments:
        if segment.get("raw_asr_text", "").strip() and not segment.get("words"):
            raise SpeechError(
                "SCORING_TIMESTAMPS_MISSING", "Masked scoring requires actual word timestamps"
            )
        for word in segment.get("words", []):
            midpoint = (word["start_sec"] + word["end_sec"]) / 2
            if not any(m["start_sec"] <= midpoint < m["end_sec"] for m in masks):
                words.append(word["word"])
    return " ".join(t for i, t in enumerate(tokens) if i not in excluded), " ".join(words)


def diarization_score(
    reference: list[dict], prediction: list[dict], collar=0.25, skip_overlap=False
) -> dict:
    """Exact interval integration with global one-to-one speaker assignment, no identity inference."""
    ref_speakers = sorted({t["speaker_id"] for t in reference})
    pred_speakers = sorted({t["speaker_id"] for t in prediction})
    if not reference:
        return {"der": None, "jer": None, "status": "not_evaluable"}
    boundaries = sorted(
        {
            max(0, t[key] + delta)
            for t in reference + prediction
            for key in ("start_sec", "end_sec")
            for delta in (-collar, 0, collar)
        }
    )
    cells = []
    intersection = np.zeros((len(ref_speakers), len(pred_speakers)))
    ref_durations = np.zeros(len(ref_speakers))
    pred_durations = np.zeros(len(pred_speakers))
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        middle = (start + end) / 2
        if any(
            abs(middle - t[key]) < collar for t in reference for key in ("start_sec", "end_sec")
        ):
            continue
        gold = {t["speaker_id"] for t in reference if t["start_sec"] <= middle < t["end_sec"]}
        pred = {t["speaker_id"] for t in prediction if t["start_sec"] <= middle < t["end_sec"]}
        if skip_overlap and len(gold) > 1:
            continue
        duration = end - start
        cells.append((gold, pred, duration))
        for i, speaker in enumerate(ref_speakers):
            if speaker in gold:
                ref_durations[i] += duration
                for j, other in enumerate(pred_speakers):
                    if other in pred:
                        intersection[i, j] += duration
        for j, speaker in enumerate(pred_speakers):
            if speaker in pred:
                pred_durations[j] += duration
    rows, cols = linear_sum_assignment(-intersection)
    mapping = {pred_speakers[j]: ref_speakers[i] for i, j in zip(rows, cols, strict=True)}
    missed = false_alarm = confusion = total = 0.0
    for gold, pred, duration in cells:
        correct = len(gold & {mapping.get(p) for p in pred})
        missed += max(0, len(gold) - len(pred)) * duration
        false_alarm += max(0, len(pred) - len(gold)) * duration
        confusion += (min(len(gold), len(pred)) - correct) * duration
        total += len(gold) * duration
    unions = ref_durations[:, None] + pred_durations[None, :] - intersection
    jaccard = np.divide(intersection, unions, out=np.zeros_like(intersection), where=unions > 0)
    rows, cols = linear_sum_assignment(-jaccard)
    jer = (len(ref_speakers) - sum(jaccard[i, j] for i, j in zip(rows, cols, strict=True))) / len(
        ref_speakers
    )
    return {
        "der": (missed + false_alarm + confusion) / total if total else None,
        "jer": float(jer),
        "missed_speaker_sec": missed,
        "false_alarm_speaker_sec": false_alarm,
        "confusion_speaker_sec": confusion,
        "reference_speaker_sec": total,
        "collar_sec": collar,
        "skip_overlap": skip_overlap,
        "protocol": "exact_intervals_global_assignment_v1",
        "status": "evaluable" if total else "not_evaluable",
    }


def corpus_counts(rows: list[dict]) -> dict:
    counts = {
        key: sum(r[key] for r in rows)
        for key in ("S", "D", "I", "N", "H", "character_errors", "reference_characters")
    }
    counts["wer_lexical_corpus"] = (
        (counts["S"] + counts["D"] + counts["I"]) / counts["N"] if counts["N"] else None
    )
    counts["cer"] = (
        counts["character_errors"] / counts["reference_characters"]
        if counts["reference_characters"]
        else None
    )
    return counts


def paired_cluster_bootstrap(rows: list[dict], resamples=2000, seed=55, confidence=0.95) -> dict:
    groups: dict[str, Any] = defaultdict(lambda: np.zeros(3, dtype=np.float64))
    for row in rows:
        baseline, candidate = row["baseline"], row["candidate"]
        groups[row["group_id"]] += [
            baseline["S"] + baseline["D"] + baseline["I"],
            candidate["S"] + candidate["D"] + candidate["I"],
            baseline["N"],
        ]
    if not groups:
        return {"lower": None, "upper": None, "independent_groups": 0}
    matrix = np.array([groups[k] for k in sorted(groups)])
    rng = np.random.default_rng(seed)
    deltas = []
    baseline_rates, candidate_rates = [], []
    for _ in range(resamples):
        total = matrix[rng.integers(0, len(matrix), size=len(matrix))].sum(axis=0)
        if total[2]:
            deltas.append((total[1] - total[0]) / total[2])
            baseline_rates.append(total[0] / total[2])
            candidate_rates.append(total[1] / total[2])
    alpha = (1 - confidence) / 2
    low, high = np.quantile(deltas, [alpha, 1 - alpha]) if deltas else [None, None]
    return {
        "lower": None if low is None else float(low),
        "upper": None if high is None else float(high),
        "method": "paired_cluster_bootstrap",
        "seed": seed,
        "resamples": resamples,
        "confidence_level": confidence,
        "independent_groups": len(groups),
        "delta_definition": "candidate - baseline",
        "valid_resamples": len(deltas),
        # Descriptive marginal intervals use exactly the same cluster draws.
        # The release gate still uses the paired delta interval above.
        "system_intervals": {
            system: {
                "lower": float(np.quantile(rates, alpha)) if rates else None,
                "upper": float(np.quantile(rates, 1 - alpha)) if rates else None,
            }
            for system, rates in (("baseline", baseline_rates), ("candidate", candidate_rates))
        },
    }


def temporal_iou(a: dict, b: dict) -> float:
    intersection = max(0, min(a["end_sec"], b["end_sec"]) - max(a["start_sec"], b["start_sec"]))
    union = max(a["end_sec"], b["end_sec"]) - min(a["start_sec"], b["start_sec"])
    return intersection / union if union > 0 else 0


def maximum_matching(compatible: np.ndarray) -> list[tuple[int, int]]:
    if not compatible.size:
        return []
    rows, cols = linear_sum_assignment(-compatible.astype(np.int64))
    return [(int(i), int(j)) for i, j in zip(rows, cols, strict=True) if compatible[i, j]]


def prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "support": tp + fn,
        "status": "evaluable" if tp + fn else "not_evaluable",
    }


def entity_score(reference: list[dict], prediction: list[dict], tolerance_sec: float = 0.5) -> dict:
    def compatible(a, b):
        if a["type"] != b["type"]:
            return False
        return (
            a.get("start_sec", 0) <= b.get("end_sec", 0) + tolerance_sec
            and b.get("start_sec", 0) <= a.get("end_sec", 0) + tolerance_sec
        )

    def equal(a, b):
        return all(
            a.get(key) == b.get(key) for key in ("type", "canonical_value", "unit", "polarity")
        )

    # Anchor/type alignment precedes value scoring. Occurrences ordered locally break ties.
    cost = np.full((len(reference), len(prediction)), 1e6)
    for i, a in enumerate(reference):
        for j, b in enumerate(prediction):
            if compatible(a, b):
                cost[i, j] = abs(a.get("start_sec", 0) - b.get("start_sec", 0)) + abs(i - j) * 0.001
    rows, cols = linear_sum_assignment(cost)
    matched = [(int(i), int(j)) for i, j in zip(rows, cols, strict=True) if cost[i, j] < 1e6]
    substitutions = [(i, j) for i, j in matched if not equal(reference[i], prediction[j])]
    correct = len(matched) - len(substitutions)
    deleted, inserted = len(reference) - len(matched), len(prediction) - len(matched)
    output = prf(correct, inserted + len(substitutions), deleted + len(substitutions))
    output.update(
        C_sub=len(substitutions),
        C_del=deleted,
        C_ins=inserted,
        critical_entity_error_rate=(len(substitutions) + deleted + inserted) / len(reference)
        if reference
        else None,
        confusions=[
            {"reference": reference[i], "prediction": prediction[j]} for i, j in substitutions
        ],
    )
    return output


def temporal_event_score(
    reference: list[dict], prediction: list[dict], duration_sec: float, iou=0.5
) -> dict:
    matrix = np.zeros((len(reference), len(prediction)), dtype=bool)
    for i, gold in enumerate(reference):
        for j, pred in enumerate(prediction):
            matrix[i, j] = (
                bool(set(gold["labels"]) & set(pred["labels"])) and temporal_iou(gold, pred) >= iou
            )
    pairs = maximum_matching(matrix)
    result = prf(len(pairs), len(prediction) - len(pairs), len(reference) - len(pairs))
    result["false_positives_per_audio_hour"] = (
        result["fp"] / (duration_sec / 3600) if duration_sec else None
    )
    result["matching"] = "one_to_one_class_compatible_maximum_matching"
    result["minimum_temporal_iou"] = iou
    return result


def multilabel_score(gold: list[list[str]], predicted: list[list[str]], labels: list[str]) -> dict:
    y = np.array([[label in values for label in labels] for values in gold], dtype=int)
    p = np.array([[label in values for label in labels] for values in predicted], dtype=int)
    if not gold:
        return {"macro_f1": None, "micro_f1": None, "per_label": {}}
    precision, recall, f1, support = precision_recall_fscore_support(
        y, p, average=None, zero_division=0
    )
    confusion = multilabel_confusion_matrix(y, p)
    per_label = {
        label: {
            "precision": float(precision[i]),
            "recall": float(recall[i]) if support[i] else None,
            "f1": float(f1[i]) if support[i] else None,
            "support": int(support[i]),
            "confusion_matrix": confusion[i].tolist(),
            "status": "evaluable" if support[i] else "not_evaluable",
        }
        for i, label in enumerate(labels)
    }
    return {
        "macro_f1": float(f1.mean()) if all(support) else None,
        "micro_f1": float(
            precision_recall_fscore_support(y, p, average="micro", zero_division=0)[2]
        ),
        "per_label": per_label,
    }


def salience_score(gold: list[bool], predictions: list[bool | str]) -> dict:
    tp = fp = fn = tn = unknown = 0
    for g, p in zip(gold, predictions, strict=True):
        if p == "unknown" or p is None:
            unknown += 1
            if g:
                fn += 1
        elif p:
            tp += int(g)
            fp += int(not g)
        else:
            fn += int(g)
            tn += int(not g)
    return prf(tp, fp, fn) | {
        "tn": tn,
        "unknown": unknown,
        "coverage": (len(gold) - unknown) / len(gold) if gold else 0,
    }
