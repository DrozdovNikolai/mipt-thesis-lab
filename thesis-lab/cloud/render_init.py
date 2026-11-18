"""Render cloud-init with an absolute, persistent shutdown deadline; creates no VM."""

import argparse
import base64
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import shlex


def render(public_key, deadline, now):
    fields = public_key.strip().split()
    if len(fields) < 2 or fields[0] not in {"ssh-ed25519", "ssh-rsa"}:
        raise ValueError("Expected an OpenSSH public key, never a private key")
    base64.b64decode(fields[1], validate=True)
    if not now + timedelta(minutes=10) <= deadline <= now + timedelta(hours=6):
        raise ValueError("Deadline must be 10 minutes to 6 hours in the future")
    timer = "\n".join([
        "[Unit]", "Description=Firefly experiment absolute shutdown deadline",
        "[Timer]", "OnCalendar=" + deadline.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "Persistent=true", "AccuracySec=1s", "Unit=firefly-thesis-stop.service",
        "[Install]", "WantedBy=timers.target", "",
    ])
    service = "\n".join([
        "[Unit]", "Description=Stop temporary Firefly experiment VM",
        "[Service]", "Type=oneshot", "ExecStart=/usr/bin/systemctl poweroff", "",
    ])
    # bootcmd runs before package operations: a package failure should not prevent
    # installing the guard. An absolute deadline does not reset after a reboot.
    boot = "\n".join([
        "set -eu",
        "if [ \"$(date -u +%s)\" -ge " + str(int(deadline.timestamp())) + " ]; then systemctl --no-block poweroff; exit 0; fi",
        "printf '%s' " + shlex.quote(service) + " > /etc/systemd/system/firefly-thesis-stop.service",
        "printf '%s' " + shlex.quote(timer) + " > /etc/systemd/system/firefly-thesis-stop.timer",
        "systemctl daemon-reload",
        "systemctl enable --now --no-block firefly-thesis-stop.timer",
    ])
    return {
        "ssh_pwauth": False,
        "disable_root": True,
        "users": [{"name": "fflab", "shell": "/bin/bash", "sudo": "ALL=(ALL) NOPASSWD:ALL", "lock_passwd": True, "ssh_authorized_keys": [" ".join(fields)]}],
        "bootcmd": [["/bin/bash", "-ceu", boot]],
        "package_update": True,
        "package_upgrade": False,
        "packages": ["docker.io", "docker-compose-v2", "python3", "sysstat", "curl"],
        "runcmd": [["systemctl", "enable", "--now", "docker"], ["mkdir", "-p", "/opt/firefly-thesis"], ["chown", "fflab:fflab", "/opt/firefly-thesis"], ["systemctl", "is-active", "firefly-thesis-stop.timer"]],
        "final_message": "Firefly bootstrap finished; shutdown deadline: " + deadline.isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-public-key", type=Path, required=True)
    parser.add_argument("--deadline", required=True, help="Absolute RFC3339 time, no more than 6 hours ahead")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    deadline = datetime.fromisoformat(args.deadline.replace("Z", "+00:00"))
    if deadline.tzinfo is None:
        parser.error("Deadline requires an explicit timezone")
    data = render(args.ssh_public_key.read_text(), deadline.astimezone(UTC), datetime.now(UTC))
    with args.output.open("x") as stream:
        stream.write("#cloud-config\n" + json.dumps(data, indent=2) + "\n")
    print(str(args.output))


if __name__ == "__main__":
    main()
