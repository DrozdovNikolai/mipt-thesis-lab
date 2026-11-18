"""Real cloud trial scaffolding: isolated queue, raw observations and audited backup.

Workload and policy parameters are explicit input files. No sample is silently
rerun or discarded. A failed trial keeps its snapshot and infrastructure manifest.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request

from h2.cloud_costs import Ledger, Rates, seconds, task_summary
from h2.cloud_ops import Cloud, save, stamp
from h2.manifests import objects
from h2.queue import digest


def verify_backup(path, *, snapshot, expected_ids):
    """Read a standalone SQLite backup without modifying its journal or archive."""
    wal = path.with_name(path.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("Backup has an uncheckpointed WAL sidecar; export a standalone database first")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.row_factory = sqlite3.Row
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("SQLite integrity check failed")
        rows = [dict(x) for x in db.execute("SELECT * FROM tasks ORDER BY accepted_at,id")]
        if {t["id"] for t in rows} != set(expected_ids):
            raise ValueError("Backup task set differs from the submitted workload")
        if {t["id"]: t for t in rows} != {t["id"]: t for t in snapshot["tasks"]}:
            raise ValueError("Backup differs from final coordinator task snapshot")
        for row in rows:
            completions = db.execute("SELECT COUNT(*) FROM events WHERE task=? AND kind='completed'",
                                     (row["id"],)).fetchone()[0]
            if completions != int(row["state"] == "done"):
                raise ValueError("Missing or duplicate accepted completion")
            if row["state"] == "done" and digest(json.loads(row["result"])) != row["result_sha"]:
                raise ValueError("Stored result hash differs from its JSON")
        with closing(sqlite3.connect(":memory:")) as restored:
            db.backup(restored)
            if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Restored SQLite integrity check failed")
            counts = {table: restored.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                      for table in ("tasks", "events", "workers")}
    return {"passed": True, "integrity_check": integrity, "restored_counts": counts,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "metrics": task_summary({"tasks": rows})}


class Trial:
    def __init__(self, cloud: Cloud, trial_id, config, *, phase="pilot", port=18084):
        self.cloud, self.id, self.config = cloud, trial_id, config
        self.output = cloud.run / "trials" / trial_id
        self.output.mkdir(parents=True, exist_ok=False)
        self.ns = "ff-h2-" + trial_id
        self.token = (cloud.runtime / "api-token").read_text()
        self.port = port
        self.phase = phase
        self.forward = None
        self.forward_log = None
        self.known_disks = set()
        self.ledger = Ledger(Rates.from_dict(cloud.plan["rates_rub_per_hour"]))
        self.started = None
        self.submitted = []
        self.last_point = None
        self.stop_sampling = threading.Event()
        self.sample_thread = None
        self.sample_error = None
        self.observation_lock = threading.Lock()
        save(self.output / "config.json", {"trial_id": trial_id, "namespace": self.ns,
             "phase": phase, "controller": config, "created_at": stamp()})

    def api(self, path, payload=None, *, timeout=30):
        request = urllib.request.Request("http://127.0.0.1:" + str(self.port) + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def render_objects(self, group):
        rendered = objects(self.cloud.state["published_image"], namespace=self.ns)
        worker = next(o for o in rendered if o["kind"] == "Deployment" and o["metadata"]["name"] == "worker")
        worker["spec"]["template"]["spec"]["nodeSelector"]["firefly-trial"] = self.id
        return rendered

    def setup(self, *, fixed_nodes=None):
        c = self.cloud
        group = c.create_group(self.id, fixed=fixed_nodes)
        save(self.output / "node-group.json", group)
        rendered = self.render_objects(group)
        worker = next(o for o in rendered if o["kind"] == "Deployment" and o["metadata"]["name"] == "worker")
        save(self.output / "manifest.json", {"apiVersion": "v1", "kind": "List", "items": rendered})
        c.kube("apply", "-f", "-", data=rendered[0])
        c.kube("apply", "-f", "-", data={"apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": "h2-api", "namespace": self.ns}, "stringData": {"token": self.token}})
        # Configure the coordinator before KEDA can read the default fixed policy.
        initial = [o for o in rendered if o["kind"] not in {"Namespace", "ScaledObject"} and o is not worker]
        c.kube("apply", "-f", "-", data={"apiVersion": "v1", "kind": "List", "items": initial})
        c.kube("-n", self.ns, "rollout", "status", "deployment/coordinator", "--timeout=150s", timeout=160)
        self.forward_log = (self.output / "port-forward.log").open("w")
        self.forward = subprocess.Popen(["kubectl", "--kubeconfig", str(c.runtime / "kubeconfig"),
            "-n", self.ns, "port-forward", "service/coordinator", str(self.port) + ":8080"],
            stdout=self.forward_log, stderr=subprocess.STDOUT)
        for _ in range(40):
            try:
                self.api("/health", timeout=3)
                break
            except (OSError, urllib.error.URLError):
                if self.forward.poll() is not None:
                    raise RuntimeError("Coordinator port forwarding exited")
                time.sleep(1)
        else:
            raise TimeoutError("Coordinator port forwarding not ready")
        self.api("/config", self.config)
        remaining = [worker] + [o for o in rendered if o["kind"] == "ScaledObject"]
        c.kube("apply", "-f", "-", data={"apiVersion": "v1", "kind": "List", "items": remaining})
        fixtures = json.loads(c.kube("-n", self.ns, "exec", "deployment/coordinator", "--", "cat", "/fixtures/manifest.json"))
        save(self.output / "fixtures.json", fixtures)
        self.fixtures = fixtures["fixtures"]
        self.start_sampling()
        return fixtures

    def cloud_inventory(self):
        c = self.cloud
        all_instances = c.yc("compute", "instance", "list")
        all_disks = c.yc("compute", "disk", "list")
        instances = []
        for raw in all_instances:
            if raw.get("labels", {}).get("experiment") != c.state["run_id"]:
                raise ValueError("Unexpected VM in the dedicated experiment folder")
            if raw["labels"].get("trial") != self.id:
                continue
            self.known_disks.add(raw["boot_disk"]["disk_id"])
            instances.append({"id": raw["id"], "created_at": raw["created_at"], "status": raw["status"],
                "cores": int(raw["resources"]["cores"]), "memory_gib": int(raw["resources"]["memory"]) / 2**30,
                "public_ip": any("one_to_one_nat" in nic.get("primary_v4_address", {}) for nic in raw["network_interfaces"]),
                "boot_disk_id": raw["boot_disk"]["disk_id"]})
        disks = [{"id": d["id"], "created_at": d["created_at"], "type": d["type_id"], "size_gib": int(d["size"]) / 2**30}
                 for d in all_disks if d["id"] in self.known_disks]
        inventory = [{"id": d["id"], "created_at": d["created_at"], "size": d["size"]} for d in all_disks]
        return instances, disks, inventory

    def seconds_until(self, deadline):
        """Admission and its horizon use the same remote coordinator clock.

        A wall-clock correction on the local WSL host must neither truncate nor
        extend a cloud workload. Local monotonic time is only used for waiting.
        """
        return max(0, seconds(deadline) - seconds(self.api("/metrics")["at"]))

    def observe(self):
        with self.observation_lock:
            return self._observe()

    def _observe(self):
        c = self.cloud
        observed_from = seconds(self.api("/metrics")["at"])
        pods = json.loads(c.kube("-n", self.ns, "get", "pods", "-l", "app=worker", "-o", "json"))
        deployment = json.loads(c.kube("-n", self.ns, "get", "deployment", "worker", "-o", "json"))
        instances, disks, inventory = self.cloud_inventory()
        metrics = self.api("/metrics")
        at = seconds(metrics["at"])
        self.ledger.observe(at, observed_from=observed_from, instances=instances, disks=disks)
        point = {"at": at, "phase": self.phase, "metrics": metrics,
            "clock": {"basis": "coordinator_utc", "inventory_started_at": observed_from,
                      "inventory_finished_at": at, "client_wall_at": time.time(),
                      "client_monotonic_at": time.monotonic()},
            "desired_pods": deployment["spec"]["replicas"], "deployment_status": deployment.get("status", {}),
            "pods": [{"name": p["metadata"]["name"], "uid": p["metadata"]["uid"],
                      "created_at": p["metadata"]["creationTimestamp"], "deleting_at": p["metadata"].get("deletionTimestamp"),
                      "node": p.get("spec", {}).get("nodeName"), "status": p.get("status", {})} for p in pods["items"]],
            "instances": instances, "disks": disks,
            "folder_disk_inventory": inventory,
            "cost": self.ledger.report()}
        try:
            point["node_metrics"] = json.loads(c.kube("get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes"))
            point["pod_metrics"] = json.loads(c.kube("get", "--raw", "/apis/metrics.k8s.io/v1beta1/namespaces/" + self.ns + "/pods"))
        except Exception as error:
            point["resource_metrics_error"] = str(error)
        with (self.output / "timeline.jsonl").open("a") as stream:
            stream.write(json.dumps(point) + "\n")
        self.last_point = point
        return point

    def start_sampling(self):
        def sample():
            while not self.stop_sampling.is_set():
                started = time.monotonic()
                try:
                    self.observe()
                except Exception as error:
                    self.sample_error = str(error)
                    with (self.output / "observation-errors.jsonl").open("a") as stream:
                        stream.write(json.dumps({"at": stamp(), "error": str(error)}) + "\n")
                self.stop_sampling.wait(max(0.1, 10 - (time.monotonic() - started)))
        self.sample_thread = threading.Thread(target=sample, daemon=True)
        self.sample_thread.start()

    def admit(self, fixture, *, expected_sha=None, deadline_seconds=600, offset_seconds=0):
        task_id = f"{self.id}-{len(self.submitted):04d}"
        payload = {"payload": {"fixture": fixture, **{k: self.fixtures[fixture][k] for k in ("audio_seconds", "sha256")}},
                   "expected_sha": expected_sha, "deadline_seconds": deadline_seconds}
        intent = {"id": task_id, "intent": payload, "requested_at": stamp(), "offset_seconds": offset_seconds}
        # Record the intent before HTTP. A lost ACK is retried using the same key.
        self.submitted.append(intent)
        save(self.output / "submitted.json", self.submitted)
        try:
            result = self.api("/admit/" + task_id, payload)
        except (OSError, urllib.error.URLError):
            result = self.api("/admit/" + task_id, payload)
        intent["accepted_at"] = result["accepted_at"]
        save(self.output / "submitted.json", self.submitted)
        return result

    def wait_completed(self, expected, *, timeout=900):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if getattr(self, "fatal_observation_error", None):
                raise ValueError(self.fatal_observation_error)
            metrics = self.api("/metrics")
            if metrics["completed"] == expected:
                return self.api("/snapshot")
            if self.forward.poll() is not None:
                raise RuntimeError("Port forward exited during trial")
            time.sleep(2)
        raise TimeoutError("Workload incomplete; preserve this trial in the report")

    def backup(self):
        snapshot = self.api("/snapshot")
        save(self.output / "snapshot.json", snapshot)
        export = """import sqlite3
from contextlib import closing
with closing(sqlite3.connect('/data/queue.sqlite')) as source:
    with closing(sqlite3.connect('/data/export.sqlite')) as target:
        source.backup(target)
        assert target.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete'
"""
        self.cloud.kube("-n", self.ns, "exec", "deployment/coordinator", "--", "python", "-c", export)
        path = self.output / "queue.sqlite"
        path.write_bytes(self.cloud.kube("-n", self.ns, "exec", "deployment/coordinator", "--", "cat", "/data/export.sqlite", binary=True))
        audit = verify_backup(path, snapshot=snapshot, expected_ids=[x["id"] for x in self.submitted])
        save(self.output / "backup-verified.json", audit)
        return audit

    def retire(self, *, observe_until=None):
        """Call only after the predeclared workload observation horizon.

        Automatic node retirement must be observed BEFORE manual deletion if
        scale-to-zero is claimed. Deletion below is ordinary experiment cleanup.
        """
        if observe_until:
            while (remaining := self.seconds_until(observe_until)) > 0:
                time.sleep(min(5, remaining))
        audit = self.backup()
        self.api("/config", {**self.config, "variant": "fixed", "fixed_workers": 0})
        self.cloud.kube("-n", self.ns, "delete", "scaledobject", "speech", "--wait=true")
        self.cloud.kube("-n", self.ns, "scale", "deployment/worker", "--replicas=0")
        self.cloud.kube("-n", self.ns, "wait", "--for=delete", "pod", "-l", "app=worker", "--timeout=660s", timeout=670)
        self.cloud.delete_group(self.id)
        self.stop_sampling.set()
        if self.sample_thread:
            self.sample_thread.join(timeout=180)
            if self.sample_thread.is_alive():
                raise RuntimeError("Sampler did not terminate")
        # A completed pool deletion may precede disappearance of its SSD in
        # Compute. Keep observing that chargeable tail instead of assuming it
        # ends when Kubernetes reports the pool operation complete.
        final = self.observe()
        end = time.monotonic() + 300
        while (final["instances"] or final["disks"]) and time.monotonic() < end:
            time.sleep(5)
            final = self.observe()
        save(self.output / "cost-summary.json", self.ledger.report())
        if not self.ledger.report()["lifecycle_complete"]:
            raise ValueError("Resource lifecycle incomplete; reconcile disks and instances before analysis")
        self.cloud.kube("delete", "namespace", self.ns, "--wait=true", timeout=120)
        self.close()
        save(self.output / "retired.json", {"at": stamp(), "trial": self.id, "backup_verified": audit["passed"]})

    def close(self):
        self.stop_sampling.set()
        if self.sample_thread:
            self.sample_thread.join(timeout=180)
        if self.forward:
            self.forward.terminate()
            try:
                self.forward.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.forward.kill()
                self.forward.wait(timeout=5)
        if self.forward_log:
            self.forward_log.close()
