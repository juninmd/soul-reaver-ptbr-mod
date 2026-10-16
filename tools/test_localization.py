import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import math
import struct
import wave
from unittest.mock import patch

import install_assets
import localize_ui
import audio_pipeline
import build_dialogue_subtitles


class AssetTransactionTests(unittest.TestCase):
    def test_package_plan_must_match_hash_bound_audio_text_and_voice_identity(self):
        root = Path(audio_pipeline.__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(dir=root, prefix=".voice-approval-test-") as temporary:
            directory = Path(temporary)
            audio_hash = "a" * 64
            reference_hash = "b" * 64
            gallery_path = directory / "gallery.json"
            gallery_path.write_text("{}", encoding="utf8")
            gallery_hash = hashlib.sha256(gallery_path.read_bytes()).hexdigest()
            chain = [{"metadata_path": "staging/example/metadata.json", "audio_sha256": audio_hash}]
            audio = {"schema": 1, "artifact_type": "user-voice-audio-approval-ledger",
                     "audio_approved_count": 1,
                     "source_manifest": {"path": gallery_path.relative_to(root).as_posix(),
                                         "sha256": gallery_hash},
                     "takes": [{"id": 7, "speaker": "raziel", "audio_sha256": audio_hash,
                                "seed": 42, "reference_audio_sha256": reference_hash,
                                "metadata_provenance_chain": chain, "audio_approved": True}]}
            audio_path = directory / "audio.json"
            audio_path.write_text(json.dumps(audio), encoding="utf8")
            audio_sha = hashlib.sha256(audio_path.read_bytes()).hexdigest()
            review = {"approval_ledger_sha256": audio_sha, "source_gallery_sha256": gallery_hash}
            review_path = directory / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf8")
            text_body = "Venha, Raziel."
            text_hash = hashlib.sha256(text_body.encode("utf8")).hexdigest()
            proposal_path = directory / "proposal.json"
            proposal_path.write_text(json.dumps({"artifact_type": "ptbr-text-review-import-proposal",
                "proposal_only": True, "proposed_text_approval_count": 1}), encoding="utf8")
            text = {"schema": 1, "artifact_type": "user-approved-ptbr-dialogue-texts",
                    "source_audio_approval": {"sha256": audio_sha},
                    "source_review": {"path": review_path.relative_to(root).as_posix(),
                                      "sha256": hashlib.sha256(review_path.read_bytes()).hexdigest()},
                    "source_text_proposal": {"path": proposal_path.relative_to(root).as_posix(),
                                             "sha256": hashlib.sha256(proposal_path.read_bytes()).hexdigest()},
                    "approved_count": 1,
                    "takes": [{"id": 7, "speaker": "raziel", "text_ptbr": text_body,
                               "text_sha256": text_hash, "audio_sha256": audio_hash,
                               "seed": 42, "reference_audio_sha256": reference_hash,
                               "metadata_provenance_chain": chain, "provenance_status": "verified",
                               "text_approved": True}]}
            text_path = directory / "text.json"
            text_path.write_text(json.dumps(text), encoding="utf8")
            voice = {"id": 7, "speaker": "raziel", "text_ptbr": text_body,
                     "text_sha256": text_hash, "audio_sha256": audio_hash,
                     "seed": 42, "reference_audio_sha256": reference_hash,
                     "metadata_provenance_chain": chain,
                     "approved_text": True, "approved_audio": True}
            checked = audio_pipeline.verify_approval_sources([voice], audio_path, text_path)
            self.assertEqual(checked["voices"][7]["seed"], 42)
            voice["seed"] = 43
            with self.assertRaisesRegex(ValueError, "seed|provenance"):
                audio_pipeline.verify_approval_sources([voice], audio_path, text_path)

    def test_fmv_ids_cannot_overwrite_voice_slots_or_native_captions(self):
        # FMV 100 is Moebius in verse, but slot 100 is an unrelated NPC bark.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "movie-plan.json"
            plan.write_text(json.dumps(dict(schema=1, voices=[dict(
                id=100, fmv="verse", speaker="moebius", text_ptbr="Onde o tempo...")])) , encoding="utf-8")
            with patch.object(audio_pipeline, "inspect") as inspect_game:
                with self.assertRaisesRegex(ValueError, "FMV"):
                    audio_pipeline.build_package(root / "game", plan, root / "package", review=True)
                inspect_game.assert_not_called()
            with self.assertRaisesRegex(ValueError, "FMV"):
                build_dialogue_subtitles.build(plan, root / "captions.tsv", review_candidate=True)
            self.assertFalse((root / "package").exists())
            self.assertFalse((root / "captions.tsv").exists())
        with self.assertRaisesRegex(ValueError, "FMV"):
            audio_pipeline.validate_voice_namespace(dict(resource_kind="fmv", voices=[dict(id=100)]))

    def test_new_proxy_preserves_other_mods_and_removes_only_owned_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            (game / "kain2.exe").write_bytes(b"test executable")
            (game / "DDraw.dll").write_bytes(b"other graphics mod")
            target = game / "DINPUT.dll"
            target.write_bytes(b"other input mod")
            candidate = root / "candidate.dll"
            candidate.write_bytes(b"new subtitle proxy")
            sha = lambda data: hashlib.sha256(data).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(dict(schema=1, assets=[dict(file="DINPUT.dll",
                payload=candidate.name, source_sha256=None,
                result_sha256=sha(candidate.read_bytes()))])), encoding="utf8")
            with patch.object(install_assets, "EXE_SHA256", sha(b"test executable")), patch.object(install_assets, "closed"):
                with self.assertRaisesRegex(ValueError, "desconhecido"):
                    install_assets.install(game, manifest, root / "backup")
                self.assertEqual(target.read_bytes(), b"other input mod")
                target.unlink()  # Test fixture only: simulate a separate clean installation.
                install_assets.install(game, manifest, root / "backup")
                install_assets.install(game, manifest, root / "backup")
                target.write_bytes(b"subsequent modification")
                with self.assertRaisesRegex(ValueError, "Conflito"):
                    install_assets.restore(game)
                self.assertEqual(target.read_bytes(), b"subsequent modification")
                target.write_bytes(candidate.read_bytes())
                install_assets.restore(game)
                self.assertFalse(target.exists())
                self.assertEqual((game / "DDraw.dll").read_bytes(), b"other graphics mod")

    def test_unapproved_audio_needs_explicit_review_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = b"\x01\x00" * 1000
            row = dict(id=0, offset=0, length=len(original))
            take = root / "take.wav"
            with wave.open(str(take), "wb") as output:
                output.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                output.writeframes(struct.pack("<500h", *[round(5000 * math.sin(i / 10)) for i in range(500)]))
            plan = root / "plan.json"
            plan.write_text(json.dumps(dict(schema=1, voices=[dict(id=0, speaker="test",
                text_ptbr="Fala de teste.", audio=take.name,
                audio_sha256=hashlib.sha256(take.read_bytes()).hexdigest(),
                approved_text=True, approved_audio=False)])), encoding="utf8")
            with patch.object(audio_pipeline, "inspect", return_value=(original, [row])):
                with self.assertRaisesRegex(ValueError, "explicitly approved"):
                    audio_pipeline.build_package(root / "game", plan, root / "rejected")
                self.assertFalse((root / "rejected").exists())
                audio_pipeline.build_package(root / "game", plan, root / "candidate", review=True)
            report = json.loads((root / "candidate/review.json").read_text(encoding="utf8"))
            self.assertFalse(report["human_listening_approved"])
            self.assertFalse(report["voices"][0]["approved_audio"])
            payload = (root / "candidate/voice-0000.pcm").read_bytes()
            self.assertEqual(len(payload), len(original))
            self.assertNotEqual(payload, original)

    def test_install_conflict_and_restore_preserve_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            (game / "kain2.exe").write_bytes(b"test executable")
            (game / "locals.pc").write_bytes(b"original")
            (game / "savegame.her").write_bytes(b"user save")
            candidate = root / "translated.pc"
            candidate.write_bytes(b"translated")
            manifest = root / "manifest.json"
            sha = lambda b: hashlib.sha256(b).hexdigest()
            manifest.write_text(json.dumps(dict(schema=1, assets=[dict(
                file="locals.pc", payload=candidate.name,
                source_sha256=sha(b"original"), result_sha256=sha(b"translated"))])), encoding="utf-8")
            with patch.object(install_assets, "EXE_SHA256", sha(b"test executable")), patch.object(install_assets, "closed"):
                install_assets.install(game, manifest, root / "backup")
                install_assets.install(game, manifest, root / "backup")
                self.assertEqual((game / "locals.pc").read_bytes(), b"translated")
                (game / "locals.pc").write_bytes(b"another mod")
                with self.assertRaisesRegex(ValueError, "Conflito"):
                    install_assets.restore(game)
                self.assertEqual((game / "locals.pc").read_bytes(), b"another mod")
                (game / "locals.pc").write_bytes(b"translated")
                install_assets.restore(game)
                self.assertEqual((game / "locals.pc").read_bytes(), b"original")
                self.assertEqual((game / "savegame.her").read_bytes(), b"user save")

    def test_real_table_roundtrip_and_button_icons(self):
        source = Path(__file__).resolve().parent.parent / "staging/backups/steam-classic-en/locals.pc.original"
        if not source.exists():
            self.skipTest("Local original table unavailable")
        original = localize_ui.decode(source.read_bytes())
        translated = localize_ui.decode(localize_ui.build(source.read_bytes()))
        self.assertEqual(translated[46], b"iniciar novo jogo")
        self.assertEqual(translated[31], b"opcoes")
        for a, b in zip(original, translated, strict=True):
            self.assertEqual([v for v in a if v >= 128], [v for v in b if v >= 128])
        self.assertEqual(sum(a != b for a, b in zip(original, translated)), len(localize_ui.TEXT))


if __name__ == "__main__":
    unittest.main()
