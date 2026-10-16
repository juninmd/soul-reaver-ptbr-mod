"""Render local Bink review candidates with mixed PT audio and visible subtitles."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import textwrap

from build_fmv_audio import build
from run_rad import run
from video_hd_batch import validate_output_size


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
                             "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def ass_time(seconds):
    count = round(seconds * 100)
    return f"{count // 360000}:{count // 6000 % 60:02}:{count // 100 % 60:02}.{count % 100:02}"


def render(plan, takes, source, separated, hashes, output, rad):
    if output.exists() or output.resolve().is_relative_to(source.resolve()):
        raise ValueError("Choose a new output directory outside the source game")
    data = json.loads(plan.read_text(encoding="utf-8-sig"))
    originals = json.loads(hashes.read_text(encoding="utf-8-sig"))
    movies = sorted({v["fmv"] for v in data["voices"]})
    if not movies or not set(movies) <= {"intro", "verse", "chrono3", "chrono5", "chrono7", "chrono9", "chrono11", "chrono13"}:
        raise ValueError("Unexpected movie name")
    for name in movies:
        movie = source / f"{name}.bik"
        if hashlib.sha256(movie.read_bytes()).hexdigest() != originals[movie.name]:
            raise ValueError(f"Source movie changed: {name}")
    output.mkdir(parents=True)
    reports = []
    for name in movies:
        movie = source / f"{name}.bik"
        directory = output / name
        report = build(plan, takes, separated / f"{name}-stereo.wav",
                       separated / name / "background.wav", directory, name)
        info = probe(movie)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        if (video["width"], video["height"]) not in {(640, 480), (320, 240)}:
            raise ValueError("Unsupported source dimensions for the subtitle layout")
        header = """[Script Info]
ScriptType: v4.00+
PlayResX: 640
PlayResY: 480
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,22,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,1.5,1,2,18,18,14,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        if video["width"] == 320:
            header = header.replace("PlayResX: 640", "PlayResX: 320").replace("PlayResY: 480", "PlayResY: 240")
            header = header.replace("Arial,22,", "Arial,11,").replace(",1,1.5,1,2,18,18,14,1", ",1,0.75,0.5,2,9,9,7,1")
        if name == "verse":
            # The original frames contain English cards on solid black. Replace
            # those cards as well as the narration; do not stack subtitles on them.
            header = header.replace("Arial,11,", "Georgia,15,").replace(",1,0.75,0.5,2,9,9,7,1", ",1,0,0,5,12,12,12,1")
        for row in report["lines"]:
            text = row["text_ptbr"]
            if any(c in text for c in "{}\\\n\r"):
                raise ValueError("Subtitle control syntax is not allowed in dialogue")
            text = r"\N".join(textwrap.wrap(text, width=32 if name == "verse" else 52))
            end = 18.0 if name == "verse" else row['start'] + row['duration']
            effect = r"{\fad(0,700)}" if name == "verse" else ""
            header += f"Dialogue: 0,{ass_time(row['start'])},{ass_time(end)},Default,,0,0,0,,{effect}{text}\n"
        if name == "verse":
            header += r"Dialogue: 0,0:00:22.00,0:00:30.40,Default,,0,0,0,,{\fs20\fad(500,700)}Continua..." + "\n"
        (directory / "captions.ass").write_text(header, encoding="utf-8")
        raw = directory / "subtitled.avi"
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(movie.resolve()),
                   "-i", str((directory / f"{name}.wav").resolve()), "-map", "0:v:0", "-map", "1:a:0",
                   "-vf", ("drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill," if name == "verse" else "") + "ass=captions.ass", "-c:v", "rawvideo", "-pix_fmt", "bgr24", "-c:a", "pcm_s16le",
                   "-t", info["format"]["duration"], str(raw.resolve())]
        subprocess.run(command, cwd=directory, check=True)
        candidate = directory / f"{name}-ptbr.bik"
        run(rad, "Binkc", [raw], candidate)
        try:
            size_budget = validate_output_size(candidate.stat().st_size, movie.stat().st_size)
        except ValueError:
            candidate.unlink(missing_ok=True)
            raise
        final = probe(candidate)
        result_video = next(s for s in final["streams"] if s["codec_type"] == "video")
        result_audio = next(s for s in final["streams"] if s["codec_type"] == "audio")
        if result_video["codec_name"] != "binkvideo" or result_audio["codec_name"] != "binkaudio_dct":
            raise ValueError("Candidate uses an unexpected Bink codec")
        if any(result_video[k] != video[k] for k in ("width", "height", "nb_read_frames")) or Fraction(result_video["avg_frame_rate"]) != Fraction(video["avg_frame_rate"]):
            raise ValueError("Candidate changed video dimensions, frame count or frame rate")
        if result_audio.get("sample_rate") != "44100" or result_audio.get("channels") != 2:
            raise ValueError("Candidate changed the expected stereo 44100 Hz audio format")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(candidate), "-f", "null", "-"],
                       check=True, stdout=subprocess.DEVNULL)
        report.update(candidate=str(candidate), candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                      candidate_size=candidate.stat().st_size, size_budget=size_budget,
                      decode_complete=True, human_listening_approved=False, game_playback_verified=False)
        (directory / "candidate-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        reports.append(report)
    (output / "candidates.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "takes", "source", "separated", "hashes", "output", "rad"):
        parser.add_argument("--" + name, type=Path, required=True)
    render(**vars(parser.parse_args()))
