"""Manually calculable metric fixtures, never a benchmark report."""

import pytest

from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    entity_score,
    lexical_normalizer_v1,
    multilabel_score,
    paired_cluster_bootstrap,
    salience_score,
    temporal_event_score,
)


def test_edit_counts_and_corpus_weighting():
    a = edit_counts("a b c", "a x c d")
    assert (a["S"], a["D"], a["I"], a["N"]) == (1, 0, 1, 3)
    b = edit_counts("one two three four five six seven", "one two three four five six seven")
    assert corpus_counts([a, b])["wer_lexical_corpus"] == 0.2
    assert edit_counts("a b", "")["D"] == 2


def test_empty_reference_insertions():
    result = edit_counts("", "invented words")
    assert result["I"] == 2 and result["wer"] is None
    assert edit_counts("", "")["I"] == 0


def test_normalizer_preserves_critical_information():
    assert lexical_normalizer_v1("NOT 3.5 feet—below!") == "not 3.5 feet below"
    assert lexical_normalizer_v1("don't") == "don't"
    assert lexical_normalizer_v1("15") != lexical_normalizer_v1("fifteen")


def ent(value, polarity="affirmative"):
    return {
        "type": "flaps_setting",
        "canonical_value": value,
        "unit": None,
        "polarity": polarity,
        "start_sec": 0,
        "end_sec": 1,
    }


def test_occurrence_entity_scoring():
    result = entity_score([ent(15), ent(15)], [ent(15)])
    assert result["tp"] == 1 and result["C_del"] == 1
    wrong = entity_score([ent(15)], [ent(50)])
    assert wrong["C_sub"] == 1 and wrong["C_ins"] == 0 and wrong["critical_entity_error_rate"] == 1
    assert entity_score([ent(15)], [ent(15, "negated")])["C_sub"] == 1
    assert entity_score([ent(15)], [ent(50), ent(50), ent(50)])["critical_entity_error_rate"] == 3


def test_temporal_duplicate_is_false_positive():
    event = {"start_sec": 2, "end_sec": 4, "labels": ["CHECKLIST"]}
    result = temporal_event_score([event], [event, event], 3600)
    assert result["tp"] == 1 and result["fp"] == 1 and result["false_positives_per_audio_hour"] == 1


def test_absent_label_not_perfect_score():
    result = multilabel_score(
        [["CHECKLIST"]], [["CHECKLIST"]], ["CHECKLIST", "CONFIGURATION_MENTION"]
    )
    assert result["macro_f1"] is None
    assert result["per_label"]["CONFIGURATION_MENTION"]["status"] == "not_evaluable"


def test_unknown_salience_not_true_negative():
    result = salience_score([True, False], ["unknown", "unknown"])
    assert result["tn"] == 0 and result["fn"] == 1 and result["unknown"] == 2


def test_bootstrap_paired_group_seed():
    rows = [
        {
            "group_id": str(i // 2),
            "baseline": edit_counts("a b c", "a x c"),
            "candidate": edit_counts("a b c", "a b c"),
        }
        for i in range(10)
    ]
    first = paired_cluster_bootstrap(rows)
    assert first == paired_cluster_bootstrap(rows)
    assert first["upper"] == pytest.approx(-1 / 3)
    assert first["independent_groups"] == 5
