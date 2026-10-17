"""Build isolated 640x480 company opening candidates from approved PNG cards."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from fractions import Fraction
from pathlib import Path

from run_rad import run as run_rad

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME = ROOT / "staging/menu-nosgoth-test/game"
DEFAULT_OUT = ROOT / "staging/company-openings-v2"
DEFAULT_RAD = ROOT / "staging/radtools/bin/radvideo64.exe"
ART = {
    "crylogo": ROOT / "content/art/company-crystal-dynamics.png",
    "publogo": ROOT / "content/art/company-eidos.png",
}
EXPECTED_SOURCE_SHA256 = {
    "crylogo": "de25840d0e384908489709b993847ec4b04b4d9806f2538256bc1bb6b50cc402",
    "publogo": "25ca73fa5b7d8794bfba3b607363142ba08fc512ef2452aa302d527fdbfc3cc2",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    return json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
         "-of", "json", str(path)], text=True))


def build_one(name: str, game: Path, output: Path, rad: Path) -> dict:
    source = game / f"{name}.bik"
    source_hash = sha(source)
    if source_hash != EXPECTED_SOURCE_SHA256[name]:
        raise ValueError(f"Unsupported or altered source Bink: {source} ({source_hash})")
    info = probe(source)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    if (int(video["width"]), int(video["height"])) != (320, 240):
        raise ValueError(f"Expected the pinned 320x240 source; refusing altered-resolution input: {source}")
    if audio.get("codec_name") != "binkaudio_dct" or audio.get("sample_rate") != "44100" or audio.get("channels") != 2:
        raise ValueError(f"Unexpected source audio format: {source}")

    artwork = ART[name]
    art_hash_before = sha(artwork)
    art_probe = probe(artwork)
    art_video = next(s for s in art_probe["streams"] if s["codec_type"] == "video")
    art_width, art_height = int(art_video["width"]), int(art_video["height"])
    if art_width * 3 != art_height * 4:
        raise ValueError(f"Approved art must already have exact 4:3 geometry: {artwork}")

    frames = int(video["nb_read_frames"])
    fps = Fraction(video["avg_frame_rate"])
    duration = Fraction(frames, 1) / fps
    dest = output / f"{name}.bik"
    wav = output / f"{name}-audio.wav"

    subprocess.run(["ffmpeg", "-n", "-nostdin", "-v", "error", "-i", str(source),
                    "-map", "0:a:0", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", str(wav)],
                   check=True)

    attempts = []
    extra = 0
    for attempt in range(4):
        total = frames + extra
        total_duration = Fraction(total, 1) / fps
        avi = output / f"{name}-input-{attempt + 1}.avi"
        fade = min(0.7, float(duration) / 10)
        fade_out_start = max(0.0, float(duration) - fade)
        filters = ["scale=640:480:flags=lanczos",
                   f"fade=t=in:st=0:d={fade:.9f}",
                   f"fade=t=out:st={fade_out_start:.9f}:d={fade:.9f}"]
        if extra:
            filters.append(f"tpad=stop_mode=clone:stop_duration={float(Fraction(extra, 1) / fps):.9f}")
        command = ["ffmpeg", "-n", "-nostdin", "-v", "error", "-loop", "1", "-framerate", str(fps),
                   "-i", str(artwork), "-i", str(wav), "-af", "apad", "-vf", ",".join(filters),
                   "-map", "0:v:0", "-map", "1:a:0", "-frames:v", str(total), "-fps_mode", "cfr",
                   "-r", str(fps), "-t", f"{float(total_duration):.9f}", "-c:v", "rawvideo",
                   "-pix_fmt", "bgr24", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", str(avi)]
        subprocess.run(command, check=True)
        avi_info = probe(avi)
        avi_video = next(s for s in avi_info["streams"] if s["codec_type"] == "video")
        if (int(avi_video["width"]), int(avi_video["height"])) != (640, 480):
            raise RuntimeError(f"{name}: intermediate AVI geometry changed")
        if int(avi_video["nb_read_frames"]) != total:
            raise RuntimeError(f"{name}: AVI has {avi_video['nb_read_frames']} frames; expected {total}")

        run_rad(rad, "Binkc", [avi], dest)
        encoded = probe(dest)
        encoded_video = next(s for s in encoded["streams"] if s["codec_type"] == "video")
        actual = int(encoded_video["nb_read_frames"])
        attempts.append({"input_frames": total, "encoded_frames": actual, "sha256": sha(dest)})
        if actual == frames:
            break
        if actual > frames:
            raise RuntimeError(f"{name}: RAD encoded {actual} frames; expected {frames}")
        dest.unlink()
        dest.with_suffix(dest.suffix + ".process.json").unlink(missing_ok=True)
        extra += frames - actual
    else:
        raise RuntimeError(f"{name}: RAD frame count did not converge")

    encoded_video = next(s for s in encoded["streams"] if s["codec_type"] == "video")
    encoded_audio = next(s for s in encoded["streams"] if s["codec_type"] == "audio")
    if (int(encoded_video["width"]), int(encoded_video["height"])) != (640, 480):
        raise RuntimeError(f"{name}: unexpected encoded geometry")
    if abs(float(Fraction(encoded_video["avg_frame_rate"]) - fps)) > 0.01:
        raise RuntimeError(f"{name}: encoded fps changed")
    if (encoded_audio.get("codec_name"), encoded_audio.get("sample_rate"), encoded_audio.get("channels")) != (
            "binkaudio_dct", "44100", 2):
        raise RuntimeError(f"{name}: encoded audio format changed")
    subprocess.run(["ffmpeg", "-n", "-nostdin", "-v", "error", "-i", str(dest), "-f", "null", "-"],
                   check=True, stdout=subprocess.DEVNULL)
    art_hash_after = sha(artwork)
    if art_hash_after != art_hash_before:
        raise RuntimeError(f"Approved PNG changed during encoding: {artwork}")

    report = {
        "source": str(source), "source_sha256": source_hash,
        "source_video": {"width": int(video["width"]), "height": int(video["height"]),
                         "fps": video["avg_frame_rate"], "frames": frames,
                         "duration_seconds": float(info["format"]["duration"])},
        "source_audio": {"codec": audio["codec_name"], "sample_rate": audio["sample_rate"],
                         "channels": audio["channels"]},
        "artwork": str(artwork), "artwork_sha256_before_and_after": art_hash_after,
        "candidate": str(dest), "candidate_sha256": sha(dest), "candidate_size": dest.stat().st_size,
        "candidate_video": {"codec": encoded_video["codec_name"], "width": int(encoded_video["width"]),
                            "height": int(encoded_video["height"]), "fps": encoded_video["avg_frame_rate"],
                            "frames": int(encoded_video["nb_read_frames"])},
        "candidate_audio": {"codec": encoded_audio["codec_name"],
                            "sample_rate": encoded_audio["sample_rate"],
                            "channels": encoded_audio["channels"]},
        "attempts": attempts, "full_ffmpeg_decode": "passed", "game_playback": "not tested",
        "audio_note": "Source Bink audio was decoded to PCM and re-encoded by RAD; bit-exact passthrough was unavailable in the local Binkc workflow.",
    }
    (output / f"{name}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=DEFAULT_GAME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--rad", type=Path, default=DEFAULT_RAD)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing staging output: {args.output}")
    args.output.mkdir(parents=True)
    results = [build_one(name, args.game, args.output, args.rad) for name in ("crylogo", "publogo")]
    (args.output / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
