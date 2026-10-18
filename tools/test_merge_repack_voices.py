import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import merge_repack_voices as merge

SLOT = 200


def fixture(root):
    exe = b"\0" * merge.TABLE_OFFSET + b"".join(struct.pack("<II", i * SLOT, SLOT) for i in range(merge.COUNT))
    voices = bytes(range(256)) * (merge.COUNT * SLOT // 256 + 1)
    voices = voices[:merge.COUNT * SLOT]
    merge.EXE_SHA256, merge.VOICES_SHA256 = merge.digest(exe), merge.digest(voices)
    package = root / "package"
    package.mkdir()
    existing = b"\x05\0" * (SLOT // 2)
    (package / "voice-0003.pcm").write_bytes(existing)
    patches = [dict(id=3, file="voice-0003.pcm", sha256=merge.digest(existing), length=SLOT)]
    manifest = dict(schema=1, id="sr1-ptbr-review", name="t", version="0.1.0", exe_sha256="x", source_sha256="y",
                    result_sha256="z", patches=patches, coverage=dict(replaced=1, total=merge.COUNT, complete=False))
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package, exe, voices


def clip(path, samples, rate=22050, channels=1):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.package, self.exe, self.voices = fixture(self.root)
        self.clips = self.root / "clips"
        self.clips.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_merge(self):
        return merge.merge(self.package, self.clips, self.exe, self.voices, self.root / "out")

    def test_adds_new_slot_and_keeps_approved_payload(self):
        clip(self.clips / "0007.wav", [100] * 50)
        result = self.run_merge()
        manifest = json.loads((self.root / "out" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((result["added"], manifest["coverage"]["replaced"]), (1, 2))
        self.assertEqual([p["id"] for p in manifest["patches"]], [3, 7])
        self.assertEqual((self.root / "out" / "voice-0003.pcm").read_bytes(), (self.package / "voice-0003.pcm").read_bytes())
        self.assertEqual(len((self.root / "out" / "voice-0007.pcm").read_bytes()), SLOT)

    def test_result_hash_matches_patched_file(self):
        clip(self.clips / "0007.wav", [100] * 50)
        result = self.run_merge()
        expected = bytearray(self.voices)
        expected[3 * SLOT:4 * SLOT] = (self.package / "voice-0003.pcm").read_bytes()
        expected[7 * SLOT:7 * SLOT + 100] = struct.pack("<50h", *[100] * 50)
        expected[7 * SLOT + 100:8 * SLOT] = b"\0" * 100
        self.assertEqual(result["result_sha256"], merge.digest(bytes(expected)))

    def test_refuses_to_overwrite_an_approved_slot(self):
        clip(self.clips / "0003.wav", [100] * 50)
        with self.assertRaisesRegex(ValueError, "already approved"):
            self.run_merge()

    def test_refuses_clip_longer_than_slot(self):
        clip(self.clips / "0007.wav", [100] * (SLOT // 2 + 1))
        with self.assertRaisesRegex(ValueError, "longer than its slot"):
            self.run_merge()

    def test_refuses_wrong_format_and_clipping(self):
        clip(self.clips / "0007.wav", [100] * 10, rate=44100)
        with self.assertRaisesRegex(ValueError, "expected PCM16 mono"):
            self.run_merge()
        (self.clips / "0007.wav").unlink()
        clip(self.clips / "0008.wav", [32767] * 10)
        with self.assertRaisesRegex(ValueError, "clipping"):
            self.run_merge()


if __name__ == "__main__":
    unittest.main()
