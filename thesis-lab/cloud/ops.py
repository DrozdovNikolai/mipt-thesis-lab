"""Provision and control only resources recorded in one Firefly experiment manifest."""

import argparse
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import shlex
from pathlib import Path
import subprocess
import time
import urllib.request

from cloud.render_init import render

ROOT = Path(__file__).resolve().parents[1]


def stamp():
    return datetime.now(UTC).isoformat()


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def yc(plan, *args, timeout=360):
    result = subprocess.run(["yc", "--profile", plan["profile"], "--folder-id", plan["folder_id"], *args, "--format", "json"], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # These commands never carry secrets; include the API error for diagnosis.
        raise RuntimeError(f"yc {' '.join(args[:3])}: {result.stderr[-3000:]}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def read(run):
    return json.loads((run / "plan.json").read_text()), json.loads((run / "resources.json").read_text())


def check_owned(plan, manifest, instance):
    if instance.get("folder_id") != plan["folder_id"] or instance.get("labels", {}).get("experiment") != manifest["run_id"]:
        raise ValueError("Resource ownership does not match the experiment manifest")


def ssh_args(run, role):
    _, state = read(run)
    instance = state["instances"][role]
    address = instance["network_interfaces"][0]["primary_v4_address"]["one_to_one_nat"]["address"]
    command = ["ssh", "-i", state["ssh_key"], "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3", "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=" + str(run / "known_hosts"), "-o", "HostKeyAlias=" + instance["id"]]
    if role == 'loadgen' and state.get('loadgen_ssh_via_server'):
        address = instance['network_interfaces'][0]['primary_v4_address']['address']
        proxy=ssh_args(run,'server')
        proxy=proxy[:-1]+['-W',address+':22',proxy[-1]]
        command+=['-o','ProxyCommand='+shlex.join(proxy)]
    return command+["fflab@"+address]


def refresh(run):
    plan, state = read(run)
    for role, instance in state["instances"].items():
        actual = yc(plan, "compute", "instance", "get", instance["id"])
        check_owned(plan, state, actual)
        state["instances"][role] = actual
    save(run / "resources.json", state)
    return state


def stop(run):
    plan, state = read(run)
    failures = []
    for role, instance in state["instances"].items():
        try:
            actual = yc(plan, "compute", "instance", "get", instance["id"])
            check_owned(plan, state, actual)
            if actual["status"] not in ("STOPPED", "STOPPING"):
                yc(plan, "compute", "instance", "stop", actual["id"])
            print("STOPPED", role, actual["id"], flush=True)
        except Exception as error:
            failures.append({"role": role, "error": str(error)})
    save(run / "stop.json", {"at": stamp(), "failures": failures})
    if failures:
        raise RuntimeError("One or more VM stop operations failed; see stop.json")


def provision(run):
    run.mkdir(parents=True, exist_ok=False)
    plan = json.loads((ROOT / "cloud/plan.json").read_text())
    if plan["grant"]["confirmed_remaining_rub"] < 200 or plan["approved_first_window_hours"] > 6:
        raise ValueError("The approved first window or available grant is invalid")
    for service, kind in (("compute", "instance"), ("compute", "disk"), ("vpc", "network")):
        if yc(plan, service, kind, "list"):
            raise ValueError("The experiment folder is no longer empty; inspect before provisioning")
    with urllib.request.urlopen("https://api.ipify.org", timeout=20) as response:
        address = str(ipaddress.IPv4Address(response.read().decode().strip()))
    key = Path.home() / ".ssh/firefly-thesis-cloud-20261003"
    key.parent.mkdir(mode=0o700, exist_ok=True)
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "firefly-thesis-cloud", "-f", str(key)], check=True)
    key.chmod(0o600)
    started = datetime.now(UTC)
    deadline = started + timedelta(hours=6)
    state = {"run_id": run.name, "created_at": stamp(), "deadline": deadline.isoformat(), "ssh_key": str(key), "operator_ipv4": address, "instances": {}, "security_groups": {}}
    save(run / "plan.json", plan)
    save(run / "resources.json", state)
    config = render(key.with_suffix(".pub").read_text(), deadline, started)
    init = run / "cloud-init.json"
    init.write_text("#cloud-config\n" + json.dumps(config, indent=2) + "\n")
    labels = "project=firefly-thesis,experiment=" + state["run_id"]

    def created(key, value):
        state[key] = value
        save(run / "resources.json", state)
        print("CREATED", key, value.get("id", ""), flush=True)
        return value

    try:
        network = created("network", yc(plan, "vpc", "network", "create", "ff-thesis-20261003", "--labels", labels))
        subnet = created("subnet", yc(plan, "vpc", "subnet", "create", "ff-thesis-20261003-a", "--network-id", network["id"], "--zone", plan["zone"], "--range", plan["subnet_cidr"], "--labels", labels))
        for role in ("server", "loadgen"):
            rules = ["direction=ingress,protocol=tcp,port=22,v4-cidrs=" + address + "/32", "direction=egress,protocol=any,port=any,v4-cidrs=0.0.0.0/0"]
            if role == "server":
                rules.append("direction=ingress,protocol=tcp,from-port=18000,to-port=18002,v4-cidrs=10.77.0.20/32")
            flags = [arg for rule in rules for arg in ("--rule", rule)]
            state["security_groups"][role] = yc(plan, "vpc", "security-group", "create", "ff-thesis-" + role, "--network-id", network["id"], "--labels", labels, *flags)
            save(run / "resources.json", state)
        sa = created("service_account", yc(plan, "iam", "service-account", "create", "ff-thesis-metrics", "--description", "Temporary Firefly metrics writer"))
        yc(plan, "resource-manager", "folder", "add-access-binding", plan["folder_id"], "--role", "monitoring.editor", "--subject", "serviceAccount:" + sa["id"])
        state["metrics_role_bound"] = True
        save(run / "resources.json", state)
        for machine in plan["machines"]:
            role = machine["role"]
            interface = f"subnet-id={subnet['id']},address={machine['private_ip']},nat-ip-version=ipv4,security-group-ids={state['security_groups'][role]['id']}"
            disk = f"name=ff-thesis-{role}-20261003,type=network-ssd,size={machine['ssd_gib']},image-id={plan['image_id']},auto-delete=true"
            instance = yc(plan, "compute", "instance", "create", "ff-thesis-" + role + "-20261003", "--zone", plan["zone"], "--platform", plan["platform"], "--cores", str(machine["cores"]), "--core-fraction", "100", "--memory", str(machine["memory_gib"]), "--create-boot-disk", disk, "--network-interface", interface, "--service-account-id", sa["id"], "--metadata-from-file", "user-data=" + str(init), "--metadata", "serial-port-enable=1", "--labels", labels + ",role=" + role)
            state["instances"][role] = instance
            save(run / "resources.json", state)
            print("CREATED instance", role, instance["id"], flush=True)
        state["provisioned_at"] = stamp()
        save(run / "resources.json", state)
    except BaseException as error:
        save(run / "provision-failure.json", {"at": stamp(), "error": str(error)})
        if state["instances"]:
            stop(run)
        raise


def cleanup(run):
    # Deleting disks is allowed only after independently verified local copies.
    plan, state = read(run)
    confirmation = json.loads((run / "backup-verified.json").read_text())
    if not confirmation.get("passed") or confirmation.get("run_id") != state["run_id"]:
        raise ValueError("Verified backup marker is absent")
    removed = []
    for role, instance in state["instances"].items():
        actual = yc(plan, "compute", "instance", "get", instance["id"])
        check_owned(plan, state, actual)
        if not actual["boot_disk"].get("auto_delete"):
            raise ValueError("Boot disk auto-delete was not enabled")
        yc(plan, "compute", "instance", "delete", actual["id"])
        removed.append({"type": "instance", "id": actual["id"], "disk_id": actual["boot_disk"]["disk_id"], "at": stamp()})
        save(run / "cleanup.json", {"removed": removed, "complete": False})
    for value in state["security_groups"].values():
        yc(plan, "vpc", "security-group", "delete", value["id"])
    yc(plan, "vpc", "subnet", "delete", state["subnet"]["id"])
    yc(plan, "vpc", "network", "delete", state["network"]["id"])
    yc(plan, "resource-manager", "folder", "remove-access-binding", plan["folder_id"], "--role", "monitoring.editor", "--subject", "serviceAccount:" + state["service_account"]["id"])
    yc(plan, "iam", "service-account", "delete", state["service_account"]["id"])
    save(run / "cleanup.json", {"removed": removed, "complete": True, "completed_at": stamp(), "remaining_instances": yc(plan, "compute", "instance", "list"), "remaining_disks": yc(plan, "compute", "disk", "list")})


def watchdog(run):
    _, state = read(run)
    deadline = datetime.fromisoformat(state["deadline"])
    while datetime.now(UTC) < deadline:
        if (run / "cleanup.json").exists() and json.loads((run / "cleanup.json").read_text()).get("complete"):
            return
        time.sleep(min(30, max(1, (deadline - datetime.now(UTC)).total_seconds())))
    stop(run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("provision", "stop", "refresh", "cleanup", "watchdog"))
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    globals()[args.action](args.run.resolve())
