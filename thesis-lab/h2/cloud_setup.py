"""Publish the frozen CPU image and install KEDA plus an absolute stop guard."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from h2.cloud_ops import Cloud, save, stamp


GUARD = r'''
import datetime,json,os,urllib.request
deadline=datetime.datetime.fromisoformat(os.environ['DEADLINE'])
if datetime.datetime.now(datetime.timezone.utc)<deadline:
    raise SystemExit(0)
base='http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token'
with urllib.request.urlopen(urllib.request.Request(base,headers={'Metadata-Flavor':'Google'}),timeout=20) as r:
    token=json.load(r)['access_token']
url='https://mks.api.cloud.yandex.net/managed-kubernetes/v1/clusters/'+os.environ['CLUSTER_ID']+':stop'
req=urllib.request.Request(url,data=b'{}',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=30) as r:
    result=json.load(r)
print(json.dumps({'stop_requested':True,'operation':result.get('id')}),flush=True)
'''


def publish_image(cloud):
    if cloud.state.get("published_image"):
        return cloud.state["published_image"]
    source = cloud.plan["source_image"]
    details = json.loads(subprocess.check_output(["docker", "image", "inspect", source], text=True))[0]
    names = [x.split("=", 1)[0] for x in details["Config"].get("Env", [])]
    if any(any(word in name.upper() for word in ("TOKEN", "PASSWORD", "SECRET", "PRIVATE_KEY")) for name in names):
        raise ValueError("Review unexpected credential-like image environment before upload")
    save(cloud.run / "image-source.json", {"id": details["Id"], "size": details["Size"],
        "created": details["Created"], "environment_variable_names": names,
        "rootfs_layers": details["RootFS"]["Layers"]})
    command = ["yc", "--profile", cloud.plan["profile"], "--no-browser", "iam", "create-token"]
    token = subprocess.check_output(command, text=True, timeout=60).strip()
    config = cloud.runtime / "docker"
    config.mkdir(mode=0o700, exist_ok=True)
    login = subprocess.run(["docker", "--config", str(config), "login", "cr.yandex", "--username", "iam",
                            "--password-stdin"], input=token, text=True, capture_output=True, timeout=90)
    if login.returncode:
        raise RuntimeError("Private registry login failed")
    tag = "cr.yandex/" + cloud.state["registry"]["id"] + "/h2-cpu:" + cloud.state["suffix"]
    subprocess.run(["docker", "tag", source, tag], check=True)
    try:
        with (cloud.run / "image-push.log").open("w") as stream:
            subprocess.run(["docker", "--config", str(config), "push", tag], check=True,
                           stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    finally:
        subprocess.run(["docker", "--config", str(config), "logout", "cr.yandex"], capture_output=True)
    info = json.loads(subprocess.check_output(["docker", "image", "inspect", tag], text=True))[0]
    prefix = "cr.yandex/" + cloud.state["registry"]["id"] + "/h2-cpu@sha256:"
    matches = [x for x in info.get("RepoDigests", []) if x.startswith(prefix)]
    if len(matches) != 1 or info["Id"] != source:
        raise ValueError("Image digest or local content identity mismatch")
    cloud.state["published_image"] = matches[0]
    cloud.state["image_published_at"] = stamp()
    cloud.record()
    return matches[0]


def setup(cloud):
    image = publish_image(cloud)
    manifest = Path.home() / ".local/share/firefly-thesis/h2-tools/keda-2.18.0.yaml"
    target = cloud.run / "keda-2.18.0.yaml"
    target.write_bytes(manifest.read_bytes())
    save(cloud.run / "keda-source.json", {"path": str(manifest),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "version": "2.18.0", "same_manifest_as_local_integration": True})
    cloud.kube("apply", "--server-side", "-f", target, timeout=180)
    for name in ("keda-operator", "keda-operator-metrics-apiserver", "keda-admission-webhooks"):
        cloud.kube("-n", "keda", "rollout", "status", "deployment/" + name, "--timeout=240s", timeout=250)
    ns = "ff-h2-guard"
    objects = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "deadline", "namespace": ns},
         "data": {"guard.py": GUARD}},
        {"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": "deadline", "namespace": ns},
         "spec": {"schedule": "* * * * *", "concurrencyPolicy": "Forbid", "successfulJobsHistoryLimit": 1,
            "failedJobsHistoryLimit": 2, "jobTemplate": {"spec": {"backoffLimit": 2,
                "activeDeadlineSeconds": 90, "template": {"spec": {
                    "restartPolicy": "Never", "automountServiceAccountToken": False,
                    "nodeSelector": {"firefly-role": "system"},
                    "volumes": [{"name": "code", "configMap": {"name": "deadline"}}],
                    "containers": [{"name": "guard", "image": image, "command": ["python", "/guard/guard.py"],
                        "env": [{"name": "DEADLINE", "value": cloud.state["deadline"]},
                                {"name": "CLUSTER_ID", "value": cloud.state["cluster"]["id"]}],
                        "resources": {"requests": {"cpu": "20m", "memory": "32Mi"},
                                      "limits": {"cpu": "200m", "memory": "128Mi"}},
                        "volumeMounts": [{"name": "code", "mountPath": "/guard", "readOnly": True}]}]}}}}}}]
    save(cloud.run / "deadline-guard-manifest.json", {"apiVersion": "v1", "kind": "List", "items": objects})
    cloud.kube("apply", "-f", "-", data={"apiVersion": "v1", "kind": "List", "items": objects})
    cloud.kube("-n", ns, "create", "job", "guard-install-check", "--from=cronjob/deadline")
    cloud.kube("-n", ns, "wait", "--for=condition=complete", "job/guard-install-check", "--timeout=90s", timeout=100)
    cloud.state["setup_at"] = stamp()
    cloud.record()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    setup(Cloud(args.run))
