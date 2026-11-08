"""Focused offline tests for ARGB1555 page conversion and fail-closed I/O."""
import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import tempfile
import unittest

from PIL import Image

MODULE_PATH = Path(__file__).with_name("build_hd_texture_pack.py")
SPEC = importlib.util.spec_from_file_location("build_hd_texture_pack", MODULE_PATH)
hd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hd)


class PackRoundTripTests(unittest.TestCase):
    def test_output_inside_source_install_is_rejected_before_processing(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "game"
            game.mkdir()
            archive = game / "textures.big"
            archive.write_bytes(b"immutable input")
            output = game / "hd-candidate"
            with self.assertRaisesRegex(ValueError, "fora do diretório"):
                hd.build(archive, [4], output, Path(temporary) / "missing-ai.exe")
            self.assertFalse(output.exists())
            self.assertEqual(archive.read_bytes(), b"immutable input")

    def test_known_words_and_bitplane_nearest_replication(self):
        words = [0x0000, 0x8000, 0x7FFF, 0xFFFF]
        raw = struct.pack("<4H", *words) + bytes(hd.PAGE_BYTES - 8)
        image, plane = hd.unpack_page(raw)
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(image.getpixel((1, 0)), (0, 0, 0))
        self.assertEqual(image.getpixel((2, 0)), (255, 255, 255))
        self.assertEqual(image.getpixel((3, 0)), (255, 255, 255))
        self.assertEqual(plane[:4], bytes((0, 1, 0, 1)))
        expanded = hd.expand_plane_nearest(plane)
        width = hd.SIDE * hd.SCALE
        self.assertEqual(expanded[:16], bytes((0,)*4 + (1,)*4 + (0,)*4 + (1,)*4))
        self.assertEqual(expanded[width:width + 16], expanded[:16])
        rgb = Image.new("RGB", (width, width), (255, 128, 0))
        packed = hd.pack_page(rgb, expanded)
        first = struct.unpack_from("<4H", packed)
        self.assertEqual(first, (0x7E00, 0x7E00, 0x7E00, 0x7E00))
        self.assertEqual(len(packed), width * width * 2)

    def test_wrong_dimensions_and_plane_length_refused(self):
        with self.assertRaises(ValueError):
            hd.unpack_page(b"short")
        with self.assertRaises(ValueError):
            hd.expand_plane_nearest(b"short")
        with self.assertRaises(ValueError):
            hd.pack_page(Image.new("RGB", (256, 256)), bytes(1024 * 1024))

    def test_all_32_rgb5_values_roundtrip_and_preserve_bit15(self):
        words = [((value << 10) | (value << 5) | value | (0x8000 if value & 1 else 0))
                 for value in range(32)]
        raw = struct.pack("<32H", *words) + bytes(hd.PAGE_BYTES - 64)
        original_rgb, original_plane = hd.unpack_page(raw)
        expanded_plane = hd.expand_plane_nearest(original_plane)
        width = hd.SIDE * hd.SCALE
        scaled_pixels = bytearray(width * width * 3)
        for y in range(hd.SIDE):
            for x in range(hd.SIDE):
                pixel = original_rgb.getpixel((x, y))
                for dy in range(hd.SCALE):
                    for dx in range(hd.SCALE):
                        offset = ((y * hd.SCALE + dy) * width + x * hd.SCALE + dx) * 3
                        scaled_pixels[offset:offset + 3] = bytes(pixel)
        repacked = hd.pack_page(Image.frombytes("RGB", (width, width), bytes(scaled_pixels)), expanded_plane)
        got = tuple(struct.unpack_from("<H", repacked, ((value // hd.SIDE) * hd.SCALE * width + (value % hd.SIDE) * hd.SCALE) * 2)[0]
                    for value in range(32))
        self.assertEqual(got, tuple(words))
        repacked_words = struct.iter_unpack("<H", repacked)
        bit15_count = sum((word[0] >> 15) & 1 for word in repacked_words)
        self.assertEqual(bit15_count, sum(value & 1 for value in range(32)) * hd.SCALE * hd.SCALE)

    def test_source_page_unpack_matches_ai_input_png_exactly(self):
        repo = MODULE_PATH.parents[2]
        # Read only from a local/staged copy. The Steam installation must never be
        # touched implicitly by the test suite; set SRMOD_TEXTURES_BIG to opt in.
        candidates = []
        env = os.environ.get("SRMOD_TEXTURES_BIG")
        if env:
            candidates.append(Path(env))
        candidates.append(repo / "staging/source-archive-verify/textures.big")
        candidates.append(repo / "staging/texture-mini-review-v1/textures.big")
        archive = next((path for path in candidates if path.is_file()), None)
        if archive is None:
            self.skipTest("no local textures.big copy available (set SRMOD_TEXTURES_BIG)")
        data = archive.read_bytes()
        if hashlib.sha256(data).hexdigest() != hd.SOURCE_SHA256:
            self.skipTest("Steam source archive is not the supported immutable source")
        raw = data[hd.HEADER + 4 * hd.PAGE_BYTES:hd.HEADER + 5 * hd.PAGE_BYTES]
        decoded, _ = hd.unpack_page(raw)
        preserved = repo / "staging/offline-wave2/textures/page4-hd-candidate-run2/page-0004/original-rgb-256.png"
        with Image.open(preserved) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (hd.SIDE, hd.SIDE))
            self.assertEqual(decoded.tobytes(), image.tobytes())


class BuildGuardsTests(unittest.TestCase):
    def test_wrong_source_hash_and_existing_destination_preserved(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "game").mkdir()
            archive = root / "game/textures.big"
            archive.write_bytes(b"not the supported archive")
            exe = root / "realesrgan.exe"
            exe.write_bytes(b"fixture")
            output = root / "fresh"
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                hd.build(archive, [4], output, exe)
            self.assertFalse(output.exists())
            existing = root / "existing"
            existing.mkdir()
            marker = existing / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nova"):
                hd.build(archive, [4], existing, exe)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_pages_must_be_explicit_valid_and_unique(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "game").mkdir()
            archive, exe = root / "game/x.big", root / "realesrgan.exe"
            archive.write_bytes(b"x")
            exe.write_bytes(b"x")
            for pages in ([], [4, 4], [-1], [1287]):
                with self.subTest(pages=pages), self.assertRaises(ValueError):
                    hd.build(archive, pages, root / ("out" + str(len(pages))), exe)

    def test_transparent_texels_stay_zero_and_opaque_never_become_zero(self):
        raw = struct.pack("<H", 0) + struct.pack("<H", 0x0001) + bytes(256 * 256 * 2 - 4)
        mask = hd.expand_plane_nearest(hd.transparent_plane(raw))
        side = 1024
        rgb = Image.new("RGB", (side, side), (200, 100, 50))  # upscale "preencheu" tudo
        rgb.putpixel((4, 0), (0, 0, 0))  # texel opaco que escureceu até zero
        packed = hd.pack_page(rgb, bytes(side * side), mask)
        word = lambda x, y: struct.unpack_from("<H", packed, (y * side + x) * 2)[0]
        self.assertEqual(word(0, 0), 0)
        self.assertEqual(word(3, 3), 0)
        self.assertNotEqual(word(4, 0), 0)


if __name__ == "__main__":
    unittest.main()
