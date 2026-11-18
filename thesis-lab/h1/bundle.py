"""Create a portable, checksummed CPU baseline bundle from the existing worktree."""

import argparse
from datetime import UTC, datetime
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IMAGES = {
    "firefly-thesis/backend-runtime:20260916": "sha256:47bf950acece7b1a02f09c7d94f43fc6ac89dc3082e8844e2cac255db755413f",
    "firefly-thesis/postgres:18.1-frozen": "sha256:b40d931bd0e7ce6eecc59a5a6ac3b3c04a01e559750e73e7086b6dbd7f8bf545",
    "firefly-thesis/redis:7-frozen": "sha256:ee64a64eaab618d88051c3ade8f6352d11531fcf79d9a4818b9b183d8c1d18ba",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def permitted(path):
    return (
        not any(part.startswith(".env") or part in {"__pycache__", ".git", "node_modules", ".venv"} for part in path.parts)
        and path.suffix not in {".pem", ".key", ".p12", ".pfx", ".pyc"}
        and path.name not in {"credentials.json", "authorized_key.json", "id_rsa", "id_ed25519"}
    )


def copy(source, destination):
    if source.is_symlink():
        raise ValueError(f"Symlink requires explicit review: {source.name}")
    if source.is_file() and permitted(source.relative_to(ROOT)):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--without-images", action="store_true", help="For source-only inspection, not deployment")
    parser.add_argument("--backend", type=Path, default=ROOT / "worktrees/h1-durable/firefly-backend")
    parser.add_argument("--purpose", default="Existing CPU H3 baseline replication; not evidence for new H2/finer H3")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"created_at": datetime.now(UTC).isoformat(), "purpose": args.purpose, "images": {}, "sources": {}}
    try:
        backend = args.backend.resolve()
        manifest["backend_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=backend, text=True).strip()
        manifest["backend_status_sha256"] = hashlib.sha256(subprocess.check_output(["git", "status", "--porcelain=v1", "-z"], cwd=backend)).hexdigest()
        names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=backend).decode().split("\0")
        top = {"app", "alembic", "seed", "tests", "scripts", "pyproject.toml", "alembic.ini", "README.md"}
        for name in sorted(set(names)):
            if name and Path(name).parts[0] in top:
                copy(backend / name, out / "backend" / name)
        for directory in ("expanded", "benchmarks", "cloud", "h3", "h1"):
            for source in sorted((ROOT / directory).rglob("*")):
                if source.suffix in {".py", ".sql", ".yml", ".json", ".md", ".mjs"}:
                    copy(source, out / source.relative_to(ROOT))
        for name in ("THESIS_HYPOTHESES.md", "YANDEX_CLOUD_DASHBOARD_PLAN.md", "EXPANDED_PLAN.md"):
            copy(ROOT / name, out / name)
        instructor = ROOT / "worktrees/h1-durable/firefly-instructor"
        manifest['instructor_revision'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=instructor,text=True).strip()
        for directory in ('lib','test','integration_test','web','build/web'):
            for file in (instructor/directory).rglob('*'):
                if file.is_file(): copy(file,out/'instructor'/file.relative_to(instructor))
        for name in ('pubspec.yaml','pubspec.lock'):
            copy(instructor/name,out/'instructor'/name)
        (out / "results").mkdir()
        for source in sorted(out.rglob("*")):
            if source.is_file():
                manifest["sources"][str(source.relative_to(out))] = digest(source)
        for target, reference in IMAGES.items():
            inspected = json.loads(subprocess.check_output(["docker", "image", "inspect", reference], text=True))[0]
            manifest["images"][target] = {key: inspected.get(key) for key in ("Id", "RepoDigests", "Architecture", "Os", "Size")}
            if args.without_images:
                continue
            existing = subprocess.run(["docker", "image", "inspect", target], capture_output=True, text=True)
            if existing.returncode == 0 and json.loads(existing.stdout)[0]["Id"] != inspected["Id"]:
                raise ValueError(f"Refusing to replace an existing, different image tag: {target}")
            subprocess.run(["docker", "tag", reference, target], check=True)
        if not args.without_images:
            with (out / "images.tar.gz").open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=1, mtime=0) as compressed:
                process = subprocess.Popen(["docker", "save", *IMAGES], stdout=subprocess.PIPE)
                try:
                    shutil.copyfileobj(process.stdout, compressed, length=1024 * 1024)
                finally:
                    process.stdout.close()
                if process.wait():
                    raise RuntimeError("docker save failed")
        manifest["images_exported"] = not args.without_images
        (out / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")
        files = sorted(p for p in out.rglob("*") if p.is_file())
        (out / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.relative_to(out)}\n" for p in files))
        print(json.dumps({"path": str(out), "files": len(files), "images_exported": manifest["images_exported"], "sha256sums": digest(out / "SHA256SUMS")}, indent=2))
    except BaseException as error:
        (out / "bundle-failure.json").write_text(json.dumps({"type": type(error).__name__, "message": str(error)}, indent=2))
        raise


if __name__ == "__main__":
    main()
