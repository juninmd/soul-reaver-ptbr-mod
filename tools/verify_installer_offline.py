"""Offline acceptance test for the installer core on an isolated copy.

Never touches the Steam install and never opens the game. It recreates a clean
classic copy from the recorded originals, then drives the `srmod` CLI through
apply, per-component inspection and restore, asserting hashes and preservation
of a save and a foreign DLL.

Usage:
  python tools/verify_installer_offline.py \
    --steam "D:\\SteamLibrary\\steamapps\\common\\Legacy of Kain Soul Reaver" \
     --bundle modules --work staging/install-test-modules --srmod-bin target/debug/srmod.exe
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXE_SHA256 = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a"
VOICES_SHA256 = "e2a193b62f9723f5f477f705c53a56f895375ce2d980d276d0d0fceeb2645df5"


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def find_original(name: str, expected: str, roots) -> Path:
    stem, _, suffix = name.rpartition(".")
    variants = [f"{name}.original", name]
    if stem:
        variants.append(f"{stem}.original.{suffix}")
    for root in roots:
        for variant in variants:
            candidate = Path(root) / variant
            if candidate.is_file() and sha256(candidate) == expected:
                return candidate
    raise FileNotFoundError(f"Original não encontrado para {name} ({expected[:12]}…)")


def run(srmod: list[str], *args: str, expect_ok: bool = True) -> subprocess.CompletedProcess:
    command = [*srmod, *args]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if expect_ok and result.returncode != 0:
        raise RuntimeError(f"Falhou: {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steam", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--srmod-bin", type=Path, default=None)
    args = parser.parse_args()

    steam, bundle, work = args.steam.resolve(), args.bundle.resolve(), args.work.resolve()
    if work.exists():
        raise FileExistsError(f"Pasta de trabalho já existe; preserve-a e escolha outra: {work}")
    game = work / "game"
    backups = work / "external-backups"
    game.mkdir(parents=True)
    backups.mkdir()
    report: dict = {"schema": 1, "steamTouched": False, "gameLaunched": False, "steps": []}

    if args.srmod_bin is None:
        raise ValueError("--srmod-bin é obrigatório para esta verificação")
    srmod = [str(args.srmod_bin.resolve())]

    roots = [
        steam / ".soul-reaver-ptbr",
        Path(os.environ["LOCALAPPDATA"]) / "SoulReaverPTBR" / "backups" / "steam-classic-en",
        Path("staging/backups/steam-classic-en"),
    ]

    # Recreate a clean English copy from recorded originals only.
    shutil.copyfile(steam / "kain2.exe", game / "kain2.exe")
    assert sha256(game / "kain2.exe") == EXE_SHA256, "kain2.exe da Steam não é o original"
    shutil.copyfile(find_original("voices.dat", VOICES_SHA256, roots), game / "voices.dat")
    voices_module = bundle / "voices"
    localization_module = bundle / "localization"
    video_module = bundle / "video"
    assets = read_json(localization_module / "assets.json")["assets"]
    videos = read_json(video_module / "video.json")["assets"]
    for item in assets:
        if item["source_sha256"] is None:
            continue  # created-only file, must start absent
        shutil.copyfile(find_original(item["file"], item["source_sha256"], roots), game / item["file"])
    for item in videos:
        shutil.copyfile(find_original(item["file"], item["source_sha256"], roots), game / item["file"])
    shutil.copyfile(steam / "savegame.her", game / "savegame.her")
    save_hash = sha256(game / "savegame.her")
    (game / "foreign-mod.dll").write_bytes(b"another mod dll, must survive")
    report["steps"].append({"makeCleanCopy": "ok", "assets": len(assets), "videoFiles": len(videos)})

    def components() -> dict:
        return json.loads(run(srmod, "components", str(game)).stdout)

    before = components()
    assert before["graphics"]["installed"] is False, "gráficos deveriam estar ausentes"
    assert before["localization"]["files"] == 0, "localização deveria estar ausente"

    run(srmod, "apply", str(game), str(voices_module / "manifest.json"))
    run(srmod, "assets-apply", str(game), str(localization_module / "assets.json"), str(backups))
    run(srmod, "video-apply", str(game), str(video_module / "video.json"), str(backups))
    run(srmod, "graphics-apply", str(game), str(bundle / "graphics"), "widescreen")
    has_ui = (bundle / "ui" / "ui.json").is_file()
    if has_ui:
        run(srmod, "ui-apply", str(game), str(bundle / "ui" / "ui.json"), str(backups))
    installed = components()
    report["steps"].append({"install": "ok", "localizationFiles": installed["localization"]["files"],
                            "graphics": installed["graphics"], "ui": installed["ui"]})
    assert installed["localization"]["menus"] and installed["localization"]["videos"] == 0
    assert installed["localization"]["subtitles"]
    assert installed["video"]["installed"] and installed["video"]["files"] == 8
    manager = game / ".soul-reaver-ptbr"
    localization_journal = read_json(manager / "assets-state.json")
    video_journal = read_json(manager / "video-state.json")
    assert len(localization_journal["assets"]) == 3
    assert len(video_journal["assets"]) == 8
    assert not any(item["file"].endswith(".bik") for item in localization_journal["assets"])
    assert all(item["file"].endswith(".bik") for item in video_journal["assets"])
    report["steps"].append({
        "separateJournals": "ok",
        "localizationState": "assets-state.json (3 arquivos; sem BIK)",
        "videoState": "video-state.json (8 BIK)",
    })
    assert installed["graphics"]["installed"] and installed["graphics"]["widescreen"]
    assert installed["graphics"]["files"] == 3
    if has_ui:
        assert installed["ui"]["installed"] and installed["ui"]["files"] == 2

    # A conflicting, unowned wrapper must be refused on a clean copy.
    lost = game / "DDraw.dll"
    lost.write_bytes(b"another graphics mod wrapper")
    conflict = run(srmod, "graphics-apply", str(game), str(bundle / "graphics"), "widescreen", expect_ok=False)
    assert "preexistente" in (conflict.stderr + conflict.stdout)
    assert lost.read_bytes() == b"another graphics mod wrapper"
    lost.unlink()
    report["steps"].append({"unownedWrapperRefused": "ok"})

    run(srmod, "restore", str(game))
    run(srmod, "assets-restore", str(game))
    run(srmod, "video-restore", str(game))
    if has_ui:
        run(srmod, "ui-restore", str(game))
    run(srmod, "graphics-restore", str(game))
    after = components()
    report["steps"].append({"restore": "ok"})
    assert after["localization"]["files"] == 0
    assert after["localization"]["videos"] == 0
    assert after["video"]["installed"] is False and after["video"]["files"] == 0
    assert after["graphics"]["installed"] is False
    if has_ui:
        assert after["ui"]["installed"] is False
    assert sha256(game / "kain2.exe") == EXE_SHA256, "executável não voltou ao original"
    assert (game / "foreign-mod.dll").read_bytes() == b"another mod dll, must survive"
    assert sha256(game / "savegame.her") == save_hash, "save foi alterado"
    assert not (game / "DDraw.dll").exists() and not (game / "DINPUT.dll").exists()
    for item in videos:
        assert sha256(game / item["file"]) == item["source_sha256"], f"vídeo não foi restaurado: {item['file']}"
    assert not (game / "hd-ui-cache.dll").exists() and not (game / "ui-ptbr.bin").exists()

    report["passed"] = True
    (work / "installer-offline-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "report": str(work / "installer-offline-report.json")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
