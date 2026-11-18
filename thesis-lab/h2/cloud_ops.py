"""Bounded, manifest-scoped YC infrastructure for the H2 experiment.

No default kubectl context, production repository or existing cloud resource is
modified. Secrets are stored outside the repository in a private runtime path.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request

from h2.cloud_preflight import assess_quotas

ROOT = Path(__file__).resolve().parents[1]


def stamp():
    return datetime.now(UTC).isoformat()


def save(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


class Cloud:
    def __init__(self, run):
        self.run = Path(run).resolve()
        self.plan = json.loads((self.run / "plan.json").read_text())
        self.state = json.loads((self.run / "resources.json").read_text())
        self.runtime = Path(self.state["runtime"])

    def record(self):
        save(self.run / "resources.json", self.state)

    def yc(self, *args, timeout=180):
        command = ["yc", "--profile", self.plan["profile"], "--folder-id", self.plan["folder_id"],
                   "--no-browser", *map(str, args), "--format", "json"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            # None of these calls carries secret values on the command line.
            raise RuntimeError("YC " + " ".join(map(str, args[:3])) + ": " + result.stderr[-1800:])
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def wait_operation(self, operation, *, timeout=1800):
        limit = time.monotonic() + timeout
        current = operation
        while not current.get("done"):
            if time.monotonic() > limit:
                raise TimeoutError("Operation " + current["id"])
            time.sleep(5)
            current = self.yc("operation", "get", operation["id"])
            save(self.run / "operations" / (operation["id"] + ".json"), current)
        if current.get("error"):
            raise RuntimeError(json.dumps(current["error"]))
        return current.get("response", current)

    def owned(self, resource):
        if (resource.get("folder_id") != self.plan["folder_id"]
                or resource.get("labels", {}).get("experiment") != self.state["run_id"]):
            raise ValueError("Resource ownership does not match this run")

    def kube(self, *args, data=None, timeout=90, binary=False):
        command = ["kubectl", "--kubeconfig", str(self.runtime / "kubeconfig"), *map(str, args)]
        payload = json.dumps(data) if data is not None else None
        result = subprocess.run(command, input=payload, capture_output=True, text=not binary, timeout=timeout)
        if result.returncode:
            detail = result.stderr.decode() if binary else result.stderr
            raise RuntimeError("kubectl " + " ".join(map(str, args[:3])) + ": " + detail[-1500:])
        return result.stdout

    def create_group(self, trial, *, fixed=None):
        if trial in self.state["groups"]:
            raise ValueError("Node group already recorded; do not create another trial silently")
        labels = "project=firefly-thesis,experiment=" + self.state["run_id"] + ",trial=" + trial
        name = "ff-h2-" + trial + "-" + self.state["suffix"]
        node_labels = "firefly-role=" + ("system" if trial == "system" else "worker") + ",firefly-trial=" + trial
        args = ["managed-kubernetes", "node-group", "create", "--name", name,
                "--cluster-id", self.state["cluster"]["id"], "--platform", "standard-v3",
                "--cores", "4", "--memory", "8GB", "--core-fraction", "100",
                "--disk-type", "network-ssd", "--disk-size", "40GB", "--version", self.plan["kubernetes_version"],
                "--container-runtime", "containerd", "--auto-upgrade=false", "--auto-repair=false",
                "--max-expansion", "0", "--max-unavailable", "1", "--labels", labels, "--template-labels", labels,
                "--node-labels", node_labels, "--location", "zone=" + self.plan["zone"]
                + ",subnet-id=" + self.state["subnet"]["id"], "--network-interface",
                "subnets=" + self.state["subnet"]["id"] + ",ipv4-address=nat,security-group-ids="
                + self.state["security_group"]["id"], "--async"]
        if fixed is None:
            args += ["--auto-scale", "min=0,max=3,initial=0"]
        else:
            args += ["--fixed-size", str(fixed)]
        if trial != "system":
            args += ["--node-taints", "firefly-role=worker:NoSchedule"]
        operation = self.yc(*args)
        self.state["groups"][trial] = {"name": name, "created_request_at": stamp(), "operation": operation,
                                      "fixed": fixed, "trial": trial}
        self.record()
        save(self.run / "operations" / (operation["id"] + ".json"), operation)
        group = self.wait_operation(operation)
        # Operation response JSON may use camelCase; fetch canonical CLI shape.
        group = self.yc("managed-kubernetes", "node-group", "get", group["id"])
        self.owned(group)
        self.state["groups"][trial].update(id=group["id"], resource=group, ready_at=stamp())
        self.record()
        return group

    def delete_group(self, trial):
        entry = self.state["groups"][trial]
        group = self.yc("managed-kubernetes", "node-group", "get", entry["id"])
        self.owned(group)
        operation = self.yc("managed-kubernetes", "node-group", "delete", entry["id"], "--async")
        entry["delete_operation"] = operation
        self.record()
        save(self.run / "operations" / (operation["id"] + ".json"), operation)
        self.wait_operation(operation)
        entry["deleted_at"] = stamp()
        self.record()

    def stop(self):
        if not self.state.get("cluster", {}).get("id"):
            return
        cluster = self.yc("managed-kubernetes", "cluster", "get", self.state["cluster"]["id"])
        self.owned(cluster)
        if cluster["status"] not in {"STOPPED", "STOPPING"}:
            result = self.yc("managed-kubernetes", "cluster", "stop", cluster["id"], "--async")
            save(self.run / "stop-operation.json", result)
            self.wait_operation(result, timeout=900)
        limit = time.monotonic() + 900
        while cluster["status"] != "STOPPED":
            if time.monotonic() >= limit:
                raise TimeoutError("Cluster stop has not completed")
            time.sleep(5)
            cluster = self.yc("managed-kubernetes", "cluster", "get", cluster["id"])
            self.owned(cluster)
        save(self.run / "stop-requested.json", {"at": stamp(), "cluster_id": cluster["id"], "confirmed_status": "STOPPED"})

    def cleanup(self):
        from h2.cloud_trial import verify_backup
        verified = []
        for trial in sorted((self.run / "trials").glob("*")) if (self.run / "trials").exists() else []:
            if not (trial / "submitted.json").exists():
                # No trial HTTP admission was attempted by this driver.
                continue
            submitted = json.loads((trial / "submitted.json").read_text())
            snapshot = json.loads((trial / "snapshot.json").read_text())
            audit = verify_backup(trial / "queue.sqlite", snapshot=snapshot,
                                  expected_ids=[x["id"] for x in submitted])
            verified.append({"trial": trial.name, **audit})
        save(self.run / "backup-verified.json", {"at": stamp(), "run_id": self.state["run_id"],
            "passed": True, "trials": verified, "note": "Backup integrity does not imply the hypothesis passed."})
        known_disks = set()
        for instance in self.yc("compute", "instance", "list"):
            if instance.get("labels", {}).get("experiment") == self.state["run_id"]:
                known_disks.add(instance["boot_disk"]["disk_id"])
        for cost_file in (self.run / "trials").glob("*/cost-summary.json"):
            known_disks.update(x["id"] for x in json.loads(cost_file.read_text())["resources"] if x["kind"] == "disk")
        removed = []

        def record(kind, identifier):
            removed.append({"type": kind, "id": identifier, "at": stamp()})
            save(self.run / "cleanup.json", {"complete": False, "removed": removed})

        if self.state.get("cluster", {}).get("id"):
            cluster = self.yc("managed-kubernetes", "cluster", "get", self.state["cluster"]["id"])
            self.owned(cluster)
            groups = self.yc("managed-kubernetes", "node-group", "list", "--cluster-id", cluster["id"])
            for group in groups:
                self.owned(group)
                result = self.yc("managed-kubernetes", "node-group", "delete", group["id"], "--async")
                save(self.run / "operations" / (result["id"] + ".json"), result)
                self.wait_operation(result)
                record("node_group", group["id"])
            operation = self.yc("managed-kubernetes", "cluster", "delete", cluster["id"], "--async")
            save(self.run / "operations" / (operation["id"] + ".json"), operation)
            self.wait_operation(operation)
            record("cluster", cluster["id"])
        remaining_instances = self.yc("compute", "instance", "list")
        if any(v.get("labels", {}).get("experiment") == self.state["run_id"] for v in remaining_instances):
            raise ValueError("Experimental VM remains after deleting cluster; inspect before deleting network")
        for disk in self.yc("compute", "disk", "list"):
            if disk["id"] in known_disks:
                if disk.get("instance_ids"):
                    raise ValueError("Experimental disk is still attached")
                self.yc("compute", "disk", "delete", disk["id"])
                record("orphan_disk", disk["id"])
        if self.state.get("registry"):
            registry = self.yc("container", "registry", "get", self.state["registry"]["id"])
            self.owned(registry)
            for image in self.yc("container", "image", "list", "--registry-id", registry["id"]):
                self.yc("container", "image", "delete", image["id"])
                record("registry_image", image["id"])
            self.yc("container", "registry", "delete", registry["id"])
            record("registry", registry["id"])
        for kind, command in (("security_group", "security-group"), ("subnet", "subnet"), ("network", "network")):
            if self.state.get(kind):
                value = self.yc("vpc", command, "get", self.state[kind]["id"])
                self.owned(value)
                self.yc("vpc", command, "delete", value["id"])
                record(kind, value["id"])
        for binding in self.state["bindings"]:
            self.yc("resource-manager", "folder", "remove-access-binding", self.plan["folder_id"],
                    "--role", binding["role"], "--subject", "serviceAccount:" + binding["sa"])
        for key in ("cluster_sa", "node_sa"):
            if self.state.get(key):
                sa = self.yc("iam", "service-account", "get", self.state[key]["id"])
                if sa.get("folder_id") != self.plan["folder_id"] or sa.get("description") != self.state["run_id"]:
                    raise ValueError("Service account ownership mismatch")
                self.yc("iam", "service-account", "delete", sa["id"])
                record("service_account", sa["id"])
        save(self.run / "cleanup.json", {"complete": True, "completed_at": stamp(), "removed": removed,
            "remaining_instances": self.yc("compute", "instance", "list"),
            "remaining_disks": self.yc("compute", "disk", "list"),
            "remaining_clusters": self.yc("managed-kubernetes", "cluster", "list")})

    def provision(self):
        if self.state.get("provision_started_at"):
            raise ValueError("Provisioning already attempted; inspect recorded operations before resuming")
        observations = {}
        for service in ("compute", "vpc", "managed-kubernetes", "container-registry"):
            observations["quota_" + service] = self.yc("quota-manager", "quota-limit", "list",
                "--service", service, "--resource-type", "resource-manager.cloud",
                "--resource-id", self.plan["cloud_id"])
        checks = assess_quotas(observations, zone=self.plan["zone"])
        save(self.run / "quota-at-provision.json", {"at": stamp(), "checks": checks, "observations": observations})
        if not all(x["fits"] for x in checks):
            raise ValueError("Insufficient quota; no resource created")
        if self.plan["max_window_hours"] > 6 or self.plan["budget_rub"] > 500:
            raise ValueError("First window exceeds the recorded budget")
        if self.plan["peak_hourly_rub"] * self.plan["max_window_hours"] > self.plan["budget_rub"]:
            raise ValueError("Allocation estimate exceeds window budget")
        if self.plan["conservative_grant_estimate_rub"] < self.plan["budget_rub"] + 200:
            raise ValueError("Insufficient budget reserve")
        checked_at = datetime.fromisoformat(self.plan["preflight_at"])
        if (datetime.now(UTC) - checked_at).total_seconds() > 86400:
            raise ValueError("Refresh account costs and current SKU prices before provisioning")
        if datetime.now(UTC) + timedelta(hours=self.plan["max_window_hours"]) >= datetime.fromisoformat(self.plan["grant_expires_at"]):
            raise ValueError("Experiment window extends beyond the documented grant validity")
        if self.yc("compute", "instance", "list") or self.yc("managed-kubernetes", "cluster", "list"):
            raise ValueError("Experiment folder no longer empty; inspect existing resources")
        now = datetime.now(UTC)
        self.state.update(provision_started_at=now.isoformat(),
            deadline=(now + timedelta(hours=self.plan["max_window_hours"])).isoformat())
        with urllib.request.urlopen("https://api.ipify.org", timeout=20) as response:
            self.state["operator_ipv4"] = str(ipaddress.IPv4Address(response.read().decode().strip()))
        self.record()
        labels = "project=firefly-thesis,experiment=" + self.state["run_id"]

        def created(key, *args):
            self.state[key] = self.yc(*args)
            self.record()
            print("CREATED", key, self.state[key].get("id"), flush=True)
            return self.state[key]

        network = created("network", "vpc", "network", "create", "ff-h2-" + self.state["suffix"], "--labels", labels)
        subnet = created("subnet", "vpc", "subnet", "create", "ff-h2-" + self.state["suffix"],
            "--network-id", network["id"], "--zone", self.plan["zone"], "--range", "10.79.0.0/24", "--labels", labels)
        rules = ["direction=egress,protocol=any,v4-cidrs=0.0.0.0/0",
                 "direction=ingress,protocol=any,predefined=self_security_group",
                 "direction=ingress,protocol=any,v4-cidrs=[10.79.0.0/24,10.80.0.0/16,10.81.0.0/16]",
                 "direction=ingress,protocol=tcp,from-port=0,to-port=65535,predefined=loadbalancer_healthchecks"]
        for port in (443, 6443):
            rules.append(f"direction=ingress,protocol=tcp,port={port},v4-cidrs={self.state['operator_ipv4']}/32")
        flags = [value for rule in rules for value in ("--rule", rule)]
        sg = created("security_group", "vpc", "security-group", "create", "ff-h2-" + self.state["suffix"],
                     "--network-id", network["id"], "--labels", labels, *flags)
        for role, permissions in (("cluster_sa", ["k8s.clusters.agent", "vpc.publicAdmin"]),
                                  ("node_sa", ["container-registry.images.puller", "k8s.editor"])):
            sa = created(role, "iam", "service-account", "create", "ff-h2-" + role.replace("_", "-")
                         + "-" + self.state["suffix"], "--description", self.state["run_id"])
            for permission in permissions:
                self.yc("resource-manager", "folder", "add-access-binding", self.plan["folder_id"],
                        "--role", permission, "--subject", "serviceAccount:" + sa["id"])
                self.state["bindings"].append({"sa": sa["id"], "role": permission})
                self.record()
        created("registry", "container", "registry", "create", "ff-h2-" + self.state["suffix"], "--labels", labels)
        operation = self.yc("managed-kubernetes", "cluster", "create", "ff-h2-" + self.state["suffix"],
            "--network-id", network["id"], "--public-ip", "--release-channel", "regular",
            "--version", self.plan["kubernetes_version"], "--cluster-ipv4-range", "10.80.0.0/16",
            "--service-ipv4-range", "10.81.0.0/16", "--security-group-ids", sg["id"],
            "--service-account-id", self.state["cluster_sa"]["id"],
            "--node-service-account-id", self.state["node_sa"]["id"],
            "--master-location", "zone=" + self.plan["zone"] + ",subnet-id=" + subnet["id"],
            "--auto-upgrade=false", "--master-logging", "enabled=false", "--labels", labels, "--async")
        self.state["cluster_operation"] = operation
        metadata = operation.get("metadata", {})
        identifier = metadata.get("cluster_id") or metadata.get("clusterId")
        if identifier:
            self.state["cluster"] = {"id": identifier}
        self.record()
        save(self.run / "operations" / (operation["id"] + ".json"), operation)
        cluster = self.wait_operation(operation)
        self.state["cluster"] = self.yc("managed-kubernetes", "cluster", "get", cluster["id"])
        self.record()
        subprocess.run(["yc", "--profile", self.plan["profile"], "managed-kubernetes", "cluster", "get-credentials",
            cluster["id"], "--external", "--kubeconfig", str(self.runtime / "kubeconfig"),
            "--context-name", self.state["run_id"]], capture_output=True, check=True, timeout=90)
        (self.runtime / "kubeconfig").chmod(0o600)
        self.create_group("system", fixed=1)
        self.state["provisioned_at"] = stamp()
        self.record()


def initialize(run, plan_file):
    run.mkdir(parents=True, exist_ok=False)
    (run / "operations").mkdir()
    plan = json.loads(plan_file.read_text())
    runtime = Path.home() / ".local/share/firefly-thesis" / run.name
    runtime.mkdir(mode=0o700, exist_ok=False)
    token_path = runtime / "api-token"
    token_path.write_text(secrets.token_urlsafe(40))
    token_path.chmod(0o600)
    save(run / "plan.json", plan)
    save(run / "resources.json", {"run_id": run.name, "initialized_at": stamp(),
        "suffix": datetime.now(UTC).strftime("%m%d%H%M"), "runtime": str(runtime), "groups": {}, "bindings": []})


def watchdog(run):
    while True:
        cloud = Cloud(run)
        if (cloud.run / "cleanup.json").exists() and json.loads((cloud.run / "cleanup.json").read_text()).get("complete"):
            return
        if cloud.state.get("deadline") and datetime.now(UTC) >= datetime.fromisoformat(cloud.state["deadline"]):
            try:
                cloud.stop()
                if (cloud.run / "stop-requested.json").exists():
                    return
            except Exception as error:
                with (cloud.run / "watchdog-errors.jsonl").open("a") as stream:
                    stream.write(json.dumps({"at": stamp(), "error": str(error)}) + "\n")
        time.sleep(15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "provision", "stop", "watchdog", "cleanup"))
    parser.add_argument("run", type=Path)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    if args.action == "init":
        if not args.plan:
            parser.error("init requires --plan")
        initialize(args.run.resolve(), args.plan.resolve())
    elif args.action == "watchdog":
        watchdog(args.run.resolve())
    else:
        getattr(Cloud(args.run), args.action)()
