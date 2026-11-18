"""Mirror upstream KEDA images without rebuilding or altering their contents."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess

import yaml

from h2.cloudru_ops import private_write, save, stamp


def inspect(image):
    return json.loads(subprocess.check_output(["docker", "image", "inspect", image], text=True))[0]


def publish_revision(cloud, *, source, revision):
    """Publish a versioned pilot correction; retain the original image identity."""
    if not re.fullmatch(r"[a-z0-9-]+", revision):
        raise ValueError("Invalid image revision")
    cloud.ensure_time(1200)
    original = inspect(source)
    registry = cloud.state["registry"]["name"] + ".cr.cloud.ru"
    config = cloud.runtime / ("docker-" + revision)
    config.mkdir(mode=0o700, exist_ok=True)
    profile = cloud.client.profile
    auth = base64.b64encode((profile["key_id"] + ":" + profile["key_secret"]).encode()).decode()
    private_write(config / "config.json", json.dumps({"auths": {registry: {"auth": auth}}}))
    tag = registry + "/h2-cpu:" + revision
    try:
        subprocess.run(["docker", "tag", source, tag], check=True)
        with (cloud.run / (revision + "-push.log")).open("w") as stream:
            pushed = subprocess.run(["docker", "--config", str(config), "push", "--platform=linux/amd64", tag],
                capture_output=True, text=True, timeout=900)
            stream.write(pushed.stdout + pushed.stderr)
            pushed.check_returncode()
            hashes = re.findall(r"\bdigest: (sha256:[0-9a-f]{64})\b", pushed.stdout + pushed.stderr)
            if len(hashes) != 1:
                raise ValueError("Pushed image digest is ambiguous")
            target = registry + "/h2-cpu@" + hashes[0]
            subprocess.run(["docker", "--config", str(config), "pull", "--platform=linux/amd64", target],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
            published = inspect(target)
        for field in ("RootFS", "Config", "Architecture", "Os"):
            if original[field] != published[field]:
                raise ValueError("Published image differs from the local revision: " + field)
        proof = {"at": stamp(), "revision": revision, "local_image": original["Id"], "published_image": target,
            "previous_published_image": cloud.state["published_image"], "content_parity": True,
            "rootfs_layers": published["RootFS"]["Layers"]}
        save(cloud.run / (revision + "-published.json"), proof)
        cloud.state.setdefault("image_revisions", []).append(proof)
        cloud.state["published_image"] = target
        cloud.record()
        return target
    finally:
        (config / "config.json").unlink(missing_ok=True)


def mirror_keda(cloud):
    source_file = Path.home() / ".local/share/firefly-thesis/h2-tools/keda-2.18.0.yaml"
    objects = list(yaml.safe_load_all(source_file.read_text()))
    sources = sorted({c["image"] for o in objects if o and o["kind"] == "Deployment"
                      for c in o["spec"]["template"]["spec"]["containers"]})
    registry = cloud.state["registry"]["name"] + ".cr.cloud.ru"
    config = cloud.runtime / "docker-keda"
    config.mkdir(mode=0o700, exist_ok=True)
    profile = cloud.client.profile
    auth = base64.b64encode((profile["key_id"] + ":" + profile["key_secret"]).encode()).decode()
    private_write(config / "config.json", json.dumps({"auths": {registry: {"auth": auth}}}))
    mapping = cloud.state.setdefault("keda_images", {})
    try:
        for source in sources:
            if source in mapping:
                continue
            cloud.ensure_time(1200)
            if not source.startswith("ghcr.io/kedacore/") or not source.endswith(":2.18.0"):
                raise ValueError("Unexpected upstream KEDA image")
            name = source.rsplit("/", 1)[-1].split(":")[0]
            tag = registry + "/" + name + ":2.18.0"
            with (cloud.run / (name + "-mirror.log")).open("w") as stream:
                subprocess.run(["docker", "pull", "--platform=linux/amd64", source], check=True,
                               stdout=stream, stderr=subprocess.STDOUT, timeout=600)
                original = inspect(source)
                subprocess.run(["docker", "tag", source, tag], check=True)
                pushed = subprocess.run(["docker", "--config", str(config), "push", "--platform=linux/amd64", tag],
                                        capture_output=True, text=True, timeout=600)
                stream.write(pushed.stdout + pushed.stderr)
                pushed.check_returncode()
                # Docker's local RepoDigests can retain the original multi-arch
                # index even though --platform pushed only the amd64 manifest.
                hashes = re.findall(r"\bdigest: (sha256:[0-9a-f]{64})\b", pushed.stdout + pushed.stderr)
                if len(hashes) != 1:
                    raise ValueError("Pushed single-platform manifest digest is ambiguous")
                digests = [registry + "/" + name + "@" + hashes[0]]
                subprocess.run(["docker", "--config", str(config), "pull", "--platform=linux/amd64", digests[0]], check=True,
                               stdout=stream, stderr=subprocess.STDOUT, timeout=600)
                mirrored = inspect(digests[0])
            for field in ("RootFS", "Config", "Architecture", "Os"):
                if original[field] != mirrored[field]:
                    raise ValueError("Mirrored image content differs from upstream: " + field)
            proof = {"source": source, "source_digests": original.get("RepoDigests"), "mirror": digests[0],
                     "content_parity": True, "rootfs_layers": original["RootFS"]["Layers"],
                     "config_sha256": hashlib.sha256(json.dumps(original["Config"], sort_keys=True).encode()).hexdigest(),
                     "architecture": mirrored["Architecture"], "os": mirrored["Os"]}
            save(cloud.run / (name + "-mirror-verified.json"), proof)
            mapping[source] = digests[0]
            cloud.record()
            print(json.dumps({"mirrored": source, "verified": True}), flush=True)
    finally:
        (config / "config.json").unlink(missing_ok=True)
    return objects, mapping
