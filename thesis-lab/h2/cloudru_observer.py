"""Read-only auxiliary evidence collector; never changes cloud.state or workloads."""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import time

from h2.cloudru_ops import Cloud, save, stamp


def collect(cloud, *, phase=None):
    out = cloud.run / ("kubernetes-observations" + ("-" + phase if phase else ""))
    out.mkdir(exist_ok=True)
    seen = set()
    while datetime.now(UTC) < datetime.fromisoformat(cloud.state["deadline"]):
        state = json.loads((cloud.run / "state.json").read_text())
        stops = [phase + "/summary.json", phase + "/failure.json"] if phase else ["pilot/summary.json", "pilot-driver-failure.json"]
        finished = any((cloud.run / name).exists() for name in stops)
        for name, pool in state.get("groups", {}).items():
            if not name.startswith(("pilot-", "main-")) or pool.get("deleted_at"):
                continue
            namespace = "ff-h2-" + name
            target = out / name
            target.mkdir(exist_ok=True)
            at = stamp()
            try:
                snapshot = json.loads(cloud.kube("-n", namespace, "get",
                    "pods,deployments,scaledobjects,hpa,events", "-o", "json", timeout=25))
                with (target / "objects.jsonl").open("a") as stream:
                    stream.write(json.dumps({"at": at, "objects": snapshot["items"]}) + "\n")
                for pod in snapshot["items"]:
                    if pod["kind"] != "Pod" or pod["metadata"].get("labels", {}).get("app") != "worker":
                        continue
                    if not any(c.get("state", {}).get("running") for c in pod.get("status", {}).get("containerStatuses", [])):
                        continue
                    key = pod["metadata"]["uid"]
                    if key not in seen:
                        code = "import json,platform,pathlib; print(json.dumps({'platform':platform.platform(),'cpuinfo':pathlib.Path('/proc/cpuinfo').read_text(),'cpu_max':pathlib.Path('/sys/fs/cgroup/cpu.max').read_text(),'memory_max':pathlib.Path('/sys/fs/cgroup/memory.max').read_text()}))"
                        info = json.loads(cloud.kube("-n", namespace, "exec", pod["metadata"]["name"],
                                                    "--", "python", "-c", code, timeout=20))
                        save(target / ("runtime-" + key + ".json"), {"at": at, "pod_uid": key,
                            "node": pod["spec"].get("nodeName"), **info})
                        seen.add(key)
                    log = cloud.kube("-n", namespace, "logs", pod["metadata"]["name"],
                                     "--since=45s", "--tail=250", "--timestamps", timeout=20)
                    with (target / "worker-logs.jsonl").open("a") as stream:
                        stream.write(json.dumps({"at": at, "pod_uid": key, "log": log}) + "\n")
            except Exception as error:
                with (target / "observer-errors.jsonl").open("a") as stream:
                    stream.write(json.dumps({"at": at, "error": cloud.client.redact(str(error))}) + "\n")
        if finished:
            break
        time.sleep(30)
    save(out / "finished.json", {"at": stamp(), "read_only": True,
        "note": "Auxiliary snapshots every 30s; log chunks overlap by up to 15s. Not the performance sampler."})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--phase")
    args = parser.parse_args()
    collect(Cloud(args.run), phase=args.phase)
