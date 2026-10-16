"""Run a staged RAD command hidden and close only its verified Done window."""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import time


def windows(pid):
    user = ctypes.windll.user32
    result = []
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback
    def visit(window, _):
        owner = ctypes.c_ulong()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(4096)
            user.GetWindowTextW(window, title, len(title))
            result.append((window, title.value))
        return True

    user.EnumWindows(visit, 0)
    return result


def run(executable, command, inputs, output, flags=None, timeout=None):
    if output.exists():
        raise ValueError("Output already exists; choose a new candidate")
    info = subprocess.STARTUPINFO()
    info.dwFlags = subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    args = [str(executable.resolve()), command, *[str(p.resolve()) for p in inputs], str(output.resolve())]
    if flags is None:
        flags = ["/V100", "/D900000", "/U6", "/L4"] if command == "Binkc" else ["/T0", "/L4"]
    args += list(flags)
    process = subprocess.Popen(args, startupinfo=info)
    marker = output.with_suffix(output.suffix + ".process.json")
    marker.write_text(json.dumps(dict(pid=process.pid, command=args), indent=2), encoding="utf-8")
    print(f"RAD process {process.pid}; tracking {output}", flush=True)
    reported = time.monotonic()
    deadline = None if not timeout else reported + timeout
    while process.poll() is None:
        if deadline and time.monotonic() > deadline:
            process.kill()
            raise ValueError("RAD timed out")
        for handle, title in windows(process.pid):
            if "Done!" in title:
                print(title, flush=True)
                ctypes.windll.user32.PostMessageW(handle, 0x111, 2, 0)
        if time.monotonic() - reported > 20:
            print(json.dumps(dict(pid=process.pid, windows=[t for _, t in windows(process.pid)],
                                  output_bytes=output.stat().st_size if output.exists() else 0)), flush=True)
            reported = time.monotonic()
        time.sleep(0.25)
    if process.returncode or not output.exists() or output.stat().st_size < 100:
        raise ValueError(f"RAD failed: {process.returncode}")
    print(f"Completed {output.stat().st_size} bytes", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("Binkc", "BinkMix"))
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.exe, args.command, args.input, args.output)
