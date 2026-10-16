'use strict';

// Passive Frida 17 bridge. It only configures the separately built, hash-checking
// texture cache and substitutes SRVs for registered pages. It is not a loader.
const MAX_PAGES = 32;
const MAX_SRV_SLOTS = 128;
const PAGE_SIDE = 1024;
const DXGI_FORMAT_R16_UINT = 57;

function isAbsoluteWindowsPath(value) {
  return typeof value === 'string' && /^(?:[A-Za-z]:\\|\\\\)/.test(value) &&
    !/[\r\n\0]/.test(value);
}

function validatePages(pages) {
  if (!Array.isArray(pages) || pages.length === 0 || pages.length > MAX_PAGES) {
    throw new Error('pages must contain 1 through 32 entries');
  }
  const seen = new Set();
  return pages.map((page, index) => {
    if (!page || typeof page !== 'object') throw new Error('page ' + index + ' must be an object');
    const { sourceRawPath, sourceSha256, hdRawPath, hdSha256, width, height, format } = page;
    if (!isAbsoluteWindowsPath(sourceRawPath) || !isAbsoluteWindowsPath(hdRawPath)) {
      throw new Error('page ' + index + ' raw paths must be absolute Windows paths');
    }
    if (!/^[a-fA-F0-9]{64}$/.test(sourceSha256 || '') || !/^[a-fA-F0-9]{64}$/.test(hdSha256 || '')) {
      throw new Error('page ' + index + ' hashes must be 64 hexadecimal characters');
    }
    if (width !== PAGE_SIDE || height !== PAGE_SIDE || format !== 'R16_UINT') {
      throw new Error('page ' + index + ' must be 1024x1024 R16_UINT');
    }
    const key = sourceSha256.toLowerCase();
    if (seen.has(key)) throw new Error('duplicate source hash at page ' + index);
    seen.add(key);
    return { sourceRawPath, sourceSha256: sourceSha256.toLowerCase(), hdRawPath,
      hdSha256: hdSha256.toLowerCase(), width, height, format };
  });
}

// These exact helpers are used by the native hook and the offline VM fixture.
function releaseOwnedBindings(owned, release) {
  const pending = owned.splice(0, owned.length);
  const errors = [];
  for (const reference of pending) {
    try { release(reference); } catch (error) { errors.push(error); }
  }
  return errors;
}

function resolveBindingBatch(startSlot, inputs, resolve, release, maxSlots) {
  if (!Number.isInteger(startSlot) || startSlot < 0 || !Array.isArray(inputs) ||
      inputs.length > maxSlots || startSlot + inputs.length > maxSlots) {
    throw new Error('shader resource binding range is invalid');
  }
  const bindings = inputs.slice();
  const owned = [];
  const replacedSlots = [];
  try {
    for (let index = 0; index < inputs.length; index++) {
      const input = inputs[index];
      if (input === null || input === undefined) continue;
      const slot = startSlot + index;
      const result = resolve(input, slot);
      if (!result || result.hr !== 0 || result.value === null || result.value === undefined) continue;
      bindings[index] = result.value;
      owned.push(result.value);
      replacedSlots.push(slot);
    }
    return { bindings, owned, replacedSlots };
  } catch (error) {
    const releaseErrors = releaseOwnedBindings(owned, release);
    if (releaseErrors.length) error.cleanupReleaseErrors = releaseErrors;
    throw error;
  }
}

globalThis.hdTexturePure = { validatePages, resolveBindingBatch, releaseOwnedBindings };

const CACHE_EXPORTS = Object.freeze({
  register: 'RegisterTexturePage',
  resolve: 'ResolveTextureReplacement',
  invalidate: 'InvalidateTextureResource',
  clear: 'ClearTexturePages',
});
const hooks = new Map();
const knownContexts = new Set();
const mappedWrites = new Map();
let configured = false;
let busy = false;
let permanentlyDisabled = false;
let observer = null;
let cacheModule = null;
let cacheHandle = null;
let d3d11Pin = null;
let native = null;
let firstReplacementLogged = false;

function log(event, fields) { send({ bridge: 'hd-texture', event, ...(fields || {}) }); }
function keyOf(pointer) { return pointer.toString().toLowerCase(); }
function failedHr(value) { return typeof value === 'number' ? value < 0 : value.toInt32() < 0; }
function hrValue(value) { return typeof value === 'number' ? value : value.toInt32(); }

function nativeFunction(module, name, result, args) {
  const address = module.findExportByName(name);
  if (!address) throw new Error('texture cache export missing: ' + name);
  return new NativeFunction(address, result, args, 'stdcall');
}

function releaseComView(view) {
  if (!view || view.isNull()) return;
  const releaseAddress = view.readPointer().add(Process.pointerSize * 2).readPointer();
  new NativeFunction(releaseAddress, 'uint', ['pointer'], 'stdcall')(view);
}

function releaseOwnedNative(views) {
  const errors = releaseOwnedBindings(views, releaseComView);
  for (const error of errors) log('owned-view-release-failed', { error: String(error) });
}

function invalidate(resource) {
  if (!resource || resource.isNull() || !native) return;
  try { native.invalidate(resource); }
  catch (error) { log('invalidate-failed', { error: String(error) }); }
}

function hookContext(context) {
  if (!context || context.isNull()) return;
  const contextKey = keyOf(context);
  knownContexts.add(contextKey);
  const vtable = context.readPointer();
  const psSet = vtable.add(Process.pointerSize * 8).readPointer();
  const mapFn = vtable.add(Process.pointerSize * 14).readPointer();
  const unmapFn = vtable.add(Process.pointerSize * 15).readPointer();
  const copyRegionFn = vtable.add(Process.pointerSize * 46).readPointer();
  const copyResourceFn = vtable.add(Process.pointerSize * 47).readPointer();
  const updateFn = vtable.add(Process.pointerSize * 48).readPointer();

  attachOnce(psSet, 'PSSetShaderResources', {
    onEnter(args) {
      this.restoreBusy = busy;
      if (busy || !configured || !knownContexts.has(keyOf(args[0]))) return;
      const start = args[1].toUInt32();
      const count = args[2].toUInt32();
      if (count === 0 || count > MAX_SRV_SLOTS || start + count > MAX_SRV_SLOTS || args[3].isNull()) return;
      const originalViews = args[3];
      const inputs = [];
      for (let i = 0; i < count; i++) {
        const input = originalViews.add(i * Process.pointerSize).readPointer();
        inputs.push(input.isNull() ? null : input);
      }
      let batch;
      let didReplace = false;
      busy = true;
      try {
        batch = resolveBindingBatch(start, inputs, input => {
          const out = Memory.alloc(Process.pointerSize);
          out.writePointer(ptr(0));
          const hr = hrValue(native.resolve(args[0], input, out));
          if (hr !== 0) return { hr, value: null };
          const resolved = out.readPointer();
          if (resolved.isNull()) return { hr, value: null };
          return { hr, value: resolved };
        }, releaseComView, MAX_SRV_SLOTS);
        if (batch.owned.length > 0) {
          const replacementArray = Memory.alloc(count * Process.pointerSize);
          for (let i = 0; i < count; i++) {
            replacementArray.add(i * Process.pointerSize).writePointer(batch.bindings[i] || ptr(0));
          }
          this.originalArray = originalViews;
          this.replacementArray = replacementArray;
          this.ownedViews = batch.owned;
          args[3] = replacementArray;
          didReplace = true;
        }
      } catch (error) {
        if (batch && batch.owned.length > 0 && !didReplace) releaseOwnedNative(batch.owned);
        log('resolve-failed', { error: String(error), cleanupReleaseErrors:
          error.cleanupReleaseErrors ? error.cleanupReleaseErrors.map(String) : undefined });
      } finally { busy = false; }
      if (didReplace && !firstReplacementLogged) {
        firstReplacementLogged = true;
        log('first-replacement', { slot: batch.replacedSlots[0], width: PAGE_SIDE, height: PAGE_SIDE,
          format: 'R16_UINT', dimensionsSource: 'registered manifest', hresult: '0x00000000' });
      }
    },
    onLeave() {
      if (this.ownedViews) releaseOwnedNative(this.ownedViews);
    },
  });

  attachOnce(mapFn, 'Map', {
    onEnter(args) {
      this.known = !busy && configured && knownContexts.has(keyOf(args[0]));
      this.resource = args[1]; this.subresource = args[2].toUInt32(); this.mapType = args[3].toUInt32();
    },
    onLeave(retval) {
      if (!this.known || failedHr(retval) || this.mapType < 2 || this.mapType > 5 ||
          !this.resource || this.resource.isNull()) return;
      mappedWrites.set(keyOf(this.resource) + ':' + this.subresource, this.resource);
    },
  });

  attachOnce(unmapFn, 'Unmap', {
    onEnter(args) {
      this.known = !busy && configured && knownContexts.has(keyOf(args[0]));
      this.key = keyOf(args[1]) + ':' + args[2].toUInt32();
      this.resource = this.known ? mappedWrites.get(this.key) : null;
    },
    onLeave() {
      if (!this.resource) return;
      mappedWrites.delete(this.key);
      if (!busy && configured) invalidate(this.resource);
    },
  });

  attachOnce(updateFn, 'UpdateSubresource', {
    onEnter(args) {
      this.resource = !busy && configured && knownContexts.has(keyOf(args[0])) ? args[1] : null;
    },
    onLeave() { if (this.resource && !busy && configured) invalidate(this.resource); },
  });

  for (const copy of [
    { address: copyRegionFn, name: 'CopySubresourceRegion' },
    { address: copyResourceFn, name: 'CopyResource' },
  ]) {
    attachOnce(copy.address, copy.name, {
      onEnter(args) {
        this.destination = !busy && configured && knownContexts.has(keyOf(args[0])) ? args[1] : null;
      },
      onLeave() { if (this.destination && !busy && configured) invalidate(this.destination); },
    });
  }
}

function attachOnce(address, label, callbacks) {
  const key = keyOf(address);
  if (hooks.has(key)) return;
  hooks.set(key, Interceptor.attach(address, callbacks));
  log('hook-installed', { name: label });
}

function hookD3D11Factories(module) {
  if (!pinD3D11(module)) return false;
  let found = 0;
  for (const spec of [
    { name: 'D3D11CreateDevice', deviceIndex: 7, contextIndex: 9 },
    { name: 'D3D11CreateDeviceAndSwapChain', deviceIndex: 9, contextIndex: 11 },
  ]) {
    const address = module.findExportByName(spec.name);
    if (!address) continue;
    found++;
    attachOnce(address, spec.name, {
      onEnter(args) { this.deviceOut = args[spec.deviceIndex]; this.contextOut = args[spec.contextIndex]; },
      onLeave(retval) {
        if (failedHr(retval)) return;
        try {
          if (this.contextOut && !this.contextOut.isNull()) {
            const context = this.contextOut.readPointer();
            if (!context.isNull()) hookContext(context);
          }
        } catch (error) { failClosed('device-context-capture-failed', error); }
      },
    });
  }
  return found === 2;
}

function pinD3D11(module) {
  if (d3d11Pin) return d3d11Pin.base.equals(module.base);
  try {
    const kernel = Process.getModuleByName('kernel32.dll');
    const load = new NativeFunction(kernel.getExportByName('LoadLibraryW'), 'pointer', ['pointer'], 'stdcall');
    const handle = load(Memory.allocUtf16String(module.path));
    if (handle.isNull()) return false;
    if (!handle.equals(module.base)) {
      new NativeFunction(kernel.getExportByName('FreeLibrary'), 'int', ['pointer'], 'stdcall')(handle);
      return false;
    }
    d3d11Pin = { handle, base: module.base };
    return true;
  } catch (error) { log('d3d11-pin-failed', { error: String(error) }); return false; }
}

function detachHooks() {
  for (const hook of hooks.values()) { try { hook.detach(); } catch (_) { } }
  hooks.clear(); knownContexts.clear(); mappedWrites.clear();
}

function unpinD3D11() {
  if (!d3d11Pin) return;
  const pin = d3d11Pin; d3d11Pin = null;
  const kernel = Process.findModuleByName('kernel32.dll');
  if (kernel) new NativeFunction(kernel.getExportByName('FreeLibrary'), 'int', ['pointer'], 'stdcall')(pin.handle);
}

function unloadCache() {
  if (!cacheHandle) return;
  const handle = cacheHandle; cacheHandle = null; cacheModule = null; native = null;
  const kernel = Process.findModuleByName('kernel32.dll');
  if (kernel) new NativeFunction(kernel.getExportByName('FreeLibrary'), 'int', ['pointer'], 'stdcall')(handle);
}

function dispose(reason) {
  if (observer) { try { observer.detach(); } catch (_) { } observer = null; }
  configured = false;
  detachHooks();
  if (native) {
    try {
      const hr = hrValue(native.clear());
      if (hr !== 0) {
        permanentlyDisabled = true;
        log('cleanup-retained', { reason, hresult: '0x' + (hr >>> 0).toString(16),
          cacheAndD3D11PinsRetained: true });
        return;
      }
    } catch (error) {
      permanentlyDisabled = true;
      log('cleanup-retained', { reason, error: String(error), cacheAndD3D11PinsRetained: true });
      return;
    }
  }
  unloadCache();
  unpinD3D11();
  log('disposed', { reason });
}

function failClosed(reason, error) {
  permanentlyDisabled = true;
  log('fastfail', { reason, error: error ? String(error) : undefined, nativeCleanupSkipped: true });
  if (observer) { try { observer.detach(); } catch (_) { } observer = null; }
  configured = false;
  detachHooks();
  // Do not call into COM or unload either DLL after an unexpected lifecycle fault.
}

function installD3D11(module, failClosedOnError) {
  if (!configured || permanentlyDisabled) return;
  if (!hookD3D11Factories(module)) {
    if (failClosedOnError) failClosed('d3d11-factory-hooks-incomplete');
    else throw new Error('D3D11 factory hooks could not be installed');
  }
}

rpc.exports = {
  configure(config) {
    if (configured || permanentlyDisabled) throw new Error('bridge is configured or permanently disabled');
    if (!config || config.externalHostHashVerified !== true) {
      throw new Error('external host must verify executable and manifest bytes before configure');
    }
    if (config.beforeDeviceCreation !== true) throw new Error('configure must run before device creation');
    if (Process.arch !== 'ia32' || Process.pointerSize !== 4) throw new Error('only the x86 process is supported');
    if (!isAbsoluteWindowsPath(config.dllPath)) throw new Error('dllPath must be an absolute Windows path');
    const pages = validatePages(config.pages);
    const kernel = Process.getModuleByName('kernel32.dll');
    const load = new NativeFunction(kernel.getExportByName('LoadLibraryW'), 'pointer', ['pointer'], 'stdcall');
    const handle = load(Memory.allocUtf16String(config.dllPath));
    if (handle.isNull()) throw new Error('LoadLibraryW failed for texture cache');
    cacheHandle = handle;
    try {
      cacheModule = Process.findModuleByAddress(handle);
      if (!cacheModule) throw new Error('texture cache module could not be resolved');
      native = {
        register: nativeFunction(cacheModule, CACHE_EXPORTS.register, 'int', ['pointer', 'pointer', 'pointer', 'pointer', 'uint']),
        resolve: nativeFunction(cacheModule, CACHE_EXPORTS.resolve, 'int', ['pointer', 'pointer', 'pointer']),
        invalidate: nativeFunction(cacheModule, CACHE_EXPORTS.invalidate, 'int', ['pointer']),
        clear: nativeFunction(cacheModule, CACHE_EXPORTS.clear, 'int', []),
      };
      for (const page of pages) {
        const hr = native.register(Memory.allocUtf16String(page.sourceRawPath),
          Memory.allocUtf16String(page.sourceSha256), Memory.allocUtf16String(page.hdRawPath),
          Memory.allocUtf16String(page.hdSha256), PAGE_SIDE);
        if (hr !== 0) throw new Error('RegisterTexturePage returned non-S_OK: 0x' + (hr >>> 0).toString(16));
      }
      const d3d11 = Process.findModuleByName('d3d11.dll');
      configured = true;
      if (d3d11) installD3D11(d3d11, false);
      observer = Process.attachModuleObserver({
        onAdded(module) { if (module.name.toLowerCase() === 'd3d11.dll') installD3D11(module, true); },
        onRemoved(module) {
          const name = module.name.toLowerCase();
          if (name === 'd3d11.dll' || name === cacheModule.name.toLowerCase()) {
            failClosed('unexpected-module-unload:' + name);
          }
        },
      });
      if (permanentlyDisabled) throw new Error('D3D11 factory hooks could not be installed');
      log('configured', { pages: pages.length, cacheModule: cacheModule.name,
        target: { width: PAGE_SIDE, height: PAGE_SIDE, format: 'R16_UINT', formatValue: DXGI_FORMAT_R16_UINT } });
      return { configured: true, pages: pages.length };
    } catch (error) {
      if (!permanentlyDisabled) dispose('configure-failed');
      throw error;
    }
  },
  dispose() {
    if (permanentlyDisabled) return { disposed: false, permanentlyDisabled: true };
    dispose('rpc-dispose');
    return { disposed: true };
  },
};
