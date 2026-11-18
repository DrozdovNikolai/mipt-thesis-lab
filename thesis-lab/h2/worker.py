"""Lease adapter around the existing Firefly preprocessing and ASR functions."""
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time
import urllib.error
import urllib.request

BASE = os.environ["H2_COORDINATOR"].rstrip("/")
TOKEN = os.environ["H2_API_TOKEN"]
WORKER = os.environ.get("POD_UID", os.environ.get("HOSTNAME", "local"))
stopping = threading.Event()


def request(path, payload=None, *, method=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=body,
         headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def log(kind, **data):
    print(json.dumps({"at": time.time(), "kind": kind, "worker": WORKER, **data}), flush=True)


def normalize_result(payload):
    # Session identity is transport metadata, not recognizer output.
    return {"language": payload["language"], "aligned": payload["aligned"]}


def main():
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    started = time.monotonic()
    from app.tasks import speech_whisperx as speech
    from scripts.speech_gpu_worker import _process_asr_chunk
    model = speech._get_whisper_model()
    boot = {"model_load_seconds": time.monotonic() - started, "node": os.environ.get("NODE_NAME", "local")}
    log("ready", **boot)
    current = {}
    lock = threading.Lock()
    heartbeat_stop = threading.Event()

    def heartbeat_loop():
        while not heartbeat_stop.is_set():
            try:
                request("/register", {"worker": WORKER, "metadata": boot})
                with lock:
                    owned = dict(current)
                if owned:
                    request("/heartbeat", owned)
            except Exception as error:
                log("heartbeat_error", type=type(error).__name__)
            heartbeat_stop.wait(3)

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    Path("/tmp/h2-ready").write_text(WORKER)
    try:
        while not stopping.is_set():
            task = request("/claim", {"worker": WORKER})
            if not task:
                stopping.wait(0.5)
                continue
            owned = {"task_id": task["id"], "worker": WORKER, "lease": task["lease"]}
            with lock:
                current.update(owned)
            task_started = time.monotonic()
            log("claimed", task=task["id"], lease=task["lease"])
            try:
                payload = json.loads(task["payload"])
                prefix = f"/artifacts/{task['id']}/{task['lease']}/"
                with tempfile.TemporaryDirectory(prefix="ff-h2-") as folder:
                    folder = Path(folder)
                    source, wav = folder / "source.wav", folder / "chunk.wav"
                    urllib.request.urlretrieve(BASE + "/fixtures/" + payload["fixture"], source)
                    if hashlib.sha256(source.read_bytes()).hexdigest() != payload["sha256"]:
                        raise ValueError("Input fixture checksum mismatch")
                    speech._ffmpeg_convert_to_wav(source, wav)
                    req = urllib.request.Request(BASE + prefix + "wav", data=wav.read_bytes(), method="PUT")
                    with urllib.request.urlopen(req, timeout=60):
                        pass
                    request("/heartbeat", {**owned, "stage": "asr"})
                    preprocess_seconds = time.monotonic() - task_started
                    _process_asr_chunk({"session_id": task["id"], "chunk_index": 0, "chunk_start_ms": 0,
                        "wav_input": {"download_url": BASE + prefix + "wav"},
                        "asr_output": {"upload_url": BASE + prefix + "json"}}, folder)
                    result = normalize_result(request(prefix + "json"))
                    segments = result["aligned"].get("segments", [])
                    if not segments or not any(s.get("text", "").strip() for s in segments):
                        raise ValueError("Empty transcript for voiced fixture")
                    # One deliberate process exit is useful for local/cloud recovery tests.
                    marker = payload.get("crash_after_asr_first_attempt", False)
                    if marker and task["attempts"] == 1:
                        log("injected_exit_after_asr", task=task["id"])
                        os._exit(77)
                    request("/complete", {**owned, "result": result})
                    log("completed", task=task["id"], preprocess_seconds=preprocess_seconds,
                        total_seconds=time.monotonic() - task_started)
            finally:
                with lock:
                    current.clear()
    finally:
        Path("/tmp/h2-ready").unlink(missing_ok=True)
        heartbeat_stop.set()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
