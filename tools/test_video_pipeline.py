import tempfile
import unittest
from unittest.mock import patch
from fractions import Fraction
from pathlib import Path
import video_upscale_poc as up
import video_hd_runtime_poc as hd
import video_hd_batch as batch

class PipelineTests(unittest.TestCase):
    def test_output_size_budget_enforces_five_times_source_cap(self):
        source_size = 4_473_812
        exact_limit = source_size * 5
        accepted = batch.validate_output_size(exact_limit, source_size)
        self.assertEqual(batch.MAX_OUTPUT_SIZE_RATIO, 5.0)
        self.assertAlmostEqual(accepted["actual_ratio"], 5.0)
        with self.assertRaisesRegex(ValueError, "exceeds the 5x source limit"):
            batch.validate_output_size(exact_limit + 1, source_size)
        with self.assertRaisesRegex(ValueError, "must be positive"):
            batch.validate_output_size(10, 0)

    def test_oversized_retry_lowers_only_rad_target_data_rate(self):
        flags = ["/V100", "/D900000", "/U6", "/L4"]
        self.assertEqual(batch.lower_bink_data_rate(flags), ["/V100", "/D600000", "/U6", "/L4"])
        self.assertIsNone(batch.lower_bink_data_rate(["/V100", "/D100000", "/U6", "/L4"]))
        self.assertIsNone(batch.lower_bink_data_rate(["/V100", "/U6", "/L4"]))

    def test_configurable_video_geometry_supports_compact_1k_canvas(self):
        batch.set_output_geometry(1024, 768)
        self.assertEqual((batch.TARGET_WIDTH, batch.TARGET_HEIGHT), (1024, 768))
        self.assertEqual((batch.CONTENT_WIDTH, batch.CONTENT_HEIGHT), (1024, 768))
        self.assertEqual((batch.PILLAR_X, batch.PILLAR_Y), (0, 0))
        batch.set_output_geometry(2560, 1440)
        self.assertEqual((batch.CONTENT_WIDTH, batch.CONTENT_HEIGHT), (1920, 1440))
        self.assertEqual((batch.PILLAR_X, batch.PILLAR_Y), (320, 0))

    def test_configurable_video_geometry_rejects_non_exact_4_3_dimensions(self):
        with self.assertRaisesRegex(ValueError, "divisible"):
            batch.set_output_geometry(1000, 700)

    def test_cadence_json_handles_side_data_and_timestamp_quantization(self):
        import json
        payload = dict(streams=[dict(time_base="1/1000")], frames=[
            dict(best_effort_timestamp_time=value, side_data_list=[dict(side_data_type="SEI")])
            for value in ("0.000000", "0.033000", "0.067000", "0.100000")])
        with patch.object(up.subprocess, "check_output", return_value=json.dumps(payload)):
            stamps = up.validate_source_cadence("fixture.mp4", Fraction(0), 4, Fraction(30))
        self.assertEqual(len(stamps), 4)
        payload["frames"][2]["best_effort_timestamp_time"] = "0.080000"
        with patch.object(up.subprocess, "check_output", return_value=json.dumps(payload)):
            with self.assertRaisesRegex(ValueError, "constant frame rate"):
                up.validate_source_cadence("fixture.mp4", Fraction(0), 4, Fraction(30))

    def test_exact_frame_window_rounds_to_source_cadence(self):
        fps = Fraction(30000, 1001)
        self.assertEqual(round(Fraction('7.0') * fps), 210)
        self.assertEqual(up.ceil_fraction(Fraction('20.0') * fps), 600)
        self.assertEqual(up.ceil_fraction(Fraction('20.01') * fps), 600)
        self.assertEqual(up.ceil_fraction(Fraction('20.04') * fps), 601)

    def test_cli_requires_sources_and_rejects_invalid_modes(self):
        import subprocess, sys
        script = Path(up.__file__)
        r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn('--source', r.stderr)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); src = d/'s'; aud = d/'a'; src.write_bytes(b'x'); aud.write_bytes(b'x')
            r = subprocess.run([sys.executable, str(script), '--source', str(src), '--audio', str(aud), '--out', str(d/'o'), '--audio-origin', 'bad'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)

    def test_ass_source_window_clips_and_rebases_overlapping_events(self):
        body = """[Script Info]
Title: test
[V4+ Styles]
Format: Name,Fontname,Fontsize
Style: Default,Arial,20
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:19.00,0:00:21.00,Default,,0,0,0,,leading
Dialogue: 0,0:00:20.50,0:00:23.00,Default,,0,0,0,,overlap
Dialogue: 0,0:00:28.00,0:00:30.00,Default,,0,0,0,,trailing
"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)/'src.ass'; dst = Path(td)/'dst.ass'; src.write_text(body, encoding='utf8')
            up.rebase_ass(src, dst, 20.0, 7.0); out = dst.read_text(encoding='utf8')
            self.assertIn('Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,leading', out)
            self.assertIn('Dialogue: 0,0:00:00.50,0:00:03.00,Default,,0,0,0,,overlap', out)
            self.assertNotIn('trailing', out)

    def test_ass_metrics_count_visible_events_for_full_and_partial_files(self):
        body = """[Script Info]
[V4+ Styles]
Format: Name,Fontname,Fontsize
Style: Default,Arial,20
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Comment: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,not visible
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,áudio em português
Dialogue: 0,0:00:02.10,0:00:02.30,Default,,0,0,0,,século futuro
Dialogue: 0,0:00:08.00,0:00:09.00,Default,,0,0,0,,fora do recorte
"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'src.ass'; full = Path(td) / 'full.ass'; partial = Path(td) / 'partial.ass'
            src.write_text(body, encoding='utf8')
            full_metrics = batch.rescale_ass(src, full, 2560, 1440)
            partial_metrics = batch.rescale_ass(src, partial, 2560, 1440, (0.5, 2.0))
            self.assertEqual(full_metrics['events_kept'], 3)
            self.assertEqual(partial_metrics['events_kept'], 2)
            self.assertEqual(partial_metrics['events_dropped'], 1)
            self.assertIn('áudio em português', partial.read_text(encoding='utf8'))
            self.assertIn('0:00:01.60,0:00:01.80', partial.read_text(encoding='utf8'))

    def test_blackout_requires_timed_bounded_mask_and_visible_dialogue(self):
        metrics = {'events_kept': 1}
        with self.assertRaisesRegex(ValueError, 'blackout_intervals'):
            batch.blackout_filters({'blackout': True}, metrics)
        with self.assertRaisesRegex(ValueError, 'visible PT-BR'):
            batch.blackout_filters({'blackout': True, 'blackout_intervals': [
                {'x': 10, 'y': 10, 'w': 30, 'h': 20, 'start': 0, 'end': 1}
            ]}, {'events_kept': 0})
        self.assertEqual(batch.blackout_filters({'blackout': False}, None), [])
        self.assertEqual(batch.blackout_filters({'blackout': True, 'blackout_intervals': [
            {'x': 10, 'y': 10, 'w': 30, 'h': 20, 'start': 0, 'end': 1}
        ]}, metrics), [
            "drawbox=x=10:y=10:w=30:h=20:color=black:t=fill:enable='between(t,0.000,1.000)'"
        ])
        with self.assertRaisesRegex(ValueError, 'outside the canvas'):
            batch.blackout_filters({'blackout': True, 'blackout_intervals': [
                {'x': 2550, 'y': 10, 'w': 30, 'h': 20, 'start': 0, 'end': 1}
            ]}, metrics)

    def test_png_dimensions_are_read_from_header(self):
        import struct
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'frame.png'
            path.write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',640,320)+b'\x08\x02\x00\x00\x00')
            self.assertEqual(up.png_dimensions(path),(640,320))

    def test_ai_expected_dimensions_derive_from_source(self):
        for width,height in ((640,480),(320,240)):
            expected=(2560,1920) if width==640 else (1280,960)
            self.assertEqual(up.expected_ai_dimensions(width,height),expected)

    def test_output_probe_accepts_matching_stream_invariants(self):
        payload={"streams":[{"codec_type":"video","nb_read_frames":"180","width":2560,"height":1440,"avg_frame_rate":"30000/1001"},{"codec_type":"audio","sample_rate":"44100","channels":2}],"format":{"duration":"6.006"}}
        self.assertEqual(up.validate_encoded_probe(payload,180,Fraction(30000,1001),Fraction(180*1001,30000))[0]["width"],2560)
        payload["streams"][1]["channels"]=1
        with self.assertRaises(RuntimeError): up.validate_encoded_probe(payload,180,Fraction(30000,1001),Fraction(180*1001,30000))

    def test_hd_probe_rejects_wrong_audio_and_duration(self):
        video={"codec_type":"video","width":"2560","height":"1440","avg_frame_rate":"5000000/166833","nb_read_frames":"180"}
        audio={"codec_type":"audio","sample_rate":"44100","channels":2,"duration":"6.006"}
        payload={"streams":[video,audio],"format":{"duration":"6.006"}}
        self.assertEqual(hd.require_video(payload,"input clip")[0],video)
        audio["channels"]=1
        with self.assertRaises(ValueError): hd.require_video(payload,"input clip")

    def test_help_documents_audio_and_ass_origins(self):
        import subprocess, sys
        r = subprocess.run([sys.executable, str(Path(up.__file__)), '--help'], capture_output=True, text=True, check=True)
        self.assertIn('--audio-origin', r.stdout); self.assertIn('--ass-origin', r.stdout)

if __name__ == '__main__': unittest.main()
