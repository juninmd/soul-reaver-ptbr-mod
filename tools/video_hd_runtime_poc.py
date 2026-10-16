"""Create and validate a legacy Bink candidate from an offline clip."""
import argparse
import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from video_hd_batch import validate_output_size

def probe(path):
    return json.loads(subprocess.check_output(["ffprobe","-v","error","-count_frames","-show_streams","-show_format","-of","json",str(path)],text=True))
def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def require_video(data,label,expected_frames=180):
    streams=data.get("streams",[]); vs=[s for s in streams if s.get("codec_type")=="video"]; aud=[s for s in streams if s.get("codec_type")=="audio"]
    if len(vs)!=1 or not aud: raise ValueError(f"{label} must contain one video and audio stream")
    v=vs[0]; fps=Fraction(v["avg_frame_rate"]); frames=int(v.get("nb_read_frames",-1))
    if (int(v["width"]),int(v["height"]),fps,frames)!=(2560,1440,Fraction(5000000,166833),expected_frames): raise ValueError(f"{label} cadence/dimensions/frame count mismatch")
    expected_duration=Fraction(expected_frames,1)/fps
    if abs(float(data.get("format",{}).get("duration",0))-float(expected_duration))>2.0/float(fps): raise ValueError(f"{label} duration mismatch")
    a=aud[0]
    if int(a.get("sample_rate",0))!=44100 or int(a.get("channels",0))!=2: raise ValueError(f"{label} audio must be 44100 Hz stereo")
    if abs(float(a.get("duration",data.get("format",{}).get("duration",0)))-float(expected_duration))>0.15: raise ValueError(f"{label} audio duration mismatch")
    if label=="Bink candidate" and a.get("codec_name") not in ("binkaudio_dct","binkaudio_rdft"):
        raise ValueError("Bink candidate audio codec is not Bink audio")
    if label=="Bink candidate" and v.get("codec_name") != "binkvideo":
        raise ValueError("Bink candidate video codec is not legacy Bink video")
    return v,a
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--input',type=Path,required=True); p.add_argument('--rad',type=Path,required=True); p.add_argument('--out',type=Path,required=True); a=p.parse_args()
    if not a.input.is_file() or not a.rad.is_file(): raise ValueError("input clip and RAD executable must exist")
    if a.out.exists(): raise ValueError("output directory exists; choose a fresh isolated staging folder")
    src=probe(a.input); v,audio=require_video(src,"input clip"); a.out.mkdir(parents=True)
    avi=a.out/'intro-6s-2560x1440-bgr24.avi'; bik=a.out/'intro-6s-2560x1440.bik'
    subprocess.run(['ffmpeg','-y','-nostdin','-v','error','-i',str(a.input),'-map','0:v:0','-map','0:a:0','-c:v','rawvideo','-pix_fmt','bgr24','-c:a','pcm_s16le','-ar','44100','-ac','2','-frames:v','180',str(avi)],check=True)
    avi_probe=probe(avi); av,av_audio=require_video(avi_probe,"intermediate AVI")
    if av_audio.get("codec_name")!="pcm_s16le" or int(av_audio.get("sample_rate",0))!=44100 or int(av_audio.get("channels",0))!=2: raise ValueError("AVI audio format mismatch")
    subprocess.run([sys.executable,str(Path(__file__).with_name('run_rad.py')),'Binkc','--exe',str(a.rad),'--input',str(avi),'--output',str(bik)],check=True)
    if not bik.is_file() or bik.stat().st_size<100: raise ValueError("RAD did not produce a complete Bink candidate")
    try: validate_output_size(bik.stat().st_size,a.input.stat().st_size)
    except ValueError:
        bik.unlink(missing_ok=True)
        raise
    out=probe(bik); bv,ba=require_video(out,"Bink candidate")
    subprocess.run(['ffmpeg','-v','error','-i',str(bik),'-map','0:v:0','-map','0:a:0','-f','null','-'],check=True)
    report={'input':str(a.input),'input_sha256':sha(a.input),'input_fps':v['avg_frame_rate'],'input_frames':180,'avi':str(avi),'avi_sha256':sha(avi),'avi_probe':avi_probe,'candidate':str(bik),'candidate_sha256':sha(bik),'bink_probe':out,'decode':'ffmpeg full decode passed','assertions':{'width':bv['width'],'height':bv['height'],'frames':bv['nb_read_frames'],'fps':bv['avg_frame_rate'],'audio_codec':ba['codec_name']},'runtime':'game playback not tested'}
    (a.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
