import json
import unittest
from pathlib import Path

import gen_speakers_header as gen

CAPTIONS = Path(__file__).resolve().parents[1] / "modules" / "localization" / "asset-captions-unicode-v1.json"


class SpeakerTableTests(unittest.TestCase):
    def test_known_lines_and_override(self):
        speakers = gen.resolve()
        self.assertEqual(speakers[103], "raziel")
        self.assertEqual(speakers[126], "ariel")  # cast correction beats the old Kain assignment

    def test_every_caption_has_a_speaker_when_modules_are_built(self):
        if not CAPTIONS.exists():
            self.skipTest("modules/ is generated and not present")
        ids = {row["id"] for row in json.loads(CAPTIONS.read_text(encoding="utf-8-sig"))["captions"]}
        table = [int(v) for v in gen.render(gen.resolve()).split("{")[1].split("}")[0].split(",")]
        self.assertEqual([i for i in ids if table[i] == 0], [])

    def test_header_is_current(self):
        self.assertEqual(gen.OUTPUT.read_text(encoding="utf-8"), gen.render(gen.resolve()))


if __name__ == "__main__":
    unittest.main()
