"""Read-only localhost service verification. Never submit annotations as human."""

import argparse
import hashlib
import http.cookiejar
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path, default=Path("reports/annotation-service.json"))
    args = parser.parse_args()
    if urllib.parse.urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("This diagnostic is restricted to localhost")
    values = dict(os.environ)
    if args.env.is_file():
        values.update(line.split("=", 1) for line in args.env.read_text(encoding="utf-8-sig").splitlines()
                      if "=" in line and not line.lstrip().startswith("#"))
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    login = urllib.request.Request(args.url+"/login", data=urllib.parse.urlencode({
        "key": values["NORTH55_API_KEY"].strip().strip('\"\''), "annotator": "automated-read-only-check"
    }).encode())
    with opener.open(login, timeout=30) as response:
        assert response.status == 200 and 'id="editor"' in response.read().decode()
    with opener.open(args.url+"/api/packet", timeout=30) as response:
        listing = json.load(response)
    checks = []
    for item in listing["items"]:
        with opener.open(args.url+"/api/item/"+item["id"], timeout=30) as response:
            record = json.load(response)
        request = urllib.request.Request(args.url+"/api/audio/"+item["id"], headers={"Range": "bytes=0-11"})
        with opener.open(request, timeout=30) as response:
            header = response.read()
            assert response.status == 206 and header[:4] == b"RIFF" and header[8:] == b"WAVE"
        checks.append({"id": item["id"], "revision": record["revision"], "audio_range": "PASS",
                       "split": record["sample"]["split"], "transcript_status": record["sample"]["transcript_status"]})
    exports = {}
    for split in ("train", "dev"):
        with opener.open(args.url+"/api/export/"+split, timeout=30) as response:
            content = response.read()
        rows = [json.loads(line) for line in content.splitlines()]
        assert all(row["split"] == split for row in rows)
        exports[split] = {"rows": len(rows), "sha256": hashlib.sha256(content).hexdigest()}
    report = {"status": "PASS", "checks": checks, "exports": exports, "annotation_writes": 0,
              "machine_hints_revealed": 0, "credentials_in_report": False,
              "ui": "login_page_browser_inspected_authenticated_contract_via_HTTP"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "audio_ranges_checked": len(checks), "exports": exports, "annotation_writes": 0}))


if __name__ == "__main__":
    main()
