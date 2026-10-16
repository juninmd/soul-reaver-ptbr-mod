# Unicode runtime bridge candidate

`unicode_runtime_bridge.js` is an isolated Frida 17 x86 candidate that connects
the game voice stream to the existing `unicode_runtime_overlay.dll` exports.
It is staging material, not installer integration or an approved game runtime
change. It must not be run against the game during offline preparation.

## Host gate and configuration

The host must independently verify the SHA-256 of the exact `kain2.exe` it is
about to instrument, before calling `rpc.exports.configure(config)`. For the
currently supported Steam-classic executable the expected SHA-256 is
`9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a`. The
host then passes `hostHashVerified: true`; this flag is an assertion from the
trusted host, not a hash check implemented by this script. The bridge also
requires an x86 process, base address `0x400000`, and the six exact bytes
`51 A1 A8 40 C6 00` at `base + 0x9E580`. It refuses the legacy hook when that
signature differs.

Configuration shape:

```js
{
  hostHashVerified: true,
  beforeDeviceCreation: true,
  expectedExeBase: 0x400000,
  overlayPath: 'D:\\isolated-candidate\\unicode_runtime_overlay.dll',
  captionRows: [
    {
      id: 291,
      duration_ms: 4200,
      text: 'Raziel encontra Dumá no santuário.',
      pages: [
        { text: 'Raziel encontra Dumá', start_ms: 0, end_ms: 2100 },
        { text: 'no santuário.', start_ms: 2100, end_ms: 4200 }
      ]
    }
  ]
}
```

The current paginated input is
`validate/02-legendas-unicode/captions-unicode-paginated-v1.json`; its host
loads the JSON envelope and passes `envelope.captions` as `captionRows`. The
candidate DLL is `staging/unicode-runtime-v2/unicode_runtime_overlay.dll`.
The recorded host GDI layout report lists 230 captions and 266/266 pages passed
(`validate/02-legendas-unicode/runtime-v2/report.json`). That layout result
does not establish game timing or runtime rendering.

The host must install/configure the bridge before the first D3D11 device is
created. `beforeDeviceCreation: true` is a host assertion, like the hash flag.
Attaching after the game already has a 3D device can miss its factory outputs
and leave the immediate context undiscovered; this candidate cannot recover an
unknown existing context.

`pages` is optional for a short caption; the bridge then uses one page spanning
`0..duration_ms`. When provided, page intervals must be integer, positive,
contiguous, gap-free, non-overlapping, start at zero, and end at the caption
duration. Joining page text with spaces and normalizing whitespace must equal
the caption text. IDs are unique integers from 0 through 478. Text must already
be NFC, contain no Unicode control/unsupported category, and fit the native
UTF-8/UTF-16 input bounds. Layout and glyph availability are still decided by
the DLL. If `SetCaptionUtf8` rejects any page, the bridge tries to clear the
caption, logs both HRESULTs, and does not truncate or retry that page every
frame.

## Hooks and timing behavior

The signature-guarded `FONTFlush` hook updates the caption and calls
`RenderOverlay` on leave. The intended ordering is after the game's font flush
and before its final frame blit; this ordering has not been demonstrated in the
target runtime. The bridge does not hook `Present`.

It reads stream state at RVAs `0x858028`, `0x85802C`, and `0x857FDC`, and calls
the cdecl `isPlaying(channel)` at `base + 0x7C6F0`. Stream states 2 through 4 are
treated as active. `GetTickCount64` supplies monotonic elapsed time. Elapsed
time advances by the full observed interval while `isPlaying` is true, without
a 250 ms cap; this counts stalls while the voice remains marked as playing.
Pause freezes the timer only when a flush observes `isPlaying == false`.
Inactive state clears the caption; reaching the configured duration clears it
and suppresses that same continuous voice ID until the stream becomes inactive.

D3D11 devices and immediate contexts are discovered from
`D3D11CreateDevice`/`D3D11CreateDeviceAndSwapChain` outputs and the device
`GetImmediateContext` method. The bridge tracks `OMSetRenderTargets` slot 33,
checks context and texture device identity, and accepts only a 3840x2160
single-sample RTV with format 27 or 28. It queries the RTV resource for
`ID3D11Texture2D`, retains the tracked context/RTV/texture references, and
releases them on target replacement or explicit disposal. It increments a
`LoadLibraryW` reference for the loaded `d3d11.dll` before installing factory
hooks. On normal disposal it detaches hooks, releases tracked COM references,
unloads the overlay DLL (whose static COM owners may release their references),
and only then drops its D3D11 pin. The render busy flag prevents the overlay's
own D3D calls from being captured as game target changes. When there is no
accepted caption page, it skips `RenderOverlay` to avoid a full-screen
transparent draw on every font flush.

An unexpected main-executable or D3D11 unload is a fast-fail process-going-away
path: hooks and JS maps are detached/cleared, but no COM destructor or
`FreeLibrary` is called from the unload callback. Native references are
abandoned for process teardown to avoid calls through stale vtables.

The bridge writes no files and performs no desktop capture, key injection,
camera patch, registry write, or game launch. Logs go to the Frida host console.

## Status and limits

Offline VM checks validate the row/page contract and clock helper only; they do
not mock native calls or establish runtime behavior. This candidate has not
been run in Frida or attached to a process. The host hash
gate, hook offsets/signatures, D3D target timing, overlay ordering, pause/resume,
skip/load/interruption, and visual result all remain unverified at runtime.
Multi-page timing is mechanically selected from the supplied intervals, but
reading rhythm and pause observation need runtime review. Repeated occurrences of
the same voice ID without an intervening inactive state cannot be distinguished
by this stream-state contract. Full-campaign coverage and Bink/FMVs are outside
this bridge. Do not describe it as integrated or approved.

Offline checks include `node --check`, VM validation of the row/page contract
and clock helper, and `python tools/subtitles/test_unicode_pipeline_integration.py`.
That integration fixture builds a two-caption UTF-8/NFC envelope, including
accented pt-BR text and a multi-page line, then passes the actual output through
the bridge's pure row validator and asserts that text, page order, and timing
survive unchanged. The harness does not mock native calls. The installed legacy
TSV path still strips accents, and the Unicode bridge/overlay remains an
unintegrated candidate. Do not run this script inside Frida, start the game, or
attach to a real process as part of offline preparation.
