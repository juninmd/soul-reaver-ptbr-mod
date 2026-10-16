import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent / "graphics"))
import texture_identity as identity


class TextureIdentityTests(unittest.TestCase):
    def test_padding_is_excluded_and_duplicate_pages_remain_ambiguous(self):
        raw = bytes(range(256)) * 512
        pitched = b"".join(raw[y * 512:(y + 1) * 512] + b"PAD!" for y in range(256))
        index = dict(pages=[dict(index=i, **identity.digest(raw)) for i in (2, 7)])
        result = identity.match_upload(index, pitched, 516)
        self.assertEqual(result["page_candidates"], [2, 7])
        self.assertEqual(result["status"], "ambiguous")
        index["pages"].pop()
        self.assertEqual(identity.match_upload(index, pitched, 516)["status"], "unique")
        altered = b"!" + pitched[1:]
        self.assertEqual(identity.match_upload(index, altered, 516)["status"], "unmatched")

    def test_partial_or_invalid_upload_rejected(self):
        for args in ((b"x", 256, 256, 512), (b"", 256, 256, 500), (b"", 0, 256, 512)):
            with self.assertRaises(ValueError):
                identity.normalize_rows(*args)
        with self.assertRaises(ValueError):
            identity.match_upload(dict(pages=[]), b"", 512, 128, 128)

    def test_crc_collision_alone_does_not_match(self):
        raw = b"\0" * identity.PAGE
        row = dict(index=0, **identity.digest(raw))
        row["sha256"] = "f" * 64
        self.assertEqual(identity.match_upload(dict(pages=[row]), raw, 512)["status"], "unmatched")

    def test_unsupported_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "textures.big"
            path.write_bytes(b"unsupported")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                identity.build_index(path)


if __name__ == "__main__":
    unittest.main()
