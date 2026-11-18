"""Reconcile an ambiguous node-pool create before repeating its unique name.

The provider's CreateNodePoolRequest documents a unique name. Retries keep the
same name and body; a complete inventory and identity/configuration checks are
required. This runs before any task admission, never replays an ASR workload.
"""
import time

from h2.cloudru_preflight import CloudruError

TRANSIENT = {None, 429, 500, 502, 503, 504}


def matching_pool(cloud, body):
    cluster = cloud.client.request("mk8s", "/v3/clusters/" + body["clusterId"])
    saved = cloud.state["cluster"]
    if any(cluster.get(k) != saved[k] for k in ("id", "name")) or cluster.get("projectId") != cloud.client.project_id:
        raise ValueError("Pool reconciliation cluster identity mismatch")
    if cluster["status"] != "OBJECT_STATUS_RUNNING":
        raise ValueError("Pool reconciliation requires a running cluster")
    token, seen, matches = "", set(), []
    for _ in range(100):
        page = cloud.client.request("mk8s", "/v3/nodePools",
            {"clusterId": body["clusterId"], "pageSize": 100, "pageToken": token})
        for pool in page["nodePools"]:
            if pool["clusterId"] != body["clusterId"]:
                raise ValueError("Pool listing returned another cluster")
            if pool["name"] == body["name"]:
                matches.append(pool)
        token = page.get("nextPageToken", "")
        if not token:
            break
        if token in seen:
            raise ValueError("Incomplete node-pool pagination")
        seen.add(token)
    else:
        raise ValueError("Node-pool pagination exceeded bound")
    if len(matches) > 1:
        raise ValueError("Duplicate unique pool name; no task admission")
    if not matches:
        return None
    actual = cloud.client.request("mk8s", "/v3/nodePools/" + matches[0]["id"])
    if (actual["id"] != matches[0]["id"] or actual["clusterId"] != body["clusterId"]
            or actual["name"] != body["name"]):
        raise ValueError("Pool identity changed during reconciliation")
    expected_machine = body["machineConfiguration"]
    machine = actual["machineConfiguration"]
    if (machine["flavor"]["flavorId"] != expected_machine["flavorId"]
            or machine["disk"] != expected_machine["disk"]
            or actual["scalePolicy"] != body["scalePolicy"]
            or actual["networkConfiguration"]["nodesSubnetId"] != body["networkConfiguration"]["nodesSubnetId"]
            or actual["updateConfiguration"] != body["updateConfiguration"]
            or actual.get("taints") != body.get("taints")
            or actual.get("autoRepair") != body.get("autoRepair")):
        raise ValueError("Reconciled pool differs from the planned allocation")
    if actual["status"] not in {"OBJECT_STATUS_PROVISIONING", "OBJECT_STATUS_RUNNING"}:
        raise ValueError("Reconciled pool is not provisioning/running")
    return actual


def create_pool(cloud, trial_id, body):
    """Return (operation, adopted_resource), with at most three equal creates."""
    deadline = time.monotonic() + 900
    attempts, absent_since, reconcile = 0, None, False
    while time.monotonic() < deadline:
        cloud.ensure_time(60)
        if reconcile:
            try:
                actual = matching_pool(cloud, body)
            except CloudruError as error:
                if error.status not in TRANSIENT:
                    raise
                absent_since = None
                cloud.event("pool_reconcile_read_error", {"trial": trial_id, "http_status": error.status})
                time.sleep(5)
                continue
            if actual:
                cloud.event("pool_create_reconciled", {"trial": trial_id, "attempts": attempts,
                    "pool_id": actual["id"], "status": actual["status"]})
                return None, actual
            if absent_since is None:
                absent_since = time.monotonic()
            if time.monotonic() - absent_since < 120 or attempts >= 3:
                time.sleep(5)
                continue
        attempts += 1
        try:
            op = cloud.mutate("mk8s", "/v3/nodePools", body=body, label="pool:" + trial_id)
            if not isinstance(op, dict) or not all(isinstance(op.get(k), str) and op[k] for k in ("id", "resourceId")):
                raise CloudruError("mk8s", None, {"message": "Create response has no operation/resource identity"})
            return op, None
        except CloudruError as error:
            if error.status not in TRANSIENT | {409}:
                raise
            cloud.event("pool_create_ambiguous", {"trial": trial_id, "attempt": attempts,
                "http_status": error.status, "detail": error.detail})
            reconcile, absent_since = True, None
    raise TimeoutError("Node-pool creation unresolved after bounded reconciliation")
