"""List the public NASA SOTERIA bucket without credentials or audio downloads."""

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ENDPOINT = "https://nasa-soteria-data.s3.us-west-2.amazonaws.com/"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows, pages, seen = [], [], set()
    token = None
    complete = False
    for page in range(1, 101):
        params = {"list-type": "2", "max-keys": "1000"}
        if token:
            if token in seen:
                raise ValueError("Repeated continuation token")
            seen.add(token)
            params["continuation-token"] = token
        url = ENDPOINT + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=25) as response:
            body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError("Unexpected listing size")
        (args.output / f"page-{page:03}.xml").write_bytes(body)
        root = ET.fromstring(body)
        for item in root.findall("s:Contents", NS):
            rows.append({"key": item.findtext("s:Key", namespaces=NS),
                         "size": int(item.findtext("s:Size", namespaces=NS)),
                         "etag": item.findtext("s:ETag", namespaces=NS),
                         "last_modified": item.findtext("s:LastModified", namespaces=NS)})
        pages.append({"page": page, "url": url, "sha256": hashlib.sha256(body).hexdigest()})
        if root.findtext("s:IsTruncated", namespaces=NS) == "false":
            complete = True
            break
        token = root.findtext("s:NextContinuationToken", namespaces=NS)
        if not token:
            raise ValueError("Missing continuation token")
    media = [row for row in rows if Path(row["key"]).suffix.lower() in
             (".wav", ".mp3", ".m4a", ".mp4", ".m4v", ".mpeg", ".mpg")]
    annotation_names = [row for row in rows if any(term in row["key"].lower() for term in
                       ("transcri", "annotat", ".srt", ".vtt", ".textgrid", ".eaf"))]
    summary = {"checked_at": datetime.now(UTC).isoformat(), "complete_listing": complete,
               "objects": len(rows), "bytes": sum(row["size"] for row in rows),
               "extensions": dict(Counter(Path(row["key"]).suffix.lower() for row in rows)),
               "media_files": len(media), "media_bytes": sum(row["size"] for row in media),
               "crew_prefixes": sorted({row["key"].split("/")[0] for row in rows
                                        if row["key"].startswith("Crew_")}),
               "annotation_filename_matches": annotation_names,
               "annotation_content_verified": False, "audio_downloaded": False,
               "caveat": "Filename inventory alone cannot prove absence of transcripts inside other files."}
    for name, value in [("objects.json", rows), ("pages.json", pages),
                        ("media.json", media), ("summary.json", summary)]:
        (args.output / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
