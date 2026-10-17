"""Exercise the UTF-8 subtitle builder output through the bridge's pure contract."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import build_dialogue_subtitles as builder  # noqa: E402
sys.path.insert(0, str(ROOT / "validate/77-unicode-package-poc"))
import package_contract  # noqa: E402


class UnicodePipelineBridgeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def write_audio(self, name: str) -> tuple[str, str]:
        path = self.work / name
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x01\x00" * 44100)
        return path.name, hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def write_test_pe(path: Path) -> None:
        image = bytearray(128)
        image[:2] = b"MZ"
        struct.pack_into("<I", image, 0x3C, 64)
        image[64:68] = b"PE\0\0"
        struct.pack_into("<H", image, 68, 0x14C)
        path.write_bytes(image)

    def test_built_unicode_envelope_round_trips_through_bridge_validation(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise the bridge helper")

        long_text = " ".join(
            ["A maldição de Raziel — impossível…"]
            + ["áéíóúãõçâêôà ÀÉ; Raziel, Kain, Dumah, Moebius e Nosgoth."]
            + ["Água, coração, bênção e ação"] * 12
        )
        cases = [
            (10, long_text),
            (11, "A próxima fala preserva ação, bênção, coração e água."),
        ]
        voices = []
        for index, text in cases:
            audio_name, audio_sha = self.write_audio(f"voice-{index}.wav")
            voices.append({
                "id": index,
                "speaker": "raziel",
                "text_ptbr": text,
                "audio": audio_name,
                "audio_sha256": audio_sha,
                "duration_seconds": 2.0,
                "lead_samples": 0,
                "approved_text": True,
                "approved_audio": True,
            })

        plan = self.work / "plan.json"
        plan.write_text(json.dumps({
            "schema": 1,
            "resource_kind": "voices.dat",
            "voices": voices,
        }, ensure_ascii=False), encoding="utf-8")
        output = self.work / "captions-unicode.json"
        result = builder.build(plan, output, format="unicode-v1")

        payload = output.read_bytes()
        text = payload.decode("utf-8", errors="strict")
        envelope = json.loads(text)
        rows = envelope["captions"]
        self.assertEqual(result["captions"], 2)
        self.assertIn("maldição", text)
        self.assertIn("coração", text)
        for character in "áéíóúãõçâêôà ÀÉ":
            self.assertIn(character, text)
        for name in ("Raziel", "Kain", "Dumah", "Moebius", "Nosgoth"):
            self.assertIn(name, text)
        self.assertIn("…", text)
        self.assertNotIn("mal dicao", text)
        self.assertGreater(len(rows[0]["pages"]), 1)
        self.assertEqual(rows[0]["text"], long_text)
        for row in rows:
            self.assertEqual(" ".join(page["text"] for page in row["pages"]), row["text"])
            self.assertEqual(row["pages"][0]["start_ms"], 0)
            self.assertEqual(row["pages"][-1]["end_ms"], row["duration_ms"])
            for previous, current in zip(row["pages"], row["pages"][1:]):
                self.assertEqual(previous["end_ms"], current["start_ms"])

        bridge_test = ROOT / "tools/subtitles/test_unicode_runtime_bridge.cjs"
        completed = subprocess.run(
            [node, str(bridge_test), str(ROOT),
             "tools/subtitles/unicode_runtime_bridge.js", str(output)],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertIn("PASS: 2 captions", completed.stdout)

        # Close the generator-to-package path with the offline package contract.
        # Fake PE headers are fixtures only; no native overlay or game is launched.
        overlay = self.work / "overlay-fixture.dll"
        proxy = self.work / "proxy-fixture.dll"
        legacy_tsv = self.work / "legacy.tsv"
        package = self.work / "package"
        self.write_test_pe(overlay)
        self.write_test_pe(proxy)
        legacy_tsv.write_bytes(b"10\t2000\tFallback ASCII.\n")
        manifest = package_contract.build_package(overlay, output, proxy, legacy_tsv, package)
        self.assertEqual(manifest["default_route"], "legacy")
        packaged_json = package / "unicode/captions-unicode-v1.json"
        self.assertEqual(packaged_json.read_bytes(), payload)
        packaged_text = packaged_json.read_text(encoding="utf-8")
        for character in "áéíóúãõçâêôà ÀÉ":
            self.assertIn(character, packaged_text)
        self.assertIn("Raziel", packaged_text)
        self.assertTrue((package / "legacy/subtitles.tsv").read_bytes().isascii())


if __name__ == "__main__":
    unittest.main()
