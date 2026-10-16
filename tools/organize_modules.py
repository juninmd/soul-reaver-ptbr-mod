#!/usr/bin/env python3
"""Promove os pacotes candidatos para a árvore produtiva ``modules/``.

Regra do projeto: cada módulo do instalador tem UMA pasta de fonte de verdade,
auto-contida (manifesto + payloads no mesmo diretório). ``staging/`` é área de
trabalho e ``validate/`` mostra andamento — nenhum dos dois guarda arquivo
oficial. O instalador lê ``modules/`` diretamente.

Uso:
    python tools/organize_modules.py --dry-run
    python tools/organize_modules.py

O comando é seguro por padrão: recusa sobrescrever qualquer destino existente e
recusa rodar de novo depois de concluído (idempotente por recusa, não por
sobrescrita).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "staging" / "packages" / "local-full-v1"
TEXTURES_SRC = ROOT / "validate" / "95-texturas-4k"
MODULES = ROOT / "modules"

PROXY = "asset-DINPUT.dll"
SUBTITLES = "asset-subtitles.tsv"
MENUS = "asset-locals.pc"


def bundle_manifest_paths() -> dict:
    """Descrição da árvore produtiva: um módulo por componente do instalador."""
    return {
        "schema": 2,
        "name": "Soul Reaver PT-BR — módulos produtivos",
        "version": "0.2.0",
        "production": True,
        "resolution": "3840x2160",
        "windowed": True,
        "modules": {
            "voices": {"path": "voices", "manifest": "manifest.json", "component": "voices"},
            "localization": {"path": "localization", "manifest": "assets.json", "component": "assets"},
            "video": {"path": "video", "manifest": "video.json", "component": "assets"},
            "graphics": {"path": "graphics", "manifest": None, "component": "graphics"},
            "textures": {"path": "textures", "manifest": "textures.json", "component": "external"},
            "ui": {"path": "ui", "manifest": "ui.json", "component": "external"},
        },
        "experimental": ["ui", "textures"],
        "notes": [
            "Cada módulo é auto-contido: manifesto e payloads no mesmo diretório.",
            "Vídeos HD têm módulo próprio; menus, legendas e proxy ficam em localization.",
            "Texturas/interface seguem experimentais: o carregador no jogo não é comprovado.",
        ],
    }


def move(src: Path, dst: Path, dry: bool) -> str:
    if not src.exists():
        raise SystemExit(f"origem ausente: {src}")
    if dst.exists():
        raise SystemExit(f"destino já existe (recusando sobrescrever): {dst}")
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    return f"{'[dry] ' if dry else ''}{src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}"


def glob_move(pattern: str, dst_dir: Path, dry: bool, log: list[str]) -> None:
    matches = sorted(SRC.glob(pattern))
    if not matches:
        raise SystemExit(f"nenhum arquivo para o padrão {pattern}")
    for item in matches:
        log.append(move(item, dst_dir / item.name, dry))


def split_assets(dry: bool, log: list[str]) -> None:
    """Divide assets.json: localization (menus/legendas/proxy) e video (BIK)."""
    data = json.loads((SRC / "assets.json").read_text(encoding="utf-8"))
    localization, video = [], []
    for asset in data["assets"]:
        (video if asset["file"].endswith(".bik") else localization).append(asset)

    outputs = {
        MODULES / "localization" / "assets.json": {"schema": 1, "assets": localization},
        MODULES / "video" / "video.json": {"schema": 1, "assets": video},
    }
    for path, payload in outputs.items():
        if path.exists():
            raise SystemExit(f"destino já existe: {path}")
        if not dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.append(f"{'[dry] ' if dry else ''}{path.relative_to(ROOT)} ({len(payload['assets'])} assets)")

    # Move os payloads para o módulo correspondente.
    for asset in localization:
        move(SRC / asset["payload"], MODULES / "localization" / asset["payload"], dry)
    for asset in video:
        move(SRC / asset["payload"], MODULES / "video" / asset["payload"], dry)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="mostra o plano sem alterar nada")
    args = parser.parse_args()
    dry = args.dry_run
    log: list[str] = []

    if not SRC.is_dir():
        raise SystemExit(f"pacote-fonte ausente: {SRC}")

    # voices
    log.append(move(SRC / "manifest.json", MODULES / "voices" / "manifest.json", dry))
    glob_move("voice-*.pcm", MODULES / "voices", dry, log)

    # localization (menus, legendas, proxy) + video, via split do assets.json
    split_assets(dry, log)

    # graphics
    for name in ("D3DImm.dll", "DDraw.dll", "dgVoodoo.conf"):
        log.append(move(SRC / "graphics" / name, MODULES / "graphics" / name, dry))

    # ui
    log.append(move(SRC / "ui.json", MODULES / "ui" / "ui.json", dry))
    glob_move("payload/*", MODULES / "ui" / "payload", dry, log)

    # textures (sai de validate/ para o módulo produtivo)
    log.append(move(TEXTURES_SRC / "textures.json", MODULES / "textures" / "textures.json", dry))
    log.append(move(TEXTURES_SRC / "payload", MODULES / "textures" / "payload", dry))

    # índice da árvore
    bundle = MODULES / "bundle.json"
    if bundle.exists():
        raise SystemExit(f"destino já existe: {bundle}")
    if not dry:
        MODULES.mkdir(parents=True, exist_ok=True)
        bundle.write_text(
            json.dumps(bundle_manifest_paths(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    log.append(f"{'[dry] ' if dry else ''}{bundle.relative_to(ROOT)}")

    print("\n".join(log))
    print(f"\n{'PLANO (nada alterado)' if dry else 'CONCLUÍDO'}: {len(log)} operações")
    return 0


if __name__ == "__main__":
    sys.exit(main())
