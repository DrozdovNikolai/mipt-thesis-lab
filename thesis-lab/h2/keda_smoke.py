"""Exercise real KEDA, HPA, WhisperX and pod failure in an isolated kind cluster."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request

from h2.manifests import objects

ROOT = Path(__file__).resolve().parents[1]
KUBECONFIG = Path.home() / ".local/share/firefly-thesis/h2-local-k8s/config"
RUNTIME = Path.home() / ".local/share/firefly-thesis/h2-local-20261005/runtime.env"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--namespace", default="ff-h2-local-a")
    args = parser.parse_args()
    output, ns = args.output, args.namespace
    output.mkdir(parents=True, exist_ok=False)
    token = RUNTIME.read_text().strip().split("=", 1)[1]
    command = ["kubectl", "--kubeconfig", str(KUBECONFIG)]

    def kube(*args, data=None, timeout=60):
        result = subprocess.run([*command, *args], input=json.dumps(data) if data is not None else None,
            capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError("kubectl " + " ".join(args[:3]) + ": " + result.stderr[-2000:])
        return result.stdout

    def api(path, payload=None):
        req = urllib.request.Request("http://127.0.0.1:18083" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)

    manifest = {"apiVersion": "v1", "kind": "List", "items": objects(
        "firefly-thesis/h2-cpu:20261005-v3", namespace=ns, local=True, max_workers=2)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    kube("create", "namespace", ns)
    kube("apply", "-f", "-", data={"apiVersion": "v1", "kind": "Secret",
         "metadata": {"name": "h2-api", "namespace": ns}, "stringData": {"token": token}})
    kube("apply", "-f", "-", data=manifest)
    kube("-n", ns, "rollout", "status", "deployment/coordinator", "--timeout=90s", timeout=100)
    port_log = (output / "port-forward.log").open("w")
    forward = subprocess.Popen([*command, "-n", ns, "port-forward", "service/coordinator", "18083:8080"],
                                stdout=port_log, stderr=subprocess.STDOUT)
    points, summaries = [], []
    fixtures = json.loads((ROOT / "results/h2-local-asr-20261005-c/fixtures.json").read_text())["fixtures"]
    refs = json.loads((ROOT / "results/h2-local-asr-20261005-c/references.json").read_text())
    config = {"variant": "count", "max_workers": 2, "fixed_workers": 2, "target_queue": 1,
              "cold_start_seconds": 30, "safety_factor": 1.2,
              "costs": {"preprocess": {"fixed_seconds": 0.2, "seconds_per_audio_second": 0.01},
                        "asr": {"fixed_seconds": 1, "seconds_per_audio_second": 0.1}}}
    (output / "config.json").write_text(json.dumps(config, indent=2))

    def observe(phase):
        metrics = api("/metrics")
        pods = json.loads(kube("-n", ns, "get", "pods", "-l", "app=worker", "-o", "json"))
        deployment = json.loads(kube("-n", ns, "get", "deployment", "worker", "-o", "json"))
        point = {"at": time.time(), "phase": phase, "metrics": metrics,
                 "desired": deployment["spec"]["replicas"], "status": deployment.get("status", {}),
                 "pods": [{"name": p["metadata"]["name"], "uid": p["metadata"]["uid"],
                           "deleting": p["metadata"].get("deletionTimestamp"), "status": p.get("status", {})}
                          for p in pods["items"]]}
        points.append(point)
        with (output / "timeline.jsonl").open("a") as stream:
            stream.write(json.dumps(point) + "\n")
        return point

    def idle(phase):
        end = time.monotonic() + 180
        while time.monotonic() < end:
            point = observe(phase)
            if point["desired"] == 0 and not point["pods"]:
                return
            time.sleep(3)
        raise RuntimeError("Workers did not scale to zero")

    try:
        for _ in range(30):
            try:
                api("/health")
                break
            except Exception:
                time.sleep(1)
        api("/config", config)
        idle("initial-idle")
        for phase, fault in (("count", False), ("work", False), ("work-fault", True)):
            config["variant"] = "work" if phase.startswith("work") else "count"
            api("/config", config)
            task_ids = []
            for i in range(4):
                name, task_id = "main-900", phase + "-" + str(i)
                task_ids.append(task_id)
                api("/admit/" + task_id, {"payload": {"fixture": name, **fixtures[name]},
                     "deadline_seconds": 180, "expected_sha": refs[name]["result_sha"]})
            killed = None
            end = time.monotonic() + 360
            phase_points = []
            while time.monotonic() < end:
                point = observe(phase)
                phase_points.append(point)
                snapshot = api("/snapshot")
                tasks = [t for t in snapshot["tasks"] if t["id"] in task_ids]
                if fault and not killed:
                    victim_task = next((t for t in tasks if t["state"] == "running" and t["stage"] == "asr"), None)
                    pod = next((p for p in point["pods"] if victim_task and p["uid"] == victim_task["worker"]), None)
                    if pod:
                        killed = {"at": time.time(), "task": victim_task, "pod": pod}
                        (output / "worker-before-kill.log").write_text(kube("-n", ns, "logs", pod["name"]))
                        (output / "fault.json").write_text(json.dumps(killed, indent=2))
                        kube("-n", ns, "delete", "pod", pod["name"], "--grace-period=0", "--force", "--wait=false")
                if all(t["state"] == "done" for t in tasks):
                    break
                time.sleep(2)
            else:
                raise RuntimeError("ASR/KEDA phase timeout: " + phase)
            assert all(t["expected_sha"] == t["result_sha"] for t in tasks)
            assert max(p["desired"] for p in phase_points) == 2
            if fault:
                assert killed
                retried = next(t for t in tasks if t["id"] == killed["task"]["id"])
                assert retried["attempts"] >= 2 and retried["worker"] != killed["pod"]["uid"]
            for pod in observe(phase)["pods"]:
                try:
                    (output / (phase + "-" + pod["name"] + ".log")).write_text(kube("-n", ns, "logs", pod["name"]))
                except RuntimeError:
                    pass  # deletion race; coordinator journal is authoritative
            summary = {"phase": phase, "tasks": len(tasks), "parity": True, "max_desired": 2,
                       "fault_injected": bool(killed), "retries": sum(t["attempts"] - 1 for t in tasks)}
            summaries.append(summary)
            print(json.dumps(summary), flush=True)
            idle(phase + "-idle")
        final = api("/snapshot")
        (output / "snapshot.json").write_text(json.dumps(final, indent=2))
        kube("-n", ns, "exec", "deployment/coordinator", "--", "python", "-c",
             "from h2.coordinator import queue; queue.backup('/data/backup.sqlite')")
        pod = json.loads(kube("-n", ns, "get", "pods", "-l", "app=coordinator", "-o", "json"))["items"][0]["metadata"]["name"]
        kube("-n", ns, "cp", pod + ":/data/backup.sqlite", str(output / "queue.sqlite"))
        (output / "summary.json").write_text(json.dumps({"passed": True, "phases": summaries,
            "scope": "KEDA pod scaling and recovery on one local kind node; no cloud cost claim"}, indent=2))
    except BaseException as error:
        (output / "failure.json").write_text(json.dumps({"type": type(error).__name__, "error": str(error)}, indent=2))
        try:
            (output / "snapshot-failure.json").write_text(json.dumps(api("/snapshot"), indent=2))
        except Exception:
            pass
        raise
    finally:
        for resource in ("pods", "events", "hpa", "scaledobject"):
            try:
                (output / (resource + ".json")).write_text(kube("-n", ns, "get", resource, "-o", "json"))
            except Exception:
                pass
        forward.terminate()
        forward.wait(timeout=10)
        port_log.close()
        # Cluster cleanup is external, after raw data and persistent DB are copied.


if __name__ == "__main__":
    main()
