"""Open another bounded, documented phase under the existing total budget."""
from datetime import datetime, timedelta
import json

from h2.cloud_budget import policy as budget_policy
from h2.cloudru_ops import save, stamp


def change_window(cloud, *, deadline, phase):
    if datetime.fromisoformat(deadline) > datetime.fromisoformat(cloud.state["created_at"]) + timedelta(hours=23):
        raise ValueError("Phase would approach the independent guard key's 24-hour expiry")
    if any(k != "system" and not v.get("deleted_at") for k, v in cloud.state["groups"].items()):
        raise ValueError("Retire the previous ASR group before changing phase windows")
    cron = json.loads(cloud.kube("-n", "ff-h2-guard", "get", "cronjob", "deadline", "-o", "json"))
    old = cloud.state["deadline"]
    containers = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    target = next(x for x in containers if x["name"] == "guard")
    values = {x["name"]: x.get("value") for x in target["env"]}
    if values["CLUSTER_ID"] != cloud.state["cluster"]["id"] or values["DEADLINE"] != old:
        raise ValueError("Unexpected guard identity or previous deadline")
    for item in target["env"]:
        if item["name"] == "DEADLINE":
            item["value"] = deadline
    patch = {"spec": {"jobTemplate": {"spec": {"template": {"spec": {"containers": containers}}}}}}
    cloud.kube("-n", "ff-h2-guard", "patch", "cronjob", "deadline", "--type=merge", "-p", json.dumps(patch))
    actual = json.loads(cloud.kube("-n", "ff-h2-guard", "get", "cronjob", "deadline", "-o", "json"))
    targets = actual["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    readback = next(e["value"] for c in targets if c["name"] == "guard" for e in c["env"] if e["name"] == "DEADLINE")
    if readback != deadline:
        raise ValueError("Remote deadline readback differs")
    proof = {"at": stamp(), "phase": phase, "old_deadline": old, "new_deadline": deadline,
             "previous_stop_test": cloud.state["guard_stop_verified_at"], "remote_guard_readback_verified": True,
             "budget_policy_unchanged_by_window": True, "budget_policy": budget_policy(cloud)}
    save(cloud.run / (phase + "-guard-window.json"), proof)
    cloud.state.setdefault("previous_deadlines", []).append(old)
    cloud.state["deadline"] = deadline
    cloud.state[phase.replace("-", "_") + "_window_opened_at"] = stamp()
    cloud.record()
    return proof
