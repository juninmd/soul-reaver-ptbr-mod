"""Mix timed synthetic dialogue into separated Bink audio; produces review candidates."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stamp(seconds):
    milliseconds = round(seconds * 1000)
    return f"{milliseconds // 3600000:02}:{milliseconds // 60000 % 60:02}:{milliseconds // 1000 % 60:02},{milliseconds % 1000:03}"


def build(plan, takes, original, background, output, fmv):
    if output.exists():
        raise ValueError("Choose a new review directory")
    source, rate = sf.read(original, dtype="float32", always_2d=True)
    bed, bed_rate = sf.read(background, dtype="float32", always_2d=True)
    if source.shape != bed.shape or rate != bed_rate or source.shape[1] != 2:
        raise ValueError("Background must match the complete stereo source")
    rows = sorted((v for v in read(plan)["voices"] if v.get("fmv") == fmv), key=lambda v: v["start"])
    if not rows:
        raise ValueError("No timed dialogue for this movie")
    candidates = {}
    for metadata in takes.glob("*/metadata.json"):
        data = read(metadata)
        identity = data["identity"]["voice"]
        if identity["id"] in candidates:
            raise ValueError("Multiple takes for the same id; select a take directory explicitly")
        candidates[identity["id"]] = (metadata.parent / "voice.wav", data)
    result = source.copy()
    fade = round(rate * 0.06)
    srt, evidence = [], []
    previous_end = 0
    for i, row in enumerate(rows, 1):
        start, end = round(row["start"] * rate), round(row["end"] * rate)
        if start < previous_end or end <= start or end > len(source):
            raise ValueError(f"Invalid or overlapping interval {row['id']}")
        previous_end = end
        take, metadata = candidates[row["id"]]
        if metadata["identity"]["voice"]["text_ptbr"] != row["text_ptbr"]:
            raise ValueError("Generated text does not match the timing plan")
        if hashlib.sha256(take.read_bytes()).hexdigest() != metadata["audio_sha256"]:
            raise ValueError("Take hash differs")
        voice, voice_rate = sf.read(take, dtype="float32")
        if voice.ndim != 1 or not len(voice) or not np.isfinite(voice).all():
            raise ValueError("Invalid take samples")
        # Explicit resampling, no pitch/speed changes or truncated dialogue.
        from scipy.signal import resample_poly
        from math import gcd
        divisor = gcd(rate, voice_rate)
        voice = resample_poly(voice, rate // divisor, voice_rate // divisor)
        if len(voice) > end - start:
            raise ValueError(f"Take {row['id']} exceeds interval by {(len(voice) - end + start) / rate:.3f}s")
        mask = np.ones(end - start, dtype="float32")
        edge = min(fade, len(mask) // 2)
        mask[:edge] = np.linspace(0, 1, edge)
        mask[-edge:] = np.linspace(1, 0, edge)
        result[start:end] = source[start:end] * (1 - mask[:, None]) + bed[start:end] * mask[:, None]
        result[start:start + len(voice)] += voice[:, None] * 0.85
        duration = len(voice) / rate
        srt.append(f"{i}\n{stamp(row['start'])} --> {stamp(row['start'] + duration)}\n{row['text_ptbr']}\n")
        evidence.append(dict(id=row["id"], start=row["start"], end=row["end"], duration=duration,
                             audio_sha256=metadata["audio_sha256"], text_ptbr=row["text_ptbr"]))
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite mixed audio")
    peak = float(np.max(np.abs(result)))
    gain = min(1.0, 0.97 / peak)
    output.mkdir(parents=True)
    sf.write(output / f"{fmv}.wav", result * gain, rate, subtype="PCM_16")
    (output / f"{fmv}.srt").write_text("\n".join(srt), encoding="utf-8")
    report = dict(schema=1, fmv=fmv, frames=len(result), sample_rate=rate, gain=gain,
                  source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                  background_sha256=hashlib.sha256(background.read_bytes()).hexdigest(),
                  lines=evidence, validation="Candidate only; ASR, listening and game playback pending")
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("plan", "takes", "original", "background", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--fmv", required=True)
    print(json.dumps(build(**vars(parser.parse_args())), ensure_ascii=False))
