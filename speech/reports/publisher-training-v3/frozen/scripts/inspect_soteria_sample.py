"""Offline container/PCM validation of the acquired sample; no ASR or human gold."""

import hashlib
import json
import math
import struct
import subprocess
import wave
from pathlib import Path


def main():
    audit = Path("reports/direct-data-search-v1")
    source = json.loads((audit / "soteria-acquisition.json").read_text())
    path = Path(source["local_path"].replace("\\", "/"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Source file changed")
    output = path.parent / "inspection"
    output.mkdir(exist_ok=True)
    common = ["docker", "run", "--rm", "--network", "none", "--mount",
              f"type=bind,source={path.parent.resolve()},target=/input,readonly", "--mount",
              f"type=bind,source={output.resolve()},target=/output"]
    probe_cmd = common + ["--entrypoint", "ffprobe", "north55-speech-gpu:0.1.0", "-v", "error",
                          "-show_entries", "stream=index,codec_type,codec_name,sample_rate,channels,duration:format=duration,size",
                          "-of", "json", f"/input/{path.name}"]
    probe = json.loads(subprocess.run(probe_cmd, check=True, capture_output=True, text=True).stdout)
    audio = [stream for stream in probe["streams"] if stream["codec_type"] == "audio"]
    if len(audio) != 1:
        raise ValueError("Expected one audio stream; inspect channel mapping")
    wav_path = output / "source-audio-48k-stereo.wav"
    decode_cmd = common + ["--entrypoint", "ffmpeg", "north55-speech-gpu:0.1.0", "-v", "error",
                           "-n", "-i", f"/input/{path.name}", "-map", "0:a:0", "-vn",
                           "-c:a", "pcm_s16le", "/output/source-audio-48k-stereo.wav"]
    decoded = not wav_path.exists()
    if decoded:
        subprocess.run(decode_cmd, check=True, capture_output=True)
    with wave.open(str(wav_path), "rb") as handle:
        channels, rate, width = handle.getnchannels(), handle.getframerate(), handle.getsampwidth()
        frames = handle.getnframes()
        pcm = handle.readframes(frames)
    if (channels, rate, width) != (2, 48000, 2):
        raise ValueError("Unexpected PCM format")
    squares = [0, 0]
    peaks = [0, 0]
    for values in struct.iter_unpack("<hh", pcm):
        for channel, sample in enumerate(values):
            squares[channel] += sample * sample
            peaks[channel] = max(peaks[channel], abs(sample))
    rms = [math.sqrt(total / frames) / 32768 for total in squares]
    if not all(value > 0 for value in rms):
        raise ValueError("Empty/silent channel in the sample")
    result = {"status": "PASS", "scope": "file integrity and offline audio decoding only",
              "probe": probe, "commands": [probe_cmd, decode_cmd], "decoded_this_run": decoded,
              "wav_path": str(wav_path), "wav_sha256": hashlib.sha256(wav_path.read_bytes()).hexdigest(),
              "frames": frames, "duration_sec": frames / rate, "sample_rate": rate,
              "channels": channels, "channel_rms": rms, "channel_peak_pcm16": peaks,
              "human_listening_verified": False, "transcript_verified": False,
              "asr_executed": False, "benchmark_admitted": False,
              "original_time_origin_sec": 0.0, "transformation": "AAC decoded to PCM16, same rate/channels"}
    (audit / "soteria-audio-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "commands"}, indent=2))


if __name__ == "__main__":
    main()
