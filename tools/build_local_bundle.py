"""Assemble an explicitly unapproved, local-only review bundle; never publish it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build(voices, assets, reports, hashes, output, playback_evidence=()):
    if output.exists():
        raise ValueError("Choose a new bundle directory")
    voice_manifest = read(voices / "manifest.json")
    if voice_manifest["id"] != "sr1-ptbr-review":
        raise ValueError("This builder accepts explicit review candidates only")
    voice_manifest["name"] = "Candidato PT-BR - escuta pendente"
    originals = read(hashes) if reports else {}
    playback = {}
    for evidence_path in playback_evidence:
        evidence = read(evidence_path)
        if evidence.get("passed") is not True:
            raise ValueError(f"Playback verification failed: {evidence_path}")
        for movie in evidence["movies"]:
            if movie.get("passed") is not True or movie.get("all_frames_played") is not True:
                raise ValueError(f"Incomplete movie playback: {evidence_path}")
            playback[movie["candidate_sha256"]] = dict(
                evidence=str(evidence_path.resolve()),
                natural_story_trigger_verified=movie.get("natural_story_trigger_verified") is True)
    entries = []
    for item in read(assets)["assets"]:
        entries.append((item, assets.parent / item["payload"]))
    provenance = []
    for item, _ in entries:
        if item['file'].lower().endswith('.bik'):
            proof = playback.get(item['result_sha256'])
            provenance.append(dict(file=item['file'], source_asset_manifest=str(assets.resolve()),
                human_listening_approved=False, game_playback_verified=proof is not None,
                natural_story_trigger_verified=bool(proof and proof['natural_story_trigger_verified']),
                playback_evidence=proof['evidence'] if proof else None))
    for report_path in reports:
        report = read(report_path)
        if report.get("decode_complete") is not True:
            raise ValueError(f"Movie has no complete decode evidence: {report_path}")
        movie = Path(report["candidate"])
        name = report["fmv"] + ".bik"
        # Original source hashes are kept with the rendering inventory.
        entries.append((dict(file=name, source_sha256=originals[name],
                             result_sha256=report["candidate_sha256"]), movie))
        proof = playback.get(report["candidate_sha256"])
        provenance.append(dict(file=name, report=str(report_path.resolve()),
                               human_listening_approved=False,
                               game_playback_verified=proof is not None,
                               natural_story_trigger_verified=bool(proof and proof["natural_story_trigger_verified"]),
                               playback_evidence=proof["evidence"] if proof else None))
    names = [item["file"] for item, _ in entries]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate asset")
    # Check every source before creating a partially populated output.
    for item, path in entries:
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["result_sha256"]:
            raise ValueError(f"Asset changed: {path}")
    for patch in voice_manifest["patches"]:
        path = voices / patch["file"]
        if path.name != patch["file"] or hashlib.sha256(path.read_bytes()).hexdigest() != patch["sha256"]:
            raise ValueError("Voice payload changed or path invalid")
    output.mkdir(parents=True)
    for name in ("review.json", *[p["file"] for p in voice_manifest["patches"]]):
        shutil.copyfile(voices / name, output / name)
    (output / "manifest.json").write_text(json.dumps(voice_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    review = read(output / "review.json")
    review["manifest_sha256"] = hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
    (output / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    assembled = []
    for item, path in entries:
        payload = "asset-" + Path(item["file"]).name
        shutil.copyfile(path, output / payload)
        assembled.append(dict(file=item["file"], source_sha256=item["source_sha256"],
                              result_sha256=item["result_sha256"], payload=payload))
    (output / "assets.json").write_text(json.dumps(dict(schema=1, assets=assembled), indent=2), encoding="utf-8")
    (output / "local-review.json").write_text(json.dumps(dict(schema=1, local_only=True,
        human_listening_approved=False, campaign_complete=False, movies=provenance), indent=2), encoding="utf-8")
    print(json.dumps(dict(output=str(output), voices=len(voice_manifest["patches"]), assets=len(assembled))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("voices", "assets", "hashes", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--report", dest="reports", type=Path, action="append", default=[])
    parser.add_argument("--playback-evidence", type=Path, action="append", default=[])
    build(**vars(parser.parse_args()))
