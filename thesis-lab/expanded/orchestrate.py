"""Host orchestrator. Only the expanded compose project and its allowlisted databases are changed."""

import argparse
from datetime import datetime, UTC
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.expanded.yml")]
PROFILES = [
    dict(id="history-1k", n=1000, pilots=1000),
    dict(id="history-10k", n=10000, pilots=1000),
    dict(id="history-100k", n=100000, pilots=1000),
    dict(id="pilots-100", n=100000, pilots=100),
    dict(id="skew-80-10", n=100000, pilots=1000, skew=True),
    dict(id="neighbors-4", n=100000, pilots=1000, neighbors=4),
]
VARIANTS = ("original", "optimized", "projection")


def run(args, **kw):
    return subprocess.run(args, cwd=ROOT, check=True, **kw)


def compose(*args, **kw):
    return run(COMPOSE + list(args), **kw)


def inside(output, module, *args, database="functional"):
    assert database in ("functional", "seed", *VARIANTS)
    out = "/results/" + str(output.relative_to(ROOT / "results"))
    url = f"postgresql+asyncpg://thesis:thesis@db:5432/thesis_exp_{database}"
    sync = url.replace("postgresql+asyncpg", "postgresql+psycopg")
    compose(
        "run",
        "--rm",
        "--no-deps",
        "-e",
        "THESIS_OUTPUT=" + out,
        "-e",
        "THESIS_QUIET_GATE=" + os.environ.get("THESIS_QUIET_GATE", "0"),
        "-e",
        "DATABASE_URL=" + url,
        "-e",
        "DATABASE_SYNC_URL=" + sync,
        "runner",
        "python",
        "-m",
        module,
        *map(str, args),
    )


def psql(sql):
    return compose(
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        "thesis",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    )


def prepare(output, profile):
    output.mkdir(parents=True, exist_ok=True)
    compose("stop", "original", "optimized", "projection", "seed", "worker")
    inside(output, "expanded.init_db", database="seed")
    compose("up", "-d", "--wait", "seed")
    inside(output, "expanded.dataset", json.dumps(profile), database="seed")
    compose("stop", "seed")
    for variant in VARIANTS:
        db = "thesis_exp_" + variant
        psql(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        psql(f"CREATE DATABASE {db} TEMPLATE thesis_exp_seed")
        inside(output, "expanded.install", variant, database=variant)
    compose("up", "-d", "--wait", *VARIANTS)
    inside(output, "expanded.reads", "--check")
    for variant in VARIANTS:
        inside(output, "expanded.explain", variant, database=variant)


def freeze(output, config):
    output.mkdir(parents=True, exist_ok=True)
    assert not (output / "run.json").exists(), "Refusing to overwrite an existing run"
    config["started_at"] = datetime.now(UTC).isoformat()
    (output / "run.json").write_text(json.dumps(config, indent=2))
    hashes = {}
    for folder in (
        "expanded",
        "worktrees/expanded/firefly-backend",
        "worktrees/expanded/firefly-instructor",
        "worktrees/expanded/firefly-session",
        "worktrees/expanded/firefly-commander",
    ):
        p = ROOT / folder
        if "worktrees" in folder:
            paths = (
                subprocess.check_output(
                    [
                        "git",
                        "ls-files",
                        "-z",
                        "--cached",
                        "--others",
                        "--exclude-standard",
                    ],
                    cwd=p,
                )
                .decode()
                .split("\0")
            )
            files = [
                p / f
                for f in paths
                if f and not Path(f).name.startswith(".env") and (p / f).is_file()
            ]
        else:
            files = [
                f for f in p.rglob("*") if f.is_file() and "__pycache__" not in f.parts
            ]
        for f in files:
            hashes[str(f.relative_to(ROOT))] = hashlib.sha256(
                f.read_bytes()
            ).hexdigest()
    (output / "versions.json").write_text(json.dumps(hashes, indent=2))
    revisions = {
        name: subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT / "worktrees/expanded" / name
        )
        .decode()
        .strip()
        for name in (
            "firefly-backend",
            "firefly-instructor",
            "firefly-session",
            "firefly-commander",
        )
    }
    (output / "revisions.json").write_text(json.dumps(revisions, indent=2))
    bundle = ROOT / "worktrees/expanded/firefly-instructor/build/web/main.dart.js"
    if bundle.exists():
        (output / "browser-bundle.json").write_text(
            json.dumps(
                dict(
                    main_dart_js_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                    node=subprocess.check_output(["node", "--version"])
                    .decode()
                    .strip(),
                    flutter="3.38.9",
                    dart="3.10.8",
                    chromium="148.0.7778.96",
                ),
                indent=2,
            )
        )
    (output / "plan.md").write_bytes((ROOT / "EXPANDED_PLAN.md").read_bytes())
    (output / "compose.yml").write_bytes(
        subprocess.check_output(COMPOSE + ["config"], cwd=ROOT)
    )


def main(args):
    output = ROOT / "results" / args.output
    profiles = (
        PROFILES
        if args.profile == "all"
        else [p for p in PROFILES if p["id"] == args.profile]
    )
    assert profiles
    config = dict(
        phase=args.phase,
        profiles=profiles,
        repeats=args.repeats,
        requests=args.requests,
    )
    freeze(output, config)
    try:
        compose("up", "-d", "--wait", "db", "redis")
        if args.phase == "h2":
            compose("stop", "functional")
            inside(output, "expanded.init_db")
            compose("up", "-d", "--wait", "functional")
            inside(output, "expanded.h2", "--repeats", args.repeats)
        elif args.phase in ("reads", "pilot"):
            for profile in profiles:
                target = output / profile["id"]
                prepare(target, profile)
                for rep in range(args.repeats):
                    if rep:
                        compose("restart", "-t", "2", *VARIANTS)
                        compose("up", "-d", "--wait", *VARIANTS)
                    inside(
                        target,
                        "expanded.reads",
                        "--rep",
                        rep,
                        "--requests",
                        args.requests,
                    )
                (target / "complete.json").write_text(json.dumps(dict(passed=True)))
        elif args.phase == "mixed":
            profile = next(p for p in PROFILES if p["id"] == "history-100k")
            target = output / profile["id"]
            prepare(target, profile)
            env = {
                **os.environ,
                "THESIS_OUTPUT": "/results/"
                + str(target.relative_to(ROOT / "results")),
            }
            compose("up", "-d", "--force-recreate", "worker", env=env)
            inside(target, "expanded.mixed", "--repeats", args.repeats)
            compose("stop", "worker")
        (output / "complete.json").write_text(
            json.dumps(dict(completed_at=datetime.now(UTC).isoformat()))
        )
    except BaseException as exc:
        (output / "failure.json").write_text(
            json.dumps(dict(type=type(exc).__name__, message=str(exc)))
        )
        raise
    print("Expanded run complete:", output, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["pilot", "reads", "h2", "mixed"], required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--profile", default="all")
    p.add_argument("--repeats", type=int, default=10)
    p.add_argument("--requests", type=int, default=20)
    main(p.parse_args())
