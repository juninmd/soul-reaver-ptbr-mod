import json
import struct
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import build_menu_background as menu


class MenuBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "art.png"
        Image.new("RGB", (640, 480), (120, 64, 200)).save(self.image)
        self.tim = struct.pack("<IIIHHHH", 16, 2, menu.TITLE_BYTES - 8, 512, 0, 512, 480) + b"\x00\x80" * (512 * 480)
        offset = 4 + menu.ENTRY_COUNT * 16
        archive = bytearray(offset)
        struct.pack_into("<I", archive, 0, menu.ENTRY_COUNT)
        struct.pack_into("<III4s", archive, 4 + menu.TITLE_INDEX * 16, 0xF2C63638, menu.TITLE_BYTES, offset, b"TLE1")
        archive += self.tim + b"other resources must stay intact"
        self.archive = bytes(archive)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in {"ARCHIVE_BYTES": len(archive), "TITLE_OFFSET": offset, "SOURCE_SHA256": menu.digest(archive), "TITLE_HASH": menu.digest(self.tim)}.items():
            self.stack.enter_context(patch.object(menu, key, value))

    def test_only_title_pixels_change_and_native_format_round_trips(self):
        header = menu.title_header(self.archive)
        tim = menu.encode_title(self.image, header)
        result = menu.replace_title(self.archive, tim)
        self.assertEqual(len(result), len(self.archive))
        self.assertEqual(result[:menu.TITLE_OFFSET + 20], self.archive[:menu.TITLE_OFFSET + 20])
        self.assertEqual(result[menu.TITLE_OFFSET + menu.TITLE_BYTES:], self.archive[menu.TITLE_OFFSET + menu.TITLE_BYTES:])
        self.assertNotEqual(result, self.archive)
        pixel = menu.decode_title(tim).getpixel((0, 0))
        self.assertTrue(all(abs(a - b) <= 8 for a, b in zip(pixel, (120, 64, 200))))

    def test_unknown_base_and_header_or_size_changes_are_refused(self):
        changed = bytearray(self.archive)
        changed[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "Base bigfile.dat desconhecida"):
            menu.replace_title(changed, self.tim)
        with self.assertRaisesRegex(ValueError, "cabeçalho e o tamanho"):
            menu.replace_title(self.archive, self.tim[:-2])
        with self.assertRaisesRegex(ValueError, "cabeçalho e o tamanho"):
            menu.replace_title(self.archive, b"bad!" + self.tim[4:])

    def test_panorama_and_transparency_are_not_silently_cropped_or_flattened(self):
        for size, mode, color in [((900, 300), "RGB", (0, 0, 0)), ((640, 480), "RGBA", (0, 0, 0, 0))]:
            Image.new(mode, size, color).save(self.image)
            with self.assertRaises(ValueError):
                menu.encode_title(self.image, self.tim[:20])

    def test_build_preserves_source_and_refuses_existing_output(self):
        game = self.root / "game"
        game.mkdir()
        (game / "kain2.exe").write_bytes(b"compatible fixture, never executed")
        (game / "bigfile.dat").write_bytes(self.archive)
        output = self.root / "candidate"
        with patch.object(menu, "EXE_HASHES", {menu.digest((game / "kain2.exe").read_bytes())}):
            report = menu.build(game, self.image, output)
            self.assertTrue(report["bytes_outside_title_unchanged"])
            self.assertFalse(report["runtime_verified"])
            self.assertEqual((game / "bigfile.dat").read_bytes(), self.archive)
            plan = json.loads((output / "assets.json").read_text())
            self.assertEqual(plan["assets"][0]["result_sha256"], menu.digest((output / "asset-bigfile.dat").read_bytes()))
            with self.assertRaisesRegex(ValueError, "saída nova"):
                menu.build(game, self.image, output)
            with self.assertRaisesRegex(ValueError, "fora da instalação"):
                menu.build(game, self.image, game / "unsafe")

    def test_manifest_traversal_duplicates_and_tampering_are_refused(self):
        manifest = self.root / "assets.json"
        payload = self.root / "proxy.dll"
        payload.write_bytes(b"proxy fixture")
        entry = {"file": "DINPUT.dll", "source_sha256": None, "result_sha256": menu.digest(payload.read_bytes()), "payload": payload.name}
        for entries in [[dict(entry, payload="../proxy.dll")], [entry, entry], [dict(entry, result_sha256="0" * 64)]]:
            manifest.write_text(json.dumps({"schema": 1, "assets": entries}))
            with self.assertRaises(ValueError):
                menu.localization_payloads(manifest)
        manifest.write_text(json.dumps({"schema": 1, "assets": [entry]}))
        entries, payloads = menu.localization_payloads(manifest)
        self.assertEqual(entries, [entry])
        self.assertEqual(payloads, [("proxy.dll", b"proxy fixture")])

    def test_two_backgrounds_preserve_headers_table_and_all_other_resources(self):
        archive = bytearray(self.archive)
        items_offset = len(archive)
        items_tim = struct.pack("<IIIHHHH", 16, 2, menu.TITLE_BYTES - 8, 0, 0, 512, 480) + self.tim[20:]
        struct.pack_into("<III4s", archive, 4 + menu.ITEMS_INDEX * 16,
                         0xC23115E8, menu.TITLE_BYTES, items_offset, b"MENU")
        archive += items_tim + b"trailing unrelated resource"
        game = self.root / "two-background-game"
        game.mkdir()
        (game / "kain2.exe").write_bytes(b"compatible fixture, never executed")
        (game / "bigfile.dat").write_bytes(archive)
        items_image = self.root / "items.png"
        Image.new("RGB", (800, 600), (16, 40, 32)).save(items_image)
        with patch.multiple(menu, ARCHIVE_BYTES=len(archive), SOURCE_SHA256=menu.digest(archive),
                            ITEMS_OFFSET=items_offset, ITEMS_HASH=menu.digest(items_tim),
                            EXE_HASHES={menu.digest((game / "kain2.exe").read_bytes())}):
            output = self.root / "two-background-candidate"
            report = menu.build(game, self.image, output, items_image=items_image)
            candidate = (output / "asset-bigfile.dat").read_bytes()
            regions = [(menu.TITLE_OFFSET + 20, menu.TITLE_OFFSET + menu.TITLE_BYTES),
                       (items_offset + 20, items_offset + menu.TITLE_BYTES)]
            self.assertTrue(menu.outside_backgrounds_unchanged(archive, candidate, regions))
            self.assertTrue(report["bytes_outside_backgrounds_unchanged"])
            self.assertEqual([row["entry"] for row in report["backgrounds"]], ["title1.pti", "bkgdmenu.pti"])
            for start, end in regions:
                self.assertNotEqual(archive[start:end], candidate[start:end])
            self.assertEqual((game / "bigfile.dat").read_bytes(), archive)
            changed = bytearray(candidate)
            changed[-1] ^= 1
            self.assertFalse(menu.outside_backgrounds_unchanged(archive, changed, regions))

    def test_incompatible_submenu_entry_is_refused_before_output_creation(self):
        game = self.root / "invalid-submenu-game"
        game.mkdir()
        (game / "kain2.exe").write_bytes(b"compatible fixture, never executed")
        (game / "bigfile.dat").write_bytes(self.archive)
        output = self.root / "refused-candidate"
        with patch.object(menu, "EXE_HASHES", {menu.digest((game / "kain2.exe").read_bytes())}):
            with self.assertRaisesRegex(ValueError, "Entrada bkgdmenu.pti incompatível"):
                menu.build(game, self.image, output, items_image=self.image)
        self.assertFalse(output.exists())
        self.assertEqual((game / "bigfile.dat").read_bytes(), self.archive)


if __name__ == "__main__":
    unittest.main()
