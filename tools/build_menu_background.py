"""Build local menu-background candidates without writing to the source game.

Example:
  python tools/build_menu_background.py --game <source-copy> \
    --image content/art/menu-nosgoth.png --output staging/menu-nosgoth-v1 \
    --localization modules/localization/assets.json \
    --items-image content/art/menu-itens-nosgoth.png

Only native title1.pti and optional bkgdmenu.pti pixels are replaced. Archive table, TIM headers,
other resources and executable remain unchanged. Output is local-only: the DAT
contains original game resources and must not be published. Never launches a game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import tempfile
from pathlib import Path

from PIL import Image

SOURCE_SHA256 = "30295bb8bdd059a3001f4b30d68973fd2e6a3ae50ea444087c8a17e94adeb035"
EXE_HASHES = {
    "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a",
    "396a757334daa8fdf8930de70a63929bbe0cb0d6bc3250ce5a2dd50056c1e243",
}
ARCHIVE_BYTES = 85_923_840
ENTRY_COUNT = 1325
TITLE_INDEX = 92
TITLE_OFFSET = 14_495_744
TITLE_BYTES = 491_540
TITLE_HASH = "db9cce17f69f724c3970ba94d4e76d3430cab8276b037b5a2d022218f05c2a77"
ITEMS_INDEX = 90
ITEMS_OFFSET = 0xCE2000
ITEMS_HASH = "f98130afdcc3d02c715dbaa1677f5f87efaf769636b49d79fbb9159ece3823a4"
WIDTH, HEIGHT = 512, 480
SOURCES = {
    "locals.pc": "2244304cbf1d89f7aaee44c534cf185c0ffd037272deee909247727be1d54d84",
    "DINPUT.dll": None,
    ".soul-reaver-ptbr/subtitles.tsv": None,
    "bigfile.dat": SOURCE_SHA256,
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def title_header(source: bytes) -> bytes:
    if len(source) != ARCHIVE_BYTES or digest(source) != SOURCE_SHA256:
        raise ValueError("Base bigfile.dat desconhecida; nenhum arquivo do jogo foi alterado")
    if struct.unpack_from("<I", source)[0] != ENTRY_COUNT:
        raise ValueError("Contagem de entradas do arquivo incompatível")
    entry = struct.unpack_from("<III4s", source, 4 + TITLE_INDEX * 16)
    if entry != (0xF2C63638, TITLE_BYTES, TITLE_OFFSET, b"TLE1"):
        raise ValueError("Entrada title1.pti incompatível")
    original = source[TITLE_OFFSET:TITLE_OFFSET + TITLE_BYTES]
    if digest(original) != TITLE_HASH:
        raise ValueError("Textura de título original incompatível")
    if struct.unpack_from("<IIIHHHH", original) != (16, 2, TITLE_BYTES - 8, 512, 0, WIDTH, HEIGHT):
        raise ValueError("Cabeçalho TIM incompatível")
    return original[:20]


def encode_title(image: Path, header: bytes) -> bytes:
    with Image.open(image) as original:
        if original.format != "PNG" or original.width * 3 != original.height * 4:
            raise ValueError("A arte deve ser PNG em proporção 4:3; não será cortada automaticamente")
        if "A" in original.getbands() and original.getchannel("A").getextrema() != (255, 255):
            raise ValueError("A arte do menu precisa ter fundo opaco")
        # The native 512x480 texture is drawn as 640x480 by the menu. Export to
        # non-square texture pixels so the final 4:3 composition keeps its shape.
        pixels = original.convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    result = bytearray(header)
    for r, g, b in struct.iter_unpack("BBB", pixels.tobytes()):
        r, g, b = ((channel * 31 + 127) // 255 for channel in (r, g, b))
        result.extend(struct.pack("<H", 0x8000 | r | g << 5 | b << 10))
    return bytes(result)


def items_header(source: bytes) -> bytes:
    # Validate the original archive before using offsets, even when called alone.
    title_header(source)
    entry = struct.unpack_from("<III4s", source, 4 + ITEMS_INDEX * 16)
    if entry != (0xC23115E8, TITLE_BYTES, ITEMS_OFFSET, b"MENU"):
        raise ValueError("Entrada bkgdmenu.pti incompatível")
    original = source[ITEMS_OFFSET:ITEMS_OFFSET + TITLE_BYTES]
    if digest(original) != ITEMS_HASH:
        raise ValueError("Fundo original dos submenus incompatível")
    if struct.unpack_from("<IIIHHHH", original) != (16, 2, TITLE_BYTES - 8, 0, 0, WIDTH, HEIGHT):
        raise ValueError("Cabeçalho TIM dos submenus incompatível")
    return original[:20]


def outside_backgrounds_unchanged(source: bytes, candidate: bytes, regions: list[tuple[int, int]]) -> bool:
    if len(source) != len(candidate):
        return False
    cursor = 0
    for start, end in sorted(regions):
        if source[cursor:start] != candidate[cursor:start]:
            return False
        cursor = end
    return source[cursor:] == candidate[cursor:]


def replace_title(source: bytes, candidate: bytes) -> bytes:
    header = title_header(source)
    if len(candidate) != TITLE_BYTES or candidate[:20] != header:
        raise ValueError("A substituição deve preservar o cabeçalho e o tamanho TIM")
    result = source[:TITLE_OFFSET] + candidate + source[TITLE_OFFSET + TITLE_BYTES:]
    if result == source:
        raise ValueError("A textura candidata é igual à original")
    return result


def decode_title(tim: bytes) -> Image.Image:
    pixels = bytearray()
    for (value,) in struct.iter_unpack("<H", tim[20:]):
        pixels.extend(((value & 31) * 255 // 31, ((value >> 5) & 31) * 255 // 31, ((value >> 10) & 31) * 255 // 31))
    return Image.frombytes("RGB", (WIDTH, HEIGHT), bytes(pixels))


def localization_payloads(manifest: Path | None) -> tuple[list[dict], list[tuple[str, bytes]]]:
    if manifest is None:
        return [], []
    record = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if record.get("schema") != 1 or not 1 <= len(record.get("assets", [])) <= 4:
        raise ValueError("Manifesto de localização inválido")
    entries, payloads, names, files = [], [], set(), set()
    for entry in record["assets"]:
        name, payload = entry["file"], entry["payload"]
        if name not in SOURCES or name in names or payload in files or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", payload):
            raise ValueError("Entrada de localização desconhecida, duplicada ou caminho inválido")
        if entry.get("source_sha256") != SOURCES[name] or not re.fullmatch(r"[a-f0-9]{64}", entry["result_sha256"]):
            raise ValueError("Hash de origem ou resultado incompatível")
        raw = (manifest.parent / payload).read_bytes()
        if digest(raw) != entry["result_sha256"]:
            raise ValueError(f"Payload de localização alterado: {name}")
        names.add(name)
        files.add(payload)
        if name != "bigfile.dat":
            if payload == "asset-bigfile.dat":
                raise ValueError("Nome do payload do menu já ocupado")
            entries.append(entry)
            payloads.append((payload, raw))
    return entries, payloads


def build(game: Path, image: Path, output: Path, localization: Path | None = None, items_image: Path | None = None) -> dict:
    game, image, output = (path.resolve() for path in (game, image, output))
    if output.exists() or output.is_relative_to(game):
        raise ValueError("Escolha uma saída nova fora da instalação do jogo")
    if digest((game / "kain2.exe").read_bytes()) not in EXE_HASHES:
        raise ValueError("Executável de origem incompatível")
    source = (game / "bigfile.dat").read_bytes()
    header = title_header(source)
    image_bytes = image.read_bytes()
    tim = encode_title(image, header)
    if image.read_bytes() != image_bytes:
        raise ValueError("A arte mudou durante a conversão; candidato recusado")
    candidate = replace_title(source, tim)
    regions = [(TITLE_OFFSET + 20, TITLE_OFFSET + TITLE_BYTES)]
    backgrounds = [{"entry": "title1.pti", "index": TITLE_INDEX, "offset": TITLE_OFFSET,
                    "image_sha256": digest(image_bytes), "tim_sha256": digest(tim)}]
    items_tim, items_bytes = None, None
    if items_image is not None:
        items_image = items_image.resolve()
        items_bytes = items_image.read_bytes()
        items_tim = encode_title(items_image, items_header(source))
        if items_image.read_bytes() != items_bytes:
            raise ValueError("A arte dos submenus mudou durante a conversão; candidato recusado")
        candidate = candidate[:ITEMS_OFFSET] + items_tim + candidate[ITEMS_OFFSET + TITLE_BYTES:]
        regions.append((ITEMS_OFFSET + 20, ITEMS_OFFSET + TITLE_BYTES))
        backgrounds.append({"entry": "bkgdmenu.pti", "index": ITEMS_INDEX, "offset": ITEMS_OFFSET,
                            "image": str(items_image), "image_sha256": digest(items_bytes),
                            "tim_sha256": digest(items_tim), "scope": "main menu choices after Enter"})
    if not outside_backgrounds_unchanged(source, candidate, regions):
        raise ValueError("Alteração fora das regiões de pixels permitidas; candidato recusado")
    entries, payloads = localization_payloads(localization)
    entries.append({"file": "bigfile.dat", "source_sha256": SOURCE_SHA256, "result_sha256": digest(candidate), "payload": "asset-bigfile.dat"})
    report = {
        "schema": 1, "local_only": True, "game_launched": False, "runtime_verified": False,
        "source_game": str(game), "image": str(image), "image_sha256": digest(image_bytes),
        "source_sha256": SOURCE_SHA256, "result_sha256": digest(candidate),
        "entry": "\\kain2\\game\\psx\\frontend\\title1.pti", "entry_index": TITLE_INDEX,
        "entry_offset": TITLE_OFFSET, "entry_bytes": TITLE_BYTES,
        "texture_dimensions": [WIDTH, HEIGHT], "expected_display_aspect": "4:3",
        "format": "TIM RGB555 with native high bit", "archive_bytes": len(candidate),
        "archive_table_unchanged": candidate[:4 + ENTRY_COUNT * 16] == source[:4 + ENTRY_COUNT * 16],
        "tim_header_unchanged": tim[:20] == header,
        "bytes_outside_title_unchanged": candidate[:TITLE_OFFSET] == source[:TITLE_OFFSET] and candidate[TITLE_OFFSET + TITLE_BYTES:] == source[TITLE_OFFSET + TITLE_BYTES:],
        "bytes_outside_backgrounds_unchanged": True, "backgrounds": backgrounds,
        "changed_pixel_bytes": sum(a != b for a, b in zip(source[TITLE_OFFSET + 20:TITLE_OFFSET + TITLE_BYTES], tim[20:])),
        "localization_files": len(entries),
    }
    # All preflight checks finish before the output tree is created.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".menu-", dir=output.parent) as temporary:
        staged = Path(temporary)
        for name, raw in payloads:
            (staged / name).write_bytes(raw)
        (staged / "asset-bigfile.dat").write_bytes(candidate)
        (staged / "title1.pti").write_bytes(tim)
        (staged / "menu-source.png").write_bytes(image_bytes)
        decoded = decode_title(tim)
        decoded.save(staged / "texture-native.png")
        decoded.resize((640, 480), Image.Resampling.LANCZOS).save(staged / "preview-4x3.png")
        if items_tim is not None:
            (staged / "bkgdmenu.pti").write_bytes(items_tim)
            (staged / "items-source.png").write_bytes(items_bytes)
            decode_title(items_tim).resize((640, 480), Image.Resampling.LANCZOS).save(staged / "items-preview-4x3.png")
        (staged / "assets.json").write_text(json.dumps({"schema": 1, "assets": entries}, indent=2), encoding="utf-8")
        (staged / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        if output.exists():
            raise ValueError("A saída apareceu durante o empacotamento; preservada")
        staged.rename(output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--localization", type=Path)
    parser.add_argument("--items-image", type=Path, help="Arte PNG 4:3 para bkgdmenu.pti, seleção do menu após Enter")
    args = parser.parse_args()
    try:
        print(json.dumps(build(**vars(args)), ensure_ascii=False))
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
