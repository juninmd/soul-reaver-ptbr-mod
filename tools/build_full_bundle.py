"""Assemble a local review tree using the production ``modules/`` layout.

The module tree groups every component the installer can apply: PT-BR voices,
localization (menus, subtitles and proxy), a separate FMV module, the dgVoodoo
4K wrapper with an explicit resolution, and optional experimental components.

Nothing here is publishable. The output is local-only and its `bundle.json`
records which components are ready and which remain experimental. Original
game files, saves and AI weights never enter the git tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

WRAPPER = ("DDraw.dll", "D3DImm.dll")


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def rewrite_conf(source: Path, resolution: str, windowed: bool) -> bytes:
    """Return the dgVoodoo.conf with an explicit resolution and no watermark."""
    text = source.read_text(encoding="utf-8-sig", errors="surrogateescape")
    lines = text.splitlines()
    section = None
    seen_directx = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else None
        if key == "FullScreenMode" and windowed:
            lines[index] = "FullScreenMode                       = false"
        if key == "PresentationModel" and windowed:
            # Flip models can bypass DWM composition, which hides the vector subtitle/map overlay windows.
            lines[index] = "PresentationModel                    = discard"
        if section != "DirectX":
            continue
        if key == "Resolution":
            lines[index] = f"Resolution                          = {resolution}"
            seen_directx = True
        elif key == "dgVoodooWatermark":
            lines[index] = "dgVoodooWatermark                   = false"
        elif key == "Filtering":
            # 16x anisotropic keeps the native 256x256 pages sharp at oblique angles on a 4K output.
            lines[index] = "Filtering                           = 16"
    if not seen_directx:
        raise ValueError("dgVoodoo.conf sem seção [DirectX]/Resolution")
    return ("\n".join(lines) + "\n").encode("utf-8")


def build(voices: Path, assets: Path, dgvoodoo: Path, output: Path,
          resolution: str = "3840x2160", windowed: bool = True,
          hd_textures: Path | None = None, ui: Path | None = None) -> dict:
    voices, assets, dgvoodoo, output = map(Path, (voices, assets, dgvoodoo, output))
    if output.exists():
        raise ValueError("Escolha uma pasta de saída nova e inexistente")

    manifest = read_json(voices / "manifest.json")
    if manifest.get("id") != "sr1-ptbr-review":
        raise ValueError("Este construtor aceita apenas candidatos de revisão explícitos")
    asset_plan = read_json(assets / "assets.json")
    localization_assets = [item for item in asset_plan["assets"] if not item["file"].endswith(".bik")]
    video_assets = [item for item in asset_plan["assets"] if item["file"].endswith(".bik")]

    # Verify every input before creating a partially populated output.
    for patch in manifest["patches"]:
        payload = voices / patch["file"]
        if not payload.is_file() or sha256(payload) != patch["sha256"]:
            raise ValueError(f"Áudio ausente ou alterado: {patch['file']}")
    for item in asset_plan["assets"]:
        payload = assets / item["payload"]
        if not payload.is_file() or sha256(payload) != item["result_sha256"]:
            raise ValueError(f"Localização ausente ou alterada: {item['file']}")
    for name in (*WRAPPER, "dgVoodoo.conf"):
        candidates = [dgvoodoo / "MS" / "x86" / name, dgvoodoo / name]
        if not any(c.is_file() for c in candidates):
            raise ValueError(f"Arquivo dgVoodoo ausente: {name}")

    output.mkdir(parents=True)

    modules: dict[str, dict] = {
        "voices": {"path": "voices", "manifest": "manifest.json", "component": "voices"},
        "localization": {"path": "localization", "manifest": "assets.json", "component": "assets"},
        "graphics": {"path": "graphics", "manifest": None, "component": "graphics"},
    }

    # Voices: manifest + payloads + coverage review.
    voice_dir = output / "voices"
    voice_dir.mkdir()
    shutil.copyfile(voices / "manifest.json", voice_dir / "manifest.json")
    for name in ("review.json", *(p["file"] for p in manifest["patches"])):
        if (voices / name).is_file():
            shutil.copyfile(voices / name, voice_dir / name)

    # Localization and video get separate manifests, payload trees and journals.
    localization_dir = output / "localization"
    localization_dir.mkdir()
    (localization_dir / "assets.json").write_text(
        json.dumps({"schema": 1, "assets": localization_assets}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for item in localization_assets:
        shutil.copyfile(assets / item["payload"], localization_dir / item["payload"])
    if video_assets:
        video_dir = output / "video"
        video_dir.mkdir()
        (video_dir / "video.json").write_text(
            json.dumps({"schema": 1, "assets": video_assets}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for item in video_assets:
            shutil.copyfile(assets / item["payload"], video_dir / item["payload"])
        modules["video"] = {"path": "video", "manifest": "video.json", "component": "assets"}

    # Graphics wrapper with an explicit resolution.
    graphics = output / "graphics"
    graphics.mkdir()
    for name in WRAPPER:
        candidates = [dgvoodoo / "MS" / "x86" / name, dgvoodoo / name]
        source = next(c for c in candidates if c.is_file())
        shutil.copyfile(source, graphics / name)
    conf_source = next(c for c in (dgvoodoo / "dgVoodoo.conf", dgvoodoo / "MS" / "x86" / "dgVoodoo.conf") if c.is_file())
    (graphics / "dgVoodoo.conf").write_bytes(rewrite_conf(conf_source, resolution, windowed))

    components = {
        "voices": True,
        "localization": bool(localization_assets),
        "video": bool(video_assets),
        "graphics": True,
        "widescreen": True,
        "textures": False,
        "ui": False,
    }
    experimental: list[str] = []
    resolutions = [resolution]

    if ui is not None:
        ui = Path(ui)
        plan = read_json(ui / "ui.json")
        for item in plan["assets"]:
            if sha256(ui / item["payload"]) != item["result_sha256"]:
                raise ValueError(f"Interface ausente ou alterada: {item['file']}")
        ui_dir = output / "ui"
        ui_dir.mkdir()
        shutil.copyfile(ui / "ui.json", ui_dir / "ui.json")
        for item in plan["assets"]:
            destination = ui_dir / item["payload"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ui / item["payload"], destination)
        modules["ui"] = {"path": "ui", "manifest": "ui.json", "component": "external"}
        components["ui"] = True
        experimental.append("ui")

    if hd_textures is not None:
        hd_textures = Path(hd_textures)
        index = read_json(hd_textures / "index.json")
        entries = []
        textures_dir = output / "textures"
        hd_dir = textures_dir / "payload" / "hd-textures"
        hd_dir.mkdir()
        for page, record in sorted(index["pages"].items(), key=lambda kv: int(kv[0])):
            source = hd_textures / record["packedRaw"]
            destination = hd_dir / f"page-{int(page):04}.raw"
            shutil.copyfile(source, destination)
            entries.append({
                "file": f"hd-textures/page-{int(page):04}.raw",
                "source_sha256": None,
                "result_sha256": sha256(destination),
                "payload": str(destination.relative_to(textures_dir)).replace("\\", "/"),
            })
        (textures_dir / "textures.json").write_text(json.dumps(dict(schema=1, assets=entries), indent=2), encoding="utf-8")
        modules["textures"] = {"path": "textures", "manifest": "textures.json", "component": "external"}
        components["textures"] = True
        experimental.append("textures")
        resolutions.append("1024x1024 por página (não 4K nativo)")

    (output / "bundle.json").write_text(json.dumps({
        "schema": 2,
        "name": "Pacote local PT-BR (revisão)",
        "version": manifest.get("version", "0.1.0"),
        "local_only": True,
        "publishable": False,
        "modules": modules,
        "components": components,
        "resolution": resolution,
        "windowed": windowed,
        "experimental": experimental,
        "notes": [
            "Cobertura de dublagem parcial; campanha ainda em inglês.",
            "Texturas e interface exigem validação de runtime antes de qualquer promoção.",
            "60 FPS e HUD/menus reais continuam pendentes.",
        ],
        "resolutions": resolutions,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"output": str(output), "components": components}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voices", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--dgvoodoo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", default="3840x2160")
    parser.add_argument("--fullscreen", action="store_true", help="Por padrão o bundle abre em janela")
    parser.add_argument("--hd-textures", type=Path, default=None)
    parser.add_argument("--ui", type=Path, default=None, help="Pasta com ui.json + payload (experimental)")
    args = parser.parse_args()
    result = build(args.voices, args.assets, args.dgvoodoo, args.output,
                   args.resolution, not args.fullscreen, args.hd_textures, args.ui)
    print(json.dumps(result, ensure_ascii=False))
