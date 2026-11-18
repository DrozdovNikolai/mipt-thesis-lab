"""Prepare a small explicit build context on the Linux filesystem."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".cache/firefly-thesis-h2"
WORKTREE = ROOT / "worktrees/h2-autoscaling/firefly-backend"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="firefly-thesis/h2-cpu:20261005-v1")
    args = parser.parse_args()
    context = CACHE / "build"
    context.mkdir(exist_ok=True, parents=True)
    for name, source in (("app", WORKTREE / "app"), ("scripts", WORKTREE / "scripts"), ("h2", ROOT / "h2"),
                         ("cache/hf", CACHE / "hf"), ("cache/torch", CACHE / "torch")):
        dest = context / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "h2/Dockerfile", context / "Dockerfile")
    frozen = {str(p.relative_to(context)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in context.rglob("*") if p.is_file()}
    (ROOT / "results/h2-local-20261005-a/build-inputs.json").write_text(json.dumps(frozen, indent=2))
    subprocess.run(["docker", "build", "--tag", args.tag, str(context)], check=True)
    identity = subprocess.check_output(["docker", "image", "inspect", args.tag, "--format", "{{.Id}}"], text=True).strip()
    (ROOT / "results/h2-local-20261005-a/image-id.txt").write_text(identity + "\n")
    print(identity)


if __name__ == "__main__":
    main()
