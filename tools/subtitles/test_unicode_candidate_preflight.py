import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).with_name("unicode_candidate_preflight.py")
spec = importlib.util.spec_from_file_location("unicode_candidate_preflight", MODULE_PATH)
preflight_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight_module)


def pe_x86() -> bytes:
    data = bytearray(512)
    data[:2] = b"MZ"
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    data[0x80:0x84] = b"PE\0\0"
    data[0x84:0x86] = (0x14C).to_bytes(2, "little")
    data[0x94:0x96] = (0xE0).to_bytes(2, "little")
    data[0x98:0x9A] = (0x10B).to_bytes(2, "little")
    return bytes(data)


def sample_captions(count=230):
    return {
        "schema": 1, "format": "unicode-v1", "encoding": "UTF-8",
        "normalization": "NFC", "namespace": "voices.dat",
        "captions": [
            {"id": i, "duration_ms": 100, "text": "ação",
             "pages": [{"text": "ação", "start_ms": 0, "end_ms": 100}]}
            for i in range(count)
        ],
    }


class UnicodeCandidatePreflightTests(unittest.TestCase):
    def test_structurally_valid_replacement_corpus_requires_explicit_pin_update(self):
        (self.game / "kain2.exe").write_bytes(pe_x86())
        hashed = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        with mock.patch.object(preflight_module, "EXPECTED_EXE_SHA256", hashed(self.game / "kain2.exe")), \
             mock.patch.object(preflight_module, "EXPECTED_VOICES_SHA256", hashed(self.game / "voices.dat")), \
             mock.patch.object(preflight_module, "EXPECTED_CAPTIONS_SHA256", hashed(self.captions)):
            self.assertTrue(preflight_module.preflight(self.game, self.overlay, self.captions)["candidate_only"])
            data = sample_captions()
            data["captions"][0]["text"] = "outra fala"
            data["captions"][0]["pages"][0]["text"] = "outra fala"
            self.write_captions(data)
            with self.assertRaisesRegex(preflight_module.PreflightError, "corpus V6"):
                preflight_module.preflight(self.game, self.overlay, self.captions)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=preflight_module.ROOT / "staging")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.game.mkdir()
        for filename in ("kain2.exe", "voices.dat", "DDraw.dll", "D3DImm.dll"):
            (self.game / filename).write_bytes(b"placeholder")
        (self.game / "dgVoodoo.conf").write_text(
            "Resolution = h:3840, v:2160\nFullScreenMode = false\n", encoding="utf-8")
        self.overlay = self.root / "overlay.dll"
        self.overlay.write_bytes(pe_x86())
        self.captions = self.root / "captions.json"
        self.write_captions(sample_captions())

    def write_captions(self, data):
        self.captions.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def run_captions(self, data):
        self.write_captions(data)
        with self.assertRaises(preflight_module.PreflightError):
            preflight_module._captions(self.captions)

    def test_active_dinput_proxy_is_rejected_before_hash_validation(self):
        with mock.patch.object(preflight_module, "sha256", return_value="0" * 64):
            with self.assertRaisesRegex(preflight_module.PreflightError, "DINPUT.dll"):
                (self.game / "DINPUT.dll").write_bytes(b"active")
                preflight_module.preflight(self.game, self.overlay, self.captions)

    def test_caption_namespace_is_enforced(self):
        data = sample_captions()
        data["namespace"] = "fmv"
        self.run_captions(data)

    def test_controls_are_rejected(self):
        data = sample_captions()
        data["captions"][0]["text"] = "linha\nseguinte"
        data["captions"][0]["pages"][0]["text"] = "linha\nseguinte"
        self.run_captions(data)

    def test_bidi_format_character_is_rejected(self):
        data = sample_captions()
        data["captions"][0]["text"] = "raziel \u202e texto"
        data["captions"][0]["pages"][0]["text"] = "raziel \u202e texto"
        self.run_captions(data)

    def test_duplicate_ids_are_rejected(self):
        data = sample_captions()
        data["captions"][1]["id"] = data["captions"][0]["id"]
        self.run_captions(data)

    def test_caption_count_must_be_230_not_479(self):
        self.run_captions(sample_captions(479))

    def test_page_gaps_are_rejected(self):
        data = sample_captions()
        data["captions"][0]["pages"] = [
            {"text": "a", "start_ms": 0, "end_ms": 40},
            {"text": "ção", "start_ms": 41, "end_ms": 100},
        ]
        self.run_captions(data)

    def test_output_must_be_fresh_and_existing_contents_are_preserved(self):
        target = self.root / "report.json"
        target.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(preflight_module.PreflightError, "arquivo novo"):
            preflight_module.write_report({"candidate_only": True}, target, self.game)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_output_inside_game_is_rejected(self):
        target = self.game / "report.json"
        with self.assertRaisesRegex(preflight_module.PreflightError, "dentro da cópia"):
            preflight_module.validate_output_path(target, self.game)
        self.assertFalse(target.exists())

    def test_pe_optional_header_bounds_and_magic_are_checked(self):
        malformed = self.root / "bad-overlay.dll"
        payload = bytearray(pe_x86())
        malformed.write_bytes(payload[:0xA0])
        with self.assertRaisesRegex(preflight_module.PreflightError, "SizeOfOptionalHeader"):
            preflight_module._pe_x86(malformed, "overlay DLL")
        payload = bytearray(pe_x86())
        payload[0x98:0x9A] = (0x20B).to_bytes(2, "little")
        malformed.write_bytes(payload)
        with self.assertRaisesRegex(preflight_module.PreflightError, "overlay DLL.*0x10b"):
            preflight_module._pe_x86(malformed, "overlay DLL")


if __name__ == "__main__":
    unittest.main()
