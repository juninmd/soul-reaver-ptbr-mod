import importlib.util
import contextlib
import ctypes
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).with_name("run_unicode_poc.py")
SPEC = importlib.util.spec_from_file_location("unicode_runtime_runner", MODULE)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class RuntimeRunnerTests(unittest.TestCase):
    def test_seconds_bounds(self):
        for value in ("0", "91", "-1"):
            with self.assertRaises(SystemExit):
                runner.parse_args(["--game", "g", "--overlayDLL", "o", "--captionsJSON", "c",
                                   "--output", "x", "--seconds", value])
        self.assertEqual(runner.parse_args(["--game", "g", "--overlayDLL", "o", "--captionsJSON", "c",
                                            "--output", "x", "--seconds", "90"]).seconds, 90)

    def test_no_flag_never_imports_frida_or_spawns(self):
        with tempfile.TemporaryDirectory(dir=runner.ROOT / "validate") as temp:
            output = Path(temp) / "fresh"
            with mock.patch.object(runner, "run_preflight", return_value={"read_only": True}), \
                 mock.patch.object(runner, "runtime_attempt") as runtime, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(["--game", "g", "--overlayDLL", "o", "--captionsJSON", "c",
                                              "--output", str(output)]), 0)
                runtime.assert_not_called()
        self.assertNotIn("frida", sys.modules)

    def test_preflight_failure_happens_before_optional_import(self):
        with tempfile.TemporaryDirectory(dir=runner.ROOT / "validate") as temp:
          output = Path(temp) / "fresh"
          with mock.patch.object(runner, "run_preflight", side_effect=ValueError("bad candidate")), \
             mock.patch("builtins.__import__", wraps=__import__) as importer, \
             mock.patch.object(runner, "runtime_attempt") as runtime, \
             contextlib.redirect_stderr(io.StringIO()):
            code = runner.main(["--game", "g", "--overlayDLL", "o", "--captionsJSON", "c",
                                "--output", str(output), "--runtime-authorized"])
            self.assertEqual(code, 2)
            runtime.assert_not_called()
            self.assertFalse(any("frida" in str(call) for call in importer.call_args_list))

    def test_bootstrap_guard_contract_is_embedded_before_bridge(self):
        combined = runner._with_bootstrap("'use strict';\nrpc.exports = { configure() {} };\n")
        for token in ("0xEC354", "0.625", "0.46875", "RegSetValueExA", "RegSetValueExW",
                      "attachModuleObserver", "guard-float-mismatch"):
            self.assertIn(token, combined)
        self.assertEqual(combined.count("rpc.exports = {"), 1)
        self.assertGreater(combined.index("rpc.exports.bootstrapreport = bootstrapReport;"),
                           combined.index("rpc.exports = { configure() {} };"))

    def test_spawned_process_handle_uses_query_exit_code_and_owned_termination(self):
        calls = []
        class Kernel:
            def GetExitCodeProcess(self, handle, ptr):
                calls.append("query")
                ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ulong))[0] = runner.STILL_ACTIVE
                return 1
            def TerminateProcess(self, handle, code):
                calls.append(("terminate", handle, code))
                return 1
            def CloseHandle(self, handle):
                calls.append(("close", handle))
        handle = runner.OwnedProcessHandle(Kernel(), 1234)
        self.assertTrue(handle.active())
        handle.terminate(7)
        handle.close()
        self.assertIn(("terminate", 1234, 7), calls)
        self.assertEqual(calls[-1], ("close", 1234))
        self.assertFalse(hasattr(runner, "_process_exists"))

    def test_runtime_authorized_route_is_mocked_without_spawning_or_importing_frida(self):
        with tempfile.TemporaryDirectory(dir=runner.ROOT / "validate") as temp:
            output = Path(temp) / "fresh"
            output.mkdir()
            (output / "preflight.json").write_text("{}", encoding="utf-8")
            args = runner.parse_args(["--game", "g", "--overlayDLL", "o", "--captionsJSON", "c",
                                     "--output", str(output), "--runtime-authorized"])
            status = {"errors": []}
            with mock.patch.object(runner, "run_preflight", return_value={"runtime_attempted": False}), \
                 mock.patch.object(runner, "runtime_attempt", return_value=status) as runtime, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(["--game", "g", "--overlayDLL", "o", "--captionsJSON", "c",
                                              "--output", str(output), "--runtime-authorized"]), 0)
                runtime.assert_called_once()
            self.assertNotIn("frida", sys.modules)


if __name__ == "__main__":
    unittest.main()
