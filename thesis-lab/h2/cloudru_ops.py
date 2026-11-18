"""Bounded Cloud.ru pilot lifecycle. Only resources in this run's manifest are owned.

Credentials stay in the owner's private home directory. This write-capable client
is deliberately separate from the read-only preflight client.
"""
from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from h2.cloudru_access import AccessError, NoRedirect, authenticate, load_profile
from h2.cloudru_preflight import CloudruError, ENDPOINTS, ReadClient, select_flavor

ZONE = "479a4ab3-3ff3-4972-95c5-7610bac5c0bb"
VPC = "43bbae1c-90c3-4abd-8d72-a48078899989"
# Frozen local image ID; never rebuild it during a comparison.
SOURCE = "sha256:a410db19970c48afe507d872e065aa4d4ceed15feca3a5f4469144c589aadf5e"


def stamp():
    return datetime.now(UTC).isoformat()


def save(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp-" + secrets.token_hex(3))
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def private_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Private file cannot be a symlink")
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(6))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
        # Concurrent observers must never see a half-written kubeconfig.
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class WriteClient(ReadClient):
    def __init__(self, profile):
        self.profile = profile
        self._lock = threading.RLock()
        for attempt in range(3):
            try:
                super().__init__(profile)
                break
            except AccessError:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        self._authenticated_at = time.monotonic()

    def bearer(self):
        with self._lock:
            if time.monotonic() - self._authenticated_at > 1800:
                self._token = authenticate(self.profile)
                self._secrets += (self._token,)
                self._authenticated_at = time.monotonic()
            return self._token

    def request(self, service, path, query=None, *, method="GET", body=None):
        for attempt in range(3 if method == "GET" else 1):
            try:
                return self._request_once(service, path, query, method=method, body=body)
            except CloudruError as error:
                if method != "GET" or attempt == 2 or error.status not in {None, 429, 500, 502, 503, 504}:
                    raise
                time.sleep(attempt + 1)

    def _request_once(self, service, path, query=None, *, method="GET", body=None):
        if service not in ENDPOINTS or not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("Use a named service and absolute API path")
        if method not in {"GET", "POST", "DELETE", "PUT", "PATCH"} or (method == "GET" and body is not None):
            raise ValueError("Unsupported request")
        url = ENDPOINTS[service] + path
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True, quote_via=urllib.parse.quote)
        request = urllib.request.Request(url, method=method,
            headers={"Authorization": "Bearer " + self.bearer(), "Content-Type": "application/json"},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=40) as response:
                content = response.read()
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(16384))
            except (ValueError, UnicodeError):
                detail = {"message": "Non-JSON response omitted"}
            finally:
                exc.close()
            raise CloudruError(service, exc.code, self.redact(detail)) from None
        except (urllib.error.URLError, OSError, ValueError, UnicodeError) as error:
            # Do not automatically retry mutations: a lost response can follow a successful create.
            cause = getattr(error, "reason", error)
            raise CloudruError(service, None, {"message": "Transport or JSON failure; reconcile before retry",
                "exception_type": type(error).__name__, "cause_type": type(cause).__name__,
                "errno": getattr(cause, "errno", None)}) from None


def assert_owned(obj, saved, project_id=None):
    if obj.get("id") != saved["id"] or obj.get("name") != saved["name"]:
        raise ValueError("Resource identity differs from run manifest")
    actual_project = obj.get("projectId", obj.get("project", {}).get("id"))
    if project_id and actual_project != project_id:
        raise ValueError("Resource belongs to another project")


def node_pool_request(cluster_id, subnet_id, flavor_id, name, *, fixed=None, system=False):
    if fixed is not None and (type(fixed) is not int or not 0 <= fixed <= 3):
        raise ValueError("The pilot permits at most three ASR nodes")
    if system and fixed != 1:
        raise ValueError("Exactly one system node is required")
    body = {"clusterId": cluster_id, "name": name,
        "scalePolicy": {"fixedScale": {"count": fixed}} if fixed is not None else
                       {"autoScale": {"minCount": 0, "maxCount": 3, "initialCount": 0}},
        "machineConfiguration": {"flavorId": flavor_id, "disk": {"typeName": "SSD", "size": 40}},
        "networkConfiguration": {"nodesSubnetId": subnet_id},
        "updateConfiguration": {"strategy": "NODE_POOL_UPDATE_STRATEGY_ROLLING_UPDATE",
                                "rollingUpdatePolicy": {"maxSurge": 0, "maxUnavailable": 100}},
        "autoRepair": {"enabled": False}}
    if not system:
        body["taints"] = {"taints": [{"key": "firefly-role", "value": "worker", "effect": "EFFECT_NO_SCHEDULE"}]}
    return body


class Cloud:
    def __init__(self, run):
        self.run = Path(run).resolve()
        self.state = json.loads((self.run / "state.json").read_text())
        self.plan = json.loads((self.run / "plan.json").read_text())
        self.runtime = Path(self.state["runtime"])
        self.client = WriteClient(load_profile())
        if self.client.project_id != self.state["project_id"]:
            raise ValueError("Profile project differs from run")
        guard_profile = self.runtime / "guard-profile.json"
        if guard_profile.exists():
            guard = json.loads(guard_profile.read_text())
            self.client._secrets += (guard["key_id"], guard["key_secret"])
        self._kube_lock = threading.Lock()
        self._kube_token = None

    def record(self):
        save(self.run / "state.json", self.client.redact(self.state))

    def ensure_time(self, seconds=0):
        if datetime.now(UTC) + timedelta(seconds=seconds) >= datetime.fromisoformat(self.state["deadline"]):
            raise RuntimeError("Guarded experiment window has ended")

    def event(self, name, value):
        with (self.run / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(self.client.redact({"at": stamp(), "name": name, **value})) + "\n")

    def mutate(self, service, path, *, method="POST", body=None, query=None, label, secret_response=False):
        self.event("request", {"label": label, "service": service, "method": method, "path": path,
                               "body": body, "query": query})
        try:
            value = self.client.request(service, path, query, method=method, body=body)
        except CloudruError as error:
            self.event("request_error", {"label": label, "http_status": error.status, "detail": error.detail})
            raise
        if not secret_response:
            self.event("response", {"label": label, "value": value})
        return value

    def wait_operation(self, service, op, timeout=1200, observe=None):
        end = time.monotonic() + timeout
        last_observed = 0
        while not op.get("done"):
            if time.monotonic() >= end:
                raise TimeoutError("Cloud operation did not finish: " + op["id"])
            if observe and time.monotonic() - last_observed >= 10:
                observe()
                last_observed = time.monotonic()
            time.sleep(5)
            try:
                op = self.client.request(service, ("/v3/operations/" if service == "mk8s" else "/v1/operations/") + op["id"])
            except CloudruError as error:
                if error.status not in {None, 429, 500, 502, 503, 504}:
                    raise
                self.event("operation_poll_error", {"service": service, "operation_id": op["id"],
                    "http_status": error.status, "detail": error.detail})
        self.event("operation_complete", {"service": service, "operation": op})
        if op.get("error", {}).get("code", 0):
            raise RuntimeError("Cloud operation failed: " + json.dumps(op["error"]))
        if observe:
            observe()
        return op

    def create_sa(self, label, roles):
        self.ensure_time(600)
        name = self.state["prefix"] + "-" + label.replace("_", "-")
        if label not in self.state:
            obj = self.mutate("iam", "/api/v2/serviceAccounts", label=label,
                              body={"name": name, "description": self.state["run_id"],
                                    "target": {"projectId": self.client.project_id}})
            uuid.UUID(obj["id"])
            self.state[label] = {"id": obj["id"], "name": obj["name"], "permissions": []}
            self.record()
        obj = self.state[label]
        existing = {p["role"] for p in obj["permissions"]}
        for role in roles:
            if role in existing:
                continue
            permission = self.mutate("iam", "/api/v3/permissions", label=label + ":" + role,
                body={"subjectId": obj["id"], "resourceId": self.client.project_id,
                      "roleIdentifier": {"roleName": role}})
            self.state[label]["permissions"].append({"role": role, "response": permission})
            self.record()
        return self.state[label]

    def prepare_identities(self):
        self.create_sa("cluster_sa", ["platform.project.service-user", "k8s.user", "nlb.user", "vpc.user",
                                      "ar.registry.viewer", "monaas.write"])
        # Cloud.ru's public role matrix permits stop only for k8s.admin.
        # The account is restricted to this dedicated project and deleted after the run.
        guard = self.create_sa("guard_sa", ["platform.project.service-user", "k8s.admin"])
        if not self.state.get("guard_key_id"):
            key = self.mutate("iam", "/api/v2/serviceAccounts/" + guard["id"] + "/accessKeys",
                label="guard_key", body={"description": self.state["run_id"], "ttl": "24h"}, secret_response=True)
            # Handle proto field naming without emitting any key values.
            key_id = key.get("keyId", key.get("key_id"))
            secret = key["secret"]
            if not key_id or not secret:
                raise ValueError("Unexpected access-key response")
            self.client._secrets += (key_id, secret)
            private_write(self.runtime / "guard-profile.json", json.dumps({"project_id": self.client.project_id,
                "key_id": key_id, "key_secret": secret}))
            self.state["guard_key_id"] = key["id"]
            self.record()

    def create_compute(self, label, resource, body):
        if label in self.state:
            return self.state[label]
        self.ensure_time(1200)
        obj = self.mutate("compute", "/api/v1/" + resource, body=body, label=label)
        self.state[label] = {"id": obj["id"], "name": obj["name"]}
        self.record()
        save(self.run / (label + ".json"), obj)
        end = time.monotonic() + 300
        while obj.get("state") not in {"created", "active", "available", "ACTIVE", "CREATED", "AVAILABLE"}:
            if time.monotonic() >= end:
                raise TimeoutError("Compute resource is not ready: " + label)
            time.sleep(5)
            obj = self.client.request("compute", "/api/v1/" + resource + "/" + obj["id"])
            if str(obj.get("state", "")).lower().startswith(("error", "failed")):
                raise RuntimeError("Compute resource failed: " + label)
        save(self.run / (label + ".json"), obj)
        if label == "nat" and obj.get("floating_ip"):
            self.state["nat_ip"] = {k: obj["floating_ip"][k] for k in ("id", "name")}
            self.record()
        return obj

    def provision(self):
        self.ensure_time(2400)
        self.prepare_identities()
        c = self.client
        before = {r: c.compute_list(r) for r in ("vms", "disks", "subnets", "nat-gateways", "floating-ips")}
        save(self.run / "initial-compute.json", before)
        if before["vms"]["items"] or before["disks"]["items"] or c.clusters()["clusters"]:
            raise ValueError("The dedicated pilot project is not empty; reconcile before deploying")
        subnet_net = ipaddress.ip_network("10.80.0.0/24")
        if any(subnet_net.overlaps(ipaddress.ip_network(s["subnet_address"])) for s in before["subnets"]["items"]):
            raise ValueError("Pilot CIDR overlaps an existing subnet")
        configuration = c.request("mk8s", "/v3/productConfiguration", {"projectId": c.project_id})
        master = select_flavor(configuration, cpu=2, ram=4, purpose="FLAVOR_PURPOSE_CONTROLPLANE", zone="ru.AZ-2")
        worker = select_flavor(configuration, cpu=2, ram=4, purpose="FLAVOR_PURPOSE_DATAPLANE", zone="ru.AZ-2")
        self.state["flavor_id"] = worker["flavorId"]
        self.record()
        subnet = self.create_compute("subnet", "subnets", {"name": self.state["prefix"] + "-subnet",
            "project_id": c.project_id, "availability_zone_id": ZONE, "vpc_id": VPC,
            "subnet_address": str(subnet_net), "description": self.state["run_id"],
            "routed_network": True, "default": False})
        self.create_compute("nat", "nat-gateways", {"name": self.state["prefix"] + "-nat",
            "project_id": c.project_id, "availability_zone_id": ZONE, "vpc_id": VPC,
            "nat_type": "Public sNAT", "description": self.state["run_id"]})
        body = {"name": self.state["prefix"] + "-cluster", "projectId": c.project_id,
            "controlPlaneConfiguration": {"zones": [ZONE], "version": "v1.33.13",
                "sizingConfiguration": {"masterCount": 1, "flavorId": master["flavorId"]}},
            "networkConfiguration": {"privateVipSubnetId": subnet["id"], "servicesSubnetCidr": "10.96.0.0/20",
                "podsSubnetCidr": "10.81.0.0/16", "kubeApiInternet": True,
                "networkPlugin": {"cilium": {"enabled": True, "enableEbpfReplacement": False}}},
            "releaseChannel": "RELEASE_CHANNEL_STABLE", "identityConfiguration": {"clusterSaId": self.state["cluster_sa"]["id"]},
            "monitoringService": {"enabled": True}, "loggingService": {"enabled": False}, "auditService": {"enabled": False}}
        op = self.mutate("mk8s", "/v3/clusters", body=body, label="cluster")
        self.state["cluster"] = {"id": op["resourceId"], "name": body["name"], "operation_id": op["id"]}
        self.record()
        self.wait_operation("mk8s", op)
        actual = c.request("mk8s", "/v3/clusters/" + self.state["cluster"]["id"])
        assert_owned(actual, self.state["cluster"], c.project_id)
        save(self.run / "cluster-created.json", actual)
        self.create_group("system", fixed=1, system=True)
        self.refresh_kubeconfig(force=True)
        self.state["provisioned_at"] = stamp()
        self.record()

    def create_group(self, trial_id, *, fixed=None, system=False):
        self.ensure_time(900)
        if not re.fullmatch(r"[a-z0-9-]{3,30}", trial_id):
            raise ValueError("Invalid trial name")
        groups = self.state.setdefault("groups", {})
        if trial_id in groups:
            raise ValueError("Trial pool already exists; do not reuse it")
        if not system and any(k != "system" and not v.get("deleted_at") for k, v in groups.items()):
            raise ValueError("Previous ASR pool must be fully retired within the 8-vCPU quota")
        name = (self.state["prefix"] + "_" + trial_id).replace("-", "_")
        body = node_pool_request(self.state["cluster"]["id"], self.state["subnet"]["id"],
                                 self.state["flavor_id"], name, fixed=fixed, system=system)
        from h2.cloudru_pool_recovery import create_pool
        op, adopted = create_pool(self, trial_id, body)
        pool_id = op["resourceId"] if op else adopted["id"]
        groups[trial_id] = {"id": pool_id, "name": name, "operation_id": op["id"] if op else None,
                            "reconciled_after_lost_response": op is None}
        self.record()
        if op:
            self.wait_operation("mk8s", op, observe=lambda: self.observe_pool_creation(trial_id))
        elif fixed:
            # A zero-sized autoscaling pool can stay PROVISIONING until its
            # first pod arrives; fixed pools must finish creating their VMs.
            end = time.monotonic() + 900
            while adopted["status"] != "OBJECT_STATUS_RUNNING":
                if time.monotonic() >= end:
                    raise TimeoutError("Reconciled fixed pool did not become ready")
                self.observe_pool_creation(trial_id)
                time.sleep(5)
                adopted = self.client.request("mk8s", "/v3/nodePools/" + pool_id)
                assert_owned(adopted, groups[trial_id])
                if adopted["status"] not in {"OBJECT_STATUS_PROVISIONING", "OBJECT_STATUS_RUNNING"}:
                    raise ValueError("Reconciled fixed pool failed to provision")
        actual = self.client.request("mk8s", "/v3/nodePools/" + pool_id)
        assert_owned(actual, groups[trial_id])
        save(self.run / ("pool-" + trial_id + ".json"), actual)
        return actual

    def observe_pool_creation(self, trial_id):
        """Capture provisioning states even for fixed pools before the queue exists."""
        point = {"at": time.time(), "pool_id": self.state["groups"][trial_id]["id"]}
        try:
            page = self.client.request("mk8s", "/v3/nodePools/" + point["pool_id"] + ":listNodes", {"pageSize": 100})
            if page.get("nextPageToken"):
                raise ValueError("Incomplete pool inventory")
            point["nodes"] = page.get("nodes", [])
            vms = self.client.compute_list("vms")["items"]
            point["vms"] = [{k: v[k] for k in ("id", "name", "created_time", "state", "flavor", "interfaces")} for v in vms]
            point["disks"] = self.client.compute_list("disks")["items"]
            point["complete"] = True
        except Exception as error:
            point.update(complete=False, error=self.client.redact(str(error)))
        directory = self.run / "provisioning-observations"
        directory.mkdir(exist_ok=True)
        with (directory / (trial_id + ".jsonl")).open("a") as stream:
            stream.write(json.dumps(point) + "\n")

    def delete_group(self, trial_id):
        group = self.state["groups"][trial_id]
        if group.get("deleted_at"):
            return
        path = "/v3/nodePools/" + group["id"]
        actual = self.client.request("mk8s", path)
        assert_owned(actual, group)
        if actual["clusterId"] != self.state["cluster"]["id"]:
            raise ValueError("Pool cluster identity mismatch")
        op = self.mutate("mk8s", path, method="DELETE", label="delete-pool:" + trial_id)
        self.wait_operation("mk8s", op)
        group["deleted_at"] = stamp()
        self.record()

    def refresh_kubeconfig(self, *, force=False):
        import yaml
        with self._kube_lock:
            token = self.client.bearer()
            if self._kube_token == token and not force:
                return
            path = self.runtime / "kubeconfig"
            if not path.exists() or force:
                result = self.client.request("mk8s", "/v3/clusters/" + self.state["cluster"]["id"] + ":getKubeConfig",
                    method="POST", body={"clusterId": self.state["cluster"]["id"], "network": "NETWORK_TYPE_PUBLIC"})
                cfg = yaml.safe_load(base64.b64decode(result["config"]))
            else:
                cfg = yaml.safe_load(path.read_text())
            for user in cfg["users"]:
                user["user"] = {"token": token}
            private_write(path, yaml.safe_dump(cfg))
            self._kube_token = token

    def kube(self, *args, data=None, timeout=90, binary=False):
        self.refresh_kubeconfig()
        result = subprocess.run(["kubectl", "--kubeconfig", str(self.runtime / "kubeconfig"), *map(str, args)],
            input=json.dumps(data).encode() if data is not None else None, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(self.client.redact(result.stderr.decode(errors="replace"))[:4000])
        return result.stdout if binary else result.stdout.decode()

    def stop(self):
        if not self.state.get("cluster") or self.state["cluster"].get("deleted_at"):
            return
        path = "/v3/clusters/" + self.state["cluster"]["id"]
        actual = self.client.request("mk8s", path)
        assert_owned(actual, self.state["cluster"], self.client.project_id)
        if actual["status"] not in {"OBJECT_STATUS_STOPPED", "OBJECT_STATUS_STOPPING", "OBJECT_STATUS_DELETING"}:
            op = self.mutate("mk8s", path + ":stop", label="stop", body={"clusterId": actual["id"]})
            self.wait_operation("mk8s", op)

    def cleanup(self):
        """Delete owned resources in dependency order; leave failures visible and retryable."""
        errors = []
        def delete(label, service, path, *, query=None, project=True, operation=False):
            saved = self.state.get(label)
            if not saved or saved.get("deleted_at"):
                return
            try:
                obj = self.client.request(service, path + saved["id"], query)
                assert_owned(obj, saved, self.client.project_id if project else None)
                op = self.mutate(service, path + saved["id"], method="DELETE", query=query, label="delete:" + label)
                if operation:
                    self.wait_operation(service, op)
                else:
                    end = time.monotonic() + 300
                    while time.monotonic() < end:
                        try:
                            self.client.request(service, path + saved["id"], query)
                        except CloudruError as error:
                            if error.status == 404:
                                break
                            raise
                        time.sleep(5)
                    else:
                        raise TimeoutError("Deletion not observed: " + label)
                saved["deleted_at"] = stamp()
                self.record()
            except CloudruError as error:
                if error.status == 404:
                    saved["deleted_at"] = stamp()
                    self.record()
                else:
                    errors.append({"resource": label, "http_status": error.status, "detail": error.detail})
            except Exception as error:
                errors.append({"resource": label, "error": self.client.redact(str(error))})
        delete("cluster", "mk8s", "/v3/clusters/", operation=True)
        if not self.state.get("cluster") or self.state["cluster"].get("deleted_at"):
            delete("nat", "compute", "/api/v1/nat-gateways/")
            # A NAT-created address can outlive its parent; track it independently.
            if not self.state.get("nat_ip") and (self.run / "nat.json").exists():
                address = json.loads((self.run / "nat.json").read_text()).get("floating_ip")
                if address:
                    self.state["nat_ip"] = {k: address[k] for k in ("id", "name")}
                    self.record()
            delete("nat_ip", "compute", "/api/v1/floating-ips/")
            delete("subnet", "compute", "/api/v1/subnets/")
            delete("registry", "ar", "/v1/registries/", query={"projectId": self.client.project_id}, project=False, operation=True)
            for label in ("guard_sa", "cluster_sa"):
                delete(label, "iam", "/api/v2/serviceAccounts/", project=False)
        report = {"at": stamp(), "errors": errors, "owned_resources": self.state}
        save(self.run / "cleanup.json", self.client.redact(report))
        if errors:
            raise RuntimeError("Cleanup incomplete; see cleanup.json")
        return report


def initialize(run):
    profile = load_profile()
    run = Path(run).resolve()
    run.mkdir(parents=True, exist_ok=False)
    suffix = datetime.now(UTC).strftime("%m%d%H%M") + secrets.token_hex(2)
    runtime = Path.home() / ".local/share/firefly-thesis" / run.name
    runtime.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(runtime / "api-token", secrets.token_urlsafe(32))
    state = {"run_id": run.name, "prefix": "ffh2-" + suffix, "project_id": profile["project_id"],
             "runtime": str(runtime), "created_at": stamp(), "deadline": (datetime.now(UTC) + timedelta(hours=6)).isoformat(),
             "groups": {}}
    plan = {"provider": "Cloud.ru Evolution", "pilot_only": True, "budget_rub": 500, "max_hours": 6,
        "source_image": SOURCE, "compute_vcpu_max": 8, "asr_worker_resources": {"cpu": "1500m", "memory": "2Gi"},
        "master_rub_per_hour": 8.601, "node_rub_per_hour": 2.9768, "node_ssd_rub_per_hour": .636,
        "maximum_core_rub_per_hour": 23.0522, "estimated_six_hour_total_before_variable_usage": 146.89756848,
        "price_basis": "Cloud.ru API quote and public tariffs; estimate, not actual Billing",
        "guard": "Local watchdog cleans owned resources at deadline; independent cluster CronJob stops compute.",
        "rates_rub_per_hour": {"vcpu": 1.4884, "ram_gib": 0, "network_ssd_gib": .0159, "active_public_ipv4": .2074},
        "rates_note": "2-vCPU/4-GB bundled VM price allocated to vCPU for existing ledger; not a CPU component tariff. SSD uses provider billed GB in size_gib field."}
    save(run / "plan.json", plan)
    save(run / "state.json", state)
    return run


def watchdog(run):
    cloud = Cloud(run)
    while True:
        cloud.state = json.loads((cloud.run / "state.json").read_text())
        if (cloud.run / "cleanup.json").exists() and not json.loads((cloud.run / "cleanup.json").read_text())["errors"]:
            return
        if datetime.now(UTC) >= datetime.fromisoformat(cloud.state["deadline"]):
            try:
                cloud.stop()
            except Exception as error:
                cloud.event("watchdog_stop_error", {"error": str(error)})
            try:
                cloud.cleanup()
                return
            except Exception as error:
                cloud.event("watchdog_error", {"error": str(error)})
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "identities", "provision", "stop", "cleanup", "watchdog"])
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    if args.action == "init":
        run = initialize(args.run)
        with (run / "watchdog.log").open("w") as stream:
            process = subprocess.Popen([sys.executable, "-m", "h2.cloudru_ops", "watchdog", str(run)],
                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        save(run / "watchdog.json", {"pid": process.pid, "started_at": stamp()})
        print(json.dumps({"run": str(run), "watchdog_pid": process.pid}))
        return
    if args.action == "watchdog":
        watchdog(args.run)
        return
    cloud = Cloud(args.run)
    try:
        getattr(cloud, "prepare_identities" if args.action == "identities" else args.action)()
        print(json.dumps({"action": args.action, "ok": True}))
    except CloudruError as error:
        print(json.dumps({"action": args.action, "ok": False, "http_status": error.status, "detail": error.detail}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
