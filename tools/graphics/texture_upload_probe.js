'use strict';

// Frida script: observe D3D11 texture creation, uploads, SRV formats and pixel-shader bindings.
// This is an observer only. It never replaces texture data or changes descriptors.

const MAX_HASH_BYTES = 16 * 1024 * 1024;
const hookedDevices = new Set();
const hookedTextureVtables = new Set();
const hookedContextVtables = new Set();
const resourceDescs = new Map();
const shaderViewDescs = new Map();
const mappedResources = new Map();
let uploadCount = 0;
const hookedModules = new Set();
let sequence = 0;
let capturePageBytes = false;
let capturedPages = 0;

const formats = {
  53: 'DXGI_FORMAT_R16_TYPELESS',
  61: 'DXGI_FORMAT_R8_UNORM', 28: 'DXGI_FORMAT_R8G8B8A8_UNORM',
  87: 'DXGI_FORMAT_B8G8R8A8_UNORM', 56: 'DXGI_FORMAT_R16_UNORM',
  85: 'DXGI_FORMAT_B5G6R5_UNORM', 86: 'DXGI_FORMAT_B5G5R5A1_UNORM', 71: 'DXGI_FORMAT_BC1_UNORM',
  77: 'DXGI_FORMAT_BC3_UNORM', 10: 'DXGI_FORMAT_R16G16B16A16_FLOAT'
};
formats[54] = 'DXGI_FORMAT_R16_FLOAT';
formats[55] = 'DXGI_FORMAT_D16_UNORM';
formats[57] = 'DXGI_FORMAT_R16_UINT';
formats[58] = 'DXGI_FORMAT_R16_SNORM';
formats[59] = 'DXGI_FORMAT_R16_SINT';

function u32(p, off) { return p.add(off).readU32(); }
function crc32(bytes) {
  if (!bytes) return null;
  const a = new Uint8Array(bytes), table = crc32.table || (crc32.table = (() => {
    const t = []; for (let n = 0; n < 256; n++) { let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    } return t;
  })());
  let c = 0xffffffff; for (const b of a) c = table[(c ^ b) & 255] ^ (c >>> 8);
  return ('00000000' + ((c ^ 0xffffffff) >>> 0).toString(16)).slice(-8);
}
function safeBytes(p, n) {
  if (!p || p.isNull() || n <= 0 || n > MAX_HASH_BYTES) return null;
  try { return p.readByteArray(n); } catch (_) { return null; }
}
function pageIdentity(p, pitch, d) {
  // Compare stored 16-bit words, excluding GPU row padding. Never interpret alpha.
  if (!d || d.width !== 256 || d.height !== 256 ||
      ![53, 54, 55, 56, 57, 58, 59, 85, 86].includes(d.format) || pitch < 512 || pitch > MAX_HASH_BYTES / 256) return {};
  const raw = safeBytes(p, pitch * 256);
  if (!raw) return {};
  const src = new Uint8Array(raw), packed = new Uint8Array(131072);
  for (let y = 0; y < 256; y++) packed.set(src.subarray(y * pitch, y * pitch + 512), y * 512);
  if (capturePageBytes && capturedPages < 16) {
    send({ kind: 'TexturePageBytes', sequence: ++sequence, captureIndex: capturedPages++,
      descriptor: d, canonicalRowBytes: 512, canonicalCrc32: crc32(packed.buffer),
      note: 'Private diagnostic payload; use SHA-256 offline before claiming identity' }, packed.buffer);
  }
  return { canonicalRowBytes: 512, canonicalBytes: packed.byteLength, canonicalCrc32: crc32(packed.buffer),
    identityClaim: 'raw 16-bit bytes only; CRC is a lookup aid, not unique page proof' };
}
function emit(kind, data) { send({ kind, sequence: ++sequence, ...data }); }

function descriptor(p) {
  if (!p || p.isNull()) return null;
  // D3D11_TEXTURE2D_DESC: Width, Height, MipLevels, ArraySize, Format, SampleDesc...
  const format = u32(p, 16);
  return { width: u32(p, 0), height: u32(p, 4), mipLevels: u32(p, 8), arraySize: u32(p, 12), format, formatName: formats[format] || `DXGI_FORMAT_${format}`, sampleCount: u32(p, 20), sampleQuality: u32(p, 24), usage: u32(p, 28), bindFlags: u32(p, 32), cpuAccessFlags: u32(p, 36), miscFlags: u32(p, 40) };
}

function shaderViewDescriptor(p) {
  if (!p || p.isNull()) return null;
  const format = u32(p, 0), dimension = u32(p, 4);
  const result = { format, formatName: formats[format] || `DXGI_FORMAT_${format}`, viewDimension: dimension };
  // D3D11_SRV_DIMENSION_TEXTURE2D is 4; the union starts at byte 8.
  if (dimension === 4) {
    result.mostDetailedMip = u32(p, 8);
    result.mipLevels = u32(p, 12);
  }
  return result;
}

function queryShaderViewDescriptor(view) {
  if (!view || view.isNull()) throw Error('SRV pointer is null');
  const abi = Process.arch === 'ia32' ? 'stdcall' : Process.arch === 'x64' ? 'win64' : null;
  if (!abi) throw Error(`Unsupported architecture for COM ABI: ${Process.arch}`);
  // ID3D11ShaderResourceView::GetDesc follows ID3D11View::GetResource.
  const getDesc = view.readPointer().add(Process.pointerSize * 8).readPointer();
  const output = Memory.alloc(32);
  new NativeFunction(getDesc, 'void', ['pointer', 'pointer'], abi)(view, output);
  const result = shaderViewDescriptor(output);
  if (!result) throw Error('GetDesc did not produce a shader resource descriptor');
  return result;
}

function hookDevice(device) {
  if (!device || device.isNull() || hookedDevices.has(device.toString())) return;
  hookedDevices.add(device.toString());
  const vtable = device.readPointer(), createTexture2D = vtable.add(Process.pointerSize * 5).readPointer();
  if (hookedTextureVtables.has(createTexture2D.toString())) return;
  hookedTextureVtables.add(createTexture2D.toString());
  Interceptor.attach(createTexture2D, {
    onEnter(args) {
      this.desc = descriptor(args[1]); this.init = args[2]; this.outTexture = args[3]; this.device = args[0];
      if (!this.desc || this.desc.width < 128 || this.desc.height < 128 || this.desc.width > 4096 || this.desc.height > 4096) { this.desc = null; return; }
      const first = this.init.isNull() ? null : this.init.readPointer();
      const pitch = this.init.isNull() ? null : u32(this.init, Process.pointerSize);
      const blockCompressed = (this.desc.format >= 71 && this.desc.format <= 84) || (this.desc.format >= 94 && this.desc.format <= 99);
      const rows = blockCompressed ? Math.max(1, Math.ceil(this.desc.height / 4)) : this.desc.height;
      const bytes = first && !first.isNull() ? safeBytes(first, Math.min(MAX_HASH_BYTES, Math.max(0, pitch * rows))) : null;
      emit('CreateTexture2D', { descriptor: this.desc, initData: !this.init.isNull(), rowPitch: pitch, firstRelevantTextureRawCrc32: crc32(bytes), firstRelevantTextureRawBytes: bytes ? Math.min(bytes.byteLength, MAX_HASH_BYTES) : 0 });
    },
    onLeave(retval) { if (this.desc && retval.toInt32() === 0) {
      const texture = this.outTexture && !this.outTexture.isNull() ? this.outTexture.readPointer() : null;
      if (texture && !texture.isNull()) resourceDescs.set(texture.toString(), this.desc);
      emit('CreateTexture2DResult', { descriptor: this.desc, hresult: retval.toInt32(), texture: texture && !texture.isNull() ? texture : null });
    }}
  });
  // ID3D11Device::CreateShaderResourceView is vtable slot 7.
  const createShaderResourceView = vtable.add(Process.pointerSize * 7).readPointer();
  Interceptor.attach(createShaderResourceView, {
    onEnter(args) {
      this.resource = args[1]; this.inputDescWasNull = args[2].isNull(); this.outView = args[3];
      this.resourceDesc = this.resource && !this.resource.isNull() ? resourceDescs.get(this.resource.toString()) : null;
      if (!this.resourceDesc || this.resourceDesc.width !== 256 || this.resourceDesc.height !== 256) this.resourceDesc = null;
    },
    onLeave(retval) {
      if (!this.resourceDesc || retval.toInt32() !== 0) return;
      const view = this.outView && !this.outView.isNull() ? this.outView.readPointer() : null;
      if (!view || view.isNull()) return;
      let desc;
      try { desc = queryShaderViewDescriptor(view); }
      catch (error) {
        emit('ShaderResourceViewGetDescFailed', { view: view.toString(), reason: String(error) });
        return;
      }
      const entry = { ...desc, resource: this.resource.toString(), resourceDescriptor: this.resourceDesc };
      shaderViewDescs.set(view.toString(), entry);
      emit('CreateShaderResourceView', { view: view.toString(), ...entry, pDescWasNull: this.inputDescWasNull, descriptorSource: 'ID3D11ShaderResourceView::GetDesc', hresult: retval.toInt32() });
    }
  });
  const getImmediateContext = vtable.add(Process.pointerSize * 40).readPointer();
  Interceptor.attach(getImmediateContext, { onEnter(args) { this.ppContext = args[1]; }, onLeave(hr) {
    if (this.ppContext && !this.ppContext.isNull()) hookContext(this.ppContext.readPointer());
  }});
  emit('deviceHooked', { device: device.toString() });
}

function hookContext(context) {
  if (!context || context.isNull()) return;
  const vt = context.readPointer(), key = vt.toString();
  if (hookedContextVtables.has(key)) return; hookedContextVtables.add(key);
  const mapFn = vt.add(Process.pointerSize * 14).readPointer();
  Interceptor.attach(mapFn, { onEnter(args) { this.resource = args[1]; this.subresource = args[2].toUInt32(); this.mapType = args[3].toUInt32(); this.mapped = args[5]; }, onLeave(hr) {
    if (hr.toInt32() === 0 && this.resource && !this.resource.isNull() && this.mapped && !this.mapped.isNull()) {
      const data = this.mapped.readPointer(), pitch = u32(this.mapped, Process.pointerSize);
      const desc = resourceDescs.get(this.resource.toString());
      mappedResources.set(this.resource.toString() + ':' + this.subresource, { data, pitch, mapType: this.mapType, desc });
      emit('Map', { resource: this.resource.toString(), mapType: this.mapType, rowPitch: pitch, descriptor: desc || null });
    }
  }});
  // ID3D11DeviceContext::PSSetShaderResources is vtable slot 8.
  const psSetShaderResources = vt.add(Process.pointerSize * 8).readPointer();
  Interceptor.attach(psSetShaderResources, { onEnter(args) {
    const start = args[1].toUInt32(), count = Math.min(args[2].toUInt32(), 128), views = args[3];
    if (!views || views.isNull() || count === 0) return;
    for (let i = 0; i < count; i++) {
      const view = views.add(i * Process.pointerSize).readPointer();
      if (!view || view.isNull()) continue;
      const desc = shaderViewDescs.get(view.toString());
      if (desc) emit('PSSetShaderResources', { slot: start + i, view: view.toString(), stage: 'pixel', ...desc });
    }
  }});
  const unmapFn = vt.add(Process.pointerSize * 15).readPointer();
  Interceptor.attach(unmapFn, { onEnter(args) {
    const subresource = args[2].toUInt32(), key = args[1].toString() + ':' + subresource, m = mappedResources.get(key), d = m && m.desc;
    if (m && d && subresource === 0 && m.mapType >= 2 && m.mapType <= 5 && d.width === 256 && d.height === 256 && uploadCount < 128) {
      const bytes = safeBytes(m.data, Math.min(MAX_HASH_BYTES, m.pitch * d.height));
      emit('UnmapUpload', { resource: key, mapType: m.mapType, rowPitch: m.pitch, bytes: bytes ? bytes.byteLength : 0, crc32: crc32(bytes), ...pageIdentity(m.data, m.pitch, d), descriptor: d }); uploadCount++;
    }
    mappedResources.delete(key);
  }});
  const updateFn = vt.add(Process.pointerSize * 48).readPointer();
  Interceptor.attach(updateFn, { onEnter(args) {
    const key = args[1].toString(), d = resourceDescs.get(key);
    if (!d || d.width !== 256 || d.height !== 256 || uploadCount >= 128) return;
    // Partial boxes and mip levels do not contain an entire page; do not read
    // a full-height buffer from a partial upload.
    if (args[2].toUInt32() !== 0 || !args[3].isNull()) return;
    const src = args[4], pitch = args[5].toUInt32(), bytes = src && !src.isNull() ? safeBytes(src, Math.min(MAX_HASH_BYTES, pitch * d.height)) : null;
    emit('UpdateSubresource', { resource: key, rowPitch: pitch, bytes: bytes ? bytes.byteLength : 0, crc32: crc32(bytes), ...pageIdentity(src, pitch, d), descriptor: d }); uploadCount++;
  }});
  emit('contextHooked', { context: context.toString() });
}

function hookModule(m) {
  if (!m || hookedModules.has(m.name)) return;
  hookedModules.add(m.name); emit('moduleObserved', { module: m.name, base: m.base.toString(), size: m.size });
  const create = m.findExportByName('D3D11CreateDevice');
  if (create) Interceptor.attach(create, { onEnter(args) { this.ppDevice = args[7]; this.ppContext = args[9]; }, onLeave(hr) {
    if (hr.toInt32() === 0 && this.ppDevice && !this.ppDevice.isNull()) hookDevice(this.ppDevice.readPointer());
    if (hr.toInt32() === 0 && this.ppContext && !this.ppContext.isNull()) hookContext(this.ppContext.readPointer());
    emit('deviceFactoryReturned', { module: m.name, hresult: hr.toInt32() });
  }});
  const createSwap = m.findExportByName('D3D11CreateDeviceAndSwapChain');
  if (createSwap) Interceptor.attach(createSwap, { onEnter(args) { this.ppDevice = args[9]; this.ppContext = args[11]; }, onLeave(hr) {
    if (hr.toInt32() === 0 && this.ppDevice && !this.ppDevice.isNull()) hookDevice(this.ppDevice.readPointer());
    if (hr.toInt32() === 0 && this.ppContext && !this.ppContext.isNull()) hookContext(this.ppContext.readPointer());
    emit('deviceFactoryReturned', { module: m.name, hresult: hr.toInt32(), swapChain: true });
  }});
}

function scan() {
  for (const m of Process.enumerateModules()) if (/^d3d11\.dll$/i.test(m.name) || /^dxgi\.dll$/i.test(m.name)) hookModule(m);
}

rpc.exports = {
  init(options) {
    if (options && typeof options.capturePageBytes !== 'boolean') throw Error('capturePageBytes must be boolean');
    capturePageBytes = !!(options && options.capturePageBytes);
    scan(); return { maxHashBytes: MAX_HASH_BYTES, observerOnly: true, capturePageBytes, maxCapturedPages: 16 };
  },
  scan,
  hookDevice(address) { hookDevice(ptr(address)); return { hooked: true, address: ptr(address).toString() }; },
  onAdded(name) { const m = Process.findModuleByName(name); if (m) hookModule(m); },
  onRemoved(name) { hookedModules.delete(name); if (/^d3d11\.dll$/i.test(name)) { hookedDevices.clear(); hookedTextureVtables.clear(); hookedContextVtables.clear(); resourceDescs.clear(); shaderViewDescs.clear(); mappedResources.clear(); } emit('moduleRemoved', { module: name }); }
};

Process.attachModuleObserver({ onAdded(module) { if (/^(d3d11|dxgi)\.dll$/i.test(module.name)) hookModule(module); }, onRemoved(module) { rpc.exports.onRemoved(module.name); } });
scan();
