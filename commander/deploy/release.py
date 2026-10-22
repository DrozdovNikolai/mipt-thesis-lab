#!/usr/bin/env python3
"""Install verified dist bytes and atomically select an immutable static release.

Old releases and hashed assets are retained. No network calls, rebuilding, automatic
pruning, backend writes, or implicit production destination.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(root, source, release):
    if not (source / "index.html").is_file() or not (source / "assets").is_dir():
        raise ValueError("Source must contain a built index.html and assets directory")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Release source must not contain symbolic links")
    manifest = {str(path.relative_to(source)): digest(path) for path in sorted(source.rglob("*")) if path.is_file()}
    releases = root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    destination = releases / release
    if destination.exists():
        raise ValueError("Release ID already exists; choose a new immutable ID")
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    for path in (source / "assets").rglob("*"):
        if path.is_file():
            target = assets / path.relative_to(source / "assets")
            if target.exists() and digest(target) != digest(path):
                raise ValueError(f"Hashed asset collision: {target.name}")
    stage = Path(tempfile.mkdtemp(prefix=".install-", dir=releases))
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True)
        (stage / "release-manifest.json").write_text(json.dumps({"release": release, "sha256": manifest}, indent=2) + "\n")
        for path in (stage / "assets").rglob("*"):
            if not path.is_file():
                continue
            target = assets / path.relative_to(stage / "assets")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
                    temporary = Path(temp.name)
                try:
                    shutil.copyfile(path, temporary)
                    temporary.chmod(0o644)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        # mkdtemp uses 0700; the static-server user needs traversal permission.
        stage.chmod(0o755)
        os.rename(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def activate(root, release):
    destination = root / "releases" / release
    if not (destination / "index.html").is_file():
        raise ValueError("Requested installed release is missing index.html")
    manifest = json.loads((destination / "release-manifest.json").read_text())
    for name, expected in manifest["sha256"].items():
        if digest(destination / name) != expected:
            raise ValueError(f"Installed release bytes changed: {name}")
    temporary = root / f".current-{os.getpid()}"
    try:
        temporary.symlink_to(Path("releases") / release)
        os.replace(temporary, root / "current")
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--release", required=True)
    parser.add_argument("--source", type=Path, help="Install this verified dist; omit for rollback")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", args.release):
        parser.error("Release ID must be a simple name, not a path")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.source:
        install(root, args.source.resolve(), args.release)
    if args.activate:
        activate(root, args.release)
    print(json.dumps({"root": str(root), "release": args.release, "activated": args.activate}))


if __name__ == "__main__":
    main()
