"""Merge human-approved repack voice clips into an existing voices package; never replaces approved slots.

Reads PCM16 mono 22050 Hz WAVs named NNNN.wav (one per slot), pads each to its slot length and writes a NEW
package directory. The source package and the original game files are only read.
"""

import argparse
import json
from pathlib import Path
import struct
import sys
import wave

from audio_pipeline import atomic_json, digest, read_json
from inspect_voices import COUNT, EXE_SHA256, RATE, TABLE_OFFSET, VOICES_SHA256


def slot_table(exe):
    if digest(exe) != EXE_SHA256:
        raise ValueError("kain2.exe must be the untouched original")
    return list(struct.iter_unpack("<II", exe[TABLE_OFFSET:TABLE_OFFSET + COUNT * 8]))


def read_clip(path, length):
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, RATE, "NONE"):
            raise ValueError(f"{path.name}: expected PCM16 mono 22050 Hz")
        pcm = audio.readframes(audio.getnframes())
    if not pcm or len(pcm) > length:
        raise ValueError(f"{path.name}: empty or longer than its slot ({len(pcm)} > {length})")
    peak = max(abs(s) for s in struct.unpack(f"<{len(pcm) // 2}h", pcm))
    if peak >= 32767 or peak < 4:
        raise ValueError(f"{path.name}: clipping or effectively silent")
    return pcm + b"\0" * (length - len(pcm))


def merge(package_dir, clips_dir, original_exe, original_voices, output):
    manifest = read_json(package_dir / "manifest.json")
    if output.exists():
        raise ValueError("Choose a new output directory")
    table = slot_table(original_exe)
    if digest(original_voices) != VOICES_SHA256:
        raise ValueError("voices.dat must be the untouched original")
    present = {p["id"] for p in manifest["patches"]}
    clips = sorted(clips_dir.glob("[0-9][0-9][0-9][0-9].wav"))
    if not clips:
        raise ValueError("No clips found")
    patched = bytearray(original_voices)
    payloads = {}
    patches = list(manifest["patches"])
    for patch in patches:  # keep every already-approved slot byte for byte
        data = (package_dir / patch["file"]).read_bytes()
        if digest(data) != patch["sha256"]:
            raise ValueError(f"Existing payload {patch['file']} fails its hash")
        offset = table[patch["id"]][0]
        patched[offset:offset + len(data)] = data
        payloads[patch["file"]] = data
    added = []
    for clip in clips:
        index = int(clip.stem)
        if index in present:
            raise ValueError(f"Slot {index} is already approved; refusing to overwrite it")
        offset, length = table[index]
        payload = read_clip(clip, length)
        if payload == original_voices[offset:offset + length]:
            raise ValueError(f"Slot {index}: identical to the original")
        name = f"voice-{index:04d}.pcm"
        payloads[name] = payload
        patches.append(dict(id=index, file=name, sha256=digest(payload), length=len(payload)))
        patched[offset:offset + length] = payload
        added.append(index)
    patches.sort(key=lambda p: p["id"])
    manifest.update(patches=patches, result_sha256=digest(bytes(patched)), version=bump(manifest["version"]),
                    coverage=dict(replaced=len(patches), total=COUNT, complete=len(patches) == COUNT))
    output.mkdir(parents=True)
    for name, data in payloads.items():
        (output / name).write_bytes(data)
    atomic_json(output / "manifest.json", manifest)
    return dict(added=len(added), total=len(patches), result_sha256=manifest["result_sha256"])


def bump(version):
    major, minor, patch = (int(x) for x in version.split("."))
    return f"{major}.{minor + 1}.0"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True, help="existing voices package (manifest.json + voice-*.pcm)")
    parser.add_argument("--clips", type=Path, required=True, help="folder with approved NNNN.wav clips")
    parser.add_argument("--original-exe", type=Path, required=True)
    parser.add_argument("--original-voices", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new package directory")
    args = parser.parse_args()
    result = merge(args.package, args.clips, args.original_exe.read_bytes(), args.original_voices.read_bytes(), args.output)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
