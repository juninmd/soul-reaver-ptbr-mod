"""Offline, resumable FMV batch for Legacy of Kain: Soul Reaver classic.

Per video, in isolated and idempotent stages:
  1. decode every frame of a source Bink (read-only) to PNG;
  2. upscale each frame with Real-ESRGAN (`realesrgan-x4plus`, scale 4);
  3. fit 4:3 content inside a configurable canvas, apply subtitles *after* the
     upscale and keep the audio track;
  4. re-encode legacy Bink with RADTools; the compressed MP4 fallback is retained
     if the Bink encoder fails, while large AVI intermediates are removed by default.

Nothing here opens the game, writes to the Steam install or touches saves. Every
output lives under an isolated `--out` root. Existing output is never overwritten
without `--resume`, and the tool never claims runtime or playback verification.

Geometry: source is required to be 4:3. The default canvas is 1024x768 to limit
disk use; use --target-width/--target-height for a larger output when needed.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_rad import run as run_rad  # noqa: E402  (proven hidden-window RAD invoker)

REPO = Path(__file__).resolve().parent.parent

# Default output follows the user's compact 1K preference; larger canvases are opt-in.
TARGET_WIDTH, TARGET_HEIGHT = 1024, 768
CONTENT_WIDTH, CONTENT_HEIGHT = 1024, 768
PILLAR_X, PILLAR_Y = 0, 0
AUDIO_RATE, AUDIO_CHANNELS = 44100, 2
MAX_OUTPUT_SIZE_RATIO = 5.0


def set_output_geometry(width: int, height: int) -> None:
    """Fit a 4:3 source inside a canvas; dimensions must preserve exact 4:3 pixels."""
    global TARGET_WIDTH, TARGET_HEIGHT, CONTENT_WIDTH, CONTENT_HEIGHT, PILLAR_X, PILLAR_Y
    if width <= 0 or height <= 0 or width % 4 or height % 3:
        raise ValueError("target width must be divisible by 4 and height by 3")
    TARGET_WIDTH, TARGET_HEIGHT = width, height
    if width * 3 >= height * 4:
        CONTENT_HEIGHT = height
        CONTENT_WIDTH = height * 4 // 3
    else:
        CONTENT_WIDTH = width
        CONTENT_HEIGHT = width * 3 // 4
    PILLAR_X = (width - CONTENT_WIDTH) // 2
    PILLAR_Y = (height - CONTENT_HEIGHT) // 2

# Priority order requested for the batch (short logos first only as a smoke test).
DEFAULT_PLAN = [
    {"name": "intro", "order": 1, "captions": "staging/fmv-dub-v1/mix-v2/intro.ass",
     "audio": ["staging/fmv-dub-v1/mix-v2/intro.wav"]},
    {"name": "verse", "order": 2, "captions": "staging/fmv-dub-v2/verse-render-v2/verse/captions.ass",
     "audio": ["staging/fmv-dub-v2/rendered-v2/verse/verse.wav"], "blackout": True},
    {"name": "chrono3", "order": 3, "captions": "staging/fmv-dub-v2/rendered-v2/chrono3/captions.ass",
     "audio": ["staging/fmv-dub-v2/rendered-v2/chrono3/chrono3.wav"]},
    {"name": "chrono5", "order": 4, "captions": "staging/fmv-dub-v2/rendered-v2/chrono5/captions.ass",
     "audio": ["staging/fmv-dub-v2/rendered-v2/chrono5/chrono5.wav"]},
    {"name": "chrono7", "order": 5, "captions": "staging/fmv-dub-v2/rendered-v2/chrono7/captions.ass",
     "audio": ["staging/fmv-dub-v2/rendered-v2/chrono7/chrono7.wav"]},
    {"name": "chrono9", "order": 6, "captions": "staging/fmv-dub-v2/rendered-v2/chrono9/captions.ass",
     "audio": ["staging/fmv-dub-v2/rendered-v2/chrono9/chrono9.wav"]},
    {"name": "chrono11", "order": 7, "captions": "staging/fmv-dub-v2/rendered-v2/chrono11/captions.ass",
     "audio": ["staging/fmv-dub-v2/rendered-v2/chrono11/chrono11.wav"]},
    {"name": "chrono13", "order": 8, "captions": "staging/fmv-dub-v2/rendered-v2/chrono13/captions.ass",
     "audio": ["staging/fmv-dub-v2/rendered-v2/chrono13/chrono13.wav"]},
    {"name": "credits", "order": 9},
    {"name": "crylogo", "order": 10},
    {"name": "publogo", "order": 11},
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, cwd=None, log=None):
    text = " ".join(str(part) for part in command)
    if log is not None:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {text}\n")
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if log is not None and (result.stdout or result.stderr):
        with log.open("a", encoding="utf-8") as handle:
            handle.write(result.stdout)
            handle.write(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {text}\n{result.stderr[-2000:]}")
    return result


def probe(path: Path, count_frames: bool = True) -> dict:
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command.append("-count_frames")
    command += ["-show_streams", "-show_format", "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr}")
    return json.loads(result.stdout)


def ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def validate_output_size(output_size: int, source_size: int) -> dict:
    """Central policy: enforce the final compressed-file budget vs. source Bink."""
    max_ratio = MAX_OUTPUT_SIZE_RATIO
    if output_size <= 0 or source_size <= 0:
        raise ValueError("video sizes and max output ratio must be positive")
    limit = int(source_size * max_ratio)
    if output_size > limit:
        raise ValueError(f"output {output_size} bytes exceeds the {max_ratio:g}x source limit of {limit} bytes")
    return {"source_size": source_size, "max_ratio": max_ratio, "max_size": limit,
            "output_size": output_size, "actual_ratio": output_size / source_size}


def lower_bink_data_rate(flags: list[str]) -> list[str] | None:
    """Lower only the documented RAD target data-rate switch for an oversized encode."""
    for index, flag in enumerate(flags):
        match = re.fullmatch(r"/D(\d+)", flag, flags=re.IGNORECASE)
        if match:
            current = int(match.group(1))
            if current <= 100_000:
                return None
            updated = max(100_000, current * 2 // 3)
            result = list(flags)
            result[index] = f"/D{updated}"
            return result
    return None


def video_stream(data: dict) -> dict:
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if len(streams) != 1:
        raise ValueError("expected exactly one video stream")
    return streams[0]


def audio_stream(data: dict):
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    return streams[0] if streams else None


def png_dimensions(path: Path):
    with Path(path).open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"invalid PNG frame: {path}")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def ass_time_to_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def ass_seconds(value: str) -> float:
    hours, minutes, seconds = value.strip().split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def ass_format(seconds: float) -> str:
    seconds = max(0.0, seconds)
    count = round(seconds * 100)
    return f"{count // 360000}:{count // 6000 % 60:02}:{count // 100 % 60:02}.{count % 100:02}"


def rescale_ass(source: Path, dest: Path, play_x: int, play_y: int, window=None) -> dict:
    """Rewrite an ASS file for the final canvas, scaling text metrics uniformly.

    libass scales ASS coordinates by video/PlayRes, so a 640x480 script applied to a
    a wide frame is stretched 4/3 horizontally. Rewriting PlayRes to the canvas and
    multiplying metrics by the vertical factor keeps the glyphs unstretched.

    When ``window`` is given as (start_seconds, duration_seconds) the events are clipped
    to that window and rebased to clip time, matching the extracted frame range.
    """
    lines = Path(source).read_text(encoding="utf-8-sig").splitlines()
    factor = play_y / 480.0
    out, metrics = [], {"font": None, "outline": None, "shadow": None, "margins": None}
    style_index: dict = {}
    event_index: dict = {}
    section = ""
    kept = dropped = 0
    if window:
        low, duration = window
        if duration <= 0:
            raise ValueError("ASS window duration must be positive")
        high = low + duration
    else:
        low, high = 0.0, None
    for line in lines:
        if line.strip().startswith("["):
            section = line.strip().lower()
            out.append(line)
            continue
        if line.startswith("PlayResX"):
            out.append(f"PlayResX: {play_x}")
        elif line.startswith("PlayResY"):
            out.append(f"PlayResY: {play_y}")
        elif line.startswith("Format:"):
            names = [name.strip() for name in line.split(":", 1)[1].split(",")]
            if "styles" in section:
                style_index = {name: i for i, name in enumerate(names)}
            elif "events" in section:
                event_index = {name: i for i, name in enumerate(names)}
            out.append(line)
        elif line.startswith("Style:") and style_index:
            fields = line.split(",", len(style_index) - 1)
            for key, store in (("Fontsize", "font"), ("Outline", "outline"),
                               ("Shadow", "shadow"), ("MarginL", "margins"),
                               ("MarginR", "margins"), ("MarginV", "margins")):
                if key in style_index:
                    i = style_index[key]
                    fields[i] = f"{float(fields[i]) * factor:.2f}"
                    metrics[store] = fields[i]
            out.append(",".join(fields))
        elif line.startswith(("Dialogue:", "Comment:")) and event_index:
            fields = line.split(",", len(event_index) - 1)
            is_visible_dialogue = line.startswith("Dialogue:") and bool(
                fields[event_index["Text"]].strip()) if "Text" in event_index else False
            if window and "Start" in event_index and "End" in event_index:
                begin = ass_seconds(fields[event_index["Start"]])
                end = ass_seconds(fields[event_index["End"]])
                begin, end = max(begin, low), min(end, high)
                if end <= begin:
                    dropped += 1
                    continue
                fields[event_index["Start"]] = ass_format(begin - low)
                fields[event_index["End"]] = ass_format(end - low)
                if is_visible_dialogue:
                    kept += 1
            elif is_visible_dialogue:
                kept += 1
            for key in ("MarginL", "MarginR", "MarginV"):
                if key in event_index and fields[event_index[key]].strip().isdigit():
                    fields[event_index[key]] = str(round(int(fields[event_index[key]]) * factor))
            out.append(",".join(fields))
        else:
            out.append(line)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    metrics.update(factor=factor, source=str(source), window=list(window) if window else None,
                   events_kept=kept, events_dropped=dropped)
    return metrics


def blackout_filters(entry: dict, caption_metrics: dict | None) -> list[str]:
    """Build explicit, timed text-card masks; reject the old whole-frame switch."""
    if not entry.get("blackout"):
        return []
    intervals = entry.get("blackout_intervals")
    if not isinstance(intervals, list) or not intervals:
        raise ValueError("blackout requires explicit blackout_intervals (x, y, w, h, start, end)")
    if not caption_metrics or int(caption_metrics.get("events_kept", 0)) <= 0:
        raise ValueError("blackout requires at least one visible PT-BR dialogue event")
    filters = []
    for index, item in enumerate(intervals):
        if not isinstance(item, dict):
            raise ValueError(f"blackout_intervals[{index}] must be an object")
        try:
            x, y, width, height = (int(item[key]) for key in ("x", "y", "w", "h"))
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"blackout_intervals[{index}] has invalid coordinates or time") from exc
        if (x < 0 or y < 0 or width <= 0 or height <= 0
                or x + width > TARGET_WIDTH or y + height > TARGET_HEIGHT
                or start < 0 or end <= start):
            raise ValueError(f"blackout_intervals[{index}] is outside the canvas or has an invalid time range")
        filters.append(
            f"drawbox=x={x}:y={y}:w={width}:h={height}:color=black:t=fill:enable='between(t,{start:.3f},{end:.3f})'"
        )
    return filters


class VideoJob:
    def __init__(self, args, entry):
        self.args = args
        self.entry = entry
        self.name = entry["name"]
        self.dir = args.out / self.name
        self.log = self.dir / "run.log"

    # ---- resolution of inputs -------------------------------------------------
    def resolve_video(self) -> Path:
        for base in self.args.sources:
            for suffix in (".bik.original", ".bik"):
                candidate = Path(base) / f"{self.name}{suffix}"
                if candidate.is_file():
                    return candidate
        fallback = Path(self.args.game) / f"{self.name}.bik"
        if fallback.is_file():
            return fallback
        raise FileNotFoundError(f"no source Bink found for {self.name}")

    def resolve_audio(self):
        for rel in self.entry.get("audio", []):
            candidate = REPO / rel
            if candidate.is_file():
                return candidate
        game = Path(self.args.game) / f"{self.name}.bik"
        if game.is_file():
            return game
        return None

    def resolve_captions(self):
        rel = self.entry.get("captions")
        if not rel:
            return None
        candidate = REPO / rel
        if not candidate.is_file():
            raise FileNotFoundError(f"captions missing: {candidate}")
        return candidate

    # ---- state ----------------------------------------------------------------
    def load_state(self):
        path = self.dir / "state.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_state(self, state):
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        (self.dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def config_fingerprint(self):
        payload = {
            "target": [TARGET_WIDTH, TARGET_HEIGHT],
            "content": [CONTENT_WIDTH, CONTENT_HEIGHT, PILLAR_X, PILLAR_Y],
            "model": self.args.model,
            "scale": self.args.scale,
            "rescale_ass": not self.args.raw_ass,
            "blackout": bool(self.entry.get("blackout")),
            "start": self.args.start,
            "duration": self.args.duration,
            "audio_rate": AUDIO_RATE,
            "audio_channels": AUDIO_CHANNELS,
            "bink_flags": self.args.bink_flags,
            "max_output_size_ratio": MAX_OUTPUT_SIZE_RATIO,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    # ---- stages ---------------------------------------------------------------
    def stage_frames(self, state, video: Path, info: dict):
        vs = video_stream(info)
        width, height = int(vs["width"]), int(vs["height"])
        if width * 3 != height * 4:
            raise ValueError(f"{self.name}: source {width}x{height} is not 4:3; refusing to stretch")
        fps = Fraction(vs["avg_frame_rate"])
        total = int(vs.get("nb_read_frames") or 0)
        if total <= 0:
            raise ValueError(f"{self.name}: unknown source frame count")
        start_frame, count, partial = 0, total, False
        if self.args.duration is not None:
            # Match tools/video_upscale_poc.py: ceil the start and round the length so
            # a window reproduces the exact frame set of the approved sample.
            start_frame = ceil_fraction(Fraction(str(self.args.start or 0)) * fps)
            count = round(Fraction(str(self.args.duration)) * fps)
            partial = True
        if count <= 0:
            raise ValueError(f"{self.name}: window selects zero frames")
        frames = self.dir / "frames"
        if self.args.resume and state.get("stages", {}).get("frames", {}).get("complete"):
            recorded = state["stages"]["frames"]
            if recorded.get("count") == count and len(list(frames.glob("*.png"))) == count:
                print(f"[{self.name}] frames: reuse ({count})", flush=True)
                return recorded
        frames.mkdir(parents=True, exist_ok=True)
        for stale in frames.glob("*.png"):
            stale.unlink()
        if partial:
            vf = f"select='between(n,{start_frame},{start_frame + count - 1})',format=rgb24"
            run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(video), "-an",
                 "-vf", vf, "-fps_mode", "passthrough", "frames/%06d.png"], cwd=self.dir, log=self.log)
        else:
            run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(video), "-an",
                 "-pix_fmt", "rgb24", "-fps_mode", "passthrough", "frames/%06d.png"], cwd=self.dir, log=self.log)
        images = sorted(frames.glob("*.png"))
        if len(images) != count:
            raise RuntimeError(f"{self.name}: extracted {len(images)} frames, expected {count}")
        dims = png_dimensions(images[0])
        if dims != (width, height):
            raise RuntimeError(f"{self.name}: frame size {dims} != source {width}x{height}")
        record = {
            "complete": True, "count": count, "source_width": width, "source_height": height,
            "fps": str(fps), "source_frames": total, "start_frame": start_frame, "partial": partial,
            "source_sha256": sha256(video), "source": str(video),
            "source_size": video.stat().st_size,
        }
        state.setdefault("stages", {})["frames"] = record
        self.save_state(state)
        print(f"[{self.name}] frames: {count}/{total} extracted from {width}x{height}", flush=True)
        return record

    def stage_upscale(self, state, stage_frames):
        count = stage_frames["count"]
        ai = self.dir / "frames-ai"
        if self.args.resume and state.get("stages", {}).get("upscale", {}).get("complete"):
            recorded = state["stages"]["upscale"]
            if recorded.get("count") == count and len(list(ai.glob("*.png"))) == count:
                print(f"[{self.name}] upscale: reuse ({count})", flush=True)
                return recorded
        existing = sorted(ai.glob("*.png")) if ai.is_dir() else []
        if len(existing) == count:
            # Frames already produced by an interrupted run; validate and adopt the stage.
            dims = png_dimensions(existing[0])
            if dims == (stage_frames["source_width"] * self.args.scale, stage_frames["source_height"] * self.args.scale):
                record = {"complete": True, "count": count, "width": dims[0], "height": dims[1],
                          "model": self.args.model, "scale": self.args.scale, "adopted": True}
                state.setdefault("stages", {})["upscale"] = record
                self.save_state(state)
                print(f"[{self.name}] upscale: adopted {count} existing frames", flush=True)
                return record
        ai.mkdir(parents=True, exist_ok=True)
        for stale in ai.glob("*.png"):
            stale.unlink()
        exe = Path(self.args.realesrgan)
        command = [str(exe), "-i", str((self.dir / "frames").resolve()), "-o", str(ai.resolve()),
                   "-n", self.args.model, "-s", str(self.args.scale), "-f", "png"]
        if self.args.models:
            command += ["-m", str(Path(self.args.models).resolve())]
        run(command, cwd=str(exe.parent), log=self.log)
        images = sorted(ai.glob("*.png"))
        if len(images) != count:
            raise RuntimeError(f"{self.name}: upscaled {len(images)} frames, expected {count}")
        dims = png_dimensions(images[0])
        expected = (stage_frames["source_width"] * self.args.scale, stage_frames["source_height"] * self.args.scale)
        if dims != expected:
            raise RuntimeError(f"{self.name}: upscaled size {dims} != {expected}")
        record = {"complete": True, "count": count, "width": dims[0], "height": dims[1],
                  "model": self.args.model, "scale": self.args.scale,
                  "model_sha256": {p.suffix.lstrip("."): sha256(p) for p in
                                   sorted((Path(self.args.models or (exe.parent / "models"))).glob(f"{self.args.model}.*"))}}
        state.setdefault("stages", {})["upscale"] = record
        self.save_state(state)
        print(f"[{self.name}] upscale: {count} frames -> {dims[0]}x{dims[1]}", flush=True)
        return record

    def prepare_audio(self, state, audio_src):
        target = self.dir / "audio.wav"
        recorded = state.get("stages", {}).get("audio", {})
        if self.args.resume and recorded.get("complete") and target.is_file():
            print(f"[{self.name}] audio: reuse", flush=True)
            return recorded
        if audio_src is None:
            state.setdefault("stages", {})["audio"] = {"complete": True, "present": False}
            self.save_state(state)
            print(f"[{self.name}] audio: none", flush=True)
            return state["stages"]["audio"]
        info = probe(audio_src, count_frames=False)
        stream = audio_stream(info)
        if stream is None:
            state.setdefault("stages", {})["audio"] = {"complete": True, "present": False,
                                                       "note": f"no audio stream in {audio_src.name}"}
            self.save_state(state)
            return state["stages"]["audio"]
        run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(audio_src), "-vn",
             "-map", "0:a:0", "-c:a", "pcm_s16le", "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CHANNELS),
             str(target.resolve())], log=self.log)
        out = audio_stream(probe(target, count_frames=False))
        record = {"complete": True, "present": True, "source": str(audio_src),
                  "source_sha256": sha256(audio_src), "sample_rate": int(out["sample_rate"]),
                  "channels": int(out["channels"]), "duration": float(probe(target, False)["format"]["duration"]),
                  "sha256": sha256(target)}
        state.setdefault("stages", {})["audio"] = record
        self.save_state(state)
        print(f"[{self.name}] audio: {record['duration']:.3f}s from {audio_src.name}", flush=True)
        return record

    def stage_composite(self, state, stage_frames, audio_record, captions, extra=0, force=False):
        count = stage_frames["count"]
        fps = Fraction(stage_frames["fps"])
        avi = self.dir / "bink-input.avi"
        # Captions are prepared before the reuse check so a changed script (or a new
        # crop window) invalidates the cached AVI instead of silently reusing it.
        metrics = None
        captions_sha = None
        if captions is not None:
            dest = self.dir / "captions.ass"
            if self.args.raw_ass:
                shutil.copy2(captions, dest)
                metrics = {"factor": 1.0, "source": str(captions), "raw": True}
            else:
                metrics = rescale_ass(captions, dest, TARGET_WIDTH, TARGET_HEIGHT,
                                      window=(stage_frames["start_frame"] / float(fps),
                                              stage_frames["count"] / float(fps))
                                      if stage_frames["partial"] else None)
            captions_sha = sha256(dest)
        recorded = state.get("stages", {}).get("composite", {})
        if (not force and self.args.resume and recorded.get("complete") and recorded.get("extra", 0) == extra
                and recorded.get("captions_sha256") == captions_sha
                and avi.is_file() and sha256(avi) == recorded.get("sha256")):
            print(f"[{self.name}] composite: reuse", flush=True)
            return recorded
        total = count + extra
        filters = [f"scale={CONTENT_WIDTH}:{CONTENT_HEIGHT}:flags=lanczos",
                   f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:{PILLAR_X}:{PILLAR_Y}:black"]
        if captions is not None:
            filters.extend(blackout_filters(self.entry, metrics))
            filters.append("subtitles=captions.ass")
        elif self.entry.get("blackout"):
            blackout_filters(self.entry, None)
        if extra:
            # RADTools drops the last AVI frame on some cadences; a cloned tail gives
            # Binkc the frames it needs so the candidate keeps the exact frame count.
            filters.append(f"tpad=stop_mode=clone:stop_duration={extra / float(fps):.9f}")
        duration = float(Fraction(total, 1) / fps)
        seek = stage_frames["start_frame"] / float(fps)
        command = ["ffmpeg", "-y", "-nostdin", "-v", "error", "-framerate", str(fps),
                   "-i", "frames-ai/%06d.png"]
        if audio_record and audio_record.get("present"):
            if seek:
                command += ["-ss", f"{seek:.9f}"]
            command += ["-i", str((self.dir / "audio.wav").resolve()), "-af", "apad"]
        command += ["-vf", ",".join(filters), "-map", "0:v:0"]
        if audio_record and audio_record.get("present"):
            command += ["-map", "1:a:0", "-c:a", "pcm_s16le", "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CHANNELS)]
        command += ["-frames:v", str(total), "-fps_mode", "cfr", "-r", str(fps), "-t", f"{duration:.9f}",
                    "-c:v", "rawvideo", "-pix_fmt", "yuv420p", str(avi.resolve())]
        run(command, cwd=self.dir, log=self.log)
        out = probe(avi)
        ov = video_stream(out)
        if (int(ov["width"]), int(ov["height"])) != (TARGET_WIDTH, TARGET_HEIGHT):
            raise RuntimeError(f"{self.name}: composite is {ov['width']}x{ov['height']}")
        if int(ov.get("nb_read_frames") or 0) != total:
            raise RuntimeError(f"{self.name}: composite has {ov.get('nb_read_frames')} frames, expected {total}")
        if abs(float(Fraction(ov["avg_frame_rate"])) - float(fps)) > 0.01:
            raise RuntimeError(f"{self.name}: composite fps {ov['avg_frame_rate']} != {fps}")
        record = {"complete": True, "file": str(avi), "sha256": sha256(avi), "size": avi.stat().st_size,
                  "count": count, "extra": extra, "total_frames": total, "duration": duration,
                  "fps": str(fps), "composite_fps": ov["avg_frame_rate"], "captions_sha256": captions_sha,
                  "metrics": metrics, "audio": bool(audio_record and audio_record.get("present"))}
        state.setdefault("stages", {})["composite"] = record
        self.save_state(state)
        print(f"[{self.name}] composite: {TARGET_WIDTH}x{TARGET_HEIGHT} {total}f {avi.stat().st_size / 1e9:.2f} GB", flush=True)
        return record

    def stage_bink(self, state, composite, stage_frames):
        count = stage_frames["count"]
        target = self.dir / f"{self.name}-hd.bik"
        recorded = state.get("stages", {}).get("bink", {})
        source_size = int(stage_frames.get("source_size") or Path(stage_frames["source"]).stat().st_size)
        if (self.args.resume and recorded.get("status") == "bink" and target.is_file()
                and recorded.get("composite_sha256") == composite.get("sha256")
                and sha256(target) == recorded.get("sha256")):
            recorded["size_budget"] = validate_output_size(target.stat().st_size, source_size)
            print(f"[{self.name}] bink: reuse ({recorded['size_budget']['actual_ratio']:.2f}x source)", flush=True)
            return recorded
        rad = Path(self.args.rad)
        flags = self.args.bink_flags.split()
        extra = int(composite.get("extra", 0))
        record = {"complete": False, "status": "pending",
                  "composite_sha256": composite.get("sha256")}
        try:
            for attempt in range(4):
                if attempt:
                    composite = self.stage_composite(state, stage_frames, self.prepared_audio, self.captions_path,
                                                     extra=extra, force=True)
                target.unlink(missing_ok=True)
                target.with_suffix(target.suffix + ".process.json").unlink(missing_ok=True)
                run_rad(rad, "Binkc", [self.dir / "bink-input.avi"], target,
                        flags=flags, timeout=self.args.bink_timeout)
                if not target.is_file() or target.stat().st_size < 100:
                    raise RuntimeError("RAD Binkc produced no candidate")
                try:
                    size_budget = validate_output_size(target.stat().st_size, source_size)
                except ValueError:
                    reduced = lower_bink_data_rate(flags)
                    if reduced is None or attempt == 3:
                        raise
                    print(f"[{self.name}] bink: {target.stat().st_size} bytes exceeds source cap; "
                          f"retrying with {next(flag for flag in reduced if flag.lower().startswith('/d'))}",
                          flush=True)
                    flags = reduced
                    continue
                info = probe(target)
                vs, aud = video_stream(info), audio_stream(info)
                if vs.get("codec_name") != "binkvideo":
                    raise RuntimeError("candidate is not binkvideo")
                if (int(vs["width"]), int(vs["height"])) != (TARGET_WIDTH, TARGET_HEIGHT):
                    raise RuntimeError(f"candidate geometry mismatch: {vs['width']}x{vs['height']}")
                encoded = int(vs.get("nb_read_frames") or 0)
                if encoded == count:
                    break
                deficit = count - encoded
                if deficit < 0 or extra + deficit > 6:
                    raise RuntimeError(f"candidate frame count {encoded} != {count} and not recoverable (extra={extra})")
                extra += deficit
                print(f"[{self.name}] bink: candidate had {encoded} frames; retrying with {extra} cloned tail frame(s)", flush=True)
            else:
                raise RuntimeError("candidate frame count could not be matched after retries")
            if Fraction(vs["avg_frame_rate"]) != Fraction(stage_frames["fps"]) and \
                    abs(float(Fraction(vs["avg_frame_rate"])) - float(Fraction(stage_frames["fps"]))) > 0.01:
                raise RuntimeError("candidate fps mismatch")
            run(["ffmpeg", "-v", "error", "-i", str(target), "-f", "null", "-"], log=self.log)
            record = {"complete": True, "status": "bink", "file": str(target), "sha256": sha256(target),
                      "composite_sha256": composite.get("sha256"),
                      "size": target.stat().st_size, "size_budget": size_budget,
                      "count": count, "extra": extra,
                      "fps": vs["avg_frame_rate"], "audio_codec": aud.get("codec_name") if aud else None,
                      "audio_rate": int(aud["sample_rate"]) if aud else None,
                      "audio_channels": int(aud["channels"]) if aud else None,
                      "full_decode": "ffmpeg null decode passed"}
            codec = self.run_legacy_probe(target)
            if codec:
                record["legacy_codec_probe"] = codec
            record["content_box"] = self.measure_content_box(target, count, Fraction(stage_frames["fps"]))
        except Exception as exc:  # noqa: BLE001 - fallback must be recorded, not hidden
            target.unlink(missing_ok=True)
            target.with_suffix(target.suffix + ".process.json").unlink(missing_ok=True)
            record = {"complete": False, "status": "bink-failed", "error": str(exc),
                      "fallback": self.fallback(state, composite, stage_frames, count)}
        state.setdefault("stages", {})["bink"] = record
        self.save_state(state)
        print(f"[{self.name}] bink: {record['status']}", flush=True)
        return record

    def run_legacy_probe(self, bik: Path):
        if not self.args.probe or not self.args.codec_dll:
            return None
        if not Path(self.args.probe).is_file() or not Path(self.args.codec_dll).is_file():
            return None
        out = self.dir / "legacy-codec.json"
        try:
            run([str(self.args.probe), str(self.args.codec_dll), str(bik.resolve()), str(out.resolve())], log=self.log)
            return json.loads(out.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def measure_content_box(self, bik: Path, count: int, fps: Fraction, samples: int = 90):
        """Verify the configured 4:3 content window and any black letterbox bars.

        cropdetect locates the visible content inside the middle of the movie; the
        blackframe filter checks that any configured bars stay black.
        Together they show the image is neither stretched into the pillars nor cropped.
        """
        start = max(0.0, (count / 2) / float(fps))
        frames = str(min(samples, count))
        result = run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "info", "-ss", f"{start:.6f}",
                      "-i", str(bik.resolve()), "-vf", "cropdetect=limit=24:round=2:reset=0",
                      "-frames:v", frames, "-f", "null", "-"], log=self.log)
        boxes = Counter(re.findall(r"crop=(\d+:\d+:\d+:\d+)", result.stderr))
        record = {"samples": min(samples, count)}
        if boxes:
            box, votes = boxes.most_common(1)[0]
            width, height, x, y = (int(value) for value in box.split(":"))
            record.update({"crop": box, "votes": votes, "width": width, "height": height, "x": x, "y": y})
        else:
            record["error"] = "cropdetect produced no box"
        bar_checks = []
        bar_regions = []
        if PILLAR_X:
            bar_regions.extend((("left", f"crop={PILLAR_X}:{TARGET_HEIGHT}:0:0"),
                                ("right", f"crop={PILLAR_X}:{TARGET_HEIGHT}:{PILLAR_X + CONTENT_WIDTH}:0")))
        if PILLAR_Y:
            bar_regions.extend((("top", f"crop={TARGET_WIDTH}:{PILLAR_Y}:0:0"),
                                ("bottom", f"crop={TARGET_WIDTH}:{PILLAR_Y}:{PILLAR_Y + CONTENT_HEIGHT}:0")))
        for label, crop in bar_regions:
            check = run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "info", "-ss", f"{start:.6f}",
                         "-i", str(bik.resolve()),
                         "-vf", f"{crop},blackframe=amount=90:threshold=32",
                         "-frames:v", frames, "-f", "null", "-"], log=self.log)
            values = [float(value) for value in re.findall(r"pblack:(\d+(?:\.\d+)?)", check.stderr)]
            record[f"pillar_{label}_min_pblack"] = min(values) if values else 0.0
            bar_checks.append(record[f"pillar_{label}_min_pblack"])
        record["pillars_applicable"] = bool(bar_regions)
        record["pillars_black"] = min(bar_checks, default=100.0) >= 99.0
        if "x" in record:
            left, right = record["x"], record["x"] + record["width"]
            record["within_content_area"] = (record["x"] >= PILLAR_X
                                             and right <= PILLAR_X + CONTENT_WIDTH
                                             and record["y"] >= PILLAR_Y
                                             and record["y"] + record["height"] <= PILLAR_Y + CONTENT_HEIGHT)
        record["matches_target_content"] = bool(record.get("pillars_black")
                                                and record.get("within_content_area"))
        return record

    def fallback(self, state, composite, stage_frames, count):
        """Bink failed: keep the AVI (video+audio) and add an MP4 for review."""
        record = {"avi": composite["file"], "avi_sha256": composite["sha256"], "avi_size": composite["size"]}
        mp4 = self.dir / f"{self.name}-hd.mp4"
        try:
            run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(self.dir / "bink-input.avi"),
                 "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", str(mp4.resolve())], log=self.log)
            record.update({"mp4": str(mp4), "mp4_sha256": sha256(mp4), "mp4_size": mp4.stat().st_size})
            record["size_budget"] = validate_output_size(mp4.stat().st_size,
                int(stage_frames.get("source_size") or Path(stage_frames["source"]).stat().st_size))
        except Exception as exc:  # noqa: BLE001
            mp4.unlink(missing_ok=True)
            record["mp4_error"] = str(exc)
        return record

    def review_frames(self, state, stage_frames, bink):
        """Before/after canvas renders for the human comparison page.

        Both sides are half-size renders of the *whole* canvas, so any bars and the
        subtitle position are visible; the "before" side uses nearest-neighbour scaling
        to show the true source pixels instead of a flattering resample.
        """
        review = self.dir / "review"
        middle = stage_frames["count"] // 2
        source_frame = self.dir / "frames" / f"{middle + 1:06d}.png"
        after_source = None
        for candidate in (bink.get("file"), state.get("stages", {}).get("composite", {}).get("file")):
            if candidate and Path(candidate).is_file():
                after_source = Path(candidate)
                break
        record = {"index": middle}
        try:
            review.mkdir(parents=True, exist_ok=True)
            before, after = review / "antes.png", review / "depois.png"
            if source_frame.is_file():
                run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(source_frame.resolve()),
                     "-vf", f"scale={CONTENT_WIDTH}:{CONTENT_HEIGHT}:flags=neighbor,"
                            f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:{PILLAR_X}:{PILLAR_Y}:black,"
                            f"scale={TARGET_WIDTH // 2}:{TARGET_HEIGHT // 2}", "-frames:v", "1", str(before.resolve())],
                    log=self.log)
            if after_source is not None:
                run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(after_source.resolve()),
                     "-vf", f"select='eq(n,{middle})',scale={TARGET_WIDTH // 2}:{TARGET_HEIGHT // 2}",
                     "-frames:v", "1", "-update", "1", str(after.resolve())], log=self.log)
            record.update({"before": str(before), "after": str(after),
                           "after_source": str(after_source) if after_source else None})
        except Exception as exc:  # noqa: BLE001
            record["error"] = str(exc)
        state.setdefault("stages", {})["review"] = record
        self.save_state(state)
        return record

    def final_manifest(self, state, stage_frames, video, audio_src, captions, upscale, composite, bink):
        info = probe(video, count_frames=False)
        vs = video_stream(info)
        fps = Fraction(stage_frames["fps"])
        manifest = {
            "schema": 2,
            "name": self.name,
            "order": self.entry.get("order"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "video": str(video), "video_sha256": stage_frames["source_sha256"],
                "source_width": stage_frames["source_width"], "source_height": stage_frames["source_height"],
                "source_frames": stage_frames["source_frames"], "source_mtime_ns": video.stat().st_mtime_ns,
                "source_size": video.stat().st_size,
                "audio": str(audio_src) if audio_src else None,
            },
            "window": {"start_frame": stage_frames["start_frame"], "frames": stage_frames["count"],
                       "partial": stage_frames["partial"]},
            "fps": str(fps),
            "duration_seconds": stage_frames["count"] / float(fps),
            "source_duration_seconds": stage_frames["source_frames"] / float(fps),
            "target": {"canvas": [TARGET_WIDTH, TARGET_HEIGHT], "content": [CONTENT_WIDTH, CONTENT_HEIGHT],
                       "pillar_pixels": {"x": PILLAR_X, "y": PILLAR_Y}},
            "frames": stage_frames["count"],
            "container": {"kind": "bink" if bink.get("complete") else "fallback" if bink.get("status") == "bink-failed" else "pending"},
            "upscale": {"model": upscale.get("model"), "scale": upscale.get("scale"),
                        "output": [upscale.get("width"), upscale.get("height")],
                        "model_sha256": upscale.get("model_sha256")},
            "captions": {"input": str(captions) if captions else None,
                         "applied_after_upscale": bool(captions),
                         "metrics": composite.get("metrics"),
                         "blackout": bool(self.entry.get("blackout"))},
            "audio": {k: v for k, v in (state.get("stages", {}).get("audio", {}) or {}).items()},
            "intermediate": {"avi": state["stages"]["composite"].get("file"),
                             "avi_sha256": state["stages"]["composite"].get("sha256"),
                             "avi_size": state["stages"]["composite"].get("size"),
                             "cloned_tail_frames": state["stages"]["composite"].get("extra", 0)},
            "wav": {"file": str(self.dir / "audio.wav") if (self.dir / "audio.wav").is_file() else None,
                    "sha256": state.get("stages", {}).get("audio", {}).get("sha256")},
            "candidate": bink,
            "status": "complete" if bink.get("complete") else bink.get("status"),
            "runtimeVerified": False,
            "runtime_note": ("Offline pipeline and codec-level checks only. Bink/game playback, "
                             "skip/return, human listening and aspect-ratio verification in game are pending."),
            "blockers": [line for line in [
                None if bink.get("complete") else "Bink encoder did not produce a candidate",
                None if bink.get("legacy_codec_probe") else "Legacy x86 codec probe unavailable",
                "In-game playback (skip/return, aspect, audio) not exercised",
                "Human subtitles/audio review pending",
            ] if line],
        }
        (self.dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def process(self):
        video = self.resolve_video()
        audio_src = self.resolve_audio()
        captions = self.resolve_captions()
        if self.dir.exists() and any(self.dir.iterdir()) and not self.args.resume and not self.args.dry_run:
            raise ValueError(f"{self.dir} already has output; pass --resume to continue")
        print(f"[{self.name}] video={video}", flush=True)
        if self.args.dry_run:
            return {"name": self.name, "status": "dry-run", "video": str(video),
                    "audio": str(audio_src) if audio_src else None,
                    "captions": str(captions) if captions else None}
        self.dir.mkdir(parents=True, exist_ok=True)
        state = self.load_state() or {"name": self.name, "stages": {}}
        fingerprint = self.config_fingerprint()
        if state.get("fingerprint") and state["fingerprint"] != fingerprint and not self.args.resume:
            raise ValueError(f"{self.name}: configuration changed; use a fresh --out or a matching config")
        state["fingerprint"] = fingerprint
        info = probe(video)
        stage_frames = self.stage_frames(state, video, info)
        upscale = self.stage_upscale(state, stage_frames)
        audio = self.prepare_audio(state, audio_src)
        self.prepared_audio = audio
        self.captions_path = captions
        composite = self.stage_composite(state, stage_frames, audio, captions)
        bink = self.stage_bink(state, composite, stage_frames)
        if not self.args.keep_intermediate:
            avi = self.dir / "bink-input.avi"
            if avi.is_file():
                avi.unlink()
            if bink.get("status") == "bink-failed":
                fallback = bink.get("fallback") or {}
                fallback["avi_retained"] = False
                fallback.pop("avi", None)
                fallback.pop("avi_sha256", None)
                state.setdefault("stages", {})["bink"] = bink
                self.save_state(state)
        self.review_frames(state, stage_frames, bink)
        manifest = self.final_manifest(state, stage_frames, video, audio_src, captions,
                                       upscale, state["stages"]["composite"], bink)
        if not self.args.keep_frames:
            shutil.rmtree(self.dir / "frames-ai", ignore_errors=True)
            shutil.rmtree(self.dir / "frames", ignore_errors=True)
        return manifest


def load_plan(args):
    if args.batch:
        data = json.loads(Path(args.batch).read_text(encoding="utf-8-sig"))
        return sorted(data["videos"], key=lambda item: item.get("order", 999))
    if args.video:
        for entry in DEFAULT_PLAN:
            if entry["name"] == args.video:
                return [entry]
        return [{"name": args.video, "order": 0, "captions": str(args.captions) if args.captions else None}]
    return sorted(DEFAULT_PLAN, key=lambda item: item.get("order", 999))


def publish(args, results, out_root: Path, validate_dir: Path, plan_names=None):
    validate_dir.mkdir(parents=True, exist_ok=True)
    review = validate_dir / "quadros"
    review.mkdir(parents=True, exist_ok=True)
    videos = []
    for result in results:
        if result.get("status") == "dry-run":
            continue
        name = result["name"]
        candidate = result.get("candidate", {})
        source_size = int(result.get("input", {}).get("source_size") or 0)
        candidate_size = int(candidate.get("size") or 0)
        if candidate.get("complete"):
            budget = validate_output_size(candidate_size, source_size)
        else:
            budget = candidate.get("fallback", {}).get("size_budget")
        folder = out_root / name
        row = {
            "name": name,
            "input": result["input"]["video"],
            "input_sha256": result["input"]["video_sha256"],
            "source_resolution": f"{result['input']['source_width']}x{result['input']['source_height']}",
            "target_resolution": f"{result['target']['canvas'][0]}x{result['target']['canvas'][1]}",
            "content_area": "{}x{}".format(*result["target"]["content"]),
            "frames": result["frames"],
            "source_frames": result["input"]["source_frames"],
            "fps": result["fps"],
            "duration_seconds": round(result["duration_seconds"], 3),
            "source_duration_seconds": round(result["source_duration_seconds"], 3),
            "audio": result.get("audio"),
            "captions_applied": result["captions"]["applied_after_upscale"],
            "candidate": result["candidate"].get("file"),
            "candidate_sha256": result["candidate"].get("sha256"),
            "candidate_size": result["candidate"].get("size"),
            "source_size": source_size,
            "size_budget": budget,
            "pipeline_status": result["status"],
            "status": "bink" if result["candidate"].get("complete") else result["candidate"].get("status"),
            "legacy_codec_probe": result["candidate"].get("legacy_codec_probe"),
            "content_box": result["candidate"].get("content_box"),
            "runtimeVerified": False,
            "blockers": list(dict.fromkeys(result["blockers"] + (
                [] if (result["candidate"].get("content_box") or {}).get("matches_target_content")
                else [f"O recorte medido do conteúdo não confere com {CONTENT_WIDTH}x{CONTENT_HEIGHT} em "
                      f"x={PILLAR_X}, y={PILLAR_Y}"]))),
        }
        for kind, source in (("antes", folder / "review" / "antes.png"), ("depois", folder / "review" / "depois.png")):
            if source.is_file():
                dest = review / f"{name}-{kind}.png"
                shutil.copy2(source, dest)
                row[f"frame_{kind}"] = f"quadros/{dest.name}"
        videos.append(row)
    done = {row["name"] for row in videos}
    pending = [name for name in (plan_names or []) if name not in done]
    report = {
        "schema": 1,
        "milestone": "P4",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "decision": "content/video-review.json",
            "model": "Real-ESRGAN realesrgan-x4plus scale 4",
            "geometry": (f"4:3 content {CONTENT_WIDTH}x{CONTENT_HEIGHT} centered in "
                         f"{TARGET_WIDTH}x{TARGET_HEIGHT}; bars x={PILLAR_X}, y={PILLAR_Y}"),
            "subtitles": f"applied after upscale on the {TARGET_WIDTH}x{TARGET_HEIGHT} canvas",
            "audio": "PT-BR track preserved from the timed mix WAV, else from the installed PT-BR Bink",
            "video_source": "pristine English original Bink (no burned-in subtitles) when available",
        },
        "runtimeVerified": False,
        "runtimeNote": ("No game run was performed. Evidence is limited to offline decode/encode, "
                        "frame accounting, audio format, content-box measurement and the legacy x86 Bink codec probe."),
        "batchDirectory": str(out_root),
        "totals": {
            "planned": len(plan_names) if plan_names else len(videos),
            "videos": len(videos),
            "bink": sum(1 for row in videos if row["status"] == "bink"),
            "failed": sum(1 for row in videos if row["status"] != "bink"),
        },
        "pending": pending,
        "videos": videos,
    }
    (validate_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(validate_dir, report)
    write_html(validate_dir, videos)
    return report


def write_readme(validate_dir: Path, report: dict):
    ok = report["totals"]["bink"]
    lines = [
        f"# Vídeos processados ({TARGET_WIDTH}×{TARGET_HEIGHT}) — lote offline",
        "",
        "Artefato de **revisão offline** gerado por `tools/video_hd_batch.py`. Nenhum arquivo da instalação "
        "Steam, save ou cópia do jogo foi alterado; nada foi aberto no jogo.",
        "",
        "## Método",
        "",
        "- Quadros decodificados do BIK **original** (sem legendas embutidas); áudio PT-BR preservado do mix "
        "temporal ou do BIK PT-BR instalado.",
        "- Ampliação por quadro com **Real-ESRGAN `realesrgan-x4plus`**, escala 4.",
        f"- Conteúdo 4:3 em **{CONTENT_WIDTH}×{CONTENT_HEIGHT}**, centralizado em **{TARGET_WIDTH}×{TARGET_HEIGHT}** "
        f"(barras x={PILLAR_X}, y={PILLAR_Y}).",
        "- **Legendas aplicadas depois do upscale**, em ASS regerado para o canvas final.",
        "- Reencodificação Bink legado pelo RADTools; se falhar, o pipeline tenta manter um MP4 compacto. "
        "AVI bruto e sequências PNG temporárias são removidos por padrão.",
        f"- Teto rígido: cada arquivo final comprimido deve ocupar no máximo {MAX_OUTPUT_SIZE_RATIO:g}× o BIK original. "
        "Se exceder, o pipeline reduz a taxa de dados RAD em tentativas limitadas e valida novamente.",
        "",
        "## Estado",
        "",
        f"- Vídeos concluídos como Bink HD: **{ok}/{report['totals'].get('planned', len(report['videos']))}**.",
        f"- Processados nesta amostra: **{report['totals']['videos']}**; falhas: **{report['totals']['failed']}**.",
        "- `runtimeVerified: false` — playback no jogo, skip/return, proporção em tela e escuta não foram testados.",
        "- Este diretório é **artefato de revisão offline**; não é um pacote instalável nem foi validado no jogo.",
        "",
        "## Por vídeo",
        "",
        "| vídeo | origem | alvo | quadros | fps | duração | áudio | status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["videos"]:
        audio = row.get("audio") or {}
        audio_note = "—" if not audio.get("present") else f"{audio.get('sample_rate')} Hz {audio.get('channels')}ch"
        lines.append("| {name} | {src} | {tgt} | {frames} | {fps} | {dur:.2f}s | {audio} | {status} |".format(
            name=row["name"], src=row["source_resolution"], tgt=row["target_resolution"],
            frames=row["frames"], fps=row["fps"], dur=row["duration_seconds"], audio=audio_note,
            status=row["status"]))
    if report.get("pending"):
        lines += ["", "## Ainda não processados", ""]
        lines += [f"- {name}" for name in report["pending"]]
    lines += ["", "## Bloqueios registrados", ""]
    seen = set()
    for row in report["videos"]:
        for blocker in row["blockers"]:
            if blocker not in seen:
                seen.add(blocker)
                lines.append(f"- {blocker}")
    lines += ["", "## Comparação", "", "Abra [`comparacao.html`](comparacao.html) para ver um quadro antes/depois "
              "por vídeo. A prévia é recortada para caber na página e não substitui a inspeção do Bink final.", ""]
    (validate_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_html(validate_dir: Path, videos):
    cards = []
    for row in videos:
        before = row.get("frame_antes", "")
        after = row.get("frame_depois", "")
        audio = row.get("audio") or {}
        audio_note = "sem áudio" if not audio.get("present") else f"{audio.get('sample_rate')} Hz, {audio.get('channels')} canais"
        budget = row.get("size_budget") or {}
        if budget:
            size_line = (f"Tamanho final: {budget.get('output_size', 0):,} bytes; "
                         f"fonte: {budget.get('source_size', 0):,} bytes; "
                         f"limite {MAX_OUTPUT_SIZE_RATIO:g}×: {budget.get('max_size', 0):,} bytes "
                         f"({budget.get('actual_ratio', 0):.2f}×).")
        else:
            size_line = f"Tamanho final: sem candidato aprovado dentro do limite de {MAX_OUTPUT_SIZE_RATIO:g}×."
        cards.append(f"""<section>
  <h2>{html.escape(row['name'])} <small>{"Bink HD" if row['status'] == 'bink' else html.escape(row['status'])}</small></h2>
  <p>{html.escape(row['source_resolution'])} → {html.escape(row['target_resolution'])} ·
     {row['frames']} quadros · {html.escape(row['fps'])} fps ·
     {row['duration_seconds']:.2f}s · áudio: {html.escape(audio_note)}</p>
  <p>{html.escape(size_line)}</p>
  <div class="pair">
    <figure><img src="{html.escape(before)}" alt="antes"><figcaption>Antes — original</figcaption></figure>
    <figure><img src="{html.escape(after)}" alt="depois"><figcaption>Depois — Real-ESRGAN x4 + canvas {TARGET_WIDTH}×{TARGET_HEIGHT}</figcaption></figure>
  </div>
  <p class="hash">candidato: {html.escape(str(row.get('candidate_sha256') or '—'))}</p>
</section>""")
    document = f"""<!doctype html>
<html lang="pt-BR"><meta charset="utf-8"><title>Vídeos HD — Soul Reaver PT-BR</title>
<style>
 body{{font:16px system-ui;background:#101014;color:#e8e8ee;margin:24px;max-width:1200px}}
 h1{{font-size:24px}} h2{{font-size:18px;margin-bottom:4px}} small{{font-weight:400;color:#9b9ba6}}
 section{{border-top:1px solid #2a2a33;padding:18px 0}}
 .pair{{display:flex;gap:16px;flex-wrap:wrap}} figure{{margin:0;flex:1;min-width:320px}}
 img{{width:100%;background:#000;border:1px solid #2a2a33}} figcaption{{color:#b9b9c4;padding-top:6px;font-size:14px}}
 .hash{{color:#7d7d88;font-size:12px;word-break:break-all}}
 .warn{{background:#2a1a1a;border:1px solid #6a3030;padding:12px;border-radius:6px}}
</style>
<h1>Vídeos HD — comparação antes/depois (offline)</h1>
<p class="warn"><strong>Fora do jogo:</strong> esta página prova apenas o processamento offline dos quadros.
Playback no jogo, skip/return, proporção em tela e escuta humana permanecem não verificados
(<code>runtimeVerified: false</code>).</p>
{''.join(cards) if cards else '<p>Nenhum vídeo processado ainda.</p>'}
</html>"""
    (validate_dir / "comparacao.html").write_text(document, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="isolated batch output root")
    parser.add_argument("--game", type=Path,
                        default=Path(r"D:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver"),
                        help="read-only game directory (PT-BR Bink audio source)")
    parser.add_argument("--sources", type=Path, nargs="*", default=None,
                        help="directories with pristine English originals; searched in order")
    parser.add_argument("--realesrgan", type=Path,
                        default=REPO / "staging/realesrgan-official-v0.2.5.0/realesrgan-ncnn-vulkan.exe")
    parser.add_argument("--models", type=Path, default=REPO / "staging/realesrgan-official-v0.2.5.0/models")
    parser.add_argument("--model", default="realesrgan-x4plus")
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--rad", type=Path, default=REPO / "staging/radtools/bin/radvideo64.exe")
    parser.add_argument("--probe", type=Path, default=REPO / "staging/fmv-hd-runtime-v1/codec-probe/probe.exe")
    parser.add_argument("--codec-dll", type=Path,
                        default=REPO / "staging/fmv-hd-runtime-v1/codec-probe/binkw32.dll")
    parser.add_argument("--bink-flags", default="/V100 /D900000 /U6 /L4")
    parser.add_argument("--bink-timeout", type=float, default=7200)
    parser.add_argument("--target-width", type=int, default=1024, help="output canvas width; default 1024")
    parser.add_argument("--target-height", type=int, default=768, help="output canvas height; default 768")
    parser.add_argument("--batch", type=Path, help="JSON plan with a videos array")
    parser.add_argument("--video", help="process a single video by name")
    parser.add_argument("--captions", type=Path, help="captions override for --video")
    parser.add_argument("--start", type=float, default=0.0, help="window start in seconds (with --duration)")
    parser.add_argument("--duration", type=float, help="window duration in seconds; makes the clip partial")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keep-frames", action="store_true",
                        help="keep extracted and AI-upscaled PNG sequences; default removes them after processing")
    parser.add_argument("--keep-intermediate", action="store_true")
    parser.add_argument("--raw-ass", action="store_true", help="copy ASS unchanged instead of rescaling to canvas")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish", type=Path, help="write report.json/README.md/comparacao.html here")
    parser.add_argument("--publish-only", action="store_true",
                        help="publish from the per-video manifests already on disk (no processing)")
    parser.add_argument("--measure-only", action="store_true",
                        help="re-run geometry/codec measurements against existing candidates")
    args = parser.parse_args()

    try:
        set_output_geometry(args.target_width, args.target_height)
    except ValueError as exc:
        parser.error(str(exc))

    if args.sources is None:
        local = Path.home() / "AppData/Local/SoulReaverPTBR/backups/steam-classic-en"
        args.sources = [REPO / "staging/backups/steam-classic-en", local]
    args.sources = [Path(p) for p in args.sources]

    plan_names = [entry["name"] for entry in sorted(DEFAULT_PLAN, key=lambda item: item.get("order", 999))]
    if args.measure_only:
        for path in sorted(args.out.glob("*/manifest.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            candidate = manifest.get("candidate", {}).get("file")
            if not candidate or not Path(candidate).is_file():
                print(f"{manifest['name']}: no candidate to measure")
                continue
            job = VideoJob(args, {"name": manifest["name"]})
            job.dir = args.out / manifest["name"]
            job.log = job.dir / "run.log"
            manifest["candidate"]["content_box"] = job.measure_content_box(
                Path(candidate), manifest["frames"], Fraction(manifest["fps"]))
            if not manifest["candidate"].get("legacy_codec_probe"):
                manifest["candidate"]["legacy_codec_probe"] = job.run_legacy_probe(Path(candidate))
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            box = manifest["candidate"]["content_box"]
            print(f"{manifest['name']}: box={box.get('crop')} pillars_black={box.get('pillars_black')} "
                  f"within={box.get('within_content_area')}")
        return
    if args.publish_only:
        if not args.publish:
            raise SystemExit("--publish-only requires --publish")
        results = [json.loads(path.read_text(encoding="utf-8"))
                   for path in sorted(args.out.glob("*/manifest.json"))]
        publish(args, results, args.out, args.publish, plan_names)
        print(f"published {len(results)} manifest(s) to {args.publish}")
        return

    entries = load_plan(args)
    results = []
    failures = []
    for entry in entries:
        job = VideoJob(args, entry)
        try:
            results.append(job.process())
        except Exception as exc:  # noqa: BLE001 - report and continue the batch
            failures.append({"name": entry["name"], "error": str(exc)})
            print(f"[{entry['name']}] FAILED: {exc}", flush=True)
            if len(entries) == 1:
                raise
    summary = {"schema": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
               "runtimeVerified": False, "failures": failures,
               "videos": [r for r in results if r.get("status") != "dry-run"]}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "batch.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        if result.get("status") == "dry-run":
            print(json.dumps(result, ensure_ascii=False))
    if args.publish:
        publish(args, [r for r in results if r.get("status") != "dry-run"], args.out, args.publish, plan_names)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
