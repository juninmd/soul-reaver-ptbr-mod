"""Compare the supported classic PC texture archive without modifying either input.

ARGB1555 page layout documented by Ben Lincoln's SoulReaverPCTextureFile.cs
(The Lost Worlds). Exports opaque RGB previews: transparency needs runtime review.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import struct

from PIL import Image

SOURCE_SHA256 = "f287fc2b7452aa3f2592c5bab36654ac8ed2aa1be571e607a31e29a3666868fa"
HEADER = 4096
PAGE = 256 * 256 * 2


def decode_page(data, index):
    pixels = bytearray()
    for (value,) in struct.iter_unpack("<H", data[HEADER + index * PAGE:HEADER + (index + 1) * PAGE]):
        # Opaque previews expose the stored RGB, including unused palette regions.
        pixels.extend((((value >> 10) & 31) * 8, ((value >> 5) & 31) * 8, (value & 31) * 8))
    return Image.frombytes("RGB", (256, 256), bytes(pixels))


def compare(source, candidate, output):
    source, candidate, output = (p.resolve() for p in (source, candidate, output))
    if output.exists() or any(output.is_relative_to(p.parent) for p in (source, candidate)):
        raise ValueError("Choose a fresh output directory outside both input directories")
    original, modified = source.read_bytes(), candidate.read_bytes()
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unsupported original texture archive hash")
    if len(original) != len(modified) or (len(original) - HEADER) % PAGE:
        raise ValueError("Different size or truncated fixed-page texture archive")
    if original[:HEADER] != modified[:HEADER]:
        raise ValueError("Candidate changed the archive header; this comparison does not support it")
    count = (len(original) - HEADER) // PAGE
    changed = []
    for index in range(count):
        start = HEADER + index * PAGE
        a, b = original[start:start + PAGE], modified[start:start + PAGE]
        if a != b:
            changed.append(dict(index=index, changed_bytes=sum(x != y for x, y in zip(a, b))))
    output.mkdir(parents=True)
    rows = []
    for row in changed:
        index = row["index"]
        for label, data in (("original", original), ("mini-mod", modified)):
            decode_page(data, index).save(output / f"atlas-{index:04}-{label}.png")
        rows.append(f'<article><h2>Atlas {index}</h2><div class="pair">'
                    + ''.join(f'<figure><img width="256" height="256" src="atlas-{index:04}-{label}.png"><figcaption>{label}</figcaption></figure>' for label in ("original", "mini-mod"))
                    + f'</div><p>{row["changed_bytes"]} bytes alterados.</p></article>')
    page = '''<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Texturas: original e mini-mod</title>
<style>body{background:#17191d;color:#eee;font:17px system-ui;max-width:1000px;margin:2rem auto;padding:0 1rem}a{color:#9bd4ff}.pair{display:flex;flex-wrap:wrap;gap:24px}figure{margin:0}img{width:256px;height:256px;image-rendering:pixelated}article{border-top:1px solid #555;padding:1rem 0}figcaption{padding:8px 0}</style>
<h1>Original × mini-mod de STF911</h1><p>Comparação offline dos 22 atlas modificados. Mesma resolução: 256×256. Não é uma demonstração de texturas 4K.</p>
<p>Imagens RGB opacas para inspeção. Áreas sem uso podem ter cores fortes; transparência, UV, iluminação e resultado final precisam ser conferidos no jogo.</p>
<p><a href="https://www.moddb.com/mods/soul-reaver-1-texture-mini-mod">Página e autoria do mini-mod</a>. O autor reconhece alguns chefes claros demais.</p>'''
    (output / "comparacao.html").write_text(page + ''.join(rows) + '</html>', encoding="utf-8")
    report = dict(schema=1, source_sha256=SOURCE_SHA256,
                  candidate_sha256=hashlib.sha256(modified).hexdigest(), bytes=len(original),
                  header_identical=True, atlas_count=count, atlas_dimensions=[256, 256],
                  format="ARGB1555", changed_count=len(changed), changed=changed,
                  rgb_preview_ignores_alpha=True, inputs_modified=False, runtime_verified=False,
                  author="STF911", source_page="https://www.moddb.com/mods/soul-reaver-1-texture-mini-mod")
    (output / "inspection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "LEIA-ME.md").write_text(
        "# Comparação do mini-mod\n\nAbra `comparacao.html` no navegador. Cada par mostra original e mini-mod na mesma resolução.\n\n"
        "Avalie a aparência de Raziel e dos outros personagens; algumas alterações aumentam bastante o contraste. "
        "A comparação é de atlas opacos, sem iluminação do jogo; não comprova UV/transparência nem compatibilidade em runtime. "
        "Nenhum arquivo foi aplicado na Steam. `inspection.json` registra hashes e índices. "
        "O mini-mod pode servir de referência/opção artística, mas não aumenta a resolução das texturas.\n",
        encoding="utf-8")
    return {k: v for k, v in report.items() if k != "changed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "candidate", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.source, args.candidate, args.output), indent=2))
