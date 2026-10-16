# HD texture bridge candidate

`tools/graphics/hd_texture_bridge.js` is a passive Frida 17 candidate. It exposes
only `rpc.exports.configure()` and `dispose()`; it does not spawn or attach to a
process. An external host must hash the supported executable and the exact
manifest bytes, then call `configure()` before D3D11 device creation with
`externalHostHashVerified: true`, `beforeDeviceCreation: true`, an absolute
Windows `dllPath`, and up to 32 page records.

Each page record supplies absolute `sourceRawPath` and `hdRawPath` values, their
64-character SHA-256 strings, and exactly `width: 1024`, `height: 1024`, and
`format: "R16_UINT"`. The separate cache DLL validates raw-file hashes. All
pages register before D3D hooks are installed. Failure during registration or
initial hook setup clears registered pages, unloads the cache DLL, and removes
the D3D11 pin when native cleanup remains safe.

The bridge snapshots the x86 D3D11 factory output arguments at indexes 7/9 for
`D3D11CreateDevice` and 9/11 for `D3D11CreateDeviceAndSwapChain`. It observes
only factory-returned contexts. It hooks `PSSetShaderResources` at vtable index
8, then asks the cache to resolve every non-null SRV in the caller's valid
`StartSlot..StartSlot+NumViews` range. Binding slot 8 has no special meaning.
It substitutes only an `S_OK` result with a non-null owned SRV. The input array
stays untouched; a copied array lives through the call, and
each returned owned SRV is released once after the original call. `S_FALSE`
and failures retain the original binding. Writes observed through `UpdateSubresource`
or successful write maps (types 2–5) invalidate the resource after the original
call or `Unmap` completes.

The first replacement log reports the registered manifest dimensions only. It
does not establish actual rendered dimensions, UV alignment, alpha behavior,
correct page identity in a scene, visual quality, performance, or gameplay
compatibility. Alpha and UV behavior remain unverified; format value 57 is the
only configured texture format. The native cache has separate direct WARP
readback evidence. A Frida probe against the owned WARP host took roughly
41 seconds from spawn to configuration, exceeding its 30-second budget.
Configuration and resume were logged, followed by timeout cleanup before
context hooks or replacements were observed. Native bridge hooks remain
unverified. No game was launched or attached.

Offline checks:

```powershell
node --check tools/graphics/hd_texture_bridge.js
node tools/graphics/test_hd_texture_bridge.cjs
```

The VM test evaluates only pure validation/selection helpers and explicit
reference-tracking fixtures. It never evaluates Frida native functions.
