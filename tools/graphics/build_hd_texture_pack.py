"""Build offline 4x texture candidates from the supported Soul Reaver archive.

The source archive and its stored pages are immutable. Bit 15 is preserved as
an uninterpreted plane; no claim is made about transparency semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib

from PIL import Image

SOURCE_SHA256 = "f287fc2b7452aa3f2592c5bab36654ac8ed2aa1be571e607a31e29a3666868fa"
HEADER = 4096
SIDE = 256
SCALE = 4
PAGE_BYTES = SIDE * SIDE * 2


def digest(data: bytes) -> dict[str, str]:
    return {"sha256": hashlib.sha256(data).hexdigest(), "crc32": f"{zlib.crc32(data):08x}"}


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def unpack_page(raw: bytes) -> tuple[Image.Image, bytes]:
    if len(raw) != PAGE_BYTES:
        raise ValueError(f"A página precisa ter {PAGE_BYTES} bytes")
    rgb = bytearray(SIDE * SIDE * 3)
    plane = bytearray(SIDE * SIDE)
    for i, (word,) in enumerate(struct.iter_unpack("<H", raw)):
        r5, g5, b5 = (word >> 10) & 31, (word >> 5) & 31, word & 31
        rgb[i * 3:i * 3 + 3] = bytes((r5 * 255 // 31,
                                      g5 * 255 // 31,
                                      b5 * 255 // 31))
        plane[i] = (word >> 15) & 1
    return Image.frombytes("RGB", (SIDE, SIDE), bytes(rgb)), bytes(plane)


def expand_plane_nearest(plane: bytes) -> bytes:
    if len(plane) != SIDE * SIDE:
        raise ValueError("Plano bit 15 inválido")
    out = bytearray(SIDE * SCALE * SIDE * SCALE)
    width = SIDE * SCALE
    for y in range(SIDE):
        row = bytes(plane[y * SIDE:(y + 1) * SIDE])
        expanded = b"".join(bytes((value,)) * SCALE for value in row)
        for dy in range(SCALE):
            start = (y * SCALE + dy) * width
            out[start:start + width] = expanded
    return bytes(out)


def transparent_plane(raw: bytes) -> bytes:
    """Máscara 256x256 (1 = palavra 0x0000 original, texel transparente no formato PSX)."""
    if len(raw) != PAGE_BYTES:
        raise ValueError(f"A página precisa ter {PAGE_BYTES} bytes")
    return bytes(1 if word == 0 else 0 for (word,) in struct.iter_unpack("<H", raw))


def pack_page(rgb: Image.Image, bit15: bytes, transparent: bytes | None = None) -> bytes:
    if rgb.mode != "RGB" or rgb.size != (SIDE * SCALE, SIDE * SCALE):
        raise ValueError("RGB candidata precisa ser RGB 1024x1024")
    width = SIDE * SCALE
    if len(bit15) != width * width:
        raise ValueError("Plano bit 15 precisa ser 1024x1024")
    if transparent is not None and len(transparent) != width * width:
        raise ValueError("Máscara de transparência precisa ser 1024x1024")
    pixels = rgb.tobytes()
    packed = bytearray(width * width * 2)
    for i in range(width * width):
        r, g, b = pixels[i * 3:i * 3 + 3]
        word = (0x8000 if bit15[i] else 0) | (((r * 31 + 127) // 255) << 10) | (((g * 31 + 127) // 255) << 5) | ((b * 31 + 127) // 255)
        if transparent is not None:
            # 0x0000 é transparente: o upscale não pode preenchê-lo (franjas)
            # nem zerar texels opacos escuros (somem).
            if transparent[i]:
                word = 0
            elif word == 0:
                word = 1
        struct.pack_into("<H", packed, i * 2, word)
    return bytes(packed)


def _run_ai(exe: Path, model: Path, source_png: Path, output_png: Path) -> None:
    cmd = [str(exe), "-i", str(source_png), "-o", str(output_png), "-n", model.stem, "-s", str(SCALE), "-f", "png"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=exe.parent)
    if result.returncode:
        raise RuntimeError(f"RealESRGAN falhou ({result.returncode}): {result.stderr[-2000:]}")
    if not output_png.is_file():
        raise RuntimeError("RealESRGAN não criou a saída; não há fallback de redimensionamento")
    with Image.open(output_png) as generated:
        generated.load()
        if generated.size != (SIDE * SCALE, SIDE * SCALE):
            raise RuntimeError(f"Saída RealESRGAN tem dimensões inesperadas: {generated.size}")
        if generated.mode not in ("RGB", "RGBA"):
            raise RuntimeError(f"Modo inesperado na saída RealESRGAN: {generated.mode}")
        if generated.mode == "RGBA":
            # The source has no interpreted alpha. Preserve generated RGB only.
            generated.convert("RGB").save(output_png)
        elif generated.mode != "RGB":
            raise RuntimeError("Saída deve ser RGB")


def build(archive: Path, pages: list[int], output: Path, realesrgan: Path,
          model_name: str = "realesrgan-x4plus") -> dict:
    archive, output, realesrgan = archive.resolve(), output.resolve(), realesrgan.resolve()
    if output.exists():
        raise ValueError("A pasta de saída precisa ser nova e inexistente")
    if output.is_relative_to(archive.parent) or output in archive.parents:
        raise ValueError("A pasta de saída deve ficar fora do diretório do arquivo-fonte")
    if not pages or len(set(pages)) != len(pages):
        raise ValueError("Informe páginas explícitas, sem duplicatas")
    if any(type(i) is not int or not 0 <= i < 1287 for i in pages):
        raise ValueError("Índice de página fora do intervalo 0..1286")
    if not realesrgan.is_file():
        raise ValueError("Executável RealESRGAN local não encontrado")
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("SHA-256 do arquivo-fonte não corresponde ao original suportado")
    if len(data) != HEADER + 1287 * PAGE_BYTES:
        raise ValueError("Tamanho/layout do arquivo-fonte inválido")
    models_dir = realesrgan.parent / "models"
    model = models_dir / f"{model_name}.param"
    weights = models_dir / f"{model_name}.bin"
    if not model.is_file() or not weights.is_file():
        raise ValueError(f"Modelo local incompleto: {model.name} e {weights.name} são necessários")

    # Validate availability before creating artifacts or running the GPU path.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    rows = []
    with tempfile.TemporaryDirectory(prefix="sr-hd-texture-") as temp_name:
        temp = Path(temp_name)
        for index in pages:
            start = HEADER + index * PAGE_BYTES
            raw = data[start:start + PAGE_BYTES]
            rgb256, plane256 = unpack_page(raw)
            input_png = temp / f"page-{index:04}.png"
            result_png = temp / f"page-{index:04}-x4.png"
            rgb256.save(input_png)
            _run_ai(realesrgan, model, input_png, result_png)
            with Image.open(result_png) as loaded:
                candidate = loaded.convert("RGB")
            plane1024 = expand_plane_nearest(plane256)
            packed = pack_page(candidate, plane1024, expand_plane_nearest(transparent_plane(raw)))
            folder = output / f"page-{index:04}"
            folder.mkdir(exist_ok=False)
            shutil.copyfile(input_png, folder / "original-rgb-256.png")
            shutil.copyfile(result_png, folder / "candidate-rgb-1024.png")
            (folder / "original-argb1555-256.raw").write_bytes(raw)
            (folder / "bit15-nearest-1024.raw").write_bytes(plane1024)
            (folder / "candidate-argb1555-1024.raw").write_bytes(packed)
            rows.append({
                "id": index,
                "sourceOffset": start,
                "sourceRawSHA256": digest(raw)["sha256"],
                "sourceRawCRC32": digest(raw)["crc32"],
                "sourceRawFile": f"page-{index:04}/original-argb1555-256.raw",
                "sourceDimensions": [SIDE, SIDE],
                "candidateDimensions": [SIDE * SCALE, SIDE * SCALE],
                "candidateFormat": "little-endian 16-bit RGB5 plus bit15",
                "candidateRGBPNG": f"page-{index:04}/candidate-rgb-1024.png",
                "candidatePackedRaw": f"page-{index:04}/candidate-argb1555-1024.raw",
                "bit15PlaneRaw": f"page-{index:04}/bit15-nearest-1024.raw",
                "bit15SetPixels": sum(plane1024),
                "bit15TotalPixels": len(plane1024),
                "alphaRule": "bit 15 replicated 4x by nearest neighbor (meaning unverified); original 0x0000 texels stay 0x0000 and opaque texels never quantize to 0x0000",
                "candidatePackedSHA256": digest(packed)["sha256"],
                "candidatePackedCRC32": digest(packed)["crc32"],
                "aiModel": model_name,
                "aiProvenance": {
                    "executable": str(realesrgan),
                    "executableSHA256": file_sha256(realesrgan),
                    "modelParam": str(model),
                    "modelParamSHA256": file_sha256(model),
                    "modelWeights": str(weights),
                    "modelWeightsSHA256": file_sha256(weights),
                },
                "runtimeVerified": False,
            })
    manifest = {"schema": 1, "sourceArchiveSHA256": SOURCE_SHA256,
                "sourceArchive": str(archive), "sourceHeaderBytes": HEADER,
                "sourcePageCount": 1287, "sourcePageDimensions": [SIDE, SIDE],
                "sourceFormat": "little-endian ARGB1555 stored words; bit 15 semantics unverified",
                "scale": SCALE, "processing": "local RealESRGAN x4plus; RGB-only synthesis; no interpolation fallback",
                "rgb5Quantization": "pack uses nearest integer ((channel*31+127)//255); unpack uses floor(v5*255/31)",
                "pages": rows, "runtimeVerified": False,
                "limitations": ["1024x1024 candidate per 256x256 page, not native 4K", "no game/runtime validation", "no character identity inferred"]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", required=True, help="Índices explícitos, zero-based")
    parser.add_argument("--out", type=Path, required=True, help="Diretório novo, ainda inexistente")
    parser.add_argument("--realesrgan", type=Path, required=True, help="Executável local realesrgan-ncnn-vulkan")
    parser.add_argument("--model", default="realesrgan-x4plus")
    args = parser.parse_args()
    result = build(args.archive, args.pages, args.out, args.realesrgan, args.model)
    print(json.dumps({"pages": len(result["pages"]), "output": str(args.out.resolve()), "runtimeVerified": False}))


if __name__ == "__main__":
    main()
