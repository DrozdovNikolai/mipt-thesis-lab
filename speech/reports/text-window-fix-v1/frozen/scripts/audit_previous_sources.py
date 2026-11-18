"""Recheck the previously listed source endpoints without acquiring unlicensed audio."""

import hashlib
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

URLS = {
    "ru-api": "https://huggingface.co/api/datasets/NLPVladimir/aviation-command-dataset-ru",
    "ru-card": "https://huggingface.co/datasets/NLPVladimir/aviation-command-dataset-ru/raw/main/README.md",
    "ru-discussions": "https://huggingface.co/api/datasets/NLPVladimir/aviation-command-dataset-ru/discussions",
    "hiwire-catalog-search": "https://catalog.elda.org/en-us/repository/search/?q=HIWIRE",
    "hiwire-elg": "https://live.european-language-grid.eu/catalogue/corpus/2059",
    "voici-api": "https://zenodo.org/api/records/2660112",
    "iem-report": "https://iem.kug.ac.at/fileadmin/03_Microsites/01_Kuenstlerisch_wissenschaftliche_Einheiten/01_Institute/Institut_17_Elektronische_Musik_und_Akustik/Projekte/2011/report45_11.pdf",
    "dlr-page": "https://elib.dlr.de/214890/",
    "dlr-paper": "https://arxiv.org/html/2506.21990v1",
}


def main():
    root = Path("reports/all-sources-v1/source-audit")
    root.mkdir(parents=True, exist_ok=True)
    if (root / "retrieval.json").exists():
        raise ValueError("Keep the previous source audit; use a new version")

    def fetch(item):
        name, url = item
        record = {"id": name, "url": url, "checked_at": datetime.now(UTC).isoformat()}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "north55-speech-source-audit/1.0"})
            with urllib.request.urlopen(request, timeout=35) as response:
                contents = response.read(8 * 1024 * 1024 + 1)
                if len(contents) > 8 * 1024 * 1024:
                    raise ValueError("Metadata size limit exceeded")
                record.update(http_status=response.status, final_url=response.url,
                              content_type=response.headers.get("Content-Type"), bytes=len(contents),
                              sha256=hashlib.sha256(contents).hexdigest())
                (root / f"{name}.response").write_bytes(contents)
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            record.update(error_type=type(exc).__name__, error=str(exc), http_status=getattr(exc, "code", None))
        return record

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(fetch, URLS.items()))
    result = {"status": "SOURCE_RECHECK_EXECUTED", "audio_downloaded": False, "messages_sent": False,
              "purchases_made": False, "records": records}
    (root / "retrieval.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
