"""Explicitly acquire a pinned public Transformers checkpoint for the LoRA path."""

import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
from huggingface_hub import HfApi, constants, snapshot_download  # noqa: E402

from north55_speech.core import atomic_json, file_hash  # noqa: E402

constants.HF_HUB_OFFLINE = False
repo = "openai/whisper-small"
revision = "973afd24965f72e36ca33b3055d56a652f456b4d"
destination = Path("/models/whisper-small-transformers")
info = HfApi().model_info(repo, revision=revision, files_metadata=True)
if info.sha != revision or info.card_data is None or info.card_data.to_dict().get("license") != "apache-2.0":
    raise RuntimeError("Source revision/license differs from reviewed model metadata")
if info.siblings is None:
    raise RuntimeError("Publisher file listing is missing")
files = [entry.rfilename for entry in info.siblings if entry.rfilename.endswith((".json", ".txt"))
         or entry.rfilename in {"README.md", "model.safetensors"}]
snapshot_download(repo, revision=revision, local_dir=destination, allow_patterns=files, max_workers=2)
hashes = {name: file_hash(destination/name) for name in files}
for entry in info.siblings:
    if entry.rfilename in hashes and entry.lfs and entry.lfs.sha256 != hashes[entry.rfilename]:
        raise RuntimeError("Publisher LFS checksum mismatch")
manifest = {"repo": repo, "revision": revision, "license": "apache-2.0", "files": hashes,
            "purpose": "optional supervised ASR LoRA after verified training annotations",
            "excluded_formats": ["pytorch_model.bin", "flax_model.msgpack", "tf_model.h5"],
            "training_executed": False}
atomic_json(destination/"manifest.json", manifest)
atomic_json(Path("/reports/transformers-small-acquisition.json"), manifest)
print({"status": "ACQUIRED_CHECKSUM_VERIFIED", "files": len(files), "revision": revision})
