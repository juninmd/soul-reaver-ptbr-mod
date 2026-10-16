"""Build an isolated Unicode glyph atlas suitable for a future D3D upload.

The binary contract is intentionally tiny: UTF-8 text is decoded to codepoints,
each supported codepoint maps to an atlas rectangle, and legacy high-byte icon
tokens remain reserved rather than being interpreted as UTF-8.
"""
from pathlib import Path
import argparse, json, unicodedata
from PIL import Image, ImageDraw, ImageFont

TEXT = "KAIN — Você ouviu? A névoa está à À á Á â Â ã Ã é É ê Ê í Í ó Ó ô Ô õ Õ ú Ú ü Ü ç Ç. 100%… “Agora”, disse Raziel."

def build(font_path, out):
    font = ImageFont.truetype(str(font_path), 88)
    chars = sorted(set(TEXT), key=ord)
    cell_w, cell_h, cols = 128, 128, 16
    rows = (len(chars) + cols - 1) // cols
    atlas = Image.new("RGBA", (cell_w * cols, cell_h * rows), (0, 0, 0, 0))
    draw = ImageDraw.Draw(atlas); glyphs = {}
    for i, char in enumerate(chars):
        x, y = (i % cols) * cell_w, (i // cols) * cell_h
        draw.text((x + 8, y + 8), char, font=font, fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(0,0,0,255))
        glyphs[f"U+{ord(char):04X}"] = {"char": char, "x": x, "y": y, "w": cell_w, "h": cell_h}
    out.mkdir(parents=True, exist_ok=True)
    atlas.save(out / "unicode-atlas-4k.png")
    mapping = {"schema": 1, "font": str(font_path), "cell": [cell_w, cell_h], "atlas": [atlas.width, atlas.height], "glyphs": glyphs,
               "legacy_icon_tokens": "bytes 0x80-0xFF remain reserved and are not decoded as UTF-8"}
    (out / "unicode-atlas.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return mapping

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, required=True); ap.add_argument("--font", type=Path, default=Path(r"C:\Windows\Fonts\arial.ttf")); a = ap.parse_args()
    m = build(a.font, a.output); assert "U+00C1" in m["glyphs"] and "U+2014" in m["glyphs"] and "U+2026" in m["glyphs"]
    print(json.dumps({"atlas": m["atlas"], "glyphs": len(m["glyphs"]), "output": str(a.output)}))
