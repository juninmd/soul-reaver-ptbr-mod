"""Focused structural checks for the offline UI Unicode candidate."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ui_unicode_catalogue import build, write_candidate

ROOT = Path(__file__).resolve().parents[1]


class CatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ROOT / "staging/backups/steam-classic-en/locals.pc.original"
        cls.catalogue = build(source.read_bytes())

    def test_has_224_unique_ids(self):
        entries = self.catalogue["entries"]
        self.assertEqual(len(entries), 224)
        self.assertEqual({e["id"] for e in entries}, set(range(224)))

    def test_high_bytes_are_explicit_and_preserved(self):
        for entry in self.catalogue["entries"]:
            raw = bytes.fromhex(entry["sourcehex"])
            expected = [f"0x{byte:02X}" for byte in raw if byte >= 128]
            self.assertEqual(entry["preserveicons"], expected, entry["id"])
            actual = [f"0x{code}" for code in __import__("re").findall(
                r"\[icon:0x([0-9A-F]{2})\]", entry["text_ptbr"])]
            self.assertEqual(actual, expected, entry["id"])

    def test_all_candidate_text_is_nfc(self):
        for entry in self.catalogue["entries"]:
            value = entry["text_ptbr"]
            self.assertEqual(unicodedata.normalize("NFC", value), value, entry["id"])

    def test_accented_ui_labels_and_icon_tokens_survive_as_unicode(self):
        entries = self.catalogue["entries"]
        for index, expected in {
            1: "formatar cartão de memória",
            31: "opções",
            71: "configuração de vídeo",
            83: "triângulo",
            181: "pressione o botão [icon:0xD4]",
        }.items():
            self.assertEqual(entries[index]["text_ptbr"], expected)
        for index in (1, 31, 71, 83, 181):
            value = entries[index]["text_ptbr"]
            self.assertFalse(value.isascii(), f"UI entry {index} regressed to ASCII-only")
            self.assertEqual(unicodedata.normalize("NFC", value), value)

    def test_checked_in_catalogue_keeps_nfc_accents_and_icon_tokens(self):
        checked_in = json.loads((ROOT / "content/ui-ptbr-unicode.json").read_text(encoding="utf-8"))
        self.assertEqual((checked_in["encoding"], checked_in["normalization"]), ("UTF-8", "NFC"))
        entries = checked_in["entries"]
        self.assertEqual(len(entries), 224)
        for entry in entries:
            value = entry["text_ptbr"]
            self.assertEqual(unicodedata.normalize("NFC", value), value, entry["id"])
            expected_icons = [f"0x{byte:02X}" for byte in bytes.fromhex(entry["sourcehex"]) if byte >= 128]
            self.assertEqual(entry["preserveicons"], expected_icons, entry["id"])
            actual_icons = [f"0x{code}" for code in __import__("re").findall(
                r"\[icon:0x([0-9A-F]{2})\]", value)]
            self.assertEqual(actual_icons, expected_icons, entry["id"])
        self.assertEqual(entries[31]["text_ptbr"], "opções")
        self.assertEqual(entries[71]["text_ptbr"], "configuração de vídeo")
        self.assertEqual(entries[181]["text_ptbr"], "pressione o botão [icon:0xD4]")

    def test_every_entry_has_required_fields(self):
        required = {"id", "sourcehex", "source_display", "text_ptbr", "status", "preserveicons"}
        for entry in self.catalogue["entries"]:
            self.assertEqual(set(entry), required)
            self.assertIn(entry["status"], {"translated", "key_label", "symbol", "empty"})

    def test_menu_and_directional_labels_are_portuguese(self):
        entries = self.catalogue["entries"]
        self.assertEqual(entries[108]["text_ptbr"], "menu de glifos")
        self.assertEqual(entries[108]["status"], "translated")
        self.assertEqual(entries[31]["text_ptbr"], "opções")
        for index, word in {79: "cima", 80: "baixo", 81: "esquerda", 82: "direita",
                            159: "cima", 161: "esquerda", 162: "direita", 164: "baixo"}.items():
            self.assertEqual(entries[index]["text_ptbr"], word)
            self.assertEqual(entries[index]["status"], "translated")

    def test_unknown_source_hash_is_rejected(self):
        source = (ROOT / "staging/backups/steam-classic-en/locals.pc.original").read_bytes()
        with self.assertRaisesRegex(ValueError, "Unknown source locals.pc SHA-256"):
            build(source[:-1] + bytes([source[-1] ^ 1]))

    def test_existing_output_is_never_overwritten(self):
        source = ROOT / "staging/backups/steam-classic-en/locals.pc.original"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.json"
            output.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_candidate(source, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_metadata_marks_candidate_unreviewed_and_unintegrated(self):
        self.assertEqual(self.catalogue["encoding"], "UTF-8")
        self.assertEqual(self.catalogue["normalization"], "NFC")
        self.assertFalse(self.catalogue["human_review"])
        self.assertFalse(self.catalogue["integration"])


if __name__ == "__main__":
    unittest.main()
