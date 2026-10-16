import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import unicodedata
import wave

import build_dialogue_subtitles as builder


PTBR_CORPUS = (
    "áéíóúãõçâêôà ÀÉ — … § © ™. "
    "Rahab, Moebius, Dumah, Kain e Nosgoth."
)


class UnicodeSubtitleContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.audio = self.root / "voice.wav"
        with wave.open(str(self.audio), "wb") as wav:
            wav.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x01\x00" * 2205)
        self.sha = hashlib.sha256(self.audio.read_bytes()).hexdigest()

    def plan(self, text="A maldição de Raziel — impossível…", **row_extras):
        voice = dict(id=10, speaker="raziel", text_ptbr=text, audio=self.audio.name,
                     audio_sha256=self.sha, duration_seconds=2, lead_samples=0,
                     approved_text=True, approved_audio=True)
        voice.update(row_extras)
        path = self.root / "plan.json"
        path.write_text(json.dumps(dict(schema=1, resource_kind="voices.dat", voices=[voice]),
                                   ensure_ascii=False), encoding="utf-8")
        return path

    def test_unicode_v1_keeps_ptbr_utf8_nfc_and_json_envelope(self):
        plan = self.plan(PTBR_CORPUS)
        output = self.root / "unicode.json"
        builder.build(plan, output, format="unicode-v1")
        raw = output.read_bytes()
        envelope = json.loads(raw.decode("utf-8"))
        self.assertEqual((envelope["schema"], envelope["format"], envelope["encoding"], envelope["normalization"]),
                         (1, "unicode-v1", "UTF-8", "NFC"))
        self.assertEqual(envelope["captions"][0]["text"], PTBR_CORPUS)
        self.assertIn(PTBR_CORPUS.encode("utf-8"), raw)
        self.assertFalse(envelope["captions"][0]["text"].isascii(),
                         "unicode-v1 must not regress to ASCII-only text")
        for character in "áéíóúãõçâêôàÀÉ":
            self.assertIn(character, envelope["captions"][0]["text"])
        for name in ("Rahab", "Moebius", "Dumah", "Kain", "Nosgoth"):
            self.assertIn(name, envelope["captions"][0]["text"])
        self.assertEqual(unicodedata.normalize("NFC", raw.decode("utf-8")), raw.decode("utf-8"))
        meta = json.loads(output.with_suffix(".evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["schema"], 1)
        self.assertEqual(meta["format"], "unicode-v1")
        self.assertEqual(meta["encoding"], "UTF-8")
        self.assertEqual(meta["normalization"], "NFC")
        self.assertEqual(meta["namespace"], "voices.dat")
        self.assertEqual(meta["origin"], str(plan.resolve()))
        self.assertEqual(meta["source_sha256"], hashlib.sha256(plan.read_bytes()).hexdigest())
        self.assertEqual(meta["sha256"], hashlib.sha256(raw).hexdigest())

    def test_unicode_v1_normalizes_and_rejects_unsupported_chars(self):
        decomposed = "A maldic\u0327a\u0303o de Raziel"
        output = self.root / "normalized.json"
        builder.build(self.plan(decomposed), output, format="unicode-v1")
        normalized = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(normalized["captions"][0]["text"], unicodedata.normalize("NFC", decomposed))
        for text in ("\ttexto", "texto\n", "linha\nseguinte", "tab\ttexto", "nul\x00texto", "bidi \u202e texto", "zero\u200bwidth", "private \ue000", "surrogate \ud800"):
            with self.subTest(text=repr(text)):
                output = self.root / "rejected.json"
                with self.assertRaises(ValueError):
                    builder.build(self.plan(text), output, format="unicode-v1")
                self.assertFalse(output.exists())

    def test_unicode_pagination_preserves_every_word_and_contiguous_timing(self):
        text = " ".join([PTBR_CORPUS] * 20)
        plan = self.plan(text)
        data = json.loads(plan.read_text(encoding="utf-8"))
        data["voices"][0]["duration_seconds"] = 30
        plan.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        output = self.root / "long.json"
        builder.build(plan, output, format="unicode-v1")
        row = json.loads(output.read_text(encoding="utf-8"))["captions"][0]
        pages = row["pages"]
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page["text"]) <= 220 for page in pages))
        self.assertEqual(" ".join(page["text"] for page in pages), text)
        self.assertEqual(" ".join(" ".join(page["text"].split()) for page in pages).split(), text.split())
        self.assertEqual(pages[0]["start_ms"], 0)
        self.assertEqual(pages[-1]["end_ms"], row["duration_ms"])
        for previous, current in zip(pages, pages[1:]):
            self.assertEqual(previous["end_ms"], current["start_ms"])
        self.assertTrue(all(page["end_ms"] - page["start_ms"] >= 1 for page in pages))
        self.assertTrue(all(unicodedata.normalize("NFC", page["text"]) == page["text"]
                            for page in pages))
        self.assertTrue(any(not page["text"].isascii() for page in pages),
                        "every Unicode page must retain non-ASCII characters")

    def test_unicode_pagination_refuses_duration_shorter_than_page_count(self):
        text = " ".join(f"palavra{i}" for i in range(70))
        plan = self.plan(text)
        data = json.loads(plan.read_text(encoding="utf-8"))
        tiny_audio = self.root / "tiny.wav"
        with wave.open(str(tiny_audio), "wb") as wav:
            wav.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x01\x00" * 22)
        data["voices"][0]["audio"] = tiny_audio.name
        data["voices"][0]["audio_sha256"] = hashlib.sha256(tiny_audio.read_bytes()).hexdigest()
        data["voices"][0]["duration_seconds"] = 1
        plan.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        output = self.root / "too-short.json"
        with self.assertRaisesRegex(ValueError, "too short|cannot provide"):
            builder.build(plan, output, format="unicode-v1")
        self.assertFalse(output.exists())

    def test_legacy_does_not_gain_unicode_pagination(self):
        output = self.root / "legacy-pages.tsv"
        builder.build(self.plan(), output)
        self.assertEqual(output.read_bytes(), b"10\t100\tA maldicao de Raziel - impossivel...\n")

    def test_unicode_candidate_cannot_be_misnamed_as_runtime_tsv(self):
        output = self.root / "subtitles.tsv"
        with self.assertRaisesRegex(ValueError, r"JSON.*\.json.*runtime \.tsv"):
            builder.build(self.plan(), output, format="unicode-v1")
        self.assertFalse(output.exists())
        self.assertFalse(output.with_suffix(".evidence.json").exists())

    def test_duplicate_ids_and_fmv_namespace_rejected_before_output(self):
        plan = self.plan()
        data = json.loads(plan.read_text(encoding="utf-8"))
        data["voices"].append(dict(data["voices"][0]))
        plan.write_text(json.dumps(data), encoding="utf-8")
        output = self.root / "duplicate.json"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            builder.build(plan, output, format="unicode-v1")
        self.assertFalse(output.exists())
        plan = self.plan(fmv="verse")
        with self.assertRaisesRegex(ValueError, "FMV"):
            builder.build(plan, self.root / "fmv.json", format="unicode-v1")
        plan = self.plan()
        data = json.loads(plan.read_text(encoding="utf-8"))
        data["resource_kind"] = "fmv"
        plan.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "FMV"):
            builder.build(plan, self.root / "fmv-resource.json", format="unicode-v1")

    def test_legacy_default_retains_ascii_accent_stripping(self):
        output = self.root / "legacy.tsv"
        builder.build(self.plan(), output)
        self.assertEqual(output.read_bytes(), b"10\t100\tA maldicao de Raziel - impossivel...\n")
        self.assertTrue(output.read_bytes().isascii())

    def test_legacy_stays_ascii_while_unicode_keeps_the_same_accented_source(self):
        text = "A maldição de Raziel é impossível…"
        unicode_output = self.root / "accented.json"
        builder.build(self.plan(text), unicode_output, format="unicode-v1")
        unicode_row = json.loads(unicode_output.read_text(encoding="utf-8"))["captions"][0]
        self.assertEqual(unicode_row["text"], text)
        self.assertFalse(unicode_output.read_bytes().isascii())

        legacy_output = self.root / "accented-legacy.tsv"
        builder.build(self.plan(text), legacy_output, format="legacy")
        self.assertEqual(legacy_output.read_bytes(),
                         b"10\t100\tA maldicao de Raziel e impossivel...\n")
        self.assertTrue(legacy_output.read_bytes().isascii())

    def test_existing_destination_is_never_overwritten(self):
        output = self.root / "present.json"
        output.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "fresh"):
            builder.build(self.plan(), output, format="unicode-v1")
        self.assertEqual(output.read_bytes(), b"keep")
        self.assertFalse(output.with_suffix(".evidence.json").exists())


if __name__ == "__main__":
    unittest.main()
