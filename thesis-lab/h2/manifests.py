"""Render identical KEDA/HPA policy plumbing for both dynamic strategies."""
import argparse
import json


def objects(image, *, namespace="ff-h2", max_workers=3, local=False):
    def obj(kind, name, spec=None, **kwargs):
        result = {"apiVersion": "apps/v1" if kind == "Deployment" else "v1", "kind": kind,
                  "metadata": {"name": name, "namespace": namespace, "labels": {"experiment": "firefly-h2"}}, **kwargs}
        if spec is not None:
            result["spec"] = spec
        return result
    env_token = {"name": "H2_API_TOKEN", "valueFrom": {"secretKeyRef": {"name": "h2-api", "key": "token"}}}
    coordinator = {"containers": [{"name": "coordinator", "image": image, "imagePullPolicy": "IfNotPresent",
        "command": ["uvicorn", "h2.coordinator:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning"],
        "env": [env_token, {"name": "H2_KUBERNETES_CAPACITY", "value": "1"},
                {"name": "POD_NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}}],
        "ports": [{"containerPort": 8080}],
        "resources": {"requests": {"cpu": "250m", "memory": "256Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}},
        "readinessProbe": {"httpGet": {"path": "/health", "port": 8080}},
        "volumeMounts": [{"name": "data", "mountPath": "/data"}]}],
        "volumes": [{"name": "data", "hostPath": {"path": "/var/lib/firefly-h2/" + namespace, "type": "DirectoryOrCreate"}}],
        "automountServiceAccountToken": True, "serviceAccountName": "h2-capacity-reader"}
    worker = {"terminationGracePeriodSeconds": 600, "automountServiceAccountToken": False,
        "containers": [{"name": "worker", "image": image, "imagePullPolicy": "IfNotPresent",
        "command": ["python", "-m", "h2.worker"],
        "env": [env_token, {"name": "H2_COORDINATOR", "value": "http://coordinator:8080"},
                {"name": "POD_UID", "valueFrom": {"fieldRef": {"fieldPath": "metadata.uid"}}},
                {"name": "NODE_NAME", "valueFrom": {"fieldRef": {"fieldPath": "spec.nodeName"}}}],
        "resources": {"requests": {"cpu": "3", "memory": "5Gi"}, "limits": {"cpu": "3", "memory": "5Gi"}},
        "readinessProbe": {"exec": {"command": ["python", "-c", "from pathlib import Path; assert Path('/tmp/h2-ready').exists()"]},
                           "periodSeconds": 5, "timeoutSeconds": 3}}]}
    if not local:
        coordinator["nodeSelector"] = {"firefly-role": "system"}
        worker["nodeSelector"] = {"firefly-role": "worker"}
        worker["tolerations"] = [{"key": "firefly-role", "operator": "Equal", "value": "worker", "effect": "NoSchedule"}]
        # Exactly one speech process per paid worker VM, independently of policy.
        worker["affinity"] = {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [{
            "labelSelector": {"matchLabels": {"app": "worker"}}, "topologyKey": "kubernetes.io/hostname"}]}}
    result = [obj("Namespace", namespace),
        obj("Deployment", "coordinator", {"replicas": 1, "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"app": "coordinator"}},
            "template": {"metadata": {"labels": {"app": "coordinator"}}, "spec": coordinator}}),
        obj("Service", "coordinator", {"selector": {"app": "coordinator"}, "ports": [{"port": 8080, "targetPort": 8080}]}),
        obj("Deployment", "worker", {"replicas": 0, "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"app": "worker"}},
            "template": {"metadata": {"labels": {"app": "worker"}}, "spec": worker}})]
    # The hostPath exists only on one fixed, isolated system node. It is backed
    # up before cluster cleanup. This experiment does not claim HA of the queue.
    result[0]["metadata"].pop("namespace")
    # The coordinator can observe worker startup but cannot change resources
    # or read Secrets. All strategies receive the same observation overhead.
    result[1:1] = [obj("ServiceAccount", "h2-capacity-reader"),
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
         "metadata": {"name": "h2-capacity-reader", "namespace": namespace},
         "rules": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]}]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
         "metadata": {"name": "h2-capacity-reader", "namespace": namespace},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "h2-capacity-reader"},
         "subjects": [{"kind": "ServiceAccount", "name": "h2-capacity-reader", "namespace": namespace}]}]
    result.append({"apiVersion": "keda.sh/v1alpha1", "kind": "ScaledObject",
        "metadata": {"name": "speech", "namespace": namespace}, "spec": {
            "scaleTargetRef": {"name": "worker"}, "pollingInterval": 5,
            "cooldownPeriod": 30, "minReplicaCount": 0, "maxReplicaCount": max_workers,
            "advanced": {"horizontalPodAutoscalerConfig": {"behavior": {
                "scaleUp": {"stabilizationWindowSeconds": 0, "policies": [{"type": "Pods", "value": max_workers, "periodSeconds": 15}]},
                "scaleDown": {"stabilizationWindowSeconds": 30, "policies": [{"type": "Pods", "value": max_workers, "periodSeconds": 15}]}}}},
            "triggers": [{"type": "metrics-api", "metricType": "AverageValue", "metadata": {
                "targetValue": "1", "activationTargetValue": "0", "url": "http://coordinator." + namespace + ".svc.cluster.local:8080/metrics",
                "valueLocation": "value"}}]}})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--namespace", default="ff-h2")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--max-workers", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps({"apiVersion": "v1", "kind": "List", "items": objects(args.image,
        namespace=args.namespace, local=args.local, max_workers=args.max_workers)}, indent=2))
