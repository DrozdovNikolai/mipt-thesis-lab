"""Fetch a bounded licensed SOTERIA sample for source inspection, without labels."""

import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def main():
    audit = Path("reports/direct-data-search-v1")
    inventory = json.loads((audit / "soteria-inventory/objects.json").read_text())
    # Metadata-only choice made before audio inspection. All Crew_02 variants are
    # exposed development material after this step, never independent final test.
    chosen = min((row for row in inventory if row["key"].startswith("Crew_02/DVR/")
                  and row["key"].endswith(".mp4")), key=lambda row: (row["size"], row["key"]))
    if chosen["size"] > 128 * 1024 * 1024:
        raise ValueError("Sample exceeds download budget")
    target = Path("data/input/nasa-soteria-v1")
    target.mkdir(parents=True, exist_ok=True)
    plan_path = audit / "soteria-sample-plan.json"
    plan = {"source": chosen, "selection": "smallest Crew_02 DVR MP4 by metadata",
            "group": "soteria:Crew_02", "use": "source_inspection_dev_only",
            "license": "CC BY 4.0", "source_registry": "https://registry.opendata.aws/nasa-soteria-data/"}
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError("Preserve the original sample selection")
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    key = chosen["key"]
    path = target / Path(key).name
    url = "https://nasa-soteria-data.s3.us-west-2.amazonaws.com/" + urllib.parse.quote(key)
    if not path.exists():
        request = urllib.request.Request(url, headers={"If-Match": chosen["etag"]})
        partial = path.with_suffix(".mp4.partial")
        if partial.exists():
            raise ValueError("Preserve the partial attempt; inspect before retrying")
        with urllib.request.urlopen(request, timeout=25) as response, partial.open("xb") as output:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > chosen["size"]:
                    raise ValueError("Unexpected object size")
                output.write(block)
        if size != chosen["size"]:
            raise ValueError("Truncated object")
        partial.rename(path)
    sha256 = hashlib.sha256()
    md5_parts = []
    with path.open("rb") as source:
        while block := source.read(8 * 1024 * 1024):
            sha256.update(block)
            md5_parts.append(hashlib.md5(block).digest())
    multipart = hashlib.md5(b"".join(md5_parts)).hexdigest() + f"-{len(md5_parts)}"
    matches = multipart == chosen["etag"].strip('"')
    if path.stat().st_size != chosen["size"] or not matches:
        raise ValueError("Length or computed multipart ETag verification failed; preserve download")
    result = {**plan, "checked_at": datetime.now(UTC).isoformat(), "url": url,
              "local_path": str(path), "bytes": path.stat().st_size, "sha256": sha256.hexdigest(),
              "multipart_etag_verified": matches, "verified_part_bytes": 8 * 1024 * 1024,
              "audio_content_verified": False, "transcripts_found": False,
              "asr_executed": False, "benchmark_admitted": False}
    (audit / "soteria-acquisition.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (target / "SOURCE.txt").write_text(
        "NASA SOTERIA Simulation Testbed Data. Accessed 2026-09-14.\n"
        "https://registry.opendata.aws/nasa-soteria-data/\n"
        "Creative Commons Attribution 4.0 International: https://creativecommons.org/licenses/by/4.0/\n"
        "Original sample unchanged. Crew_02 reserved for source inspection/development.\n"
        "No verified verbatim transcripts. Not admitted as cockpit ASR benchmark.\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
