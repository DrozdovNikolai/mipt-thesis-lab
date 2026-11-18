from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from h2 import cloudru_pool_recovery as recovery
from h2.cloudru_ops import node_pool_request
from h2.cloudru_preflight import CloudruError


def fixture(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(recovery.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(recovery.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    body = node_pool_request("cluster", "subnet", "flavor", "unique_pool")
    actual = deepcopy(body)
    actual.update(id="pool-id", status="OBJECT_STATUS_PROVISIONING")
    actual["machineConfiguration"] = {"flavor": {"flavorId": "flavor"}, "disk": body["machineConfiguration"]["disk"]}
    objects = []
    def read(service, path, query=None):
        if path == "/v3/clusters/cluster":
            return {"id": "cluster", "name": "owned", "projectId": "project", "status": "OBJECT_STATUS_RUNNING"}
        if path == "/v3/nodePools":
            return {"nodePools": list(objects)}
        if path == "/v3/nodePools/pool-id":
            return deepcopy(actual)
        raise AssertionError(path)
    cloud = SimpleNamespace(state={"cluster": {"id": "cluster", "name": "owned"}},
        client=SimpleNamespace(project_id="project", request=Mock(side_effect=read)),
        ensure_time=Mock(), mutate=Mock(), event=Mock())
    return cloud, body, actual, objects, clock


def test_lost_create_response_adopts_existing_identical_pool_without_repeating(monkeypatch):
    c, body, actual, objects, clock = fixture(monkeypatch)
    def create(*a, **kw):
        objects.append(actual)
        raise CloudruError("mk8s", None, {})
    c.mutate.side_effect = create
    op, adopted = recovery.create_pool(c, "main-trial", body)
    assert op is None and adopted["id"] == "pool-id"
    assert c.mutate.call_count == 1


def test_empty_success_response_is_reconciled_instead_of_creating_a_duplicate(monkeypatch):
    c, body, actual, objects, clock = fixture(monkeypatch)
    def create(*a, **kw):
        objects.append(actual)
        return {}
    c.mutate.side_effect = create
    assert recovery.create_pool(c, "main-trial", body)[1]["id"] == "pool-id"
    assert c.mutate.call_count == 1


def test_retry_waits_for_two_minutes_of_confirmed_absence_and_keeps_same_body(monkeypatch):
    c, body, actual, objects, clock = fixture(monkeypatch)
    attempts = []
    def create(*a, **kw):
        attempts.append((clock[0], deepcopy(kw["body"])))
        if len(attempts) == 1:
            raise CloudruError("mk8s", None, {})
        return {"id": "operation", "resourceId": "pool-id"}
    c.mutate.side_effect = create
    op, adopted = recovery.create_pool(c, "main-trial", body)
    assert op["resourceId"] == "pool-id" and adopted is None
    assert attempts[1][0] - attempts[0][0] >= 120
    assert attempts[0][1] == attempts[1][1] == body


def test_delayed_visibility_prevents_a_second_create(monkeypatch):
    c, body, actual, objects, clock = fixture(monkeypatch)
    original = c.client.request.side_effect
    def read(*args, **kw):
        if clock[0] >= 60 and not objects:
            objects.append(actual)
        return original(*args, **kw)
    c.client.request.side_effect = read
    c.mutate.side_effect = CloudruError("mk8s", 500, {})
    assert recovery.create_pool(c, "main-trial", body)[1]["id"] == "pool-id"
    assert c.mutate.call_count == 1


@pytest.mark.parametrize("change", ["allocation", "identity", "duplicate", "cluster"])
def test_wrong_or_ambiguous_resource_is_never_adopted(monkeypatch, change):
    c, body, actual, objects, clock = fixture(monkeypatch)
    objects.append(actual)
    if change == "allocation":
        actual["machineConfiguration"]["disk"] = {"typeName": "SSD", "size": 80}
    elif change == "identity":
        actual["name"] = "changed"
        # Listing still points at the requested name, detail read differs.
        objects[0] = {**actual, "name": body["name"]}
    elif change == "duplicate":
        objects.append(actual)
    else:
        actual["clusterId"] = "another"
    c.mutate.side_effect = CloudruError("mk8s", None, {})
    with pytest.raises(ValueError):
        recovery.create_pool(c, "main-trial", body)
    assert c.mutate.call_count == 1


def test_failed_inventory_never_authorizes_another_create(monkeypatch):
    c, body, actual, objects, clock = fixture(monkeypatch)
    c.mutate.side_effect = CloudruError("mk8s", None, {})
    c.client.request.side_effect = CloudruError("mk8s", 503, {})
    with pytest.raises(TimeoutError):
        recovery.create_pool(c, "main-trial", body)
    assert c.mutate.call_count == 1


def test_persistent_create_failure_is_bounded(monkeypatch):
    c, body, actual, objects, clock = fixture(monkeypatch)
    c.mutate.side_effect = CloudruError("mk8s", None, {})
    with pytest.raises(TimeoutError):
        recovery.create_pool(c, "main-trial", body)
    assert c.mutate.call_count == 3 and clock[0] <= 905


def test_permission_error_is_not_retried(monkeypatch):
    c, body, actual, objects, clock = fixture(monkeypatch)
    c.mutate.side_effect = CloudruError("mk8s", 403, {})
    with pytest.raises(CloudruError):
        recovery.create_pool(c, "main-trial", body)
    c.mutate.assert_called_once()
    c.client.request.assert_not_called()
