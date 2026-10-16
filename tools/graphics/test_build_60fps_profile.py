import tempfile
import unittest
import configparser
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_60fps_profile import update_config


class BuildProfileTests(unittest.TestCase):
    def test_changes_only_requested_values_and_preserves_sections(self):
        source_text = """[GeneralExt]\nFPSLimit = 30\nOther = keep\n\n[DirectX]\nForceVerticalSync = true\nTexture = untouched\n\n[Glide]\nForceVerticalSync = true\n"""
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "in.conf", Path(td) / "out.conf"
            src.write_text(source_text, encoding="utf-8")
            update_config(src, dst)
            result = dst.read_text(encoding="utf-8")
            self.assertIn("FPSLimit = 60", result)
            self.assertIn("ForceVerticalSync = false", result)
            self.assertIn("Texture = untouched", result)
            self.assertIn("[Glide]\nForceVerticalSync = true", result)
            self.assertEqual(source_text, src.read_text(encoding="utf-8"))

    def test_refuses_missing_keys(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "in.conf", Path(td) / "out.conf"
            src.write_text("[GeneralExt]\nFPSLimit=30\n[DirectX]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing key"):
                update_config(src, dst)
            self.assertFalse(dst.exists())

    def test_refuses_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "in.conf", Path(td) / "out.conf"
            src.write_text("[GeneralExt]\nFPSLimit=30\nFPSLimit=40\n[DirectX]\nForceVerticalSync=true\n", encoding="utf-8")
            with self.assertRaises(configparser.DuplicateOptionError):
                update_config(src, dst)
            self.assertFalse(dst.exists())

    def test_refuses_existing_destination_without_changing_it(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "in.conf", Path(td) / "out.conf"
            src.write_text("[GeneralExt]\nFPSLimit=30\n[DirectX]\nForceVerticalSync=true\n", encoding="utf-8")
            dst.write_text("preserve me", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                update_config(src, dst)
            self.assertEqual("preserve me", dst.read_text(encoding="utf-8"))

    def test_refuses_same_path_without_changing_source(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.conf"
            original = "[GeneralExt]\nFPSLimit=30\n[DirectX]\nForceVerticalSync=true\n"
            src.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "equal to source"):
                update_config(src, src)
            self.assertEqual(original, src.read_text(encoding="utf-8"))

    def test_refuses_duplicate_sections(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "in.conf", Path(td) / "out.conf"
            src.write_text("[GeneralExt]\nFPSLimit=30\n[GeneralExt]\nOther=1\n[DirectX]\nForceVerticalSync=true\n", encoding="utf-8")
            with self.assertRaises((ValueError, configparser.DuplicateSectionError)):
                update_config(src, dst)
            self.assertFalse(dst.exists())


if __name__ == "__main__":
    unittest.main()
