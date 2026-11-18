"""Explicit acquisition of the public BLeRIOT A/C v1 research assets.

Python standard library plus curl; works on Windows and Linux. This command
downloads files into a quarantined source directory, never admits them as gold.
It does not contact authors, authenticate, or accept gated access terms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

BASE = "https://entrepot.recherche.data.gouv.fr"
SOURCES = {
    "A": ("EWXJLT", 739009, 1710792035, "a32cadbb46925e434b38263405dc0d0d"),
    "C": ("ASYVFP", 739008, 863744696, "60aab54b76c7209b7554ffdcf23233e5"),
}


def hashes(path: Path) -> dict[str, str]:
    md5 = hashlib.md5(usedforsecurity=False)  # Publisher transport checksum, not security.
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            md5.update(block)
            sha.update(block)
    return {"md5": md5.hexdigest(), "sha256": sha.hexdigest()}


def curl(url: str, path: Path, byte_range: tuple[int, int] | None = None) -> None:
    executable = shutil.which("curl.exe") or shutil.which("curl")
    if not executable:
        raise RuntimeError("Install curl before source acquisition")
    args = [
        executable, "--fail", "--location", "--silent", "--show-error",
        "--proto", "=https", "--proto-redir", "=https", "--retry", "3",
        "--retry-delay", "3", "--retry-all-errors", "--connect-timeout", "30",
        "--max-time", "60", "--speed-limit", "1024", "--speed-time", "15",
    ]
    if byte_range:
        args.extend(["--range", f"{byte_range[0]}-{byte_range[1]}"])
    result = subprocess.run(
        [*args, "--write-out", "%{http_code}", "--output", str(path), url],
        check=True, timeout=800, capture_output=True, text=True,
    )
    expected = "206" if byte_range else "200"
    if result.stdout != expected:
        raise RuntimeError(f"Unexpected HTTP response {result.stdout}; expected {expected}")


def ranged_download(url: str, target: Path, size: int) -> None:
    """Bounded parallel ranges tolerate the archive host's stalled long transfers."""
    chunk_size = 1024 * 1024
    chunks = target.with_suffix(target.suffix + ".chunks-1m")
    chunks.mkdir(exist_ok=True)

    def fetch(index: int) -> Path:
        first = index * chunk_size
        last = min(size - 1, first + chunk_size - 1)
        path = chunks / f"{index:05d}.bin"
        if not path.exists() or path.stat().st_size != last - first + 1:
            temporary = path.with_suffix(".part")
            curl(url, temporary, (first, last))
            if temporary.stat().st_size != last - first + 1:
                raise RuntimeError("HTTP range size mismatch")
            temporary.replace(path)
        return path

    count = (size + chunk_size - 1) // chunk_size
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, index) for index in range(count)]
        for done, future in enumerate(as_completed(futures), 1):
            future.result()
            if done % 100 == 0 or done == count:
                print(f"{target.name}: {done}/{count} verified-size ranges", flush=True)
    with target.open("wb") as output:
        for index in range(count):
            with (chunks / f"{index:05d}.bin").open("rb") as stream:
                shutil.copyfileobj(stream, output)


def acquire(corpus: str, root: Path) -> dict:
    doi, archive_id, expected_size, expected_md5 = SOURCES[corpus]
    destination = root / f"bleriot-{corpus.lower()}"
    destination.mkdir(parents=True, exist_ok=True)
    metadata = destination / "source-metadata.json"
    metadata_url = f"{BASE}/api/datasets/:persistentId/?persistentId=doi:10.57745/{doi}"
    curl(metadata_url, metadata)
    version = json.loads(metadata.read_text(encoding="utf-8"))["data"]["latestVersion"]
    if version["versionNumber"] != 1 or version["versionMinorNumber"] != 0:
        raise RuntimeError("Dataset version changed; review new metadata before acquisition")
    if "creativecommons.org/licenses/by-nc/4.0/" not in version["termsOfUse"]:
        raise RuntimeError("Expected CC BY-NC 4.0 declaration missing")
    evidence = {
        "corpus": f"BLeRIOT-{corpus}", "doi": f"10.57745/{doi}", "version": "1.0",
        "metadata_url": metadata_url, "license_id": "CC-BY-NC-4.0",
        "use_scope": "local noncommercial diploma research; no product redistribution",
        "citation": version.get("citationRequirements"),
        "terms_of_use": version["termsOfUse"], "files": [],
        "quality_admission": "NOT_ADMITTED_PENDING_SCOPE_ALIGNMENT_AND_ANNOTATION_REVIEW",
    }
    for entry in sorted(version["files"], key=lambda item: item["dataFile"]["filesize"]):
        source = entry["dataFile"]
        if entry["restricted"]:
            raise RuntimeError("Restricted source requires separate access; acquisition stopped")
        # Dataverse reports the ingested TAB byte count with the ORIGINAL CSV MD5
        # for this source. Retrieve the saved original, whose bytes match that MD5.
        is_ingested = "originalFileName" in source
        name = source["originalFileName"] if is_ingested else source["filename"]
        byte_count = source["originalFileSize"] if is_ingested else source["filesize"]
        if Path(name).name != name or any(c in name for c in "\\/:"):
            raise ValueError("Unsafe publisher filename")
        if source["id"] == archive_id and (
            source["filesize"] != expected_size or source["md5"] != expected_md5
        ):
            raise RuntimeError("Archive changed from reviewed metadata")
        if source["checksum"]["type"] != "MD5":
            raise RuntimeError("Unreviewed publisher checksum format")
        url = f"{BASE}/api/access/datafile/{source['id']}"
        if is_ingested:
            url += "?format=original"
        target = destination / name
        partial = target.with_suffix(target.suffix + ".part")
        start = time.monotonic()
        print(f"{evidence['corpus']}: {name} ({byte_count} bytes)", flush=True)
        if not target.exists():
            if byte_count > 16 * 1024 * 1024:
                ranged_download(url, partial, byte_count)
            else:
                curl(url, partial)
            actual = hashes(partial)
            if partial.stat().st_size != byte_count or actual["md5"] != source["md5"]:
                raise RuntimeError(f"Publisher size/checksum mismatch: {partial}")
            partial.replace(target)
        actual = hashes(target)
        if target.stat().st_size != byte_count or actual["md5"] != source["md5"]:
            raise RuntimeError(f"Existing file does not match publisher: {target}")
        evidence["files"].append({
            "filename": name, "datafile_id": source["id"], "url": url,
            "bytes": target.stat().st_size, "publisher_md5": source["md5"],
            **actual, "verified": True, "elapsed_sec": round(time.monotonic() - start, 2),
        })
        print(f"Verified {name}: {actual['sha256']}", flush=True)
    evidence["metadata_sha256"] = hashes(metadata)["sha256"]
    evidence["completed_at"] = datetime.now(UTC).isoformat()
    (destination / "acquisition.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/input/bleriot"))
    parser.add_argument("--report", type=Path, default=Path("reports/bleriot-acquisition.json"))
    parser.add_argument("--corpus", choices=["A", "C", "both"], default="both")
    parser.add_argument("--noncommercial-research", action="store_true", required=True)
    args = parser.parse_args()
    corpora = ["A", "C"] if args.corpus == "both" else [args.corpus]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(acquire, corpus, args.output.resolve()) for corpus in corpora]
        results = [future.result() for future in futures]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        "status": "ACQUIRED_AND_CHECKSUM_VERIFIED", "sources": results,
        "benchmark_status": "NOT_RUN", "human_review_status": "PENDING",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
