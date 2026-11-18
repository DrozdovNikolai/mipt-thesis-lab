"""Cloud.ru trial adapter: pool IDs bind ASR pods to actual billed VMs/disks."""
import argparse
import json
from pathlib import Path
import time

from h2.cloudru_manifests import cloudru_objects
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_preflight import CloudruError
from h2.cloud_trial import Trial as BaseTrial
from h2.cloud_pilot import run


def nodes(client, pool_id):
    rows, seen, token = [], set(), ""
    for _ in range(100):
        page = client.request("mk8s", "/v3/nodePools/" + pool_id + ":listNodes",
                              {"pageSize": 100, "pageToken": token})
        rows += page.get("nodes", [])
        token = page.get("nextPageToken", "")
        if not token:
            return rows
        if token in seen:
            raise ValueError("Repeated node inventory cursor")
        seen.add(token)
    raise ValueError("Node inventory exceeded page bound")


def normalize_inventory(vms, disks, member_ids, known_disks, *, flavor_id):
    members = [v for v in vms if v["id"] in member_ids]
    for disk in disks:
        if any(v["id"] in member_ids for v in disk["vms"]):
            known_disks.add(disk["id"])
    instance_rows = []
    states = {"creating": "PROVISIONING", "starting": "STARTING", "running": "RUNNING", "deleting": "DELETING"}
    for vm in members:
        f = vm["flavor"]
        if f["id"] != flavor_id or (f["cpu"], f["ram"], f["gpu"], f["oversubscription"]) != (2, 4, 0, "1:1"):
            raise ValueError("Trial VM allocation changed")
        if vm["state"] not in states:
            raise ValueError("Unexpected VM state requires separate accounting: " + vm["state"])
        public = any(n.get("floating_ip") for n in vm["interfaces"])
        if public:
            raise ValueError("ASR VM unexpectedly has a billed public IP")
        instance_rows.append({"id": vm["id"], "created_at": vm["created_time"], "status": states[vm["state"]],
                              "cores": 2, "memory_gib": 4e9 / 2**30, "provider_ram_gb": 4, "public_ip": False})
    disk_rows = []
    for d in disks:
        if d["id"] not in known_disks:
            continue
        if d["disk_type"]["name"] != "SSD" or d["size"] != 40:
            raise ValueError("Trial disk allocation changed")
        disk_rows.append({"id": d["id"], "created_at": d["created_time"], "type": "network-ssd",
                          "size_gib": d["size"], "size_unit": "provider-billed-GB"})
    return instance_rows, disk_rows


class Trial(BaseTrial):
    def __init__(self, *args, **kwargs):
        if not args[0].state.get("system_pinned_at"):
            raise ValueError("Pin system deployments before starting an ASR trial")
        super().__init__(*args, **kwargs)
        self.known_instances = set()
        self.known_nodes = set()

    def render_objects(self, group):
        return cloudru_objects(self.cloud.state["published_image"], namespace=self.ns,
            system_pool_id=self.cloud.state["groups"]["system"]["id"], worker_pool_id=group["id"], compact=True)

    def cloud_inventory(self):
        c = self.cloud
        pool = c.state["groups"][self.id]
        try:
            pool_nodes = nodes(c.client, pool["id"])
        except CloudruError as error:
            if error.status == 404 and pool.get("deleted_at"):
                pool_nodes = []
            else:
                raise
        for node in pool_nodes:
            if node["nodePoolId"] != pool["id"] or node["clusterId"] != c.state["cluster"]["id"]:
                raise ValueError("Unexpected node ownership")
            machine_id = node.get("machine", {}).get("id") or node.get("id")
            if machine_id:
                self.known_instances.add(machine_id)
                self.known_nodes.add("vm-" + machine_id)
            if node.get("hostname"):
                self.known_nodes.add(node["hostname"])
        vms = c.client.compute_list("vms")["items"]
        disks = c.client.compute_list("disks")["items"]
        instances, disk_rows = normalize_inventory(vms, disks, self.known_instances,
                                                  self.known_disks, flavor_id=c.state["flavor_id"])
        save(self.output / "resource-identities.json", {"pool_id": pool["id"], "vm_ids": sorted(self.known_instances),
                                                       "disk_ids": sorted(self.known_disks), "at": stamp()})
        # Do not archive remote-console access URLs from raw Compute VM responses.
        with (self.output / "cloud-inventory.jsonl").open("a") as stream:
            stream.write(json.dumps({"at": stamp(), "nodes": pool_nodes,
                "vms": [{k: v[k] for k in ("id", "name", "flavor", "state", "created_time", "interfaces")} for v in vms],
                "disks": disks}) + "\n")
        all_disks = [{"id": d["id"], "created_at": d["created_time"], "size": d["size"], "size_unit": "GB"} for d in disks]
        return instances, disk_rows, all_disks

    def observe(self):
        try:
            point = super().observe()
        except (ValueError, AssertionError) as error:
            # A schema/allocation/lifecycle violation is not an ordinary failed
            # HTTP poll. Do not continue and later call the result valid.
            self.fatal_observation_error = str(error)
            save(self.output / "validation-failure.json", {"at": stamp(),
                "type": type(error).__name__, "error": str(error)})
            raise
        misplaced = [p for p in point["pods"] if p["node"] and p["node"] not in self.known_nodes]
        if misplaced:
            self.fatal_observation_error = "ASR pod was assigned outside this trial's owned node pool"
            save(self.output / "placement-failure.json", {"at": stamp(), "pods": misplaced,
                "known_nodes": sorted(self.known_nodes), "pool_id": self.cloud.state["groups"][self.id]["id"]})
            raise ValueError(self.fatal_observation_error)
        return point


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    cloud = Cloud(args.run)
    try:
        run(cloud, trial_class=Trial, capacity_workers=3)
    except BaseException:
        cloud.stop()
        raise
