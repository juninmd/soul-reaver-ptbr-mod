#!/usr/bin/env python3
"""Bounded candidate runner. Runtime execution requires an explicit opt-in."""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

RUNNER = Path(__file__).resolve()
ROOT = next(p for p in RUNNER.parents if (p / "AGENTS.md").is_file())
PREFLIGHT = ROOT / "tools/subtitles/unicode_candidate_preflight.py"
BRIDGE = ROOT / "tools/subtitles/unicode_runtime_bridge.js"
MAX_SECONDS = 90
STARTUP_SECONDS = 20
SETUP_SECONDS = 60
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path)
    parser.add_argument("--overlayDLL", required=True, type=Path)
    parser.add_argument("--captionsJSON", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime-authorized", action="store_true",
                        help="explicit authorization for this bounded runtime attempt")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--bridge", type=Path, default=BRIDGE)
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= MAX_SECONDS:
        parser.error(f"--seconds precisa estar entre 1 e {MAX_SECONDS}")
    return args


def run_preflight(args):
    """Use the maintained preflight as a subprocess before optional imports."""
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("--output precisa ser uma pasta validate nova e vazia; sobrescrita recusada")
    if not (output == (ROOT / "validate").resolve() or (ROOT / "validate").resolve() in output.parents):
        raise RuntimeError("--output precisa ficar dentro de validate/")
    if args.game.resolve() in output.parents:
        raise RuntimeError("--output não pode ficar dentro de --game")
    args.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("unicode_candidate_preflight", PREFLIGHT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"preflight indisponível: {PREFLIGHT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        # Preflight output lives under validate/; runtime outputs stay in this
        # same fresh folder and are created with exclusive mode.
        report = module.preflight(args.game, args.overlayDLL, args.captionsJSON)
        report["runtime_attempted"] = False
        report_path = args.output / "preflight.json"
        with report_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return report
    except Exception as exc:
        error_path = args.output / "preflight-error.json"
        with error_path.open("x", encoding="utf-8") as stream:
            json.dump({"runtime_attempted": False, "errors": [str(exc)]}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        raise


def _owned_setup_dialog(pid: int) -> bool:
    """Find a setup dialog belonging to our PID. Never sends global input."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]

    @enum_proc
    def visit(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        cls, title = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(hwnd, cls, len(cls))
        user32.GetWindowTextW(hwnd, title, len(title))
        text = (cls.value + " " + title.value).casefold()
        if "setup" in text or "configuration" in text or "configura" in text:
            found.append((hwnd, text))
        return True

    user32.EnumWindows.argtypes = [enum_proc, ctypes.c_void_p]
    user32.EnumWindows(visit, 0)
    if not found:
        return False
    # Intentionally stop short of choosing/clicking controls: localized combo
    # labels and option ordering are not established by offline evidence.
    return True


class OwnedProcessHandle:
    """Windows handle pinned to the spawned process object, avoiding PID reuse."""

    def __init__(self, kernel32, handle):
        self.kernel32 = kernel32
        self.handle = handle
    @classmethod
    def open(cls, pid: int):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.TerminateProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        access = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZE
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return cls(kernel32, handle)

    def active(self) -> bool:
        exit_code = ctypes.c_ulong()
        if not self.kernel32.GetExitCodeProcess(self.handle, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return exit_code.value == STILL_ACTIVE

    def terminate(self, exit_code=1):
        if self.active():
            if not self.kernel32.TerminateProcess(self.handle, exit_code):
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


BOOTSTRAP = r"""
'use strict';
const FOV_RVA = 0xEC354;
const FOV_FROM = 0.625;
const FOV_TO = 0.46875;
const fovGuard = { attempted: false, applied: false, reason: null };
const registryGuard = { installed: false, exports: [] };
let registryCallbacks = [];
let registryReplacements = [];

function patchApprovedFov() {
  fovGuard.attempted = true;
  const address = Process.mainModule.base.add(FOV_RVA);
  const range = Process.findRangeByAddress(address);
  if (!range || !range.protection.includes('r')) {
    fovGuard.reason = 'approved-rdata-address-not-readable';
    return;
  }
  const before = address.readFloat();
  if (Math.abs(before - FOV_FROM) > 0.000001) {
    fovGuard.reason = 'guard-float-mismatch:' + before;
    return;
  }
  const originalProtection = range.protection;
  let changedProtection = false;
  try {
    if (!originalProtection.includes('w')) {
      if (!Memory.protect(address, 4, 'rw-')) {
        fovGuard.reason = 'could-not-enable-temporary-write';
        return;
      }
      changedProtection = true;
    }
    address.writeFloat(FOV_TO);
  } finally {
    if (changedProtection && !Memory.protect(address, 4, originalProtection)) {
      fovGuard.reason = 'failed-to-restore-original-page-protection';
      return;
    }
  }
  fovGuard.applied = true;
  fovGuard.reason = 'guarded-memory-only';
}

function installRegistryGuards(module) {
  for (const name of ['RegSetValueExA', 'RegSetValueExW']) {
    const target = module.findExportByName(name);
    if (!target || registryReplacements.some(item => item.target.equals(target))) continue;
    const replacement = new NativeCallback(function () { return 0; }, 'uint',
      ['pointer', 'pointer', 'uint', 'uint', 'pointer', 'uint'], 'stdcall');
    Interceptor.replace(target, replacement);
    registryCallbacks.push(replacement);
    registryReplacements.push({ target, name });
    registryGuard.exports.push(name);
  }
  registryGuard.installed = registryGuard.exports.includes('RegSetValueExA') &&
    registryGuard.exports.includes('RegSetValueExW');
}

patchApprovedFov();
const advapi = Process.findModuleByName('advapi32.dll');
if (advapi) installRegistryGuards(advapi);
const observer = Process.attachModuleObserver({
  onAdded(module) { if (module.name.toLowerCase() === 'advapi32.dll') installRegistryGuards(module); }
});
function bootstrapReport() { return { fov: fovGuard, registry: registryGuard }; }
"""


def _with_bootstrap(bridge_source: str) -> str:
    marker = "'use strict';"
    if not bridge_source.startswith(marker):
        raise RuntimeError("bridge source não inicia com strict mode esperado")
    # Merge bootstrap into the same Frida script to avoid bridge/host ordering races.
    combined = bridge_source.replace(marker, marker + "\n" + BOOTSTRAP, 1)
    export_marker = "rpc.exports = {"
    if combined.count(export_marker) != 1:
        raise RuntimeError("esperava exatamente uma declaração rpc.exports na bridge")
    return combined + "\nrpc.exports.bootstrapreport = bootstrapReport;\n"


def runtime_attempt(args, report):
    """This function is reachable only after explicit CLI authorization."""
    output = args.output.resolve()
    allowed = {"preflight.json"}
    if not output.is_dir() or any(item.name not in allowed for item in output.iterdir()):
        raise RuntimeError("--output deve conter apenas o preflight.json recém-gerado")
    log_path = output / "runtime-events.jsonl"
    status = {"runtime_attempted": True, "process_exited": False,
              "termination": "not_started", "errors": [], "setup_dialog_seen": False,
              "first_draw_log_seen": False, "homologated": False}
    start = time.monotonic()
    process = None
    script = None
    owned_handle = None
    log_stream = log_path.open("x", encoding="utf-8", newline="\n")

    def event(kind, payload=None):
        row = {"timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "monotonic_seconds": time.monotonic() - start,
               "event": kind, "payload": payload}
        log_stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        log_stream.flush()

    try:
        # CIM check avoids a global name-based kill or attaching to a user run.
        existing = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "@(Get-CimInstance Win32_Process -Filter \"Name='kain2.exe'\").Count"],
            capture_output=True, text=True, timeout=10, check=True)
        if int(existing.stdout.strip().splitlines()[-1]) != 0:
            raise RuntimeError("já existe kain2.exe; recusando coexistência")

        # Optional Frida package import happens only after preflight, CIM gate,
        # and creation of exclusive run logs.
        frida_packages = ROOT / "staging/integration-probe/python-packages"
        if frida_packages.is_dir():
            sys.path.insert(0, str(frida_packages))
        import frida  # noqa: PLC0415

        game_dir = args.game.resolve()
        executable = str(game_dir / "kain2.exe")
        device = frida.get_local_device()
        pid = device.spawn([executable, "under", "1", "-voice", "-inspectral"], cwd=str(game_dir))
        status["owned_pid"] = pid
        status["termination"] = "spawned_paused"
        event("spawned_paused", {"pid": pid})
        owned_handle = OwnedProcessHandle.open(pid)
        process = device.attach(pid)

        def on_message(message, data):
            if message.get("type") == "send":
                payload = message.get("payload")
                if isinstance(payload, dict) and payload.get("event") == "unicode-render-succeeded":
                    status["first_draw_log_seen"] = True
                event("send", payload)
            elif message.get("type") == "error":
                status["errors"].append(message.get("stack") or message.get("description"))
                event("error", message)
            else:
                event("message", message)

        script = process.create_script(_with_bootstrap(args.bridge.read_text(encoding="utf-8")))
        script.on("message", on_message)
        script.load()
        bootstrap_report = script.exports_sync.bootstrapreport()
        event("bootstrap_guards", bootstrap_report)
        if not bootstrap_report["fov"]["applied"] or not bootstrap_report["registry"]["installed"]:
            raise RuntimeError("bootstrap recusado: guard FOV ou registro incompleto")
        captions = json.loads(args.captionsJSON.read_text(encoding="utf-8"))
        configured = script.exports_sync.configure({
            "hostHashVerified": True, "beforeDeviceCreation": True,
            "expectedExeBase": 4194304,
            "overlayPath": str(args.overlayDLL.resolve()),
            "captionRows": captions["captions"],
        })
        event("configured", configured)
        device.resume(pid)
        start = time.monotonic()
        status["termination"] = "running"

        setup_deadline = time.monotonic() + min(STARTUP_SECONDS, args.seconds)
        setup_seen = False
        while time.monotonic() < setup_deadline and owned_handle.active():
            if _owned_setup_dialog(pid):
                setup_seen = True
                status["setup_dialog_seen"] = True
                event("setup_dialog_manual_action_required", {"pid": pid,
                      "resolution": "640x480x32", "action": "left_for_user"})
                break
            time.sleep(0.2)
        if setup_seen:
            ui_deadline = time.monotonic() + min(SETUP_SECONDS, max(0, args.seconds - (time.monotonic() - start)))
            while time.monotonic() < ui_deadline and owned_handle.active():
                time.sleep(min(0.2, max(0.0, ui_deadline - time.monotonic())))

        deadline = start + args.seconds
        while time.monotonic() < deadline and owned_handle.active():
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        if not owned_handle.active():
            status["process_exited"] = True
            status["termination"] = "process_exited"
    except Exception as exc:
        status["errors"].append(f"{type(exc).__name__}: {exc}")
        event("runner_error", {"error": str(exc), "traceback": traceback.format_exc()})
    finally:
        try:
            if script is not None:
                try:
                    script.exports_sync.dispose()
                except Exception as exc:
                    status["errors"].append(f"RPC dispose: {exc}")
                try:
                    script.unload()
                except Exception as exc:
                    status["errors"].append(f"script unload: {exc}")
            if process is not None:
                try:
                    process.detach()
                except Exception as exc:
                    status["errors"].append(f"detach: {exc}")
            pid = status.get("owned_pid")
            if pid is not None and owned_handle is not None and owned_handle.active():
                try:
                    owned_handle.terminate()
                    status["termination"] = "owned_pid_terminated"
                except Exception as exc:
                    status["errors"].append(f"owned PID termination: {exc}")
            if pid is not None and owned_handle is not None:
                status["process_exited"] = not owned_handle.active()
                owned_handle.close()
            event("attempt_finished", status)
            log_stream.close()
        except Exception as exc:
            status["errors"].append(f"cleanup: {exc}")
        status_path = output / "runtime-status.json"
        with status_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(status, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return status


def main(argv=None):
    args = parse_args(argv)
    try:
        report = run_preflight(args)
    except Exception as exc:
        print(json.dumps({"runtime_attempted": False, "preflight_error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"runtime_attempted": False, "preflight": report}, ensure_ascii=False))
    if not args.runtime_authorized:
        return 0
    try:
        # Preflight is a gating stage; its report is kept in the requested folder.
        status = runtime_attempt(args, report)
        return 0 if not status["errors"] else 1
    except Exception as exc:
        print(json.dumps({"runtime_attempted": True, "error": str(exc), "homologated": False}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
