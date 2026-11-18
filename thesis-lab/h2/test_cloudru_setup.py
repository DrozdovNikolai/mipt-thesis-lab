import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from h2 import cloudru_setup as setup
from h2.cloudru_preflight import CloudruError


def fake_cloud(tmp_path, monkeypatch):
    clock = [0]
    monkeypatch.setattr(setup.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(setup.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    status = {"value": "OBJECT_STATUS_STOPPED"}
    cloud = SimpleNamespace(run=tmp_path, state={"cluster": {"id": "id", "name": "owned"}}, ensure_time=Mock(),
        client=SimpleNamespace(project_id="p", request=Mock(side_effect=lambda *a: {"id": "id", "name": "owned", "projectId": "p", "status": status["value"]})),
        mutate=Mock(), wait_operation=Mock())
    return cloud, clock, status


def test_ambiguous_resume_is_not_repeated_when_cluster_already_started(tmp_path, monkeypatch):
    cloud, clock, status = fake_cloud(tmp_path, monkeypatch)
    def accepted_but_lost(*a, **kw):
        assert clock[0] >= 120
        status["value"] = "OBJECT_STATUS_RUNNING"
        raise CloudruError("mk8s", 500, {"message": "ambiguous response"})
    cloud.mutate.side_effect = accepted_but_lost
    setup.resume_after_guard(cloud)
    assert cloud.mutate.call_count == 1
    assert (tmp_path / "resume-response-error-1.json").exists()


def test_transient_resume_retries_only_after_another_stable_stopped_interval(tmp_path, monkeypatch):
    cloud, clock, status = fake_cloud(tmp_path, monkeypatch)
    attempts = []
    def resume(*a, **kw):
        attempts.append(clock[0])
        if len(attempts) == 1:
            raise CloudruError("mk8s", 500, {"message": "temporarily unavailable"})
        status["value"] = "OBJECT_STATUS_RUNNING"
        return {"id": "operation"}
    cloud.mutate.side_effect = resume
    setup.resume_after_guard(cloud)
    assert len(attempts) == 2 and attempts[1] - attempts[0] >= 120
    assert cloud.wait_operation.call_count == 1


def test_resume_retries_are_bounded(tmp_path, monkeypatch):
    cloud, clock, status = fake_cloud(tmp_path, monkeypatch)
    cloud.mutate.side_effect = CloudruError("mk8s", 500, {"message": "persistent failure"})
    with pytest.raises(RuntimeError, match="three reconciled"):
        setup.resume_after_guard(cloud)
    assert cloud.mutate.call_count == 3


def test_changed_cluster_identity_prevents_resume(tmp_path, monkeypatch):
    cloud, clock, status = fake_cloud(tmp_path, monkeypatch)
    cloud.client.request.side_effect = None
    cloud.client.request.return_value = {"id": "different", "name": "owned", "projectId": "p", "status": "OBJECT_STATUS_STOPPED"}
    with pytest.raises(ValueError, match="identity"):
        setup.resume_after_guard(cloud)
    cloud.mutate.assert_not_called()


def stop_cloud(tmp_path, monkeypatch):
    cloud, clock, status = fake_cloud(tmp_path, monkeypatch)
    status["value"] = "OBJECT_STATUS_RUNNING"
    cloud.client.redact = lambda value: value
    cloud.kube = Mock()
    cloud.record = Mock()
    return cloud, clock, status


def test_guard_retries_dns_failure_after_reconciling_a_still_running_cluster(tmp_path, monkeypatch):
    cloud, clock, status = stop_cloud(tmp_path, monkeypatch)
    attempts = []
    def execute(*args, **kwargs):
        attempts.append(clock[0])
        if len(attempts) == 1:
            raise RuntimeError("Temporary failure in name resolution")
        status["value"] = "OBJECT_STATUS_STOPPED"
        return json.dumps({"stop_requested": True, "operation_id": "op"})
    cloud.kube.side_effect = execute
    setup.exercise_guard(cloud)
    assert len(attempts) == 2 and attempts[1] - attempts[0] >= 120
    assert cloud.state["guard_stop_verified_at"]
    assert (tmp_path / "guard-stop-exec-error-1.json").exists()
    cloud.mutate.assert_not_called()  # The local client never masquerades as the remote guard.


def test_lost_exec_response_does_not_repeat_a_stop_already_in_progress(tmp_path, monkeypatch):
    cloud, clock, status = stop_cloud(tmp_path, monkeypatch)
    def execute(*args, **kwargs):
        status["value"] = "OBJECT_STATUS_STOPPING"
        raise RuntimeError("Connection interrupted after request")
    cloud.kube.side_effect = execute
    def actual(*args):
        value = status["value"]
        if value == "OBJECT_STATUS_STOPPING":
            status["value"] = "OBJECT_STATUS_STOPPED"
        return {"id": "id", "name": "owned", "projectId": "p", "status": value}
    cloud.client.request.side_effect = actual
    setup.exercise_guard(cloud)
    cloud.kube.assert_called_once()
    assert cloud.state["guard_stop_verified_at"]


def test_failed_guard_attempts_are_bounded_and_do_not_count_as_a_pass(tmp_path, monkeypatch):
    cloud, clock, status = stop_cloud(tmp_path, monkeypatch)
    cloud.kube.side_effect = RuntimeError("DNS unavailable")
    with pytest.raises(RuntimeError, match="three reconciled"):
        setup.exercise_guard(cloud)
    assert cloud.kube.call_count == 3
    assert not cloud.state.get("guard_stop_verified_at")
    cloud.record.assert_not_called()


def test_guard_acknowledgement_alone_is_not_proof_of_an_actual_stop(tmp_path, monkeypatch):
    cloud, clock, status = stop_cloud(tmp_path, monkeypatch)
    cloud.kube.return_value = json.dumps({"stop_requested": True, "operation_id": "op"})
    with pytest.raises(TimeoutError, match="within 15 minutes"):
        setup.exercise_guard(cloud)
    cloud.kube.assert_called_once()
    assert not cloud.state.get("guard_stop_verified_at")


def test_changed_identity_blocks_remote_guard_execution(tmp_path, monkeypatch):
    cloud, clock, status = stop_cloud(tmp_path, monkeypatch)
    cloud.client.request.side_effect = None
    cloud.client.request.return_value = {"id": "other", "name": "owned", "projectId": "p", "status": "OBJECT_STATUS_RUNNING"}
    with pytest.raises(ValueError, match="identity"):
        setup.exercise_guard(cloud)
    cloud.kube.assert_not_called()


def test_guard_host_aliases_remove_external_dns_dependency_only_for_api_hosts(tmp_path, monkeypatch):
    mapping = {"iam.api.cloud.ru": "37.44.197.215", "mk8s.api.cloud.ru": "37.18.10.199"}
    monkeypatch.setattr(setup.socket, "getaddrinfo", lambda host, port, **kw: [(2, 1, 6, "", (mapping[host], port))])
    cloud = SimpleNamespace(run=tmp_path, state={"groups": {"system": {"id": "pool"}},
        "cluster": {"id": "id", "name": "owned"}, "deadline": "2026-10-16T00:00:00+00:00"})
    objects = setup.guard_objects(cloud, "frozen-image")
    pod = objects[2]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["dnsPolicy"] == "ClusterFirst" and "dnsConfig" not in pod
    assert {row["hostnames"][0]: row["ip"] for row in pod["hostAliases"]} == mapping
    assert "https://iam.api.cloud.ru/" in objects[1]["data"]["guard.py"]
    assert json.loads((tmp_path / "guard-api-addresses.json").read_text())["tls_hostname_verification"]


def test_internal_dns_address_is_rejected_before_a_guard_can_be_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.socket, "getaddrinfo", lambda *args, **kw: [(2, 1, 6, "", ("10.0.0.1", 443))])
    with pytest.raises(ValueError, match="public IPv4"):
        setup.guard_api_addresses(SimpleNamespace(run=tmp_path))


def test_post_resume_access_read_retries_a_transient_500_without_repeating_resume(tmp_path, monkeypatch):
    cloud, clock, status = fake_cloud(tmp_path, monkeypatch)
    status["value"] = "OBJECT_STATUS_RUNNING"
    cloud.refresh_kubeconfig = Mock(side_effect=[CloudruError("mk8s", 500, {}), None])
    setup.refresh_access_after_resume(cloud)
    assert cloud.refresh_kubeconfig.call_count == 2 and clock[0] >= 10
    cloud.mutate.assert_not_called()
    evidence = [json.loads(line) for line in (tmp_path / "kube-access-readiness.jsonl").read_text().splitlines()]
    assert [x["available"] for x in evidence] == [False, True]


def test_post_resume_access_does_not_retry_permission_failure(tmp_path, monkeypatch):
    cloud, clock, status = fake_cloud(tmp_path, monkeypatch)
    status["value"] = "OBJECT_STATUS_RUNNING"
    cloud.refresh_kubeconfig = Mock(side_effect=CloudruError("mk8s", 403, {}))
    with pytest.raises(CloudruError):
        setup.refresh_access_after_resume(cloud)
    cloud.refresh_kubeconfig.assert_called_once()


def test_post_resume_access_retries_are_bounded(tmp_path, monkeypatch):
    cloud, clock, status = fake_cloud(tmp_path, monkeypatch)
    status["value"] = "OBJECT_STATUS_RUNNING"
    cloud.refresh_kubeconfig = Mock(side_effect=CloudruError("mk8s", 500, {}))
    with pytest.raises(TimeoutError, match="bounded post-resume"):
        setup.refresh_access_after_resume(cloud)
    assert cloud.refresh_kubeconfig.call_count == 6
    cloud.mutate.assert_not_called()


def test_restore_only_the_original_system_node_after_resume_left_zero(tmp_path):
    cluster = {"id": "c", "name": "owned", "projectId": "p", "status": "OBJECT_STATUS_RUNNING"}
    group = {"id": "g", "name": "system", "clusterId": "c", "scalePolicy": {"fixedScale": {"count": 0}},
             "machineConfiguration": {"flavor": "same", "disk": 40}}
    cloud = SimpleNamespace(run=tmp_path, state={"cluster": {"id": "c", "name": "owned"},
        "groups": {"system": {"id": "g", "name": "system"}}, "guard_stop_verified_at": "verified"},
        client=SimpleNamespace(project_id="p", request=Mock(side_effect=[cluster, group,
            {**group, "scalePolicy": {"fixedScale": {"count": 1}}}])),
        ensure_time=Mock(), mutate=Mock(return_value={"id": "op"}), wait_operation=Mock())
    setup.ensure_system_capacity(cloud)
    call = cloud.mutate.call_args
    assert call.kwargs["method"] == "PATCH"
    assert call.kwargs["body"] == {"nodePoolId": "g", "scalePolicy": {"fixedScale": {"count": 1}}}
    cloud.wait_operation.assert_called_once()
    assert (tmp_path / "system-capacity-restored.json").exists()


def test_system_recovery_cannot_change_an_active_scientific_run(tmp_path):
    (tmp_path / "main").mkdir(); (tmp_path / "main/frozen.json").write_text("{}")
    cloud = SimpleNamespace(run=tmp_path, mutate=Mock())
    with pytest.raises(ValueError, match="forbidden"):
        setup.ensure_system_capacity(cloud)
    cloud.mutate.assert_not_called()
