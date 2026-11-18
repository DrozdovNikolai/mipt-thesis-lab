"""Extract acquired archives after validating checksums and all entry paths.

Requires the 7-Zip command line tool (7z/7zz). Outputs remain quarantined source
material, with no transcript, event, entity, or scope verification claims.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from acquire_bleriot import hashes


def safe_member(name: str, root: Path) -> Path:
    value = PurePosixPath(name.replace("\\", "/"))
    if value.is_absolute() or not value.parts:
        raise ValueError("Absolute or empty archive entry")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
    }
    for part in value.parts:
        if (
            part in {".", ".."} or any(c in part for c in ':<>"|?*')
            or any(ord(c) < 32 for c in part) or part.endswith((".", " "))
            or part.split(".")[0].upper() in reserved
        ):
            raise ValueError(f"Unsafe archive entry: {name}")
    destination = root.joinpath(*value.parts).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError("Archive entry escapes output directory")
    return destination


def parse_listing(text: str, root: Path) -> list[dict[str, str]]:
    if "----------\n" not in text:
        raise ValueError("7-Zip listing has no file entries")
    entries = []
    names = set()
    for block in text.split("----------\n", 1)[1].split("\n\n"):
        item = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if not item:
            continue
        path = safe_member(item["Path"], root)
        normalized = path.as_posix().casefold()
        if normalized in names:
            raise ValueError("Duplicate/case-colliding archive entry")
        names.add(normalized)
        for key in ("Symbolic Link", "Hard Link", "Copy Link", "Alternate Stream"):
            if item.get(key) not in {None, "", "-"}:
                raise ValueError(f"Archive links or alternate streams are forbidden: {key}")
        attributes = item.get("Attributes", "")
        if "l" in attributes or "L" in attributes or item.get("Encrypted") == "+":
            raise ValueError("Archive link or encrypted entry")
        entries.append(item)
    if not entries or len(entries) > 10000:
        raise ValueError("Unexpected archive entry count")
    if sum(int(item.get("Size", 0)) for item in entries) > 20 * 1024**3:
        raise ValueError("Archive exceeds the 20 GiB extraction bound")
    return entries


def extract(source: Path, destination: Path, seven_zip: str) -> dict:
    source, destination = source.resolve(), destination.resolve()
    evidence = json.loads((source / "acquisition.json").read_text(encoding="utf-8"))
    archive_record = next(
        file for file in evidence["files"] if Path(file["filename"]).suffix in {".rar", ".zip"}
    )
    archive = source / archive_record["filename"]
    if hashes(archive)["sha256"] != archive_record["sha256"]:
        raise ValueError("Archive differs from checksum-verified acquisition")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Extraction requires a fresh, empty destination")
    destination.mkdir(parents=True, exist_ok=True)
    args = [seven_zip, "l", "-slt", "-sccUTF-8", str(archive.resolve())]
    listing = subprocess.run(
        args, check=True, capture_output=True, encoding="utf-8", timeout=180
    ).stdout.replace("\r\n", "\n")
    entries = parse_listing(listing, destination)
    subprocess.run(
        [seven_zip, "x", "-y", "-bd", "-bso0", f"-o{destination.resolve()}", str(archive.resolve())],
        check=True, timeout=900,
    )
    actual = []
    for item in entries:
        path = safe_member(item["Path"], destination)
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Extracted link")
        if item.get("Folder") == "+" or path.is_dir():
            continue
        if not path.is_file() or path.stat().st_size != int(item["Size"]):
            raise ValueError("Extracted file size differs from archive entry")
        actual.append({
            "path": path.relative_to(destination).as_posix(),
            "bytes": path.stat().st_size, **hashes(path),
        })
    report = {
        "corpus": evidence["corpus"], "status": "EXTRACTED_CHECKSUM_VERIFIED",
        "archive_sha256": archive_record["sha256"], "entries": actual,
        "scope_review": "PENDING", "alignment_review": "PENDING",
        "benchmark_admission": False,
    }
    (destination / "extraction.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/input/bleriot"))
    parser.add_argument("--output", type=Path, default=Path("data/input/bleriot/extracted"))
    parser.add_argument("--seven-zip", default=shutil.which("7zz") or shutil.which("7z")
                        or "C:/Program Files/7-Zip/7z.exe")
    parser.add_argument("--corpus", choices=["a", "c", "both"], default="both")
    args = parser.parse_args()
    for corpus in ["a", "c"] if args.corpus == "both" else [args.corpus]:
        report = extract(args.input / f"bleriot-{corpus}", args.output / corpus, args.seven_zip)
        print(json.dumps({"corpus": report["corpus"], "files": len(report["entries"])}))


if __name__ == "__main__":
    main()
