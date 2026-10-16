'use strict';

// Frida 17 candidate bridge for the Unicode overlay DLL. This file is intentionally
// passive until rpc.exports.configure() succeeds. It is not an installer component.

const GAME_RVA = Object.freeze({
  fontFlush: 0x9e580,
  streamState: 0x858028,
  streamId: 0x85802c,
  streamChannel: 0x857fdc,
  isPlaying: 0x7c6f0,
});
const FONT_FLUSH_BYTES = [0x51, 0xa1, 0xa8, 0x40, 0xc6, 0x00];
const TEXTURE2D_IID = '6f15aaf2-d208-4e89-9ab4-489535d34f9c';
const TARGET_FORMATS = new Set([27, 28]); // R8G8B8A8_TYPELESS / UNORM
const TARGET_WIDTH = 3840;
const TARGET_HEIGHT = 2160;
const MAX_CAPTION_ID = 478;

let configured = false;
let successfulDraws = 0;
const rejectedTargetKinds = new Set();
let busy = false;
let tearingDown = false;
let permanentlyDisabled = false;
let mainBase = null;
let overlayModule = null;
let overlayLibrary = null;
let d3d11Pin = null;
let overlayMayOwnDeviceRefs = false;
let getTickCount64 = null;
let initializeTextOverlay = null;
let setCaptionUtf8 = null;
let renderOverlay = null;
let isPlaying = null;
let flushHook = null;
let activeTarget = null;
let captions = new Map();
let hookByAddress = new Map();
let devices = new Set();
let contextDevices = new Map();
let watchedModuleNames = new Set();
let playback = { id: null, elapsedMs: 0, lastTick: null, page: null, failedPage: null, endedId: null };

function log(event, fields) {
  send({ event: 'unicode-' + event, ...(fields || {}) });
}

function pointerKey(value) {
  return value.toString().toLowerCase();
}

function failedHr(value) {
  return typeof value === 'number' ? value < 0 : value.toInt32() < 0;
}

function hrString(value) {
  const number = typeof value === 'number' ? value : value.toInt32();
  return '0x' + (number >>> 0).toString(16).padStart(8, '0');
}

function validateText(value, label) {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(label + ' must be a non-empty string');
  }
  if (value.trim().length === 0) throw new Error(label + ' must contain visible text');
  if (value.normalize('NFC') !== value) {
    throw new Error(label + ' must already be NFC-normalized');
  }
  // Reject C0/C1 controls, format/private/unassigned characters and lone surrogates.
  if (/[\u0000-\u001f\u007f-\u009f\uD800-\uDFFF]/u.test(value) || /\p{C}/u.test(value)) {
    throw new Error(label + ' contains a control or unsupported Unicode character');
  }
  if (value.length > 4000 || utf8Length(value) > 16000) {
    throw new Error(label + ' exceeds the native overlay text limit');
  }
  return value;
}

function normalizedSpaces(value) {
  return value.replace(/\s+/gu, ' ').trim();
}

function utf8Length(value) {
  let length = 0;
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    length += codePoint <= 0x7f ? 1 : codePoint <= 0x7ff ? 2 : codePoint <= 0xffff ? 3 : 4;
  }
  return length;
}

function validateRows(rows) {
  if (!Array.isArray(rows) || rows.length === 0 || rows.length > MAX_CAPTION_ID + 1) {
    throw new Error('captionRows must be a non-empty array with at most 479 rows');
  }
  const result = new Map();
  for (const row of rows) {
    if (!row || !Number.isInteger(row.id) || row.id < 0 || row.id > MAX_CAPTION_ID) {
      throw new Error('caption id must be an integer from 0 through 478');
    }
    if (result.has(row.id)) throw new Error('duplicate caption id: ' + row.id);
    if (!Number.isInteger(row.duration_ms) || row.duration_ms <= 0 || row.duration_ms > 60000) {
      throw new Error('duration_ms must be an integer from 1 through 60000 for id ' + row.id);
    }
    const text = validateText(row.text, 'caption text for id ' + row.id);
    let pages;
    if (row.pages === undefined) {
      pages = [{ text, start_ms: 0, end_ms: row.duration_ms }];
    } else {
      if (!Array.isArray(row.pages) || row.pages.length === 0) {
        throw new Error('pages must be a non-empty array for id ' + row.id);
      }
      let previousEnd = 0;
      pages = row.pages.map((page, index) => {
        if (!page || !Number.isInteger(page.start_ms) || !Number.isInteger(page.end_ms) ||
            page.start_ms !== previousEnd || page.end_ms <= page.start_ms ||
            page.end_ms > row.duration_ms) {
          throw new Error('pages must be strictly contiguous with positive durations for id ' + row.id +
            ' page ' + index);
        }
        const pageText = validateText(page.text, 'page text for id ' + row.id + ' page ' + index);
        previousEnd = page.end_ms;
        return { text: pageText, start_ms: page.start_ms, end_ms: page.end_ms };
      });
      if (previousEnd !== row.duration_ms) {
        throw new Error('pages must cover the full duration for id ' + row.id);
      }
      const joined = normalizedSpaces(pages.map(page => page.text).join(' '));
      if (joined !== normalizedSpaces(text)) {
        throw new Error('page text does not match caption text after space normalization for id ' + row.id);
      }
    }
    result.set(row.id, { id: row.id, duration_ms: row.duration_ms, text, pages });
  }
  return result;
}

function readGuid(text) {
  const parts = text.replace(/[{}-]/g, '').match(/.{2}/g);
  const bytes = parts.map(part => parseInt(part, 16));
  const guid = Memory.alloc(16);
  guid.writeU32((bytes[0] * 0x1000000) + (bytes[1] << 16) + (bytes[2] << 8) + bytes[3]);
  guid.add(4).writeU16((bytes[4] << 8) | bytes[5]);
  guid.add(6).writeU16((bytes[6] << 8) | bytes[7]);
  for (let i = 0; i < 8; i++) guid.add(8 + i).writeU8(bytes[8 + i]);
  return guid;
}

const texture2dIid = readGuid(TEXTURE2D_IID);

function vtableMethod(object, slot, returnType, argTypes) {
  const address = object.readPointer().add(slot * Process.pointerSize).readPointer();
  return new NativeFunction(address, returnType, argTypes, 'stdcall');
}

function addRef(object) {
  if (object && !object.isNull()) vtableMethod(object, 1, 'uint', ['pointer'])(object);
}

function release(object) {
  if (!object || object.isNull()) return;
  try { vtableMethod(object, 2, 'uint', ['pointer'])(object); } catch (_) { }
}

function releaseTracked(canCallCom) {
  if (!activeTarget) return;
  const old = activeTarget;
  activeTarget = null;
  if (canCallCom) {
    release(old.texture);
    release(old.rtv);
    release(old.context);
  }
}

function clearPlayback(reason) {
  playback = { id: null, elapsedMs: 0, lastTick: null, page: null, failedPage: null, endedId: null };
  applyCaption('', null, reason);
}

function clearAfterDuration(id) {
  playback = { id: null, elapsedMs: 0, lastTick: null, page: null, failedPage: null, endedId: id };
  applyCaption('', null, 'duration-ended');
}

function applyCaption(text, row, reason) {
  const pointer = Memory.allocUtf8String(text);
  const result = setCaptionUtf8(pointer);
  if (failedHr(result)) {
    const clearResult = setCaptionUtf8(Memory.allocUtf8String(''));
    log('caption-rejected', {
      id: row ? row.id : null,
      reason,
      hresult: hrString(result),
      clearHresult: hrString(clearResult),
    });
    return false;
  }
  return true;
}

function setPage(row, pageIndex) {
  const key = row.id + ':' + pageIndex;
  if (playback.page === key || playback.failedPage === key) return;
  playback.page = key;
  const page = row.pages[pageIndex];
  if (!applyCaption(page.text, row, 'page-' + pageIndex)) playback.failedPage = key;
}

function pageIndexAt(row, elapsedMs) {
  for (let index = 0; index < row.pages.length; index++) {
    const page = row.pages[index];
    if (elapsedMs >= page.start_ms && elapsedMs < page.end_ms) return index;
  }
  return -1;
}

function clockStep(elapsedMs, lastTick, now, playing) {
  if (!playing) return { elapsedMs, lastTick: now };
  return {
    elapsedMs: elapsedMs + (lastTick === null ? 0 : Math.max(0, now - lastTick)),
    lastTick: now,
  };
}

function readGameState() {
  const state = mainBase.add(GAME_RVA.streamState).readS32();
  const id = mainBase.add(GAME_RVA.streamId).readS32();
  const channel = mainBase.add(GAME_RVA.streamChannel).readS32();
  return { state, id, channel };
}

function updateCaption() {
  if (busy || !configured) return;
  let current;
  try { current = readGameState(); }
  catch (error) { log('stream-state-read-failed', { error: String(error) }); clearPlayback('state-read-failed'); return; }

  const active = current.state >= 2 && current.state <= 4 && current.id >= 0 && current.id <= MAX_CAPTION_ID;
  if (!active) {
    if (playback.id !== null || playback.page !== null || playback.endedId !== null) clearPlayback('inactive');
    return;
  }
  if (playback.endedId === current.id) return;
  const row = captions.get(current.id);
  if (!row) {
    if (playback.id !== current.id || playback.page !== null) clearPlayback('no-caption');
    playback.id = current.id;
    return;
  }

  let playing = false;
  try { playing = isPlaying(current.channel) !== 0; }
  catch (error) { log('is-playing-failed', { id: current.id, error: String(error) }); }
  const tick = getTickCount64();
  const now = typeof tick === 'number' ? tick : tick.toNumber();
  if (!playing) {
    // A pause holds both the visible page and accumulated elapsed time.
    if (playback.id !== null && playback.id !== current.id) {
      clearPlayback('voice-changed-while-paused');
      playback.id = current.id;
    }
    const clock = clockStep(playback.elapsedMs, playback.lastTick, now, false);
    playback.elapsedMs = clock.elapsedMs;
    playback.lastTick = clock.lastTick;
    return;
  }

  if (playback.id !== current.id) {
    playback = { id: current.id, elapsedMs: 0, lastTick: null, page: null, failedPage: null, endedId: null };
    log('caption-start', { id: current.id, state: current.state });
  }
  const clock = clockStep(playback.elapsedMs, playback.lastTick, now, true);
  playback.elapsedMs = clock.elapsedMs;
  playback.lastTick = clock.lastTick;

  if (playback.elapsedMs >= row.duration_ms) {
    clearAfterDuration(current.id);
    return;
  }
  const pageIndex = pageIndexAt(row, playback.elapsedMs);
  if (pageIndex < 0) {
    clearPlayback('page-gap');
    return;
  }
  setPage(row, pageIndex);
}

function releaseComResource(resource) {
  if (!resource || resource.isNull()) return;
  release(resource);
}

function queryTextureFromRtv(rtv) {
  const resourceOut = Memory.alloc(Process.pointerSize);
  resourceOut.writePointer(ptr(0));
  vtableMethod(rtv, 7, 'void', ['pointer', 'pointer'])(rtv, resourceOut);
  const resource = resourceOut.readPointer();
  if (resource.isNull()) return null;

  const textureOut = Memory.alloc(Process.pointerSize);
  textureOut.writePointer(ptr(0));
  const hr = vtableMethod(resource, 0, 'int', ['pointer', 'pointer', 'pointer'])(resource, texture2dIid, textureOut);
  if (failedHr(hr)) {
    releaseComResource(resource);
    return null;
  }
  const texture = textureOut.readPointer();
  releaseComResource(resource);
  return texture.isNull() ? null : texture;
}

function getDevice(object) {
  const output = Memory.alloc(Process.pointerSize);
  output.writePointer(ptr(0));
  vtableMethod(object, 3, 'void', ['pointer', 'pointer'])(object, output);
  return output.readPointer();
}

function describeTexture(texture) {
  const desc = Memory.alloc(44);
  desc.writeByteArray(new Uint8Array(44));
  vtableMethod(texture, 10, 'void', ['pointer', 'pointer'])(texture, desc);
  return {
    width: desc.readU32(),
    height: desc.add(4).readU32(),
    format: desc.add(16).readU32(),
    sampleCount: desc.add(20).readU32(),
  };
}

function captureCurrentTarget(context, count, array) {
  const deviceKey = contextDevices.get(pointerKey(context));
  if (!deviceKey || !devices.has(deviceKey)) return;
  if (count === 0 || array.isNull()) {
    releaseTracked(true);
    return;
  }
  const rtv = array.readPointer();
  if (rtv.isNull()) {
    releaseTracked(true);
    return;
  }

  let texture = null;
  let contextDevice = ptr(0);
  let textureDevice = ptr(0);
  let retainedContext = false;
  let retainedRtv = false;
  try {
    texture = queryTextureFromRtv(rtv);
    if (!texture) { releaseTracked(true); return; }
    const desc = describeTexture(texture);
    contextDevice = getDevice(context);
    textureDevice = getDevice(texture);
    const eligible = desc.width === TARGET_WIDTH && desc.height === TARGET_HEIGHT &&
      TARGET_FORMATS.has(desc.format) && desc.sampleCount === 1 &&
      pointerKey(contextDevice) === deviceKey && pointerKey(textureDevice) === deviceKey;
    if (!eligible) {
      const kind = JSON.stringify(desc);
      if (!rejectedTargetKinds.has(kind) && rejectedTargetKinds.size < 32) {
        rejectedTargetKinds.add(kind);
        log('render-target-rejected', desc);
      }
      release(texture);
      texture = null;
      release(contextDevice);
      release(textureDevice);
      releaseTracked(true);
      return;
    }

    addRef(context);
    retainedContext = true;
    addRef(rtv);
    retainedRtv = true;
    release(contextDevice);
    contextDevice = ptr(0);
    release(textureDevice);
    textureDevice = ptr(0);
    const previous = activeTarget;
    activeTarget = { context, rtv, texture, deviceKey, desc };
    texture = null; // Transfer QueryInterface's owned reference into activeTarget.
    retainedContext = false;
    retainedRtv = false;
    if (previous) {
      release(previous.texture);
      release(previous.rtv);
      release(previous.context);
    }
  } catch (error) {
    if (texture) release(texture);
    if (retainedRtv) release(rtv);
    if (retainedContext) release(context);
    if (!contextDevice.isNull()) release(contextDevice);
    if (!textureDevice.isNull()) release(textureDevice);
    releaseTracked(true);
    log('render-target-capture-failed', { error: String(error) });
  }
}

function hookAddress(address, callbacks, label) {
  const key = pointerKey(address);
  if (hookByAddress.has(key)) return hookByAddress.get(key);
  const handle = Interceptor.attach(address, callbacks);
  hookByAddress.set(key, handle);
  log('hook-attached', { name: label, address: address.toString() });
  return handle;
}

function hookContext(context, device) {
  if (!context || context.isNull() || !device || device.isNull()) return;
  contextDevices.set(pointerKey(context), pointerKey(device));
  const method = context.readPointer().add(33 * Process.pointerSize).readPointer();
  hookAddress(method, {
    onEnter(args) {
      if (busy || !configured) return;
      this.skip = !devices.has(contextDevices.get(pointerKey(args[0])));
      if (this.skip) return;
      busy = true;
      try { captureCurrentTarget(args[0], args[1].toUInt32(), args[2]); }
      finally { busy = false; }
    },
  }, 'ID3D11DeviceContext::OMSetRenderTargets');
}

function hookDevice(device) {
  if (!device || device.isNull()) return;
  const key = pointerKey(device);
  if (devices.has(key)) return;
  devices.add(key);
  const getImmediateContext = device.readPointer().add(40 * Process.pointerSize).readPointer();
  hookAddress(getImmediateContext, {
    onEnter(args) { this.output = args[1]; this.device = args[0]; },
    onLeave() {
      try {
        const context = this.output.readPointer();
        if (!context.isNull()) hookContext(context, this.device);
      } catch (error) { log('get-immediate-context-failed', { error: String(error) }); }
    },
  }, 'ID3D11Device::GetImmediateContext');
}

function hookD3D11Factories(module) {
  if (!pinD3D11(module)) return false;
  let found = 0;
  for (const item of [
    { name: 'D3D11CreateDevice', device: 7, context: 9 },
    { name: 'D3D11CreateDeviceAndSwapChain', device: 9, context: 11 },
  ]) {
    let address;
    try { address = module.findExportByName(item.name); } catch (_) { address = null; }
    if (!address) continue;
    found++;
    hookAddress(address, {
      onEnter(args) {
        this.deviceOutput = args[item.device];
        this.contextOutput = args[item.context];
      },
      onLeave(retval) {
        if (failedHr(retval)) return;
        try {
          const device = this.deviceOutput.readPointer();
          const context = this.contextOutput.readPointer();
          if (device.isNull()) return;
          hookDevice(device);
          if (!context.isNull()) hookContext(context, device);
        } catch (error) { log('device-factory-capture-failed', { error: String(error) }); }
      },
    }, item.name);
  }
  return found === 2;
}

function pinD3D11(module) {
  if (d3d11Pin) return d3d11Pin.base.equals(module.base);
  try {
    const kernel32 = Process.getModuleByName('kernel32.dll');
    const loadLibrary = new NativeFunction(kernel32.getExportByName('LoadLibraryW'), 'pointer', ['pointer'], 'stdcall');
    const handle = loadLibrary(Memory.allocUtf16String(module.path));
    if (handle.isNull()) {
      log('fastfail', { reason: 'could-not-pin-d3d11', path: module.path });
      return false;
    }
    if (!handle.equals(module.base)) {
      const freeLibrary = new NativeFunction(kernel32.getExportByName('FreeLibrary'), 'int', ['pointer'], 'stdcall');
      freeLibrary(handle);
      log('fastfail', { reason: 'pinned-d3d11-base-mismatch', path: module.path });
      return false;
    }
    d3d11Pin = { handle, base: module.base, path: module.path };
    log('d3d11-pinned', { base: module.base.toString(), path: module.path });
    return true;
  } catch (error) {
    log('fastfail', { reason: 'd3d11-pin-exception', error: String(error) });
    return false;
  }
}

function detachOwnHooks() {
  for (const handle of hookByAddress.values()) {
    try { handle.detach(); } catch (_) { }
  }
  hookByAddress.clear();
  flushHook = null;
}

function teardown(reason, allowNativeCleanup) {
  if (tearingDown) return;
  tearingDown = true;
  const oldOverlayLibrary = overlayLibrary;
  const oldD3d11Pin = d3d11Pin;
  const d3dStillMapped = !!oldD3d11Pin &&
    Process.findModuleByAddress(oldD3d11Pin.base) !== null;
  const safeNativeCleanup = allowNativeCleanup &&
    (!oldD3d11Pin || d3dStillMapped) &&
    (!activeTarget || d3dStillMapped) &&
    (!overlayMayOwnDeviceRefs || d3dStillMapped);
  configured = false;
  busy = false;
  detachOwnHooks();
  watchedModuleNames.clear();
  if (safeNativeCleanup) releaseTracked(d3dStillMapped);
  else activeTarget = null;
  devices.clear();
  contextDevices.clear();
  captions.clear();
  playback = { id: null, elapsedMs: 0, lastTick: null, page: null, failedPage: null, endedId: null };
  mainBase = null;
  isPlaying = null;
  initializeTextOverlay = null;
  setCaptionUtf8 = null;
  renderOverlay = null;
  getTickCount64 = null;
  overlayModule = null;
  overlayLibrary = null;
  d3d11Pin = null;
  overlayMayOwnDeviceRefs = false;
  if (safeNativeCleanup && oldOverlayLibrary) {
    try {
      const kernel32 = Process.findModuleByName('kernel32.dll');
      if (kernel32) {
        const freeLibrary = new NativeFunction(kernel32.getExportByName('FreeLibrary'), 'int', ['pointer'], 'stdcall');
        freeLibrary(oldOverlayLibrary);
      }
    } catch (error) { log('overlay-unload-failed', { error: String(error) }); }
  }
  if (safeNativeCleanup && oldD3d11Pin) {
    try {
      const kernel32 = Process.findModuleByName('kernel32.dll');
      if (kernel32) {
        const freeLibrary = new NativeFunction(kernel32.getExportByName('FreeLibrary'), 'int', ['pointer'], 'stdcall');
        freeLibrary(oldD3d11Pin.handle);
      }
    } catch (error) { log('d3d11-unpin-failed', { error: String(error) }); }
  }
  if (!safeNativeCleanup) {
    permanentlyDisabled = true;
    log('fastfail', { reason: reason + ':processgoingaway', nativeDestructorsSkipped: true });
  }
  tearingDown = false;
  log('detached', { reason });
}

const moduleObserver = Process.attachModuleObserver({
  onAdded(module) {
    if (!configured) return;
    if (module.name.toLowerCase() === 'd3d11.dll' && !hookD3D11Factories(module)) {
      log('fastfail', { reason: 'could-not-install-d3d11-factory-hooks' });
      teardown('could-not-install-d3d11-factory-hooks', true);
    }
  },
  onRemoved(module) {
    const name = module.name.toLowerCase();
    if (watchedModuleNames.has(name)) {
      if (tearingDown) return;
      // Never call COM destructors or FreeLibrary from an unload notification.
      permanentlyDisabled = true;
      teardown('module-unloaded:' + name, false);
    }
  },
});

rpc.exports = {
  configure(config) {
    if (configured) throw new Error('bridge is already configured');
    if (permanentlyDisabled) throw new Error('bridge was disabled after an unexpected module unload');
    if (overlayLibrary || hookByAddress.size > 0 || d3d11Pin) {
      teardown('configure-retry-cleanup', true);
    }
    if (Process.arch !== 'ia32' || Process.pointerSize !== 4) {
      throw new Error('this candidate supports only the x86 game process');
    }
    if (!config || typeof config !== 'object') throw new Error('config is required');
    if (config.hostHashVerified !== true) {
      throw new Error('external host hashguard must verify the supported executable before configure');
    }
    if (config.beforeDeviceCreation !== true) {
      throw new Error('host must configure before the game creates its D3D11 device');
    }
    if (config.expectedExeBase !== 0x400000 && config.expectedExeBase !== '0x400000') {
      throw new Error('expectedExeBase must be 0x400000');
    }
    if (typeof config.overlayPath !== 'string' || !/^(?:[A-Za-z]:\\|\\\\)/.test(config.overlayPath)) {
      throw new Error('overlayPath must be an absolute Windows path');
    }

    const preparedRows = validateRows(config.captionRows);
    const mainModule = Process.mainModule;
    if (mainModule.base.toUInt32() !== 0x400000) throw new Error('main executable is not based at 0x400000');
    const fontFlush = mainModule.base.add(GAME_RVA.fontFlush);
    const actual = Array.from(fontFlush.readByteArray(FONT_FLUSH_BYTES.length));
    if (actual.some((value, index) => value !== FONT_FLUSH_BYTES[index])) {
      throw new Error('FONTFlush signature mismatch; legacy runtime hook is refused');
    }

    const kernel32 = Process.getModuleByName('kernel32.dll');
    const loadLibrary = new NativeFunction(kernel32.getExportByName('LoadLibraryW'), 'pointer', ['pointer'], 'stdcall');
    const path = Memory.allocUtf16String(config.overlayPath);
    const library = loadLibrary(path);
    if (library.isNull()) throw new Error('LoadLibraryW failed for overlay DLL');
    overlayLibrary = library;
    const candidate = Process.findModuleByAddress(library);
    if (!candidate) throw new Error('overlay DLL module could not be resolved');
    overlayModule = candidate;
    const initializeAddress = candidate.findExportByName('InitializeTextOverlay');
    const setCaptionAddress = candidate.findExportByName('SetCaptionUtf8');
    const renderAddress = candidate.findExportByName('RenderOverlay');
    if (!initializeAddress || !setCaptionAddress || !renderAddress) {
      throw new Error('Unicode overlay exports are incomplete');
    }

    const initialize = new NativeFunction(initializeAddress, 'int', [], 'stdcall');
    const setCaption = new NativeFunction(setCaptionAddress, 'int', ['pointer'], 'stdcall');
    const render = new NativeFunction(renderAddress, 'int', ['pointer', 'pointer', 'pointer'], 'stdcall');
    const initResult = initialize();
    if (failedHr(initResult)) throw new Error('InitializeTextOverlay failed: ' + hrString(initResult));

    mainBase = mainModule.base;
    overlayLibrary = library;
    overlayModule = candidate;
    initializeTextOverlay = initialize;
    setCaptionUtf8 = setCaption;
    renderOverlay = render;
    captions = preparedRows;
    isPlaying = new NativeFunction(mainBase.add(GAME_RVA.isPlaying), 'int', ['int'], 'cdecl');
    getTickCount64 = new NativeFunction(kernel32.getExportByName('GetTickCount64'), 'uint64', [], 'stdcall');
    watchedModuleNames = new Set([mainModule.name.toLowerCase(), 'd3d11.dll']);
    configured = true;
    successfulDraws = 0;

    const handle = hookAddress(fontFlush, {
      onLeave() {
        if (!configured || busy) return;
        updateCaption();
        if (!activeTarget || playback.id === null || playback.page === null ||
            playback.failedPage === playback.page) return;
        busy = true;
        try {
          overlayMayOwnDeviceRefs = true;
          const hr = renderOverlay(activeTarget.deviceKey ? ptr(activeTarget.deviceKey) : ptr(0),
            activeTarget.context, activeTarget.texture);
          if (failedHr(hr)) log('render-failed', { hresult: hrString(hr) });
          else if (++successfulDraws === 1) log('render-succeeded', {
            hresult: hrString(hr), target: activeTarget.desc,
            scope: 'GPU draw only; visible composition and synchronization need review',
          });
        } catch (error) {
          log('render-exception', { error: String(error) });
        } finally { busy = false; }
      },
    }, 'FONTFlush (signature-guarded)');
    flushHook = handle;

    const d3d = Process.findModuleByName('d3d11.dll');
    if (d3d && !hookD3D11Factories(d3d)) {
      teardown('could-not-pin-d3d11', true);
      throw new Error('D3D11 module could not be pinned before device hooks');
    }
    log('configured', { base: mainBase.toString(), rows: captions.size, overlay: candidate.path });
    return { configured: true, rows: captions.size, exeBase: mainBase.toString() };
  },

  dispose() {
    if (configured || overlayLibrary || hookByAddress.size > 0 || d3d11Pin) {
      teardown('rpc-dispose', true);
    }
    return { disposed: true };
  },
};
