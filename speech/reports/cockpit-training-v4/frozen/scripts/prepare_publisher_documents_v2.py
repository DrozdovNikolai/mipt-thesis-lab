"""Re-extract scanned checklist regions and preserve source/layout evidence."""

import hashlib
import json
import re
import subprocess
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_line(text):
    # List index delimiters differ from genuine values such as 1000 C or 1.5 bar.
    text = re.sub(r"^\s*\d+\s*(?:[.)]|[-–—])\s+", "", text)
    text = re.sub(r"(?:\.\s*){2,}|…+", " ", text)
    return " ".join(text.split()).strip(" |_")


def layout_metadata(text):
    return bool(re.match(r"^(?:rev[.: ]|(?:airbus\s+)?a31[89]/a3|airbus a319|boeing 737|"
                         r"to 1t[- ]?dga|issue \d|takeoff cg/trim)", text.strip(), re.I))


def main():
    old, raw, out = Path("/old/documents"), Path("/raw"), Path("/output")
    if (out / "documents.json").exists():
        raise ValueError("Do not overwrite a prepared document version")
    out.mkdir(parents=True, exist_ok=True)
    docs, evidence = {}, []
    for path in sorted(old.glob("*.json")):
        prior = read(path)
        source = read(raw / path.name)
        lines = []
        if path.stem in {"DGA_checklist-PC7", "BEA_checklist_A320_pilote"}:
            regions = ([(page, (480, 425, 690, 1190)) for page in range(1, 5)]
                       if path.stem == "DGA_checklist-PC7" else
                       [(1, (100, 190, 575, 1615)), (1, (775, 190, 610, 1390))])
            for index, (page, (x, y, width, height)) in enumerate(regions):
                image = raw / f"{path.stem}_pages/page-{page:03d}.png"
                crop = out / f"{path.stem}-{page}-{index}.png"
                subprocess.run(["ffmpeg", "-v", "error", "-i", str(image), "-vf",
                                f"crop={width}:{height}:{x}:{y}", "-frames:v", "1", str(crop)], check=True)
                text = subprocess.check_output(["tesseract", str(crop), "stdout", "-l", "eng", "--psm", "6"],
                                               stderr=subprocess.DEVNULL).decode()
                (out / f"{crop.stem}.txt").write_text(text, encoding="utf-8")
                evidence.append({"document": path.name, "page": page, "image_sha256": sha(image),
                                 "crop_pixels": [x, y, width, height], "crop_sha256": sha(crop),
                                 "method": "tesseract_eng_psm6_separate_content_regions"})
                lines.extend({"raw": line, "page": page, "region": index} for line in text.splitlines() if line.strip())
        elif prior["source_file"].endswith(".docx"):
            lines = [{"raw": line, "paragraph": b.get("paragraph")} for b in source["blocks"]
                     for line in b["text"].splitlines() if line.strip()]
        else:
            lines = [{"raw": line["text"], "page": b["page"], "column": b.get("column"),
                      "x": line["x"], "y": line["y"]} for b in prior["blocks"] for line in b["raw_lines"]]
        for line in lines:
            line.update(text=clean_line(line["raw"]), excluded_layout=layout_metadata(line["raw"]))
        docs[path.name] = {"source_file": prior["source_file"], "source_sha256": prior["source_sha256"],
                           "prior_document_sha256": sha(path), "raw_extraction_sha256": sha(raw / path.name),
                           "lines": lines, "method": "publisher_layout_v2", "human_verified": False}
    (out / "documents.json").write_text(json.dumps(docs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "layout-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"documents": len(docs), "ocr_regions": len(evidence),
                      "lines_cleaned": sum(line["raw"].strip() != line["text"] for d in docs.values() for line in d["lines"]),
                      "layout_lines_excluded": sum(line["excluded_layout"] for d in docs.values() for line in d["lines"])}))


if __name__ == "__main__":
    main()
