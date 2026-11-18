"""Extract publisher scripts for review; never label extracted/OCR text as audio gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args: list[str]) -> str:
    return subprocess.run(args, check=True, capture_output=True, encoding="utf-8", timeout=180).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifests", type=Path, required=True)
    parser.add_argument("--mode", choices=["docx-text", "pdf"], required=True)
    args = parser.parse_args()
    samples = []
    for split in ("train", "dev"):
        rows = [json.loads(line) for line in (args.manifests/f"{split}.jsonl").read_text(encoding="utf-8").splitlines()]
        if any(row["split"] != split for row in rows):
            raise ValueError("Only train/dev manifests may be opened")
        samples.extend(rows)
    names = {sample["sample_id"].split(":", 1)[1] for sample in samples if sample["source_dataset"] == "BLeRIOT-A"}
    allowed: set[str] = set()
    for name in names:
        if name.startswith("BEA_checklists_"):
            allowed.update(path.name for path in args.source.glob("BEA_checklist*.pdf"))
        elif name.startswith("BEA_cvr_"):
            allowed.add("BEA_CVR.pdf")
        elif name.startswith("DGA_CVR"):
            allowed.add(name.split("_track")[0]+".docx")
        elif name.startswith("DGA_checklist"):
            key = name.split("_sp")[0].replace("Puma-1", "Puma1").replace("Puma-2", "Puma2")
            allowed.update(path.name for path in args.source.glob(key+".*"))
    args.output.mkdir(parents=True, exist_ok=True)
    index = []
    for path in sorted(args.source.iterdir()):
        if path.name not in allowed:
            continue
        if (path.suffix == ".pdf") != (args.mode == "pdf"):
            continue
        destination = args.output / (path.stem+".json")
        if destination.exists():
            raise ValueError("Preserve the existing extracted-script revision")
        blocks = []
        if path.suffix == ".docx":
            with zipfile.ZipFile(path) as archive:
                xml = ET.fromstring(archive.read("word/document.xml"))
            namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            for i, paragraph in enumerate(xml.findall(".//w:p", namespace)):
                text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
                if text.strip():
                    blocks.append({"paragraph": i+1, "text": text, "method": "ooxml_text"})
        elif path.suffix == ".txt":
            content = path.read_bytes()
            try:
                text = content.decode("utf-8-sig")
                encoding = "utf-8-sig"
            except UnicodeDecodeError:
                text, encoding = content.decode("cp1252"), "cp1252"
            blocks.append({"text": text, "method": "publisher_text", "encoding": encoding})
        else:
            info = command(["pdfinfo", str(path)])
            page_match = re.search(r"Pages:\s+(\d+)", info)
            if page_match is None:
                raise ValueError("PDF page count is unavailable")
            count = int(page_match[1])
            pages_dir = args.output / (path.stem+"_pages")
            pages_dir.mkdir()
            for page in range(1, count+1):
                text = command(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(path), "-"])
                method = "pdf_text_layer"
                # Always retain a visual source page for row/column/number review.
                prefix = pages_dir/f"page-{page:03d}"
                command(["pdftoppm", "-r", "180", "-png", "-singlefile", "-f", str(page), "-l", str(page), str(path), str(prefix)])
                if len(text.split()) < 15:
                    text = command(["tesseract", str(prefix)+".png", "stdout", "-l", "eng+fra", "--psm", "6"])
                    method = "tesseract_eng_fra_psm6"
                blocks.append({"page": page, "text": text, "method": method,
                               "page_image": str(prefix.relative_to(args.output))+".png"})
        record = {
            "source_file": path.name, "source_sha256": sha(path), "source": "BLeRIOT-A v1.0",
            "license_id": "CC-BY-NC-4.0", "blocks": blocks,
            "audio_alignment_status": "missing", "human_verified": False,
            "annotation_status": "machine", "purpose": "publisher-script extraction for train/dev review",
            "not_an_asr_reference": True, "not_for_inference_prompts": True,
        }
        destination.write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        index.append({"file": destination.name, "sha256": sha(destination), "blocks": len(blocks),
                      "ocr_blocks": sum(str(block["method"]).startswith("tesseract") for block in blocks)})
        print(json.dumps(index[-1]), flush=True)
    (args.output/f"index-{args.mode}.json").write_text(json.dumps({"documents": index, "test_manifest_opened": False}, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
