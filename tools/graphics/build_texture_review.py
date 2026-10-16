"""Build a browsable visual review of a finished HD texture batch.

Reads the batch `index.json` (root-relative paths) and emits side-by-side
original/candidate crops plus an `index.html` and a hashes manifest. This is a
human-review aid only: it does not prove the in-game loader, UVs, alpha or
appearance.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image

PREVIEW = 512


def side_by_side(original: Path, candidate: Path) -> Image.Image:
    with Image.open(original) as src:
        left = src.convert("RGB").resize((PREVIEW, PREVIEW), Image.NEAREST)
    with Image.open(candidate) as src:
        right = src.convert("RGB").resize((PREVIEW, PREVIEW), Image.LANCZOS)
    sheet = Image.new("RGB", (PREVIEW * 2 + 8, PREVIEW), (16, 20, 28))
    sheet.paste(left, (0, 0))
    sheet.paste(right, (PREVIEW + 8, 0))
    return sheet


def build(pack: Path, output: Path, count: int) -> dict:
    pack, output = Path(pack), Path(output)
    index = json.loads((pack / "index.json").read_text(encoding="utf-8"))
    pages = sorted(index["pages"], key=lambda k: int(k))
    if output.exists():
        raise ValueError("Escolha uma pasta de saída nova e inexistente")
    if count <= 0:
        raise ValueError("--count precisa ser positivo")
    step = max(1, len(pages) // count)
    selected = pages[::step][:count]
    output.mkdir(parents=True)
    rows = []
    for page in selected:
        record = index["pages"][page]
        name = f"page-{int(page):04}"
        sheet = side_by_side(pack / record["originalRgbPng"], pack / record["rgbPng"])
        sheet.save(output / f"{name}.jpg", quality=88)
        rows.append({"page": int(page), "image": f"{name}.jpg", **record})
    (output / "manifest.json").write_text(json.dumps(
        {"schema": 1, "source": str(pack), "pages": rows, "preview": PREVIEW,
         "runtimeVerified": False,
         "note": "esquerda: original 256x256; direita: candidata 1024x1024 reduzida"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    cards = "\n".join(
        f'<figure><img src="{row["image"]}" loading="lazy"><figcaption>página {row["page"]}</figcaption></figure>'
        for row in rows)
    (output / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Revisão de texturas HD</title>"
        "<style>body{background:#0b1220;color:#cbd5e1;font:14px system-ui;margin:24px}"
        "h1{font-size:18px}figure{align-items:center;background:#111827;border:1px solid #1f2937;"
        "border-radius:10px;display:flex;flex-direction:column;gap:6px;margin:0;padding:10px}"
        "figure img{image-rendering:pixelated;max-width:100%;width:520px}"
        ".grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}"
        "figcaption{color:#94a3b8;font-size:12px}</style>"
        f"<h1>Revisão de texturas HD — {len(rows)} páginas</h1>"
        "<p style='color:#94a3b8'>Esquerda: original 256×256. Direita: candidata 1024×1024. "
        "Sem aprovação estética, sem prova de carregador/UV/alpha no jogo.</p>"
        f"<div class='grid'>{cards}</div>", encoding="utf-8")
    return {"output": str(output), "pages": len(rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=24)
    args = parser.parse_args()
    print(json.dumps(build(args.pack, args.output, args.count), ensure_ascii=False))
