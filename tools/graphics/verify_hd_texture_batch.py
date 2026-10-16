"""Verify the staged full HD texture batch without touching the game install.

This verifier uses only the Python standard library. It validates the part
manifests, staged source/candidate RAWs, per-page hashes/CRCs, bit-15 nearest
replication, PNG dimensions, and the merged index. It never writes files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

SOURCE_SHA256 = "f287fc2b7452aa3f2592c5bab36654ac8ed2aa1be571e607a31e29a3666868fa"
TOTAL_PAGES = 1287
HEADER_BYTES = 4096
SOURCE_SIDE = 256
CANDIDATE_SIDE = 1024
SOURCE_BYTES = SOURCE_SIDE * SOURCE_SIDE * 2
CANDIDATE_BYTES = CANDIDATE_SIDE * CANDIDATE_SIDE * 2
BITPLANE_BYTES = CANDIDATE_SIDE * CANDIDATE_SIDE
EXPECTED_PARTS = 21
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(Exception):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Não foi possível ler JSON {path}: {exc}") from exc


def safe_file(base: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not relative or any(part in ("", ".", "..") for part in candidate.parts):
        raise VerificationError(f"Caminho relativo inválido: {relative!r}")
    path = base.joinpath(candidate)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(base.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise VerificationError(f"Arquivo ausente ou fora da raiz: {relative}") from exc
    if not resolved.is_file() or path.is_symlink():
        raise VerificationError(f"Não é arquivo regular sem link simbólico: {relative}")
    return resolved


def digest(path: Path) -> tuple[str, str, int]:
    sha = hashlib.sha256()
    crc = 0
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
            crc = zlib.crc32(chunk, crc)
            size += len(chunk)
    return sha.hexdigest(), f"{crc & 0xffffffff:08x}", size


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise VerificationError(f"Cabeçalho PNG inválido: {path}")
    return struct.unpack(">II", header[16:24])


def validate_bit15(source: bytes, plane: bytes, page_id: int) -> int:
    if len(source) != SOURCE_BYTES or len(plane) != BITPLANE_BYTES:
        raise VerificationError(f"Tamanho RAW/plano bit15 inválido na página {page_id}")
    source_bits = bytearray(SOURCE_SIDE * SOURCE_SIDE)
    set_source_bits = 0
    for index, (word,) in enumerate(struct.iter_unpack("<H", source)):
        bit = (word >> 15) & 1
        source_bits[index] = bit
        set_source_bits += bit

    # The generator repeats each source bit 4 times horizontally and vertically.
    expanded = bytearray(BITPLANE_BYTES)
    out_width = CANDIDATE_SIDE
    for y in range(SOURCE_SIDE):
        row = source_bits[y * SOURCE_SIDE:(y + 1) * SOURCE_SIDE]
        expanded_row = bytearray().join(bytes((value,)) * 4 for value in row)
        for dy in range(4):
            start = (y * 4 + dy) * out_width
            expanded[start:start + out_width] = expanded_row
    if bytes(expanded) != plane:
        raise VerificationError(f"Plano bit15 não é a replicação nearest 4x na página {page_id}")
    return set_source_bits * 16


def verify(batch: Path) -> dict:
    batch = batch.resolve(strict=True)
    merged = load_json(batch / "manifest.json")
    index = load_json(batch / "index.json")
    if merged.get("schema") != 1 or merged.get("sourceArchiveSHA256") != SOURCE_SHA256:
        raise VerificationError("Manifesto principal não declara o schema/fonte suportados")
    if merged.get("pagesTotal") != TOTAL_PAGES or merged.get("pagesProcessed") != TOTAL_PAGES:
        raise VerificationError("Manifesto principal não declara 1.287/1.287 páginas")
    if merged.get("scale") != 4 or merged.get("runtimeVerified") is not False:
        raise VerificationError("Escala/runtime do manifesto principal inesperados")
    if index.get("schema") != 1 or not isinstance(index.get("pages"), dict):
        raise VerificationError("Índice mesclado incompatível")

    part_dirs = sorted((batch / "parts").glob("*/"))
    part_manifests = [directory / "manifest.json" for directory in part_dirs]
    if len(part_manifests) != EXPECTED_PARTS or any(not p.is_file() for p in part_manifests):
        raise VerificationError(f"Esperados {EXPECTED_PARTS} manifestos de partes; encontrados {len(part_manifests)}")

    rows_by_id: dict[int, tuple[dict, Path]] = {}
    for manifest_path in part_manifests:
        part = load_json(manifest_path)
        if part.get("schema") != 1 or part.get("sourceArchiveSHA256") != SOURCE_SHA256:
            raise VerificationError(f"Manifesto de parte incompatível: {manifest_path}")
        pages = part.get("pages")
        if not isinstance(pages, list) or not pages:
            raise VerificationError(f"Parte sem páginas: {manifest_path}")
        for row in pages:
            page_id = row.get("id")
            if type(page_id) is not int or page_id in rows_by_id:
                raise VerificationError(f"Página ausente/duplicada no manifesto: {page_id!r}")
            rows_by_id[page_id] = (row, manifest_path.parent)

    if set(rows_by_id) != set(range(TOTAL_PAGES)):
        missing = sorted(set(range(TOTAL_PAGES)) - set(rows_by_id))
        extra = sorted(set(rows_by_id) - set(range(TOTAL_PAGES)))
        raise VerificationError(f"Cobertura de páginas divergente: ausentes={missing[:10]}, extras={extra[:10]}")
    if set(index["pages"]) != {str(page_id) for page_id in range(TOTAL_PAGES)}:
        raise VerificationError("As chaves do index.json não correspondem às 1.287 páginas")
    actual_files = {
        "source_raw": sum(1 for path in batch.rglob("original-argb1555-256.raw") if path.is_file()),
        "candidate_raw": sum(1 for path in batch.rglob("candidate-argb1555-1024.raw") if path.is_file()),
        "bit15_plane": sum(1 for path in batch.rglob("bit15-nearest-1024.raw") if path.is_file()),
    }
    if actual_files != {"source_raw": TOTAL_PAGES, "candidate_raw": TOTAL_PAGES, "bit15_plane": TOTAL_PAGES}:
        raise VerificationError(f"Contagem real de arquivos diverge dos manifestos: {actual_files}")

    counts = {"source_sha256": 0, "source_crc32": 0, "candidate_sha256": 0, "candidate_crc32": 0}
    byte_totals = {"source_raw": 0, "candidate_raw": 0, "bit15_plane": 0}
    total_bit15 = 0
    for page_id in range(TOTAL_PAGES):
        row, part_root = rows_by_id[page_id]
        if row.get("sourceDimensions") != [SOURCE_SIDE, SOURCE_SIDE] or row.get("candidateDimensions") != [CANDIDATE_SIDE, CANDIDATE_SIDE]:
            raise VerificationError(f"Dimensões declaradas incorretas na página {page_id}")
        if row.get("sourceOffset") != HEADER_BYTES + page_id * SOURCE_BYTES:
            raise VerificationError(f"Offset declarado incorreto na página {page_id}")
        if row.get("candidateFormat") != "little-endian 16-bit RGB5 plus bit15":
            raise VerificationError(f"Formato declarado inesperado na página {page_id}")
        expected_page_prefix = f"page-{page_id:04}/"
        if row.get("sourceRawFile") != expected_page_prefix + "original-argb1555-256.raw" or \
                row.get("candidatePackedRaw") != expected_page_prefix + "candidate-argb1555-1024.raw" or \
                row.get("bit15PlaneRaw") != expected_page_prefix + "bit15-nearest-1024.raw" or \
                row.get("candidateRGBPNG") != expected_page_prefix + "candidate-rgb-1024.png":
            raise VerificationError(f"Caminhos de arquivo declarados incorretos na página {page_id}")

        source_path = safe_file(part_root, row["sourceRawFile"])
        candidate_path = safe_file(part_root, row["candidatePackedRaw"])
        plane_path = safe_file(part_root, row["bit15PlaneRaw"])
        source_sha, source_crc, source_size = digest(source_path)
        candidate_sha, candidate_crc, candidate_size = digest(candidate_path)
        if source_size != SOURCE_BYTES or source_sha != row.get("sourceRawSHA256") or source_crc != row.get("sourceRawCRC32"):
            raise VerificationError(f"RAW original diverge em tamanho/SHA-256/CRC32 na página {page_id}")
        if candidate_size != CANDIDATE_BYTES or candidate_sha != row.get("candidatePackedSHA256") or candidate_crc != row.get("candidatePackedCRC32"):
            raise VerificationError(f"RAW candidato diverge em tamanho/SHA-256/CRC32 na página {page_id}")
        counts["source_sha256"] += 1
        counts["source_crc32"] += 1
        counts["candidate_sha256"] += 1
        counts["candidate_crc32"] += 1
        byte_totals["source_raw"] += source_size
        byte_totals["candidate_raw"] += candidate_size

        source_bytes = source_path.read_bytes()
        plane = plane_path.read_bytes()
        set_pixels = validate_bit15(source_bytes, plane, page_id)
        if row.get("bit15TotalPixels") != BITPLANE_BYTES or row.get("bit15SetPixels") != set_pixels:
            raise VerificationError(f"Contagem do plano bit15 diverge na página {page_id}")
        total_bit15 += set_pixels
        byte_totals["bit15_plane"] += len(plane)

        original_png = safe_file(part_root, expected_page_prefix + "original-rgb-256.png")
        candidate_png = safe_file(part_root, row["candidateRGBPNG"])
        if png_dimensions(original_png) != (SOURCE_SIDE, SOURCE_SIDE):
            raise VerificationError(f"PNG original não é 256x256 na página {page_id}")
        if png_dimensions(candidate_png) != (CANDIDATE_SIDE, CANDIDATE_SIDE):
            raise VerificationError(f"PNG candidato não é 1024x1024 na página {page_id}")

        merged_entry = index["pages"].get(str(page_id))
        expected_paths = {
            "packedRaw": f"parts/{part_root.name}/page-{page_id:04}/candidate-argb1555-1024.raw",
            "rgbPng": f"parts/{part_root.name}/page-{page_id:04}/candidate-rgb-1024.png",
            "original256": f"parts/{part_root.name}/page-{page_id:04}/original-argb1555-256.raw",
            "originalRgbPng": f"parts/{part_root.name}/page-{page_id:04}/original-rgb-256.png",
            "bit15Plane": f"parts/{part_root.name}/page-{page_id:04}/bit15-nearest-1024.raw",
        }
        if not isinstance(merged_entry, dict) or any(merged_entry.get(k) != v for k, v in expected_paths.items()):
            raise VerificationError(f"Caminhos divergentes no index.json para página {page_id}")
        if merged_entry.get("sourceRawSHA256") != source_sha or merged_entry.get("candidatePackedSHA256") != candidate_sha:
            raise VerificationError(f"Hashes divergentes no index.json para página {page_id}")

    return {
        "status": "ok",
        "scope": "offline_integrity_only",
        "batch": str(batch),
        "sourceArchiveSHA256Declared": SOURCE_SHA256,
        "sourceArchiveRead": False,
        "pages": TOTAL_PAGES,
        "partManifests": len(part_manifests),
        "sourceRawFiles": TOTAL_PAGES,
        "candidateRawFiles": TOTAL_PAGES,
        "bit15PlaneFiles": TOTAL_PAGES,
        "sha256Checks": counts["source_sha256"] + counts["candidate_sha256"],
        "crc32Checks": counts["source_crc32"] + counts["candidate_crc32"],
        "dimensionsChecked": {"source": [SOURCE_SIDE, SOURCE_SIDE], "candidate": [CANDIDATE_SIDE, CANDIDATE_SIDE], "pages": TOTAL_PAGES},
        "rawBytes": byte_totals,
        "candidateToSourceSizeRatio": CANDIDATE_BYTES // SOURCE_BYTES,
        "nearest4xBit15Pages": TOTAL_PAGES,
        "bit15ExpandedSetPixels": total_bit15,
        "runtimeVerified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=Path(__file__).resolve().parents[2] / "staging/hd-textures-full-v1",
                        help="Raiz do lote completo (padrão: staging/hd-textures-full-v1)")
    args = parser.parse_args()
    try:
        result = verify(args.batch)
    except (VerificationError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
