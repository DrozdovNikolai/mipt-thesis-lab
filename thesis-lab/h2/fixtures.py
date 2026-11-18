"""Generate reproducible synthetic English training audio with eSpeak NG."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import wave

TEXTS = {
    "pilot": "Captain, the departure briefing is complete. Check the flight controls. Set the heading to two seven zero. Confirm the altitude selection. The first officer checks the runway and reads the takeoff checklist. Cabin crew, prepare for departure. We will maintain the assigned speed and monitor the engine instruments.",
    "main": "The instructor starts a simulator training session. The aircraft is approaching the airport. Reduce the airspeed and select the landing configuration. The captain calls for the approach checklist. The first officer confirms the weather and the assigned runway. If the approach becomes unstable, perform a go around. Positive climb, gear up."
}


def generate(output, durations=(30, 180, 900)):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"synthetic": True, "texts": TEXTS, "fixtures": {},
                "espeak_version": subprocess.check_output(["espeak-ng", "--version"], text=True).strip()}
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        for group, text in TEXTS.items():
            raw, base = folder / "raw.wav", folder / "base.wav"
            subprocess.run(["espeak-ng", "-v", "en-us", "-s", "145", "-w", str(raw), text], check=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ac", "1", "-ar", "16000", str(base)], check=True)
            with wave.open(str(base)) as source:
                frames = source.readframes(source.getnframes())
            for duration in durations:
                name = f"{group}-{duration}"
                data = (frames * ((duration * 32000 + len(frames) - 1) // len(frames)))[:duration * 32000]
                path = output / (name + ".wav")
                with wave.open(str(path), "wb") as target:
                    target.setnchannels(1)
                    target.setsampwidth(2)
                    target.setframerate(16000)
                    target.writeframes(data)
                manifest["fixtures"][name] = {"audio_seconds": duration,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(args.output)
