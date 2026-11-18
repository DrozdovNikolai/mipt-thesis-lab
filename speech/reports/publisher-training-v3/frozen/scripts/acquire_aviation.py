"""Explicit pinned acquisition for the user-authorized aviation scope expansion."""

import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"

import httpx  # noqa: E402
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

from north55_speech.core import atomic_json, file_hash, now  # noqa: E402


def fetch(repo, kind, selected, root, audit):
    info = HfApi().repo_info(repo, repo_type=kind, files_metadata=True)
    pin = audit / (repo.replace("/", "--") + ".json")
    if pin.exists():
        plan = json.loads(pin.read_text())
        info = HfApi().repo_info(repo, repo_type=kind, revision=plan["revision"], files_metadata=True)
    else:
        entries = {s.rfilename: {"size": s.size, "blob_id": s.blob_id,
                   "lfs": s.lfs.sha256 if s.lfs else None}
                   for s in info.siblings if selected(s.rfilename)}
        limit = (4 if kind == "model" else 2) * 1024**3
        if not entries or sum(v["size"] or 0 for v in entries.values()) > limit:
            raise ValueError("Missing files or download exceeds repository byte budget")
        plan = {"repo": repo, "repo_type": kind, "revision": info.sha, "files": entries}
        atomic_json(pin, plan)
    files = {}
    for name, details in plan["files"].items():
        print(f"Downloading {repo}/{name}", flush=True)
        path = Path(hf_hub_download(repo, name, repo_type=kind, revision=plan["revision"], local_dir=root))
        if path.stat().st_size != details["size"]:
            raise ValueError("Publisher size mismatch")
        h = file_hash(path)
        if details["lfs"]:
            if h != details["lfs"]:
                raise ValueError("Publisher LFS checksum mismatch")
        else:
            blob = path.read_bytes()
            git_hash = hashlib.sha1(f"blob {len(blob)}\0".encode() + blob).hexdigest()
            if git_hash != details["blob_id"]:
                raise ValueError("Publisher Git blob mismatch")
        files[name] = h
    return {**plan, "verified_files": files, "acquired_at": now().isoformat()}


def main(stage):
    audit = Path("/output/acquisition")
    audit.mkdir(parents=True, exist_ok=True)
    if stage == "model":
        name = "whisper-medium-en-atc-jacktol-ct2"
        root = Path("/models") / name
        if (root / "manifest.json").exists():
            raise ValueError("Model already acquired; do not overwrite its manifest")
        repo = "jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper"
        result = fetch(repo, "model", lambda n: n in {"model.bin", "config.json", "README.md",
                       "preprocessor_config.json", "vocabulary.json"}, root, audit)
        # Neither author snapshot ships tokenizer.json. Verify the complete token
        # mapping before supplying the already acquired original medium.en tokenizer.
        from tokenizers import Tokenizer
        base = Path("/models/whisper-medium-en-ct2")
        original_tokenizer = base / "tokenizer.json"
        base_manifest = json.loads((base / "manifest.json").read_text())
        if file_hash(original_tokenizer) != base_manifest["files"]["tokenizer.json"]:
            raise ValueError("Parent tokenizer changed")
        tok = Tokenizer.from_file(str(original_tokenizer))
        vocabulary = json.loads((root / "vocabulary.json").read_text())
        expected_vocab = [tok.id_to_token(i) for i in range(tok.get_vocab_size())]
        expected_vocab += [f"<|{i * .02:.2f}|>" for i in range(1501)]
        if vocabulary != expected_vocab:
            raise ValueError("Adapted vocabulary differs from parent plus standard timestamps")
        (root / "tokenizer.json").write_bytes(original_tokenizer.read_bytes())
        tokenizer = {"repo": base_manifest["repo"], "revision": base_manifest["revision"],
                     "vocabulary_mapping_verified_tokens": len(vocabulary),
                     "verified_files": {"tokenizer.json": file_hash(original_tokenizer)}}
        manifest = {"model": name, "repo": repo, "revision": result["revision"], "license": "MIT",
                    "files": result["verified_files"] | tokenizer["verified_files"],
                    "tokenizer_source": tokenizer, "acquisition": result,
                    "declared_finetuning_sources": ["ATCO2 1h subset", "UWB-ATCC"],
                    "external_training_manifest_available": False}
        atomic_json(root / "manifest.json", manifest)
        atomic_json(audit / "model-manifest.json", manifest)
    else:
        root = Path("/source")
        result = fetch("Jzuluaga/atcosim_corpus", "dataset",
                       lambda n: n == "README.md" or n.startswith("data/test-"), root, audit)
        with httpx.Client(follow_redirects=True, timeout=90) as client:
            for name, url in {
                "license.txt": "https://www2.spsc.tugraz.at/databases/ATCOSIM/DOC/license.txt",
                "fulldata.csv": "https://www2.spsc.tugraz.at/databases/ATCOSIM/TXTdata/fulldata.csv",
            }.items():
                response = client.get(url)
                response.raise_for_status()
                path = root / name
                if path.exists() and path.read_bytes() != response.content:
                    raise ValueError("Source metadata changed")
                path.write_bytes(response.content)
                result.setdefault("original_metadata", {})[name] = {"url": url, "sha256": file_hash(path)}
        if "permitted to use the corpus for research and development" not in (root / "license.txt").read_text():
            raise ValueError("Unexpected source license")
        atomic_json(root / "acquisition.json", result)
        atomic_json(audit / "dataset.json", result)
    print(f"Verified {stage}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["model", "data"])
    main(parser.parse_args().stage)
