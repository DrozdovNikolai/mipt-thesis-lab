"""Explicit acquisition of three reviewed MIT English checkpoints, never user audio."""

import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"

from huggingface_hub import HfApi, snapshot_download  # noqa: E402

from north55_speech.core import atomic_json, file_hash, now  # noqa: E402

MODELS = {
    "small_en": ("whisper-small-en-ct2", "Systran/faster-whisper-small.en"),
    "medium_en": ("whisper-medium-en-ct2", "Systran/faster-whisper-medium.en"),
    "distil_en": ("distil-whisper-large-v35-ct2", "distil-whisper/distil-large-v3.5-ct2"),
}


def main():
    api = HfApi()
    out = Path("/output")
    plan_path = out / "acquisition-plan.json"
    if plan_path.exists():
        import json
        plan = json.loads(plan_path.read_text())
    else:
        plan = {}
        for key, (name, repo) in MODELS.items():
            info = api.model_info(repo, files_metadata=True)
            if info.card_data.get("license") != "mit":
                raise ValueError("Unreviewed license")
            files = [s.rfilename for s in info.siblings if s.rfilename in {
                "model.bin", "config.json", "tokenizer.json", "preprocessor_config.json",
                "vocabulary.json", "vocabulary.txt", "README.md", "LICENSE", "LICENSE.txt"}]
            size = sum(s.size or 0 for s in info.siblings if s.rfilename in files)
            if not {"model.bin", "config.json", "tokenizer.json"} <= set(files):
                raise ValueError("Missing mandatory model files")
            plan[key] = {"model": name, "repo": repo, "revision": info.sha,
                         "license": "MIT", "selected_files": files, "declared_bytes": size}
        if sum(p["declared_bytes"] for p in plan.values()) > 4 * 1024**3:
            raise ValueError("Acquisition exceeds fixed 4 GiB budget")
        atomic_json(plan_path, plan)
    for key, entry in plan.items():
        destination = Path("/models") / entry["model"]
        existing = destination / "manifest.json"
        if existing.exists():
            import json
            saved = json.loads(existing.read_text())
            if saved["revision"] != entry["revision"] or any(
                file_hash(destination / n) != h for n, h in saved["files"].items()
            ):
                raise ValueError("Existing immutable model differs")
            continue
        print(f"Acquiring {key} at {entry['revision']} ({entry['declared_bytes']} bytes)", flush=True)
        snapshot_download(entry["repo"], revision=entry["revision"], local_dir=destination,
                          allow_patterns=entry["selected_files"], max_workers=2)
        manifest = {**entry, "acquired_at": now().isoformat(), "files": {
            name: file_hash(destination / name) for name in entry["selected_files"]}}
        atomic_json(existing, manifest)
        atomic_json(out / "model-manifests" / f"{key}.json", manifest)
        print(f"Verified {key}", flush=True)


if __name__ == "__main__":
    main()
