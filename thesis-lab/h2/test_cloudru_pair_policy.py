from copy import deepcopy

import pytest

from h2.cloudru_main import matrix
from h2.cloudru_pair_policy import restart_pair, session_summary


@pytest.mark.parametrize("correct,cost", [(24, 1), (0, 1000)])
def test_pair_restart_selection_does_not_depend_on_favorable_outcomes(correct, cost):
    specs = matrix()
    done = [{"trial": s["id"]} for s in specs[:12]]
    previous = [{"trial": specs[12]["id"], "correct": correct, "cost_upper_rub": cost}]
    failure = {"trial": specs[13]["id"], "error": "mk8s: HTTP None"}
    assert restart_pair({"trials": specs}, done, previous, failure) == [s["id"] for s in specs[12:14]]


def test_workload_failure_cannot_be_reclassified_as_preparation_restart():
    specs = matrix()
    with pytest.raises(ValueError, match="pre-admission"):
        restart_pair({"trials": specs}, [{"trial": s["id"]} for s in specs[:12]],
            [{"trial": specs[12]["id"]}], {"trial": specs[13]["id"], "error": "incorrect ASR result"})


def test_extra_completed_attempts_cannot_be_silently_discarded():
    specs = matrix()
    with pytest.raises(ValueError, match="one retained"):
        restart_pair({"trials": specs}, [{"trial": s["id"]} for s in specs[:12]],
            [{"trial": s["id"]} for s in specs[12:14]], {"trial": specs[14]["id"], "error": "mk8s: HTTP None"})


def test_pair_cannot_be_assembled_across_different_clusters():
    specs = matrix()
    row = {"accepted": 24, "correct": 24, "on_time": 24, "cost_lower_rub": 1, "cost_upper_rub": 1.1}
    with pytest.raises(ValueError, match="crosses session"):
        session_summary({"trials": specs}, (("old", [{**row, "trial": specs[0]["id"]}]),
            ("new", [{**row, "trial": specs[1]["id"]}])))
