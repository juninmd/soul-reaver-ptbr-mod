"""Offline 1440p FMV prototype; source media is read-only.

Audio defaults to source-time (--audio-origin source); ASS defaults to clip-time
(--ass-origin clip), so overlapping events are clipped and rebased to t=0.
"""
import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
from fractions import Fraction
from pathlib import Path
from video_hd_batch import validate_output_size

def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)

def probe(path, count_frames=True):
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command.append("-count_frames")
    return json.loads(subprocess.check_output(command + ["-show_streams", "-show_format", "-of", "json", str(path)], text=True))

def validate_encoded_probe(result, expected, fps, duration):
    rv=next((s for s in result.get("streams",[]) if s.get("codec_type")=="video"),None)
    if not rv or int(rv.get("nb_read_frames",-1))!=expected or (int(rv.get("width",0)),int(rv.get("height",0)))!=(2560,1440) or Fraction(rv["avg_frame_rate"])!=fps:
        raise RuntimeError("encoded output video validation failed")
    audios=[s for s in result.get("streams",[]) if s.get("codec_type")=="audio"]
    if not audios or int(audios[0].get("sample_rate",0))!=44100 or int(audios[0].get("channels",0))!=2:
        raise RuntimeError("encoded output audio validation failed")
    if abs(float(result.get("format",{}).get("duration",0))-float(duration))>2.0/float(fps):
        raise RuntimeError("encoded output duration validation failed")
    return rv,audios[0]

def validate_source_cadence(path, start, expected, fps):
    # Decode from zero: interval seeking may land on an earlier keyframe. JSON
    # avoids CSV side-data fields appended to H.264 frame records.
    period=1/fps
    interval=f"%+{float(start + expected * period + period)}"
    raw=subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-read_intervals",interval,"-show_entries","frame=best_effort_timestamp_time:stream=time_base","-of","json",str(path)],text=True)
    data=json.loads(raw)
    stamps=[Fraction(frame["best_effort_timestamp_time"]) for frame in data.get("frames",[]) if frame.get("best_effort_timestamp_time") not in (None,"N/A")]
    tick=Fraction(data["streams"][0]["time_base"])
    tolerance=max(tick, Fraction(1, 1000000))
    first=ceil_fraction(start * fps)
    if len(stamps) < first + expected:
        raise ValueError("source timestamp sequence is shorter than the selected window")
    # Every preceding timestamp matters when selecting by frame number.
    if any(abs(stamp - n * period)>tolerance for n,stamp in enumerate(stamps[:first+expected])):
        raise ValueError("source timestamps do not follow constant frame rate from zero")
    return stamps[first:first+expected]

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def ceil_fraction(value):
    return -(-value.numerator // value.denominator)

def png_dimensions(path):
    with Path(path).open("rb") as f:
        header=f.read(24)
    if len(header)!=24 or header[:8]!=b"\x89PNG\r\n\x1a\n" or header[12:16]!=b"IHDR":
        raise ValueError(f"invalid PNG frame: {path}")
    return struct.unpack(">II",header[16:24])

def expected_ai_dimensions(width,height):
    return int(width)*4,int(height)*4

def validate(args):
    for name, path in (("source", args.source), ("audio", args.audio)):
        if not path.is_file(): raise ValueError(f"{name} file not found: {path}")
    if args.ass and not args.ass.is_file(): raise ValueError(f"ASS file not found: {args.ass}")
    if args.realesrgan and (not args.realesrgan.is_file()): raise ValueError(f"Real-ESRGAN executable not found: {args.realesrgan}")
    if not math.isfinite(args.start) or not math.isfinite(args.duration) or args.start < 0 or args.duration <= 0: raise ValueError("start and duration must be finite; start >= 0 and duration > 0")
    if args.out.exists(): raise ValueError(f"output already exists; choose a fresh folder: {args.out}")
    info=probe(args.source, count_frames=False); videos=[s for s in info["streams"] if s.get("codec_type")=="video"]
    if not videos: raise ValueError("source has no video stream")
    fps=Fraction(videos[0]["avg_frame_rate"])
    if fps <= 0: raise ValueError("source video has invalid frame rate")
    if int(videos[0]["width"]) * 3 != int(videos[0]["height"]) * 4:
        raise ValueError("This prototype requires a 4:3 source; refusing to stretch another aspect ratio")
    audio_info=probe(args.audio, count_frames=False); audio_streams=[s for s in audio_info["streams"] if s.get("codec_type")=="audio"]
    if not audio_streams: raise ValueError("audio input has no audio stream")
    start_frame=ceil_fraction(Fraction(str(args.start))*fps)
    needed=Fraction(start_frame+round(Fraction(str(args.duration))*fps),1)/fps
    available=Fraction(str(audio_info.get("format",{}).get("duration",0)))
    if args.audio_origin=="source" and available < needed: raise ValueError("source-time audio does not cover selected video window")
    if args.audio_origin=="clip" and available < Fraction(str(args.duration)): raise ValueError("clip-time audio is shorter than requested duration")
    return info,videos[0],fps

def ass_time(value):
    h,m,sec=value.split(":"); whole,cs=sec.split("."); return int(h)*360000+int(m)*6000+int(whole)*100+int(cs)
def ass_fmt(t):
    t=max(0,t); h,t=divmod(t,360000); m,t=divmod(t,6000); s,cs=divmod(t,100); return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
def rebase_ass(source,dest,start,duration):
    lo=round(start*100); hi=round((start+duration)*100); lines=Path(source).read_text(encoding="utf-8-sig").splitlines(); out=[]
    for line in lines:
        if line.startswith("Dialogue:"):
            fields=line.split(",",9)
            if len(fields)<10: raise ValueError("malformed ASS Dialogue record")
            begin,end=ass_time(fields[1]),ass_time(fields[2]); begin=max(begin,lo); end=min(end,hi)
            if end <= begin: continue
            fields[1]=ass_fmt(begin-lo); fields[2]=ass_fmt(end-lo); line=",".join(fields)
        out.append(line)
    Path(dest).write_text("\n".join(out)+"\n",encoding="utf-8")

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--source",type=Path,required=True); ap.add_argument("--audio",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); ap.add_argument("--ass",type=Path); ap.add_argument("--ass-origin",choices=("source","clip"),default="clip",help="subtitle timebase; source events are clipped/rebased when source selected"); ap.add_argument("--audio-origin",choices=("source","clip"),default="source",help="source seeks audio by selected source timestamp; clip starts at zero"); ap.add_argument("--start",type=float,default=20.0); ap.add_argument("--duration",type=float,default=7.0); ap.add_argument("--realesrgan",type=Path); args=ap.parse_args()
    info,vs,fps=validate(args); expected=round(Fraction(str(args.duration))*fps); start_frame=ceil_fraction(Fraction(str(args.start))*fps); actual_start=Fraction(start_frame,1)/fps; duration=Fraction(expected,1)/fps
    if expected <= 0: raise ValueError("duration selects zero frames")
    validate_source_cadence(args.source,actual_start,expected,fps)
    # Do not create output until every user input and source stream is validated.
    args.out.mkdir(parents=True); frames=args.out/"frames"; ai_frames=args.out/"frames-ai"; frames.mkdir();
    run(["ffmpeg","-y","-nostdin","-v","error","-i",str(args.source),"-vf",f"select='between(n,{start_frame},{start_frame+expected-1})',format=rgb24","-vsync","0",str(frames/"%06d.png")])
    extracted=sorted(frames.glob("*.png"))
    if len(extracted)!=expected: raise RuntimeError(f"exact extraction failed: expected {expected}, got {len(extracted)}")
    ass_file=args.ass
    if args.ass:
        ass_file=args.out/"clip.ass"
        if args.ass_origin=="source":
            rebase_ass(args.ass,ass_file,float(actual_start),float(duration))
        else:
            shutil.copy2(args.ass,ass_file)
    def encode(inp,dest):
        pngs=sorted(inp.glob("*.png"));
        if len(pngs)!=expected: raise RuntimeError(f"encode input frame count mismatch: expected {expected}, got {len(pngs)}")
        if [p.name for p in pngs] != [f"{i:06d}.png" for i in range(1,expected+1)]: raise RuntimeError("frame sequence is incomplete or has stale/non-sequential images")
        expected_dims=expected_ai_dimensions(vs["width"],vs["height"]) if inp==ai_frames else (int(vs["width"]),int(vs["height"]))
        for image in pngs:
            dims=png_dimensions(image)
            if dims!=expected_dims: raise RuntimeError(f"frame dimensions mismatch in {image.name}: expected {expected_dims}, got {dims}")
        vf="scale=1920:1440:flags=lanczos,pad=2560:1440:320:0:black"
        if ass_file:
            apath=str(ass_file.resolve()).replace("\\","/").replace(":","\\:"); vf+=",subtitles='"+apath+"'"
        audio_seek=actual_start if args.audio_origin=="source" else Fraction(0,1)
        cmd=["ffmpeg","-y","-nostdin","-v","error","-framerate",str(fps),"-i",str(inp/"%06d.png")]
        if audio_seek: cmd += ["-ss",str(float(audio_seek))]
        cmd += ["-i",str(args.audio),"-vf",vf+",format=yuv420p","-map","0:v:0","-map","1:a:0","-frames:v",str(expected),"-fps_mode","cfr","-r",str(fps),"-c:v","libx264","-crf","18","-preset","slow","-pix_fmt","yuv420p","-video_track_timescale","5000000","-c:a","aac","-ar","44100","-ac","2","-b:a","192k","-t",str(float(duration)),str(dest)]
        run(cmd); result=probe(dest)
        try: validate_encoded_probe(result,expected,fps,duration)
        except RuntimeError as exc: raise RuntimeError(f"{exc}: {dest}") from exc
        try:
            validate_output_size(dest.stat().st_size, args.source.stat().st_size)
        except ValueError:
            dest.unlink(missing_ok=True)
            raise
        return result
    baseline=args.out/"intro-1440p-lanczos.mp4"; baseprobe=encode(frames,baseline); ai_status="not-run"; ai=None; aiprobe=None
    if args.realesrgan:
        ai_frames.mkdir(); realesrgan=args.realesrgan.resolve(); run([str(realesrgan),"-m","models","-i",str(frames.resolve()),"-o",str(ai_frames.resolve()),"-n","realesrgan-x4plus","-s","4","-f","png"],cwd=realesrgan.parent)
        outputs=sorted(ai_frames.glob("*.png"))
        if len(outputs)!=expected: raise RuntimeError(f"Real-ESRGAN frame count mismatch: expected {expected}, got {len(outputs)}")
        ai=args.out/"intro-1440p-realesrgan.mp4"; aiprobe=encode(ai_frames,ai); ai_status="complete"
    report={"poc":"video-1440p-v2","source":str(args.source),"source_sha256":sha(args.source),"audio":str(args.audio),"audio_sha256":sha(args.audio),"window":{"requested_start":args.start,"selected_source_start":float(actual_start),"duration":float(duration),"frames":expected,"fps":str(fps),"audio_origin":args.audio_origin,"ass_origin":args.ass_origin},"source_video":{"width":vs["width"],"height":vs["height"],"fps":str(fps),"frames":vs.get("nb_read_frames")},"baseline":{"file":str(baseline),"sha256":sha(baseline),"probe":baseprobe},"realesrgan":{"status":ai_status,"file":str(ai) if ai else None,"sha256":sha(ai) if ai else None,"probe":aiprobe},"runtime_claim":"offline file decode/ffprobe validation only; Bink/game playback unverified"}
    (args.out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__": main()
