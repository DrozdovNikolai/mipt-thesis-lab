"""Keep fixed infrastructure pods on the system pool so ASR nodes can reach zero."""
import argparse
import json
from pathlib import Path

from h2.cloudru_manifests import POOL_LABEL
from h2.cloudru_ops import Cloud, save, stamp


def configure(cloud):
    cloud.ensure_time(1200)
    if not cloud.state.get("setup_at"):
        raise ValueError("Install and exercise the stop guard before configuring trials")
    cluster = cloud.state["cluster"]["id"]
    page = cloud.client.request("mk8s", "/v3/clusterAddons", {"clusterId": cluster, "pageSize": 100})
    if page.get("nextPageToken"):
        raise ValueError("Unexpectedly incomplete addon inventory")
    cilium = next(a for a in page["clusterAddons"] if a["name"] == "cilium")
    body = {"clusterAddonId": cilium["id"], "appVersion": cilium["appVersion"],
            "addonConfiguration": json.dumps({"operator": {"replicas": 1}}),
            "resolveMode": "RESOLVE_CONFLICTS_MODE_PRESERVE"}
    save(cloud.run / "cilium-single-system-request.json", body)
    op = cloud.mutate("mk8s", "/v3/clusterAddons/" + cilium["id"], method="PATCH", body=body,
                       label="cilium-single-system")
    cloud.wait_operation("mk8s", op, timeout=600)
    targets = []
    for namespace in ("kube-system", "monitoring", "keda"):
        objects = json.loads(cloud.kube("-n", namespace, "get", "deployments", "-o", "json"))
        save(cloud.run / (namespace + "-deployments-before-placement.json"), objects)
        for deployment in objects["items"]:
            name = deployment["metadata"]["name"]
            patch = {"spec": {"strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxSurge": 0, "maxUnavailable": 1}},
                     "template": {"spec": {"nodeSelector": {POOL_LABEL: cloud.state["groups"]["system"]["id"]}}}}}
            cloud.kube("-n", namespace, "patch", "deployment", name, "--type=merge", "-p", json.dumps(patch))
            cloud.kube("-n", namespace, "rollout", "status", "deployment/" + name, "--timeout=180s", timeout=190)
            targets.append({"namespace": namespace, "name": name})
    # Worker-node DaemonSets must remain unrestricted; they are included in the measured overhead.
    snapshot = json.loads(cloud.kube("get", "pods", "-A", "-o", "json"))
    save(cloud.run / "system-placement-pods.json", snapshot)
    save(cloud.run / "system-placement.json", {"at": stamp(), "deployments": targets,
        "system_pool_id": cloud.state["groups"]["system"]["id"], "cilium_operator_replicas": 1,
        "scope": "Single-system-node research cluster; no HA claim. Same settings for every strategy."})
    operator = json.loads(cloud.kube("-n", "kube-system", "get", "deployment", "cilium-operator", "-o", "json"))
    if operator["spec"]["replicas"] != 1 or operator["status"].get("availableReplicas", 0) != 1:
        raise ValueError("Single system Cilium operator was not confirmed")
    cloud.state["system_pinned_at"] = stamp()
    cloud.record()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    configure(Cloud(args.run))
