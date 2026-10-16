"""Offline Unicode subtitle parser and high-resolution proof renderer.

This is deliberately separate from the native subtitle DLL. It proves text
normalization, validation, wrapping and bitmap output only.
"""
from __future__ import annotations
import argparse, json, unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SAMPLE = "KAIN — Você ouviu? A névoa está à À á Á â Â ã Ã é É ê Ê í Í ó Ó ô Ô õ Õ ú Ú ü Ü ç Ç. 100%… “Agora”, disse Raziel."

def parse_utf8(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"ok": False, "error": "invalid_utf8", "offset": exc.start}
    normalized = unicodedata.normalize("NFC", text)
    controls = [{"index": i, "codepoint": f"U+{ord(c):04X}"}
                for i, c in enumerate(normalized)
                if unicodedata.category(c).startswith("C") and c not in "\t\n\r"]
    if controls:
        return {"ok": False, "error": "control_character", "controls": controls}
    return {"ok": True, "text": normalized, "nfc": normalized == text,
            "codepoints": len(normalized)}

def wrap(draw, text, font, max_width):
    lines, current = [], ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if draw.textlength(word, font=font) > max_width:
            raise ValueError("unbroken_word_exceeds_layout_width")
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current); current = word
    if current: lines.append(current)
    return lines

def render(text: str, font_path: Path, out: Path, width: int, height: int):
    scale = width / 1920
    size = max(24, round(44 * scale))
    font = ImageFont.truetype(str(font_path), size)
    image = Image.new("RGB", (width, height), (8, 12, 19))
    draw = ImageDraw.Draw(image)
    margin = round(100 * scale); max_width = width - 2 * margin
    lines = wrap(draw, text, font, max_width)
    line_h = round(size * 1.35); y = height - margin - line_h * len(lines) - round(28 * scale)
    if y < margin:
        raise ValueError("vertical_layout_overflow")
    # measured dark panel, white text and amber accent make clipping visible
    draw.rounded_rectangle((margin-round(24*scale), y-round(18*scale), width-margin+round(24*scale), height-margin+round(22*scale)), radius=round(18*scale), fill=(0,0,0), outline=(90,110,130), width=max(1,round(2*scale)))
    for line in lines:
        draw.text((margin, y), line, font=font, fill=(245,245,240), stroke_width=max(1,round(2*scale)), stroke_fill=(15,15,20)); y += line_h
    image.save(out, "PNG")
    return {"width": width, "height": height, "font": str(font_path), "font_px": size, "lines": lines}

def font_coverage(font_path: Path, chars: str):
    """Read cmap directly when fontTools is available; otherwise say so."""
    try:
        from fontTools.ttLib import TTFont
        cmap = set().union(*(set(t.cmap.keys()) for t in TTFont(str(font_path))["cmap"].tables))
        return {"method": "fontTools.cmap", "missing": [f"U+{ord(c):04X}" for c in chars if ord(c) not in cmap]}
    except ImportError:
        return {"method": "unavailable_fontTools", "missing": None, "note": "Instale fontTools para consultar cmap; Pillow getmask não é usado como prova."}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, required=True); ap.add_argument("--font", type=Path, default=Path(r"C:\Windows\Fonts\arial.ttf")); args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    import sys
    local_packages = Path("staging/unicode-poc-v1/python-packages")
    if local_packages.exists(): sys.path.insert(0, str(local_packages.resolve()))
    cases = {"valid_nfc": SAMPLE.encode("utf-8"), "decomposed": "você e açúcar".encode("utf-8"), "invalid_utf8": b"Raziel \xff", "control": "ok\x01 ruim".encode("utf-8"), "missing_glyph_candidate": "CJK \u4e00".encode("utf-8")}
    results = {name: parse_utf8(raw) for name, raw in cases.items()}
    assert results["valid_nfc"]["ok"] and "À" in results["valid_nfc"]["text"] and "…" in results["valid_nfc"]["text"]
    assert results["decomposed"]["ok"] and results["decomposed"]["text"] == "você e açúcar"
    assert not results["invalid_utf8"]["ok"] and results["invalid_utf8"]["error"] == "invalid_utf8"
    assert not results["control"]["ok"] and results["control"]["error"] == "control_character"
    results["font_coverage"] = font_coverage(args.font, results["valid_nfc"]["text"] + "\u4e00")
    try:
        render("X" * 1000, args.font, args.output / "should-not-exist.png", 1920, 1080)
    except ValueError as exc:
        assert str(exc) == "unbroken_word_exceeds_layout_width"; results["layout_overflow"] = "rejected"
    else: raise AssertionError("layout overflow was accepted")
    try:
        render("palavra " * 200, args.font, args.output / "should-not-exist-vertical.png", 1920, 1080)
    except ValueError as exc:
        assert str(exc) == "vertical_layout_overflow"; results["vertical_overflow"] = "rejected"
    else: raise AssertionError("vertical overflow was accepted")
    # Render only accepted normalized sample; each file has native dimensions.
    results["render"] = [render(results["valid_nfc"]["text"], args.font, args.output / f"subtitle-{w}.png", w, round(w*9/16)) for w in (1920, 2560, 3840)]
    (args.output / "report.json").write_text(json.dumps({"schema": 1, "cases": results, "offline_only": True}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "renders": 3, "parser_cases": 4}, ensure_ascii=False))
if __name__ == "__main__": main()
