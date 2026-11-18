from h2.capacity import Capacity, pending_estimates


def pod(uid, created=0, phase="Pending", deleting=False):
    return {"uid": uid, "created_at": created, "phase": phase, "deleting": deleting}


def test_startup_age_ready_busy_and_terminating_pods():
    rows = [pod("starting"), pod("ready"), pod("busy"), pod("removed", deleting=True),
            pod("failed", phase="Failed"), pod("new", created=340)]
    result = pending_estimates(rows, now=350, cold_start_seconds=600, excluded_ids={"ready", "busy"})
    assert result == [250, 590]


def test_overdue_start_is_not_silently_ready():
    assert pending_estimates([pod("late")], now=700, cold_start_seconds=600, excluded_ids=set()) == [30]


def test_transient_inventory_error_can_use_recent_cache_but_not_stale_cache():
    now = [0]
    reader = Capacity(enabled=True, namespace="ff-h2-test", clock=lambda: now[0])
    reader.fetch = lambda: [pod("one")]
    assert reader.snapshot()["fresh"]
    def unavailable():
        raise OSError("sensitive HTTP detail must not be exported")
    reader.fetch = unavailable
    now[0] = 6
    recent = reader.snapshot()
    assert recent["fresh"] and len(recent["pods"]) == 1 and recent["error"] == "OSError"
    now[0] = 16
    stale = reader.snapshot()
    assert not stale["fresh"] and stale["pods"] == []


def test_disabled_local_coordinator_does_not_read_cluster_credentials():
    reader = Capacity(enabled=False)
    reader.fetch = lambda: (_ for _ in ()).throw(AssertionError("must not fetch"))
    assert reader.snapshot() == {"enabled": False, "fresh": False, "pods": [], "error": None, "age_seconds": None}


def test_coordinator_role_is_read_only_and_namespace_scoped():
    from h2.manifests import objects
    rows = objects("frozen-image", namespace="ff-h2-test")
    role = next(x for x in rows if x["kind"] == "Role")
    assert role["metadata"]["namespace"] == "ff-h2-test"
    assert role["rules"] == [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]}]
    worker = next(x for x in rows if x["kind"] == "Deployment" and x["metadata"]["name"] == "worker")
    assert worker["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
