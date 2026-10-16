"""Offline tests for the full local bundle builder."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("build_full_bundle.py")
SPEC = importlib.util.spec_from_file_location("build_full_bundle", MODULE_PATH)
bundle_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle_builder)

CONF = """[General]
FullScreenMode                       = true

[DirectX]
Resolution                          = unforced
dgVoodooWatermark                   = true
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RewriteConfTests(unittest.TestCase):
    def test_resolution_windowed_and_watermark(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "dgVoodoo.conf"
            source.write_text(CONF, encoding="utf-8")
            text = bundle_builder.rewrite_conf(source, "3840x2160", True).decode()
            self.assertIn("Resolution                          = 3840x2160", text)
            self.assertIn("FullScreenMode                       = false", text)
            self.assertIn("dgVoodooWatermark                   = false", text)

    def test_missing_directx_section_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "dgVoodoo.conf"
            source.write_text("[General]\nFullScreenMode = true\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "DirectX"):
                bundle_builder.rewrite_conf(source, "3840x2160", True)


class BuildTests(unittest.TestCase):
    def _fixtures(self, root: Path):
        voices = root / "voices"
        assets = root / "assets"
        dgvoodoo = root / "dgvoodoo"
        for directory in (voices, assets, dgvoodoo / "MS" / "x86"):
            directory.mkdir(parents=True)

        payload = b"voice payload"
        (voices / "voice-0001.pcm").write_bytes(payload)
        (voices / "review.json").write_text("{}", encoding="utf-8")
        (voices / "manifest.json").write_text(json.dumps({
            "schema": 1, "id": "sr1-ptbr-review", "name": "n", "version": "0.1.0",
            "patches": [{"id": 1, "file": "voice-0001.pcm", "sha256": sha(payload), "length": len(payload)}],
        }), encoding="utf-8")

        asset = b"localized file"
        (assets / "asset-locals.pc").write_bytes(asset)
        (assets / "assets.json").write_text(json.dumps({"schema": 1, "assets": [{
            "file": "locals.pc", "source_sha256": "a" * 64, "result_sha256": sha(asset),
            "payload": "asset-locals.pc"}]}), encoding="utf-8")

        (dgvoodoo / "MS" / "x86" / "DDraw.dll").write_bytes(b"ddraw")
        (dgvoodoo / "MS" / "x86" / "D3DImm.dll").write_bytes(b"d3dimm")
        (dgvoodoo / "dgVoodoo.conf").write_text(CONF, encoding="utf-8")
        return voices, assets, dgvoodoo

    def test_build_creates_graphics_and_bundle_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            voices, assets, dgvoodoo = self._fixtures(root)
            output = root / "bundle"
            result = bundle_builder.build(voices, assets, dgvoodoo, output)
            self.assertTrue(result["components"]["graphics"])
            self.assertTrue(result["components"]["widescreen"])
            self.assertFalse(result["components"]["textures"])
            self.assertTrue((output / "graphics" / "DDraw.dll").is_file())
            self.assertTrue((output / "graphics" / "dgVoodoo.conf").is_file())
            self.assertTrue((output / "voices" / "voice-0001.pcm").is_file())
            self.assertTrue((output / "localization" / "assets.json").is_file())
            meta = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["schema"], 2)
            self.assertIn("voices", meta["modules"])
            self.assertNotIn("video", meta["modules"])
            self.assertEqual(meta["resolution"], "3840x2160")
            self.assertTrue(meta["windowed"])
            self.assertFalse(meta["publishable"])

    def test_existing_output_is_refused_and_inputs_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            voices, assets, dgvoodoo = self._fixtures(root)
            output = root / "bundle"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nova"):
                bundle_builder.build(voices, assets, dgvoodoo, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_video_assets_are_split_into_their_own_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            voices, assets, dgvoodoo = self._fixtures(root)
            payload = b"translated FMV"
            (assets / "asset-intro.bik").write_bytes(payload)
            plan = json.loads((assets / "assets.json").read_text(encoding="utf-8"))
            plan["assets"].append({
                "file": "intro.bik", "source_sha256": "b" * 64,
                "result_sha256": sha(payload), "payload": "asset-intro.bik",
            })
            (assets / "assets.json").write_text(json.dumps(plan), encoding="utf-8")

            output = root / "modules"
            result = bundle_builder.build(voices, assets, dgvoodoo, output)
            localized = json.loads((output / "localization" / "assets.json").read_text(encoding="utf-8"))
            video = json.loads((output / "video" / "video.json").read_text(encoding="utf-8"))
            self.assertTrue(result["components"]["video"])
            self.assertFalse(any(item["file"].endswith(".bik") for item in localized["assets"]))
            self.assertEqual([item["file"] for item in video["assets"]], ["intro.bik"])
            self.assertEqual(sha((output / "video" / "asset-intro.bik").read_bytes()), sha(payload))

    def test_altered_payload_is_refused_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            voices, assets, dgvoodoo = self._fixtures(root)
            (voices / "voice-0001.pcm").write_bytes(b"changed")
            output = root / "bundle"
            with self.assertRaisesRegex(ValueError, "alterado"):
                bundle_builder.build(voices, assets, dgvoodoo, output)
            self.assertFalse(output.exists())

    def test_ui_component_optional_and_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            voices, assets, dgvoodoo = self._fixtures(root)
            ui = root / "ui"
            (ui / "payload").mkdir(parents=True)
            dll = b"ui cache dll"
            catalog = b"ui catalog"
            (ui / "payload" / "hd-ui-cache.dll").write_bytes(dll)
            (ui / "payload" / "ui-ptbr.bin").write_bytes(catalog)
            (ui / "ui.json").write_text(json.dumps({"schema": 1, "assets": [
                {"file": "hd-ui-cache.dll", "source_sha256": None, "result_sha256": sha(dll),
                 "payload": "payload/hd-ui-cache.dll"},
                {"file": "ui-ptbr.bin", "source_sha256": None, "result_sha256": sha(catalog),
                 "payload": "payload/ui-ptbr.bin"}]}), encoding="utf-8")
            output = root / "bundle"
            result = bundle_builder.build(voices, assets, dgvoodoo, output, ui=ui)
            self.assertTrue(result["components"]["ui"])
            self.assertTrue((output / "ui" / "ui.json").is_file())
            self.assertTrue((output / "ui" / "payload" / "ui-ptbr.bin").is_file())
            meta = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
            self.assertIn("ui", meta["experimental"])

    def test_ui_payload_alterado_e_recusado(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            voices, assets, dgvoodoo = self._fixtures(root)
            ui = root / "ui"
            (ui / "payload").mkdir(parents=True)
            (ui / "payload" / "ui-ptbr.bin").write_bytes(b"changed")
            (ui / "ui.json").write_text(json.dumps({"schema": 1, "assets": [
                {"file": "ui-ptbr.bin", "source_sha256": None, "result_sha256": "b" * 64,
                 "payload": "payload/ui-ptbr.bin"}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "alterada"):
                bundle_builder.build(voices, assets, dgvoodoo, root / "bundle", ui=ui)

    def test_non_review_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            voices, assets, dgvoodoo = self._fixtures(root)
            manifest = json.loads((voices / "manifest.json").read_text(encoding="utf-8"))
            manifest["id"] = "sr1-ptbr-full"
            (voices / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "revisão"):
                bundle_builder.build(voices, assets, dgvoodoo, root / "bundle")


if __name__ == "__main__":
    unittest.main()
