"""Publish the frozen image, install KEDA and exercise an independent stop guard."""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import UTC, datetime
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import subprocess
import time

from h2.cloudru_manifests import POOL_LABEL
from h2.cloudru_ops import Cloud, assert_owned, private_write, save, stamp
from h2.cloudru_preflight import CloudruError
from h2.cloudru_images import mirror_keda


GUARD = r'''
import datetime,json,os,sys,urllib.request
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None
def request(url,token=None,body=None):
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    req=urllib.request.Request(url,headers=headers,data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as r: return json.load(r)
deadline=datetime.datetime.fromisoformat(os.environ['DEADLINE'])
if '--exercise-now' not in sys.argv and datetime.datetime.now(datetime.timezone.utc)<deadline:
    print(json.dumps({'deadline_pending':True}),flush=True)
    raise SystemExit(0)
with open('/credentials/profile.json') as f: profile=json.load(f)
token=request('https://iam.api.cloud.ru/api/v2/auth/token',body={'keyId':profile['key_id'],'secret':profile['key_secret']})['access_token']
url='https://mk8s.api.cloud.ru/v3/clusters/'+os.environ['CLUSTER_ID']
actual=request(url,token)
assert actual['id']==os.environ['CLUSTER_ID'] and actual['name']==os.environ['CLUSTER_NAME']
assert actual['projectId']==profile['project_id']
if actual['status'] not in ('OBJECT_STATUS_STOPPED','OBJECT_STATUS_STOPPING','OBJECT_STATUS_DELETING'):
    op=request(url+':stop',token,{'clusterId':actual['id']})
    print(json.dumps({'stop_requested':True,'operation_id':op['id']}),flush=True)
else:
    print(json.dumps({'already_stopping_or_stopped':True}),flush=True)
'''


def publish_image(cloud):
    if cloud.state.get("published_image"):
        return cloud.state["published_image"]
    cloud.ensure_time(1500)
    source = cloud.plan["source_image"]
    details = json.loads(subprocess.check_output(["docker", "image", "inspect", source], text=True))[0]
    names = [v.split("=", 1)[0] for v in details["Config"].get("Env", [])]
    if any(any(word in name.upper() for word in ("TOKEN", "PASSWORD", "SECRET", "PRIVATE_KEY")) for name in names):
        raise ValueError("Unexpected credential-like image environment")
    save(cloud.run / "image-source.json", {"id": details["Id"], "size": details["Size"],
        "rootfs_layers": details["RootFS"]["Layers"], "environment_variable_names": names})
    if "registry" not in cloud.state:
        name = cloud.state["prefix"].replace("-", "")
        op = cloud.mutate("ar", "/v1/registries", label="registry", body={"projectId": cloud.client.project_id,
            "name": name, "isPublic": False, "registryType": "DOCKER", "tariff": "BASIC", "registryMode": "REGISTRY_MODE_LOCAL"})
        cloud.state["registry"] = {"id": op["resourceId"], "name": name, "operation_id": op["id"]}
        cloud.record()
        cloud.wait_operation("ar", op, timeout=300)
    registry = cloud.state["registry"]["name"] + ".cr.cloud.ru"
    config = cloud.runtime / "docker"
    config.mkdir(mode=0o700, exist_ok=True)
    profile = cloud.client.profile
    auth = base64.b64encode((profile["key_id"] + ":" + profile["key_secret"]).encode()).decode()
    private_write(config / "config.json", json.dumps({"auths": {registry: {"auth": auth}}}))
    tag = registry + "/h2-cpu:frozen"
    subprocess.run(["docker", "tag", source, tag], check=True)
    try:
        with (cloud.run / "image-push.log").open("w") as stream:
            subprocess.run(["docker", "--config", str(config), "push", tag], check=True,
                           stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    finally:
        (config / "config.json").unlink(missing_ok=True)
    info = json.loads(subprocess.check_output(["docker", "image", "inspect", tag], text=True))[0]
    matches = [v for v in info.get("RepoDigests", []) if v.startswith(registry + "/h2-cpu@sha256:")]
    if len(matches) != 1 or info["Id"] != source:
        raise ValueError("Remote image content identity was not confirmed")
    cloud.state["published_image"] = matches[0]
    cloud.record()
    return matches[0]


def guard_api_addresses(cloud):
    """Resolve public API addresses outside the cluster before its stop test.

    The provider's split DNS routed mk8s to a gateway returning 404, while
    direct external DNS from the pod intermittently failed. HostAliases apply
    only to the guard; HTTPS still verifies the original hostnames normally.
    """
    aliases = []
    for name in ("iam.api.cloud.ru", "mk8s.api.cloud.ru"):
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(name, 443,
            family=socket.AF_INET, type=socket.SOCK_STREAM)})
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError("Guard API address must be a public IPv4 address: " + name)
        aliases.extend({"ip": ip, "hostnames": [name]} for ip in addresses)
    save(cloud.run / "guard-api-addresses.json", {"at": stamp(), "hostAliases": aliases,
        "scope": "Only the independent guard pods. Fresh public resolution before the actual stop test.",
        "tls_hostname_verification": True,
        "limitation": "Addresses are pinned for this bounded run; a provider address change can invalidate them. The local watchdog remains independent."})
    return aliases


def guard_objects(cloud, image):
    ns = "ff-h2-guard"
    pod = {"restartPolicy": "Never", "automountServiceAccountToken": False,
        "dnsPolicy": "ClusterFirst", "hostAliases": guard_api_addresses(cloud),
        "nodeSelector": {POOL_LABEL: cloud.state["groups"]["system"]["id"]},
        "volumes": [{"name": "code", "configMap": {"name": "deadline"}},
                    {"name": "credentials", "secret": {"secretName": "cloud-access", "defaultMode": 256}}],
        "containers": [{"name": "guard", "image": image, "command": ["python", "/guard/guard.py"],
            "env": [{"name": "DEADLINE", "value": cloud.state["deadline"]},
                    {"name": "CLUSTER_ID", "value": cloud.state["cluster"]["id"]},
                    {"name": "CLUSTER_NAME", "value": cloud.state["cluster"]["name"]}],
            "resources": {"requests": {"cpu": "20m", "memory": "32Mi"}, "limits": {"cpu": "200m", "memory": "128Mi"}},
            "volumeMounts": [{"name": "code", "mountPath": "/guard", "readOnly": True},
                             {"name": "credentials", "mountPath": "/credentials", "readOnly": True}]}]}
    return [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "deadline", "namespace": ns}, "data": {"guard.py": GUARD}},
        {"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": "deadline", "namespace": ns},
         "spec": {"schedule": "* * * * *", "concurrencyPolicy": "Forbid", "successfulJobsHistoryLimit": 1,
            "failedJobsHistoryLimit": 2, "jobTemplate": {"spec": {"backoffLimit": 2, "activeDeadlineSeconds": 600,
                "template": {"spec": pod}}}}}]


def resume_after_guard(cloud):
    """Reconcile an ambiguous resume response before issuing another mutation.

    Both observed fresh stops returned HTTP 500 on immediate resume. The first
    pilot resumed successfully after two minutes in confirmed STOPPED state.
    Retain that evidence and bound this preparation retry; never retry trials.
    """
    path = "/v3/clusters/" + cloud.state["cluster"]["id"]
    cloud.ensure_time(1200)
    end = time.monotonic() + 900
    stopped_since, attempts = None, 0
    while time.monotonic() < end:
        actual = cloud.client.request("mk8s", path)
        assert_owned(actual, cloud.state["cluster"], cloud.client.project_id)
        status = actual["status"]
        with (cloud.run / "resume-reconciliation.jsonl").open("a") as stream:
            stream.write(json.dumps({"at": stamp(), "status": status, "resume_attempts": attempts}) + "\n")
        if status == "OBJECT_STATUS_RUNNING":
            return
        if status == "OBJECT_STATUS_STOPPED":
            if stopped_since is None:
                stopped_since = time.monotonic()
            if time.monotonic() - stopped_since >= 120:
                if attempts >= 3:
                    raise RuntimeError("Cluster remains stopped after three reconciled resume attempts")
                attempts += 1
                stopped_since = None
                try:
                    op = cloud.mutate("mk8s", path + ":resume", body={"clusterId": actual["id"]},
                                      label="resume-after-reconciled-stop-" + str(attempts))
                    cloud.wait_operation("mk8s", op, timeout=max(1, int(end - time.monotonic())))
                except CloudruError as error:
                    if error.status not in {None, 409, 429, 500, 502, 503, 504}:
                        raise
                    save(cloud.run / ("resume-response-error-" + str(attempts) + ".json"),
                         {"at": stamp(), "http_status": error.status, "detail": error.detail,
                          "next": "Read actual cluster state; no blind mutation retry"})
        elif status in {"OBJECT_STATUS_DELETING", "OBJECT_STATUS_ERROR", "OBJECT_STATUS_FAILED"}:
            raise RuntimeError("Cluster cannot be resumed from " + status)
        else:
            # A delayed response may already have started the cluster.
            stopped_since = None
        time.sleep(10)
    raise TimeoutError("Cluster did not resume within the bounded preparation window")


def exercise_guard(cloud):
    """Retry preparation only after reading the owned cluster's actual state."""
    cloud.ensure_time(1200)
    path = "/v3/clusters/" + cloud.state["cluster"]["id"]
    end = time.monotonic() + 900
    attempts, running_since, requested = 0, None, False
    while time.monotonic() < end:
        actual = cloud.client.request("mk8s", path)
        assert_owned(actual, cloud.state["cluster"], cloud.client.project_id)
        status = actual["status"]
        with (cloud.run / "guard-stop-reconciliation.jsonl").open("a") as stream:
            stream.write(json.dumps({"at": stamp(), "status": status, "probe_attempts": attempts,
                                    "stop_request_acknowledged": requested}) + "\n")
        if status == "OBJECT_STATUS_STOPPED":
            if not attempts:
                raise ValueError("Cluster was already stopped; independent guard not exercised")
            save(cloud.run / "guard-stopped-cluster.json", actual)
            cloud.state["guard_stop_verified_at"] = stamp()
            cloud.record()
            return
        if status == "OBJECT_STATUS_RUNNING":
            if running_since is None:
                running_since = time.monotonic()
            if not requested and (attempts == 0 or time.monotonic() - running_since >= 120):
                if attempts >= 3:
                    raise RuntimeError("Independent guard failed after three reconciled attempts")
                attempts += 1
                try:
                    output = cloud.kube("-n", "ff-h2-guard", "exec", "guard-probe", "--",
                                       "python", "/guard/guard.py", "--exercise-now", timeout=90)
                    reply = json.loads(output)
                    save(cloud.run / ("guard-stop-reply-" + str(attempts) + ".json"), reply)
                    requested = bool(reply.get("stop_requested") or reply.get("already_stopping_or_stopped"))
                    if requested:
                        save(cloud.run / "guard-stop-request.json", reply)
                except (RuntimeError, subprocess.TimeoutExpired) as error:
                    save(cloud.run / ("guard-stop-exec-error-" + str(attempts) + ".json"),
                         {"at": stamp(), "error": cloud.client.redact(str(error)),
                          "note": "Read actual cluster state before any retry; no blind stop request."})
                running_since = None
                # The next observation must reconcile this possibly successful
                # request before another invocation can be considered.
                continue
        elif status in {"OBJECT_STATUS_FAILED", "OBJECT_STATUS_ERROR", "OBJECT_STATUS_DELETING"}:
            raise RuntimeError("Cluster cannot complete a guard stop test from " + status)
        else:
            # STOPPING is positive evidence of a submitted request, even when
            # kubectl lost its response. Do not invoke the guard again.
            if status == "OBJECT_STATUS_STOPPING":
                requested = True
            running_since = None
        time.sleep(10)
    raise TimeoutError("Independent guard did not stop the cluster within 15 minutes")


def refresh_access_after_resume(cloud):
    """Readiness retry for getKubeConfig, which is a read despite using POST.

    A cluster can report RUNNING before this access endpoint recovers. This
    never retries an infrastructure mutation and never logs returned credentials.
    """
    cloud.ensure_time(600)
    end = time.monotonic() + 300
    for attempt in range(1, 7):
        if time.monotonic() >= end:
            break
        try:
            actual = cloud.client.request("mk8s", "/v3/clusters/" + cloud.state["cluster"]["id"])
            assert_owned(actual, cloud.state["cluster"], cloud.client.project_id)
            if actual["status"] != "OBJECT_STATUS_RUNNING":
                raise ValueError("Expected a running owned cluster before refreshing Kubernetes access")
            cloud.refresh_kubeconfig(force=True)
        except CloudruError as error:
            with (cloud.run / "kube-access-readiness.jsonl").open("a") as stream:
                stream.write(json.dumps({"at": stamp(), "attempt": attempt, "available": False,
                    "http_status": error.status, "operation": "read cluster and getKubeConfig"}) + "\n")
            if error.status not in {None, 429, 500, 502, 503, 504}:
                raise
            if attempt < 6:
                time.sleep(10)
            continue
        with (cloud.run / "kube-access-readiness.jsonl").open("a") as stream:
            stream.write(json.dumps({"at": stamp(), "attempt": attempt, "available": True}) + "\n")
        return
    raise TimeoutError("Kubernetes access unavailable after bounded post-resume readiness reads")


def ensure_system_capacity(cloud):
    """Restore only the already planned system node if resume left its size zero."""
    if (cloud.run / "main/frozen.json").exists() or list((cloud.run / "trials").glob("*/submitted.json")):
        raise ValueError("System preparation recovery is forbidden after task admission or main freeze")
    cloud.ensure_time(1200)
    cluster = cloud.client.request("mk8s", "/v3/clusters/" + cloud.state["cluster"]["id"])
    assert_owned(cluster, cloud.state["cluster"], cloud.client.project_id)
    if cluster["status"] != "OBJECT_STATUS_RUNNING":
        raise ValueError("System capacity restoration requires a running owned cluster")
    group = cloud.state["groups"]["system"]
    path = "/v3/nodePools/" + group["id"]
    actual = cloud.client.request("mk8s", path)
    assert_owned(actual, group)
    if actual["clusterId"] != cluster["id"]:
        raise ValueError("System pool belongs to another cluster")
    count = actual.get("scalePolicy", {}).get("fixedScale", {}).get("count")
    if count == 1:
        return
    if count != 0 or not cloud.state.get("guard_stop_verified_at"):
        raise ValueError("Only an owned zero-sized fixed system pool after a verified stop may be restored")
    save(cloud.run / "system-capacity-before-restore.json", actual)
    body = {"nodePoolId": group["id"], "scalePolicy": {"fixedScale": {"count": 1}}}
    op = cloud.mutate("mk8s", path, method="PATCH", body=body, label="restore-planned-system-capacity")
    cloud.wait_operation("mk8s", op, timeout=900)
    verified = cloud.client.request("mk8s", path)
    assert_owned(verified, group)
    if verified["clusterId"] != cluster["id"] or verified.get("scalePolicy") != {"fixedScale": {"count": 1}}:
        raise ValueError("Restored system capacity did not match the original plan")
    if verified.get("machineConfiguration") != actual.get("machineConfiguration"):
        raise ValueError("Restoring system count unexpectedly changed machine allocation")
    save(cloud.run / "system-capacity-restored.json", {"at": stamp(), "node_pool": verified,
        "reason": "Restore the original one system node after a stop/resume left count zero. No ASR policy changed."})


def setup(cloud):
    ensure_system_capacity(cloud)
    image = publish_image(cloud)
    keda_objects, keda_images = mirror_keda(cloud)
    ns = "ff-h2-guard"
    objects = guard_objects(cloud, image)
    cloud.kube("apply", "-f", "-", data=objects[0])
    # The secret is sent on stdin and is never written to the public evidence.
    cloud.kube("apply", "-f", "-", data={"apiVersion": "v1", "kind": "Secret",
        "metadata": {"name": "cloud-access", "namespace": ns},
        "stringData": {"profile.json": (cloud.runtime / "guard-profile.json").read_text()}})
    bundle = {"apiVersion": "v1", "kind": "List", "items": objects}
    save(cloud.run / "guard-manifest.json", bundle)
    cloud.kube("apply", "-f", "-", data=bundle)
    # Installation checks are preparatory attempts; preserve any prior failed
    # Job before replacing it, and allow for the first large image pull.
    prior = json.loads(cloud.kube("-n", ns, "get", "job", "guard-install-check", "--ignore-not-found", "-o", "json") or "null")
    if prior:
        save(cloud.run / ("guard-install-prior-" + str(time.time_ns()) + ".json"), prior)
        cloud.kube("-n", ns, "delete", "job", "guard-install-check", "--wait=true", timeout=120)
    cloud.kube("-n", ns, "create", "job", "guard-install-check", "--from=cronjob/deadline")
    cloud.kube("-n", ns, "wait", "--for=condition=complete", "job/guard-install-check", "--timeout=620s", timeout=630)
    if not cloud.state.get("guard_stop_verified_at"):
        # The test's forced deadline is only an exec argument, never a restartable Job spec.
        probe = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "guard-probe", "namespace": ns},
                 "spec": copy.deepcopy(objects[2]["spec"]["jobTemplate"]["spec"]["template"]["spec"])}
        probe["spec"]["containers"][0]["command"] = ["python", "-c", "import time; time.sleep(3600)"]
        cloud.kube("-n", ns, "delete", "pod", "guard-probe", "--ignore-not-found", "--wait=true", timeout=120)
        cloud.kube("apply", "-f", "-", data=probe)
        cloud.kube("-n", ns, "wait", "--for=condition=Ready", "pod/guard-probe", "--timeout=180s", timeout=190)
        exercise_guard(cloud)
    resume_after_guard(cloud)
    refresh_access_after_resume(cloud)
    ensure_system_capacity(cloud)
    cloud.kube("wait", "--for=condition=Ready", "node", "--all", "--timeout=300s", timeout=310)
    cloud.kube("-n", ns, "delete", "pod", "guard-probe", "--ignore-not-found", "--wait=true", timeout=120)
    manifest = Path.home() / ".local/share/firefly-thesis/h2-tools/keda-2.18.0.yaml"
    target = cloud.run / "keda-2.18.0.yaml"
    target.write_bytes(manifest.read_bytes())
    save(cloud.run / "keda-source.json", {"sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "version": "2.18.0"})
    deployments = []
    for obj in keda_objects:
        if obj and obj["kind"] == "Deployment":
            deployments.append(obj["metadata"]["name"])
            pod = obj["spec"]["template"]["spec"]
            pod.setdefault("nodeSelector", {})[POOL_LABEL] = cloud.state["groups"]["system"]["id"]
            # The provider's managed secret exists in keda, but its mutating
            # webhook did not inject it into these control-plane Deployments.
            pod["imagePullSecrets"] = [{"name": "cloud-registry-secret"}]
            for container in pod["containers"]:
                container["image"] = keda_images[container["image"]]
    rendered = {"apiVersion": "v1", "kind": "List", "items": [o for o in keda_objects if o]}
    save(cloud.run / "keda-rendered.json", rendered)
    cloud.kube("apply", "--server-side", "-f", "-", data=rendered, timeout=180)
    # Names are read from the pinned release, not assumed from another installer.
    for name in deployments:
        cloud.kube("-n", "keda", "rollout", "status", "deployment/" + name, "--timeout=240s", timeout=250)
    save(cloud.run / "system-pods-ready.json", json.loads(cloud.kube("get", "pods", "-A", "-o", "json")))
    save(cloud.run / "system-nodes-ready.json", json.loads(cloud.kube("get", "nodes", "-o", "json")))
    cloud.state["setup_at"] = stamp()
    cloud.record()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    cloud = Cloud(args.run)
    try:
        setup(cloud)
    except BaseException as error:
        save(cloud.run / ("setup-failure-" + str(time.time_ns()) + ".json"),
             {"at": stamp(), "error": cloud.client.redact(str(error)), "deadline": cloud.state["deadline"]})
        # Once independently tested, the remote guard plus local watchdog bound
        # repair time. Avoid an unnecessary full stop/start for an image-copy error.
        if not cloud.state.get("guard_stop_verified_at"):
            cloud.stop()
        raise
