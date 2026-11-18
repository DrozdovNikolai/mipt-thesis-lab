"""Hand-calculable presentation fixtures; never scientific benchmark evidence."""

import csv
import json

import pytest

from north55_speech.metrics import (
    edit_counts,
    entity_score,
    multilabel_score,
    paired_cluster_bootstrap,
)
from north55_speech.reporting import event_rows, write_csv, write_report


def row(group="g", primary=True):
    item = {
        "sample_id": "=malicious()",
        "group_id": group,
        "language": "en",
        "condition": "clean",
        "primary": primary,
        "clean_control": not primary,
        "non_speech": False,
        "duration_sec": 10,
    }
    for system, text in (("baseline", "flaps fifty"), ("candidate", "flaps fifteen")):
        item[system] = {
            **edit_counts("flaps fifteen", text),
            "hypothesis": text,
            "runtime_failure": False,
            "entities": entity_score([], []),
            "timing": {"end_to_end_sec": 2, "asr_sec": 1, "end_to_end_rtf": 0.2, "asr_rtf": 0.1},
        }
    return item


def test_empty_report_has_contract_and_explicit_unmeasured(tmp_path):
    write_report(tmp_path, {}, [], {"asr_quality_gate": {"status": "NEEDS_MORE_DATA"}})
    expected = {
        "metrics.json",
        "gate.json",
        "per-sample-predictions.json",
        "per-sample.csv",
        "timing.csv",
        "group-metrics.csv",
        "entity-confusions.csv",
        "event-metrics.csv",
        "event-metrics.json",
        "figures.json",
        "report.md",
        "report.html",
    }
    assert expected <= {p.name for p in tmp_path.iterdir()}
    assert not list((tmp_path / "figures").glob("*.png"))
    assert all(
        f["status"] == "NOT_MEASURED" for f in json.loads((tmp_path / "figures.json").read_text())
    )
    with (tmp_path / "event-metrics.csv").open() as stream:
        values = list(csv.DictReader(stream))
    assert len(values) == 9
    assert all(v["status"] == "NOT_RUN" and v["f1"] == "" for v in values)
    assert "не измерено" in (tmp_path / "report.html").read_text(encoding="utf-8")


def test_report_preserves_counts_hypotheses_and_escapes_untrusted_metadata(tmp_path):
    item = row()
    item["candidate"]["hypothesis"] = "<script>alert(1)</script>"
    write_report(
        tmp_path,
        {"note": "<script>alert(1)</script>"},
        [item],
        {"<script>": {"status": "<script>"}},
    )
    with (tmp_path / "per-sample.csv").open() as stream:
        values = list(csv.DictReader(stream))
    assert values[0]["sample_id"] == "'=malicious()"
    assert (values[0]["S"], values[0]["D"], values[0]["I"], values[0]["N"]) == ("1", "0", "0", "2")
    assert values[1]["hypothesis"] == item["candidate"]["hypothesis"]
    assert json.loads((tmp_path / "per-sample-predictions.json").read_text()) == [item]
    assert "<script>" not in (tmp_path / "report.html").read_text(encoding="utf-8")
    write_csv(tmp_path / "signed.csv", ["text", "number"], [{"text": "-formula", "number": -0.2}])
    assert "'-formula,-0.2" in (tmp_path / "signed.csv").read_text()


def test_marginal_ci_uses_same_seed_and_cluster_draws():
    rows = [row(str(i)) for i in range(3)]
    value = paired_cluster_bootstrap(rows)
    assert value == paired_cluster_bootstrap(rows)
    assert value["lower"] == value["upper"] == -0.5
    assert value["system_intervals"] == {
        "baseline": {"lower": 0.5, "upper": 0.5},
        "candidate": {"lower": 0.0, "upper": 0.0},
    }
    assert value["valid_resamples"] == 2000 and value["independent_groups"] == 3


def test_measured_plots_and_primary_runtime_exclude_control(tmp_path):
    primary = row()
    control = row("control", False)
    control["baseline"]["timing"]["end_to_end_sec"] = 1000
    report = {
        "baseline_wer": 0.5,
        "candidate_wer": 0.0,
        "delta_ci": paired_cluster_bootstrap([primary]),
    }
    write_report(tmp_path, report, [primary, control], {})
    outputs = {o["name"]: o for o in json.loads((tmp_path / "figures.json").read_text())}
    assert outputs["wer-ci"]["data"]["ci"]["system_intervals"]["candidate"]["upper"] == 0
    assert [p["rtf"] for p in outputs["quality-runtime"]["data"]] == [0.2, 0.2]
    for name in ("wer-ci", "critical-entities", "quality-runtime"):
        assert outputs[name]["status"] == "MEASURED"
        assert all((tmp_path / p).stat().st_size > 1000 for p in outputs[name]["files"])


@pytest.mark.parametrize("block", ["missing_annotations", "integrity_errors"])
def test_unverified_quality_cannot_become_graph(tmp_path, block):
    report = {"baseline_wer": 0.5, "candidate_wer": 0.0, block: ["unverified"]}
    write_report(tmp_path, report, [row()], {})
    outputs = json.loads((tmp_path / "figures.json").read_text())
    assert all(o["status"] == "NOT_MEASURED" for o in outputs)


def test_events_distinguish_input_and_absent_support(tmp_path):
    scored = multilabel_score([["CHECKLIST"]], [["CHECKLIST"]], ["CHECKLIST", "CREW_COORDINATION"])
    events = {
        "rules_human_text": scored,
        "candidate_human_text": scored,
        "end_to_end": {"candidate": scored},
        "baseline_asr_to_same_frozen_nlp": {"candidate": scored},
    }
    rows = event_rows(events)
    assert {r["input"] for r in rows if r["label"] == "CHECKLIST"} == {
        "human_text",
        "candidate_asr",
        "baseline_asr",
    }
    absent = [r for r in rows if r["label"] == "CREW_COORDINATION"]
    assert absent and all(r["f1"] is None and r["status"] == "not_evaluable" for r in absent)
    assert all(r["task"] != "temporal_detection" for r in rows)
    write_report(tmp_path, {}, [], {}, events)
    outputs = json.loads((tmp_path / "figures.json").read_text())
    assert (
        len([o for o in outputs if o["name"].startswith("events-") and o["status"] == "MEASURED"])
        == 4
    )


def test_unscored_runtime_is_not_quality_plot(tmp_path):
    write_report(tmp_path, {"runtime_trials": [{"trial": "A0", "rtf": 0.25}]}, [], {})
    outputs = json.loads((tmp_path / "figures.json").read_text())
    assert [o["name"] for o in outputs if o["status"] == "MEASURED"] == ["dev-runtime"]
