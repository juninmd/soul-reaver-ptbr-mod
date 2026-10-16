"""Generate reviewed dialogue offline with one resident Qwen model; benchmark batches 1/2/4."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from audio_pipeline import atomic_json, digest, read_json


def file_hash(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--extra-packages", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, choices=(1, 2, 4), default=4,
                        help="Lines synthesized per GPU batch (default: 4; benchmarked on RTX 4060 Ti)")
    parser.add_argument("--benchmark", action="store_true", help="Compare the same four texts at batch sizes 1/2/4; do not approve outputs")
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    args = parser.parse_args()
    if not 64 <= args.max_new_tokens <= 4096:
        parser.error("--max-new-tokens must be 64..4096")
    if not (args.model / "config.json").is_file():
        parser.error("--model must be an existing local checkpoint")
    if args.extra_packages:
        sys.path.insert(0, str(args.extra_packages.resolve()))
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_PROGRESS_BARS"):
        os.environ[key] = "1"
    plan = read_json(args.plan)
    if plan.get("schema") != 1:
        parser.error("Unsupported plan schema")
    voices = [v for v in plan["voices"] if v.get("approved_text") is True]
    if not voices or len({v["id"] for v in voices}) != len(voices):
        parser.error("Need reviewed text with unique voice ids")
    profiles = plan["profiles"]
    for voice in voices:
        if type(voice.get("id")) is not int or not 0 <= voice["id"] < 479 or not isinstance(voice.get("duration_seconds"), (int, float)) or not 0 < voice["duration_seconds"] <= 60:
            parser.error("Every reviewed line needs a valid id and slot duration")
        if not voice.get("text_ptbr", "").strip() or voice.get("speaker") not in profiles:
            parser.error("Every reviewed line needs text and a known speaker profile")
        if not isinstance(voice.get("synthesis_text_ptbr", voice["text_ptbr"]), str) or not voice.get("synthesis_text_ptbr", voice["text_ptbr"]).strip():
            parser.error("Pronunciation text, when provided, must be nonempty")
    args.output.mkdir(parents=True, exist_ok=True)
    marker = args.output / "producer.json"
    if marker.exists() and read_json(marker) != {"schema": 1, "kind": "sr1-local-tts"}:
        parser.error("Output belongs to another producer")
    if not marker.exists():
        if list(args.output.iterdir()):
            parser.error("Output directory is not empty or owned by this producer")
        atomic_json(marker, {"schema": 1, "kind": "sr1-local-tts"})
    lock = args.output / "producer.lock"
    try:
        with lock.open("x") as file:
            file.write(str(os.getpid()))
    except FileExistsError:
        parser.error("Producer locked; check the recorded process before removing producer.lock")
    try:
        # Libraries sometimes write diagnostics to stdout: keep CLI results parseable.
        with contextlib.redirect_stdout(sys.stderr):
            result = run(args, voices, profiles)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        lock.unlink(missing_ok=True)


def run(args, voices, profiles):
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import set_seed
    from qwen_tts import Qwen3TTSModel

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError("This validated path requires CUDA with BF16 support")
    versions = {p: importlib.metadata.version(p) for p in ("torch", "qwen-tts", "transformers")}
    references = {}
    for speaker in {v["speaker"] for v in voices}:
        profile = profiles[speaker]
        path = (args.plan.parent / profile["reference"]).resolve()
        if file_hash(path) != profile["reference_sha256"] or not profile["reference_text"].strip():
            raise ValueError(f"Invalid reference profile: {speaker}")
        audio, rate = sf.read(path, dtype="float32")
        if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 0.0001:
            raise ValueError(f"Reference must be finite, audible mono: {speaker}")
        references[speaker] = (path, profile)
        profile["reference"] = str(path)
    print("Fingerprinting the local checkpoint", file=sys.stderr, flush=True)
    model_files = {str(p.relative_to(args.model)).replace("\\", "/"): file_hash(p)
                   for p in sorted(args.model.rglob("*"))
                   if p.is_file() and p.suffix in (".json", ".safetensors", ".bin", ".txt") and ".cache" not in p.parts}
    if not any(name.endswith((".safetensors", ".bin")) for name in model_files):
        raise ValueError("Checkpoint has no local weights")
    model_fingerprint = digest(json.dumps(model_files, sort_keys=True).encode())
    torch.set_num_threads(6)
    started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(str(args.model.resolve()), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
    prompts = {speaker: model.create_voice_clone_prompt(ref_audio=str(path), ref_text=profile["reference_text"], x_vector_only_mode=False)
               for speaker, (path, profile) in references.items()}
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started
    settings = dict(non_streaming_mode=True, max_new_tokens=args.max_new_tokens, temperature=0.75, top_p=0.95)

    def generate(batch, seed):
        set_seed(seed)
        prompt = [prompts[v["speaker"]][0] for v in batch]
        with torch.inference_mode():
            return model.generate_voice_clone(text=[v.get("synthesis_text_ptbr", v["text_ptbr"]) for v in batch], language=["Portuguese"] * len(batch), voice_clone_prompt=prompt, **settings)

    if args.benchmark:
        # Warm model/kernel caches before timed comparisons.
        print("Warm-up", file=sys.stderr, flush=True)
        generate([voices[0]], args.seed)
        torch.cuda.synchronize()
        selected = [voices[i % len(voices)] for i in range(4)]
        measurements = []
        for size in (1, 2, 4):
            print(f"Benchmark batch={size}", file=sys.stderr, flush=True)
            torch.cuda.reset_peak_memory_stats()
            start = time.perf_counter()
            seconds = 0
            try:
                for offset in range(0, 4, size):
                    waves, rate = generate(selected[offset:offset + size], args.seed + offset)
                    for index, audio in enumerate(waves):
                        samples = np.asarray(audio, dtype=np.float32)
                        if not len(samples) or not np.isfinite(samples).all():
                            raise ValueError("Invalid benchmark audio")
                        seconds += len(samples) / rate
                        sf.write(args.output / f"benchmark-b{size}-{offset + index}.wav", samples, rate, subtype="PCM_16")
                torch.cuda.synchronize()
                elapsed = time.perf_counter() - start
                measurements.append(dict(batch_size=size, lines=4, elapsed_seconds=elapsed, audio_seconds=seconds,
                                         real_time_factor=elapsed / seconds, peak_vram_mib=torch.cuda.max_memory_allocated() / 1024**2, status="ok"))
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                measurements.append(dict(batch_size=size, status="out_of_memory"))
            atomic_json(args.output / "benchmark.json", dict(schema=1, load_and_prompt_seconds=load_seconds,
                        gpu=torch.cuda.get_device_name(0), model_fingerprint=model_fingerprint, model_revision=args.model_revision,
                        settings=settings, packages=versions, measurements=measurements, comparison="Four lines total per batch size; single run; human review pending"))
        return read_json(args.output / "benchmark.json")

    jobs = []
    for voice in voices:
        identity = dict(voice=voice, profile=profiles[voice["speaker"]], model_fingerprint=model_fingerprint,
                        model_revision=args.model_revision, settings=settings, seed=args.seed, batch_size=args.batch_size, packages=versions)
        key = digest(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode())
        directory = args.output / f"{voice['id']:04d}-{key[:24]}"
        cached = directory / "metadata.json"
        if cached.exists():
            metadata = read_json(cached)
            if metadata["identity"] != identity or file_hash(directory / "voice.wav") != metadata["audio_sha256"]:
                raise ValueError(f"Corrupt cache at {directory}; preserve it for investigation")
            jobs.append(dict(voice=voice, directory=directory, identity=identity, cached=True))
        else:
            if directory.exists():
                raise ValueError(f"Incomplete cache at {directory}; choose a new output directory")
            jobs.append(dict(voice=voice, directory=directory, identity=identity, cached=False))

    def finish(job, audio, rate):
        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
            raise ValueError("Generated audio is invalid")
        peak = float(np.max(np.abs(samples)))
        if peak < 0.0001:
            raise ValueError("Generated audio is silent")
        samples *= min(0.89 / peak, 4)
        with tempfile.TemporaryDirectory(prefix=".take-", dir=args.output) as temporary:
            root = Path(temporary)
            sf.write(root / "source.wav", samples, rate, subtype="PCM_16")
            subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(root / "source.wav"),
                            "-threads", "1", "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", str(root / "voice.wav")], check=True)
            converted, converted_rate = sf.read(root / "voice.wav")
            duration = len(converted) / converted_rate
            limit = job["voice"]["duration_seconds"] - job["voice"].get("lead_samples", 0) / 22050
            metadata = dict(schema=1, identity=job["identity"], audio_sha256=file_hash(root / "voice.wav"),
                            duration_seconds=duration, fits_slot=duration <= limit, approved_audio=False,
                            peak=float(np.max(np.abs(converted))))
            atomic_json(root / "metadata.json", metadata)
            root.rename(job["directory"])
        return metadata

    pending = [job for job in jobs if not job["cached"]]
    start = time.perf_counter()
    futures = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for offset in range(0, len(pending), args.batch_size):
            group = pending[offset:offset + args.batch_size]
            print(f"Generating {offset + 1}..{offset + len(group)} / {len(pending)}", file=sys.stderr, flush=True)
            waves, rate = generate([j["voice"] for j in group], args.seed + group[0]["voice"]["id"])
            for job, audio in zip(group, waves, strict=True):
                futures.append(pool.submit(finish, job, audio, rate))
        for future in futures:
            future.result()
    candidates = []
    for job in jobs:
        entry = dict(job["voice"], audio=str((job["directory"] / "voice.wav").resolve()), approved_audio=False)
        entry["audio_sha256"] = read_json(job["directory"] / "metadata.json")["audio_sha256"]
        candidates.append(entry)
    atomic_json(args.output / "candidates.json", dict(schema=1, profiles=profiles, voices=candidates))
    result = dict(schema=1, generated=len(pending), reused=len(jobs) - len(pending),
                  load_and_prompt_seconds=load_seconds, generation_and_postprocess_seconds=time.perf_counter() - start,
                  candidates=str(args.output / "candidates.json"), approved_audio=False)
    atomic_json(args.output / "run.json", result)
    return result


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
