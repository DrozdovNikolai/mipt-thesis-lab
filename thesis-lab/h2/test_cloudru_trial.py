"""Checks for orphan-cost accounting and independent deadline guard behavior."""
import io
import json
from unittest.mock import patch

import pytest

from h2.cloudru_setup import GUARD
from h2.cloudru_trial import normalize_inventory


def test_orphan_disk_still_costs_money_after_its_vm_disappears():
    known = set()
    disk = {"id": "disk", "created_time": "2026-10-14T00:00:00Z", "size": 40,
            "disk_type": {"name": "SSD"}, "vms": [{"id": "vm"}]}
    vm = {"id": "vm", "created_time": "2026-10-14T00:00:00Z", "state": "running", "interfaces": [],
          "flavor": {"id": "f", "cpu": 2, "ram": 4, "gpu": 0, "oversubscription": "1:1"}}
    instances, disks = normalize_inventory([vm], [disk], {"vm"}, known, flavor_id="f")
    assert len(instances) == len(disks) == 1
    disk["vms"] = []
    instances, disks = normalize_inventory([], [disk], {"vm"}, known, flavor_id="f")
    assert not instances and disks[0]["id"] == "disk"


def test_changed_flavor_or_stopped_vm_cannot_be_silently_costed_as_running():
    vm = {"id": "vm", "created_time": "2026-10-14T00:00:00Z", "state": "stopped", "interfaces": [],
          "flavor": {"id": "f", "cpu": 2, "ram": 4, "gpu": 0, "oversubscription": "1:1"}}
    with pytest.raises(ValueError, match="state"):
        normalize_inventory([vm], [], {"vm"}, set(), flavor_id="f")
    vm["state"] = "running"
    vm["flavor"]["oversubscription"] = "1:3"
    with pytest.raises(ValueError, match="allocation"):
        normalize_inventory([vm], [], {"vm"}, set(), flavor_id="f")


def test_workload_cannot_be_declared_complete_after_wrong_node_placement(tmp_path):
    from h2.cloudru_trial import Trial
    from h2.cloud_trial import Trial as BaseTrial
    from types import SimpleNamespace
    from unittest.mock import Mock
    trial = Trial.__new__(Trial)
    trial.id = "pilot-check"
    trial.output = tmp_path
    trial.known_nodes = {"vm-owned"}
    trial.cloud = SimpleNamespace(state={"groups": {trial.id: {"id": "owned-pool"}}})
    trial.api = Mock(return_value={"completed": 1})
    with patch.object(BaseTrial, "observe", return_value={"pods": [{"node": "vm-system"}]}):
        with pytest.raises(ValueError, match="outside"):
            trial.observe()
    with pytest.raises(ValueError, match="outside"):
        trial.wait_completed(1)
    trial.api.assert_not_called()
    assert (tmp_path / "placement-failure.json").exists()


def test_guard_before_deadline_does_not_even_read_credentials():
    with patch.dict("os.environ", {"DEADLINE": "2099-01-01T00:00:00+00:00"}), patch("sys.argv", ["guard.py"]), \
         patch("builtins.open") as opening, patch("urllib.request.build_opener") as network:
        with pytest.raises(SystemExit) as error:
            exec(compile(GUARD, "guard.py", "exec"), {})
        assert error.value.code == 0
        opening.assert_not_called()
        network.assert_not_called()


def test_invalid_vm_lifecycle_cannot_be_hidden_as_a_transient_failed_poll(tmp_path):
    from h2.cloudru_trial import Trial
    from h2.cloud_trial import Trial as BaseTrial
    from unittest.mock import Mock
    trial = Trial.__new__(Trial)
    trial.output = tmp_path
    trial.api = Mock(return_value={"completed": 1})
    with patch.object(BaseTrial, "observe", side_effect=ValueError("Unexpected VM state: stopped")):
        with pytest.raises(ValueError, match="VM state"):
            trial.observe()
    with pytest.raises(ValueError, match="VM state"):
        trial.wait_completed(1)
    trial.api.assert_not_called()
    assert (tmp_path / "validation-failure.json").exists()


@pytest.mark.parametrize("wrong_cluster", [False, True])
def test_guard_verifies_ownership_before_stopping(wrong_cluster):
    cluster = {"id": "other" if wrong_cluster else "cluster", "name": "owned", "projectId": "project",
               "status": "OBJECT_STATUS_RUNNING"}
    responses = [{"access_token": "temporary-token"}, cluster, {"id": "operation"}]
    calls = []
    def opening(request, timeout):
        calls.append(request)
        return io.BytesIO(json.dumps(responses[len(calls) - 1]).encode())
    profile = {"project_id": "project", "key_id": "key", "key_secret": "secret"}
    with patch.dict("os.environ", {"DEADLINE": "2000-01-01T00:00:00+00:00", "CLUSTER_ID": "cluster", "CLUSTER_NAME": "owned"}), \
         patch("sys.argv", ["guard.py"]), patch("builtins.open", return_value=io.StringIO(json.dumps(profile))), \
         patch("urllib.request.build_opener") as network:
        network.return_value.open.side_effect = opening
        if wrong_cluster:
            with pytest.raises(AssertionError):
                exec(compile(GUARD, "guard.py", "exec"), {})
            assert len(calls) == 2
        else:
            exec(compile(GUARD, "guard.py", "exec"), {})
            assert calls[-1].full_url.endswith("/cluster:stop")
            assert json.loads(calls[-1].data) == {"clusterId": "cluster"}
