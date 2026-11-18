import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from h2.cloudru_continuation import combine, verify_archive
from h2.cloudru_main import matrix


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_archive_verification_rejects_changed_sealed_evidence(tmp_path):
    evidence = tmp_path / "row.json"
    evidence.write_text("original")
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(hashlib.sha256(evidence.read_bytes()).hexdigest() + "  row.json\n")
    write(tmp_path / "sealed.json", {"files": 1, "sha256_manifest": hashlib.sha256(manifest.read_bytes()).hexdigest()})
    assert verify_archive(tmp_path)["files"] == 1
    evidence.write_text("modified")
    with pytest.raises(ValueError, match="Parent archive changed"):
        verify_archive(tmp_path)


@pytest.mark.parametrize("paired_sessions", [False, True])
@pytest.mark.parametrize("cost_improves", [False, True])
def test_combined_criteria_and_session_policy_are_reported_separately(tmp_path, paired_sessions, cost_improves):
    parent, current = tmp_path / "parent", tmp_path / "current"
    trials = matrix()
    plan = {"trials": trials, "bootstrap_seed": 20261005, "bootstrap_samples": 200,
        "required_on_time_rate": .95, "on_time_noninferiority_margin": .02}
    rows = [{"trial": spec["id"], "valid": True, "lifecycle_complete": True,
        "accepted": 24, "completed": 24, "correct": 24, "on_time": 24,
        "cost_lower_rub": (1 if cost_improves else 3) if spec["variant"] == "work" else 2,
        "cost_upper_rub": (1.01 if cost_improves else 3.01) if spec["variant"] == "work" else 2.01} for spec in trials[:24]]
    write(current / "plan.json", {"continuation_parent": str(parent)})
    write(current / "main/rows.json", rows[12:])
    if paired_sessions:
        write(current / "main/plan.json", {"continuation": {"pair_restart": {
            "policy": "complete-pairs-across-sessions-v1", "disclosure": "Both strategies within each session."}}})
    for directory, batch in ((parent, rows[:12]), (current, rows[12:])):
        write(directory / "main/frozen.json", {"plan_sha256": "retained-plan"})
        for row in batch:
            for name in ("timeline.jsonl", "submitted.json"):
                write(directory / "trials" / row["trial"] / name, [])
    (current / "main/PLAN.md").write_text("Protocol deviation disclosed")
    with patch("h2.cloudru_continuation.parent_evidence", return_value=(plan, rows[:12], {})), \
         patch("h2.cloudru_continuation.report") as report:
        result = combine(current)
    assert result["complete"] and result["original_numerical_criteria_met"] == cost_improves
    assert result["h2_confirmed"] == (paired_sessions and cost_improves)
    assert not result["confirmatory"]
    assert result["protocol_deviations"]
    report.assert_called_once_with(current / "combined")
    saved = json.loads((current / "combined/main/rows.json").read_text())
    assert [r["trial"] for r in saved] == [r["trial"] for r in rows]
    assert {r["source_run"] for r in saved} == {str(parent), str(current)}


def test_combination_rejects_replayed_trials(tmp_path):
    parent, current = tmp_path / "parent", tmp_path / "current"
    trials = matrix()
    row = {"trial": trials[0]["id"]}
    write(current / "plan.json", {"continuation_parent": str(parent)})
    write(current / "main/rows.json", [row])
    with patch("h2.cloudru_continuation.parent_evidence", return_value=({"trials": trials}, [row], {})):
        with pytest.raises(ValueError, match="without duplicates"):
            combine(current)
    assert not (current / "combined").exists()
