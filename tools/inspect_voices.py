"""Inspect/patch only the verified Steam classic build; never write into its source folder."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import wave

EXE_SHA256 = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a"
VOICES_SHA256 = "e2a193b62f9723f5f477f705c53a56f895375ce2d980d276d0d0fceeb2645df5"
TABLE_OFFSET = 0xFC210
COUNT = 479
RATE = 22050


def inspect(game):
    exe = (game / "kain2.exe").read_bytes()
    pcm = (game / "voices.dat").read_bytes()
    if hashlib.sha256(exe).hexdigest() != EXE_SHA256:
        raise ValueError("Unsupported kain2.exe hash")
    if hashlib.sha256(pcm).hexdigest() != VOICES_SHA256:
        raise ValueError("Unsupported voices.dat hash; use the original source")
    table = list(struct.iter_unpack("<II", exe[TABLE_OFFSET:TABLE_OFFSET + COUNT * 8]))
    cursor = 0
    for offset, length in table:
        if offset != cursor or offset % 2 or length % 2 or offset + length > len(pcm):
            raise ValueError("Invalid voice table")
        cursor += length
    if len(table) != COUNT or cursor != len(pcm):
        raise ValueError("Table does not cover the entire file")
    rows = [dict(id=i, offset=o, length=n, duration_seconds=n / (RATE * 2))
            for i, (o, n) in enumerate(table)]
    return pcm, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "extract", "patch"))
    parser.add_argument("--game", type=Path, required=True, help="Untouched source installation")
    parser.add_argument("--id", type=int)
    parser.add_argument("--output", type=Path, help="New file outside the source installation")
    parser.add_argument("--replacement", type=Path, help="PCM WAV: 22050 Hz, mono, 16 bits")
    parser.add_argument("--lead-samples", type=int, default=0)
    args = parser.parse_args()
    try:
        game = args.game.resolve()
        pcm, rows = inspect(game)
        if args.action == "inspect":
            print(json.dumps(dict(entries=len(rows), bytes=len(pcm), voices=rows), indent=2))
            return
        if args.id is None or not 0 <= args.id < COUNT or args.output is None:
            raise ValueError("extract/patch require --id (0..478) and --output")
        output = args.output.resolve()
        if output.is_relative_to(game):
            raise ValueError("Output must be outside the source installation")
        if output.exists():
            raise ValueError("Output already exists; refusing to overwrite")
        row = rows[args.id]
        offset, length = row["offset"], row["length"]
        if args.action == "extract":
            with output.open("xb") as file, wave.open(file, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(RATE)
                wav.writeframes(pcm[offset:offset + length])
        else:
            if args.replacement is None or args.lead_samples < 0:
                raise ValueError("patch requires --replacement and nonnegative --lead-samples")
            with wave.open(str(args.replacement), "rb") as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, RATE, "NONE"):
                    raise ValueError("Replacement must be uncompressed PCM16 mono 22050 Hz")
                replacement = wav.readframes(wav.getnframes())
            leading = args.lead_samples * 2
            if not replacement or leading + len(replacement) > length:
                raise ValueError("Replacement is empty or exceeds the original slot")
            slot = b"\x00" * leading + replacement
            slot += b"\x00" * (length - len(slot))
            patched = pcm[:offset] + slot + pcm[offset + length:]
            if len(patched) != len(pcm) or patched[:offset] != pcm[:offset] or patched[offset + length:] != pcm[offset + length:]:
                raise ValueError("Unexpected change outside the selected slot")
            with output.open("xb") as file:
                file.write(patched)
            row = dict(row, output_sha256=hashlib.sha256(patched).hexdigest(), outside_slot_identical=True)
        print(json.dumps(dict(output=str(output), voice=row), indent=2))
    except (OSError, ValueError, wave.Error) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
