"""Archive public corpus metadata; never import audio or declare annotation gold."""

import argparse
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

URLS = {
    "vr-report-repo": "https://api.github.com/repos/wangyubo013-blip/CDE4301-VR-401-Final-Report",
    "vr-report-tree": "https://api.github.com/repos/wangyubo013-blip/CDE4301-VR-401-Final-Report/git/trees/main?recursive=1",
    "vr-report-page": "https://wangyubo013-blip.github.io/CDE4301-VR-401-Final-Report/",
    "mendeley-flightdeck": "https://data.mendeley.com/datasets/vksyd4x8ps/1",
    "mendeley-flightdeck-api": "https://data.mendeley.com/public-api/datasets/vksyd4x8ps/versions/1",
    "western-sydney": "https://research-data.westernsydney.edu.au/published/0a75b050956311ee8a5a39b46e533ffb/",
    "modalsim94": "https://fordatis.fraunhofer.de/handle/fordatis/502?mode=simple",
    "susas": "https://catalog.ldc.upenn.edu/LDC99S78",
    "susas-actual": "https://catalog.ldc.upenn.edu/docs/LDC99S78/ACTUAL.TXT",
    "nato-n4": "https://catalog.ldc.upenn.edu/docs/LDC2006S13/N4_Corpus_README.html",
}
for term in ("cockpit", "bleriot", "hiwire", "pilot", "aviation", "flight", "crew", "checklist", "susas"):
    URLS[f"hf-search-{term}"] = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode(
        {"search": term, "limit": 100, "full": "true"}
    )
for term in ('"cockpit" AND "speech"', '"flight simulator" AND "audio"', '"VOICI"'):
    key = "zenodo-" + hashlib.sha256(term.encode()).hexdigest()[:10]
    URLS[key] = "https://zenodo.org/api/records?" + urllib.parse.urlencode({"q": term, "size": 25})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--urls", type=Path, help="Optional JSON object of named public metadata URLs")
    args = parser.parse_args()
    urls = json.loads(args.urls.read_text(encoding="utf-8")) if args.urls else URLS
    if not isinstance(urls, dict) or not urls or any(
        not isinstance(key, str) or not key.replace("-", "").replace("_", "").isalnum()
        or not isinstance(url, str) or not url.startswith("https://")
        for key, url in urls.items()
    ):
        raise ValueError("Require safe identifiers and public HTTPS metadata URLs")
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    (root / "requests.json").write_text(json.dumps(urls, indent=2), encoding="utf-8")
    limit = 8 * 1024 * 1024

    def fetch(item):
        key, url = item
        row = {"id": key, "url": url, "checked_at": datetime.now(UTC).isoformat()}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "north55-source-audit/1.0"})
            with urllib.request.urlopen(request, timeout=25) as response:
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise ValueError("Metadata response exceeds size limit")
                (root / f"{key}.response").write_bytes(body)
                row.update(status=response.status, bytes=len(body), final_url=response.url,
                           content_type=response.headers.get("Content-Type"),
                           sha256=hashlib.sha256(body).hexdigest())
                if key.startswith("hf-search-"):
                    records = json.loads(body)
                    row["dataset_ids"] = [record["id"] for record in records]
                    row["limit_reached"] = len(records) == 100
        except (OSError, ValueError, KeyError) as exc:
            row.update(status=getattr(exc, "code", None), error=f"{type(exc).__name__}: {exc}")
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(fetch, urls.items()))
    result = {"checked_at": datetime.now(UTC).isoformat(), "purpose": "metadata_discovery",
              "audio_imported": False, "messages_sent": False, "purchases_made": False,
              "records": rows}
    (root / "retrieval.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps([{k: v for k, v in row.items() if k in
                      ("id", "status", "bytes", "error", "dataset_ids", "limit_reached")}
                     for row in rows], indent=2))


if __name__ == "__main__":
    main()
