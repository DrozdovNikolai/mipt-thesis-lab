"""Cloud.ru node-pool scheduling for the unchanged H2 workload and KEDA policy.

The provider's zero-size node template did not match its documented exact pool
UUID selector in the pilot. Exclude the fixed system pool instead; Cloud.create_group
permits only one ASR pool at a time, and the trial audits actual node ownership.
"""
import uuid

from h2.manifests import objects

POOL_LABEL = "mk8s.cloud.ru/node-pool-id"


def cloudru_objects(image, *, system_pool_id, worker_pool_id, namespace="ff-h2", max_workers=3,
                    compact=False):
    system_pool_id = str(uuid.UUID(system_pool_id))
    worker_pool_id = str(uuid.UUID(worker_pool_id))
    if system_pool_id == worker_pool_id:
        raise ValueError("System and worker pools must be distinct for scale-to-zero")
    if not 1 <= max_workers <= 3:
        raise ValueError("The bounded H2 plan supports one to three ASR workers")
    result = objects(image, namespace=namespace, max_workers=max_workers)
    for item in result:
        if item["kind"] == "Deployment":
            name = item["metadata"]["name"]
            pod = item["spec"]["template"]["spec"]
            if name == "coordinator":
                pod["nodeSelector"] = {POOL_LABEL: system_pool_id}
            else:
                pod.pop("nodeSelector", None)
                pod.setdefault("affinity", {})["nodeAffinity"] = {"requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [{"matchExpressions": [{"key": POOL_LABEL, "operator": "NotIn", "values": [system_pool_id]}]}]}}
                item["spec"]["template"]["metadata"].setdefault("annotations", {})["firefly-h2/expected-pool-id"] = worker_pool_id
            pod["imagePullSecrets"] = [{"name": "cloud-registry-secret"}]
            if name == "worker" and compact:
                item["spec"]["template"]["spec"]["containers"][0]["resources"] = {
                    "requests": {"cpu": "1500m", "memory": "2Gi"},
                    "limits": {"cpu": "1500m", "memory": "2Gi"},
                }
    return result
