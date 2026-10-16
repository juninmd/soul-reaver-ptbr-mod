"""Validate a strict core external-package textures.json and its payloads."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

RAW_BYTES = 1024 * 1024 * 2
PAGE_COUNT = 1287
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ASSET_KEYS = {"file", "source_sha256", "result_sha256", "payload"}


class PackageError(Exception):
    pass


def safe_payload(base: Path, value: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise PackageError(f"Caminho payload inválido: {value!r}")
    path = base / relative
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PackageError(f"Payload usa link simbólico, não aceito pelo core: {value}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(base.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PackageError(f"Payload ausente ou fora do pacote: {value}") from exc
    if not resolved.is_file():
        raise PackageError(f"Payload não é arquivo regular: {value}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(manifest_path: Path) -> dict:
    manifest_path = manifest_path.resolve(strict=True)
    package_root = manifest_path.parent
    package = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(package, dict) or set(package) != {"schema", "assets"} or package.get("schema") != 1:
        raise PackageError("O objeto raiz deve conter exatamente schema=1 e assets")
    assets = package.get("assets")
    if not isinstance(assets, list) or len(assets) != PAGE_COUNT:
        raise PackageError(f"Esperados {PAGE_COUNT} assets; encontrados {len(assets) if isinstance(assets, list) else 'tipo inválido'}")

    seen_destinations = set()
    seen_payloads = set()
    total_bytes = 0
    for number, asset in enumerate(assets):
        if not isinstance(asset, dict) or set(asset) != ASSET_KEYS:
            raise PackageError(f"Asset {number} não corresponde aos campos estritos do core: {asset!r}")
        destination = asset["file"]
        payload_name = asset["payload"]
        result_hash = asset["result_sha256"]
        if not isinstance(destination, str) or not re.fullmatch(r"hd-textures/page-[0-9]{4}\.raw", destination):
            raise PackageError(f"Destino inválido no asset {number}: {destination!r}")
        match = re.fullmatch(r"hd-textures/page-([0-9]{4})\.raw", destination)
        assert match is not None
        page_id = int(match.group(1))
        if destination in seen_destinations or page_id != number or asset["source_sha256"] is not None:
            raise PackageError(f"Destino duplicado, ordem divergente ou source_sha256 incompatível: {destination}")
        if not isinstance(result_hash, str) or not SHA256.fullmatch(result_hash):
            raise PackageError(f"SHA-256 inválido no asset {number}")
        if not isinstance(payload_name, str) or payload_name in seen_payloads:
            raise PackageError(f"Payload duplicado/inválido no asset {number}")
        payload = safe_payload(package_root, payload_name)
        size = payload.stat().st_size
        if size != RAW_BYTES:
            raise PackageError(f"Tamanho incorreto em {payload_name}: {size}, esperado {RAW_BYTES}")
        actual_hash = sha256(payload)
        if actual_hash != result_hash:
            raise PackageError(f"SHA-256 divergente em {payload_name}: declarado {result_hash}, real {actual_hash}")
        seen_destinations.add(destination)
        seen_payloads.add(payload_name)
        total_bytes += size

    return {"status": "ok", "manifest": str(manifest_path), "assets": len(assets),
            "filesExistAndMatch": len(assets), "sha256Checks": len(assets),
            "bytesPerAsset": RAW_BYTES, "payloadBytes": total_bytes,
            "note": "O schema do core não possui campo bytes; os tamanhos foram medidos nos payloads."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[2] / "validate/95-texturas-4k/textures.json")
    args = parser.parse_args()
    try:
        result = validate(args.manifest)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, PackageError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
