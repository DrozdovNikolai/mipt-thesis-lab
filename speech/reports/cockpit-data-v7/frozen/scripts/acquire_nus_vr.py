"""Retrieve pinned public NUS VR Parquet files into inspection-only quarantine."""

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY = "wangyubo013-blip/CDE4301-VR-401-Final-Report"
REVISION = "0c520edbcd345cb9005cc77c3345eedbfef7147b"
PREFIX = "faster_whisper/whisper_training/"
MAX_FILE = 20 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def verify_blob(body, row):
    actual = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
    if len(body) != row["size"] or actual != row["sha"]:
        raise ValueError(f"Publisher length/Git blob mismatch: {row['path']}")
    if not body.startswith(b"PAR1") or not body.endswith(b"PAR1"):
        raise ValueError("Not an unencrypted Parquet file")


def select_files(tree):
    if tree.get("truncated") or tree.get("sha") != REVISION:
        raise ValueError("Require a complete tree at the pinned revision")
    selected = []
    for row in tree["tree"]:
        if row["type"] != "blob" or not row["path"].startswith(PREFIX):
            continue
        name = row["path"][len(PREFIX):]
        if not name.endswith(".parquet"):
            continue
        if not re.fullmatch(r"(?:Sample0[1-7](?:\(1\))?|CombinedSamples_01_03_04_05_06_07)\.parquet", name):
            raise ValueError(f"Unexpected prepared payload: {name}")
        if not 0 < row["size"] <= MAX_FILE:
            raise ValueError("File size outside frozen acquisition bound")
        selected.append(row)
    if len(selected) != 10 or sum(row["size"] for row in selected) > MAX_TOTAL:
        raise ValueError("Unexpected pinned collection size/count")
    return sorted(selected, key=lambda row: row["path"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=Path("reports/nus-vr-v1/metadata"))
    parser.add_argument("--output", type=Path, default=Path("data/quarantine/nus-vr-v1"))
    parser.add_argument("--report", type=Path, default=Path("reports/nus-vr-v1/acquisition.json"))
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError("Use a new --report path to preserve the previous acquisition audit")
    tree_path = args.metadata / "pinned-tree.response"
    source_files = select_files(json.loads(tree_path.read_bytes()))
    args.output.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "checked_at": datetime.now(UTC).isoformat(), "repository": REPOSITORY,
        "revision": REVISION, "tree_sha256": sha256(tree_path.read_bytes()),
        "purpose": "user_requested_public_payload_inspection",
        "admission": "QUARANTINE_RIGHTS_NOT_ESTABLISHED", "reuse_permission_verified": False,
        "training_executed": False, "inference_executed": False, "benchmark_admitted": False,
        "files": [],
    }
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for row in source_files:
        name = row["path"][len(PREFIX):]
        target = args.output / name
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/" + urllib.parse.quote(row["path"])
        reused = target.exists()
        try:
            if reused:
                body = target.read_bytes()
            else:
                request = urllib.request.Request(url, headers={"User-Agent": "north55-source-audit/1.0"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status != 200:
                        raise ValueError(f"Expected complete HTTP 200, received {response.status}")
                    body = response.read(row["size"] + 1)
            verify_blob(body, row)
            if not reused:
                with target.open("xb") as stream:
                    stream.write(body)
            result["files"].append({"name": name, "source_path": row["path"], "url": url,
                                    "bytes": len(body), "git_blob": row["sha"],
                                    "sha256": sha256(body), "local_path": target.as_posix(),
                                    "reused": reused, "verified": True})
            print(f"Verified {name}: {len(body)} bytes", flush=True)
        except (OSError, ValueError) as exc:
            result["error"] = {"source_path": row["path"], "type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["total_bytes"] = sum(row["bytes"] for row in result["files"])
    result["retrieval_status"] = "PASS"
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    note = args.output / "SOURCE.txt"
    if not note.exists():
        note.write_text(f"Source: https://github.com/{REPOSITORY}\nRevision: {REVISION}\n"
                        "Public download for inspection requested by user. No reuse license found.\n"
                        "QUARANTINE: not admitted to training, evaluation or production.\n",
                        encoding="utf-8")


if __name__ == "__main__":
    main()
