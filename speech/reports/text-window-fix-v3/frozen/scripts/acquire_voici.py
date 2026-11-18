"""Acquire the open VOICI noise source; never treat it as speech ground truth."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from acquire_bleriot import curl, hashes, ranged_download


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/input/voici"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = args.output / "source-metadata.json"
    curl("https://zenodo.org/api/records/2660112", metadata)
    record = json.loads(metadata.read_text(encoding="utf-8"))
    if record["metadata"]["license"]["id"] != "cc-by-sa-4.0":
        raise RuntimeError("Source license changed; review required")
    if record["metadata"]["access_right"] != "open":
        raise RuntimeError("Source is not open access")
    expected = {
        "Cockpit  noise Falcon 2000LXS TRH-OSL description.pdf": (185736, "62cf27aa6eeec18dfdfcd2b9b092be49"),
        "Recording 6_low_freq_boost_remove_speech_2_WoodPk_reinsert_16b.wav": (289616504, "1ea1ac980ab2563a31ba58cbfa053465"),
    }
    files = []
    for item in record["files"]:
        name = item["key"]
        if name not in expected or (item["size"], item["checksum"].removeprefix("md5:")) != expected[name]:
            raise RuntimeError("Unreviewed source content")
        path = args.output / name
        partial = path.with_suffix(path.suffix + ".part")
        url = item["links"]["self"]
        if not url.startswith("https://zenodo.org/api/records/2660112/files/"):
            raise RuntimeError("Unexpected file host")
        if not path.exists():
            print(f"Downloading VOICI {name}", flush=True)
            if item["size"] > 16 * 1024 * 1024:
                ranged_download(url, partial, item["size"])
            else:
                curl(url, partial)
            if partial.stat().st_size != item["size"] or hashes(partial)["md5"] != expected[name][1]:
                raise RuntimeError("VOICI publisher checksum mismatch")
            partial.replace(path)
        actual = hashes(path)
        if path.stat().st_size != item["size"] or actual["md5"] != expected[name][1]:
            raise RuntimeError("Existing VOICI file checksum mismatch")
        files.append({"filename": name, "url": url, "bytes": item["size"], **actual})
        print(f"Verified VOICI {name}", flush=True)
    report = {
        "status": "ACQUIRED_AND_CHECKSUM_VERIFIED", "record": 2660112,
        "license_id": "CC-BY-SA-4.0", "source_role": "noise_only",
        "scope": "Falcon 2000LXS flight background; speech removed by publisher",
        "training_admission": "PENDING_AUDIO_INSPECTION_AND_PARTITION_POLICY",
        "files": files, "metadata_sha256": hashes(metadata)["sha256"],
        "checked_at": datetime.now(UTC).isoformat(),
    }
    (args.output / "acquisition.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    Path("reports/voici-acquisition.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
