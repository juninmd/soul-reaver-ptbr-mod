'use strict';

// Prototype host verifies the executable, bridge and assets before configuration.
// Never spawns a process. Native UI, text and navigation retain their own draws.
const hooks = new Map(), contexts = new Map(), resourceKinds = new Map();
let enabled = false, busy = false, kind = -1, lastBackground = 0;
let nativeDepth = 0, overlay = null, initialize = null, render = null;
let draws = 0, replacements = 0, attempts = 0, frames = 0, captureBudget = 0, lastCapture = 0;
let movie = null;
const seen = new Set();
const pins = new Map();
function log(event, fields = {}) { send({ event, ...fields }); }
function method(object, index, ret, args) {
  return new NativeFunction(object.readPointer().add(index * Process.pointerSize).readPointer(), ret, ['pointer', ...args], 'stdcall');
}
function release(object) { if (object && !object.isNull()) method(object, 2, 'uint', [])(object); }
function hook(address, callbacks) {
  const key = address.toString();
  if (!hooks.has(key)) hooks.set(key, Interceptor.attach(address, callbacks));
}
function textureDesc(texture) {
  const d = Memory.alloc(44);
  method(texture, 10, 'void', ['pointer'])(texture, d);
  return { width: d.readU32(), height: d.add(4).readU32(), format: d.add(16).readU32(), samples: d.add(20).readU32(), bind: d.add(32).readU32() };
}
function resourceDesc(view) {
  const out = Memory.alloc(Process.pointerSize); out.writePointer(ptr(0));
  method(view, 7, 'void', ['pointer'])(view, out);
  const resource = out.readPointer();
  if (resource.isNull()) return null;
  try {
    const iid = Memory.alloc(16); iid.writeByteArray([0xf2,0xaa,0x15,0x6f,0x08,0xd2,0x89,0x4e,0x9a,0xb4,0x48,0x95,0x35,0xd3,0x4f,0x9c]);
    const texture = Memory.alloc(Process.pointerSize); texture.writePointer(ptr(0));
    if (method(resource, 0, 'int', ['pointer','pointer'])(resource, iid, texture) !== 0) return null;
    const p = texture.readPointer();
    try { return textureDesc(p); } finally { release(p); }
  } finally { release(resource); }
}
function currentRtv(context) {
  const out = Memory.alloc(Process.pointerSize), depth = Memory.alloc(Process.pointerSize);
  out.writePointer(ptr(0)); depth.writePointer(ptr(0));
  method(context, 89, 'void', ['uint','pointer','pointer'])(context, 1, out, depth);
  release(depth.readPointer());
  return out.readPointer();
}
function onDraw(context, info, count) {
  if (busy || !enabled || kind < 0 || Date.now() - lastBackground > 1500) return null;
  const textures = [];
  for (const [slot, view] of info.views) {
    if (slot > 7 || view.isNull()) continue;
    try { const d = resourceDesc(view); if (d) textures.push({ slot, ...d }); } catch (_) {}
  }
  const signature = JSON.stringify({ kind, count, textures, nativeDepth });
  if (!seen.has(signature) && seen.size < 80) { seen.add(signature); log('menu-draw', { kind, count, textures, nativeDepth }); }
  // Runtime trace: the TIM is expanded into the legacy bitmap at C400A8,
  // uploaded at the selected native screen size, then drawn as a four-vertex
  // R16 quad before the separate 256px font-atlas batches.
  if (!info.replace || !isLegacyBackgroundQuad(count,textures)) return null;
  return { context, device: info.device, kind };
}
function isLegacyBackgroundQuad(count,textures){
  return count===4 && textures.some(t=>t.slot===0 && t.width>=640 && t.height>=480 && t.width*3===t.height*4 && [53,56,57].includes(t.format));
}
globalThis.menuBackgroundPure={isLegacyBackgroundQuad};
function hookContext(context, device, replace) {
  if (context.isNull() || contexts.has(context.toString())) return;
  const info = { device, views: new Map(), replace };
  contexts.set(context.toString(), info);
  try { log('context-type',{context:context.toString(),type:method(context,112,'uint',[])(context)}); } catch(_){}
  hook(context.readPointer().add(8 * Process.pointerSize).readPointer(), {
    onEnter(a) {
      if (busy) return;
      const state = contexts.get(a[0].toString()); if (!state) return;
      const start = a[1].toUInt32(), count = a[2].toUInt32();
      if (count > 128 || start + count > 128 || (count && a[3].isNull())) return;
      for (let i=0; i<count; i++) state.views.set(start+i, a[3].add(i*Process.pointerSize).readPointer());
    },
  });
  for (const index of [12,13,20,21]) hook(context.readPointer().add(index*Process.pointerSize).readPointer(), {
    onEnter(a) {
      if (busy) return;
      draws++;
      let state=contexts.get(a[0].toString());
      if(!state){
        try { const out=Memory.alloc(Process.pointerSize);method(a[0],3,'void',['pointer'])(a[0],out);const d=out.readPointer();hookContext(a[0],d,replace);release(d);state=contexts.get(a[0].toString());log('context-alias',{context:a[0].toString()}); }
        catch(e){log('untracked-draw-context',{context:a[0].toString(),error:String(e)});return;}
      }
      try { this.work=onDraw(a[0],state,a[1].toUInt32()); } catch(e) { log('draw-inspection-error',{error:String(e)}); }
    },
    onLeave() {
      if (!this.work || busy) return;
      busy=true;
      let rtv=null;
      try {
        const w=this.work; rtv=currentRtv(w.context);
        if (!rtv.isNull()) {
          attempts++;
          if(attempts<4)log('background-target',{kind:w.kind,descriptor:resourceDesc(rtv)});
          const hr=render(w.device,w.context,rtv,w.kind);
          if (hr===0) { replacements++; if(replacements<4)log('menu-hd-draw',{kind:w.kind,hr}); }
          else if(attempts<4) log('menu-hd-refused',{hr});
        }
      } catch(e) { log('menu-hd-error',{error:String(e)}); enabled=false; }
      finally { release(rtv); busy=false; }
    },
  });
  log('context-hooked',{context:context.toString()});
}
function captureSwapchain(swapchain) {
  if (!captureBudget || busy || Date.now()-lastCapture<1500) return;
  lastCapture=Date.now(); busy=true;
  let texture=null, device=null, context=null, staging=null;
  try {
    const iid=Memory.alloc(16);iid.writeByteArray([0xf2,0xaa,0x15,0x6f,0x08,0xd2,0x89,0x4e,0x9a,0xb4,0x48,0x95,0x35,0xd3,0x4f,0x9c]);
    const out=Memory.alloc(Process.pointerSize);out.writePointer(ptr(0));
    if(method(swapchain,9,'int',['uint','pointer','pointer'])(swapchain,0,iid,out)!==0)return;
    texture=out.readPointer();const d=textureDesc(texture);
    if(d.samples!==1||d.width>4096||d.height>3072||![27,28,29,87,90,91].includes(d.format))return;
    method(texture,3,'void',['pointer'])(texture,out);device=out.readPointer();
    method(device,40,'void',['pointer'])(device,out);context=out.readPointer();
    const td=Memory.alloc(44);method(texture,10,'void',['pointer'])(texture,td);
    td.add(16).writeU32([27,28,29].includes(d.format)?28:87);td.add(8).writeU32(1);td.add(12).writeU32(1);
    td.add(28).writeU32(3);td.add(32).writeU32(0);td.add(36).writeU32(0x20000);td.add(40).writeU32(0);
    if(method(device,5,'int',['pointer','pointer','pointer'])(device,td,ptr(0),out)!==0)return;
    staging=out.readPointer();method(context,47,'void',['pointer','pointer'])(context,staging,texture);
    const mapped=Memory.alloc(Process.pointerSize+8);
    if(method(context,14,'int',['pointer','uint','uint','uint','pointer'])(context,staging,0,1,0,mapped)!==0)return;
    try { const pitch=mapped.add(Process.pointerSize).readU32();send({event:'menu-gpu-frame',index:frames++,kind,width:d.width,height:d.height,format:d.format,pitch,replacements},mapped.readPointer().readByteArray(pitch*d.height));captureBudget--; }
    finally { method(context,15,'void',['pointer','uint'])(context,staging,0); }
  } catch(e) { log('capture-error',{error:String(e)});captureBudget=0; }
  finally { release(staging);release(context);release(device);release(texture);busy=false; }
}
function swapchain(s) {
  if(s.isNull())return;
  log('swapchain-hooked',{pointer:s.toString()});
  hook(s.readPointer().add(8*Process.pointerSize).readPointer(),{onEnter(a){captureSwapchain(a[0]);}});
  const iid=Memory.alloc(16);iid.writeByteArray([0xf7,0x45,0x0a,0x79,0x42,0x0d,0x76,0x48,0x98,0x3a,0x0a,0x55,0xcf,0xe6,0xf4,0xaa]);
  const out=Memory.alloc(Process.pointerSize);
  if(method(s,0,'int',['pointer','pointer'])(s,iid,out)===0){const s1=out.readPointer();hook(s1.readPointer().add(22*Process.pointerSize).readPointer(),{onEnter(a){captureSwapchain(a[0]);}});release(s1);}
}
function hookDevice(d,replace){
  for(const index of [40,43])hook(d.readPointer().add(index*Process.pointerSize).readPointer(),{onEnter(a){this.d=a[0];this.out=a[1];},onLeave(){if(this.out&&!this.out.isNull()){const ctx=this.out.readPointer();if(!ctx.isNull())hookContext(ctx,this.d,replace);}}});
}
function factory(f) {
  hook(f.readPointer().add(10*Process.pointerSize).readPointer(),{onEnter(a){this.out=a[3];},onLeave(r){if(r.toInt32()===0)swapchain(this.out.readPointer());}});
  const iid=Memory.alloc(16);iid.writeByteArray([0x1c,0x3a,0xc8,0x50,0x72,0xe0,0x48,0x4c,0x87,0xb0,0x36,0x30,0xfa,0x36,0xa6,0xd0]);
  const out=Memory.alloc(Process.pointerSize);
  if(method(f,0,'int',['pointer','pointer'])(f,iid,out)===0){const f2=out.readPointer();hook(f2.readPointer().add(15*Process.pointerSize).readPointer(),{onEnter(a){this.out=a[6];},onLeave(r){if(r.toInt32()===0)swapchain(this.out.readPointer());}});release(f2);}
}
function observeModules(replace) {
  return Process.attachModuleObserver({onAdded(m) {
    if(/^(d3d11|dxgi)\.dll$/i.test(m.name)){
      log('graphics-module',{name:m.name,base:m.base.toString()});
      if(!pins.has(m.name.toLowerCase())){
        const load=new NativeFunction(Process.getModuleByName('kernel32.dll').getExportByName('LoadLibraryW'),'pointer',['pointer'],'stdcall');
        const handle=load(Memory.allocUtf16String(m.path));
        if(handle.isNull()||!handle.equals(m.base))throw Error('Cannot pin graphics module '+m.name);
        pins.set(m.name.toLowerCase(),handle);
      }
    }
    if(/^binkw32\.dll$/i.test(m.name)){
      const open=m.findExportByName('_BinkOpen@8'),close=m.findExportByName('_BinkClose@4');
      if(open)hook(open,{onEnter(a){this.name=a[0].readCString();},onLeave(r){if(!r.isNull()){movie=this.name;log('movie-open',{name:movie,width:r.readU32(),height:r.add(4).readU32()});}}});
      if(close)hook(close,{onEnter(){movie=null;log('movie-close');}});
    }
    if(/^d3d11\.dll$/i.test(m.name))for(const f of [{name:'D3D11CreateDevice',device:7,context:9},{name:'D3D11CreateDeviceAndSwapChain',device:9,context:11,swap:8}]){
      const p=m.findExportByName(f.name);if(p)hook(p,{onEnter(a){this.d=a[f.device];this.c=a[f.context];this.s=f.swap?a[f.swap]:null;},onLeave(r){if(r.toInt32()===0){const d=this.d.readPointer();hookDevice(d,replace);let ctx=this.c.isNull()?null:this.c.readPointer();if(!ctx||ctx.isNull()){const o=Memory.alloc(Process.pointerSize);method(d,40,'void',['pointer'])(d,o);ctx=o.readPointer();hookContext(ctx,d,replace);release(ctx);}else hookContext(ctx,d,replace);if(this.s&&!this.s.isNull())swapchain(this.s.readPointer());}}});
    }
    if(/^dxgi\.dll$/i.test(m.name))for(const name of ['CreateDXGIFactory','CreateDXGIFactory1','CreateDXGIFactory2']){const p=m.findExportByName(name);if(p)hook(p,{onEnter(a){this.out=a[name==='CreateDXGIFactory2'?2:1];},onLeave(r){if(r.toInt32()===0)factory(this.out.readPointer());}});}
  },onRemoved(m){if(/^(d3d11|dxgi)\.dll$/i.test(m.name)){enabled=false;log('graphics-module-unloaded',{name:m.name});}}});
}
let observer=null;
rpc.exports={
  configure(options) {
    if(enabled||Process.pointerSize!==4||options.externalHostHashVerified!==true)throw Error('Unsupported or unverified host');
    const base=Process.mainModule.base;
    if(!base.equals(ptr('0x400000')))throw Error('Unexpected executable base');
    const expected=[0x8b,0x54,0x24,0x0c,0x8b,0x4c,0x24,0x04];
    const actual=new Uint8Array(base.add(0x7aa80).readByteArray(expected.length));
    if(expected.some((b,i)=>b!==actual[i]))throw Error('Native background function mismatch');
    observer=observeModules(!!options.replace);
    if(options.replace){
      const load=new NativeFunction(Process.getModuleByName('kernel32.dll').getExportByName('LoadLibraryW'),'pointer',['pointer'],'stdcall');
      overlay=load(Memory.allocUtf16String(options.dllPath));if(overlay.isNull())throw Error('Overlay DLL load failed');
      const m=Process.getModuleByAddress(overlay);
      initialize=new NativeFunction(m.getExportByName('InitializeMenuBackgrounds'),'int',['pointer','pointer'],'stdcall');
      render=new NativeFunction(m.getExportByName('RenderMenuBackground'),'int',['pointer','pointer','pointer','uint'],'stdcall');
      const hr=initialize(Memory.allocUtf16String(options.titlePng),Memory.allocUtf16String(options.selectionPng));if(hr!==0)throw Error('Background initialization failed '+hr);
    }
    hook(base.add(0x7ab60),{onEnter(a){this.name=a[0].readCString().toLowerCase();},onLeave(r){if(r.isNull())return;const k=this.name.endsWith('title1.pti')?0:this.name.endsWith('bkgdmenu.pti')?1:-1;resourceKinds.set(r.toString(),k);if(k>=0)log('menu-resource',{name:this.name,kind:k,pointer:r.toString()});}});
    hook(base.add(0x7aa80),{onEnter(a){kind=resourceKinds.get(a[0].toString())??-1;lastBackground=Date.now();}});
    hook(base.add(0xaaa90),{onEnter(){nativeDepth++;},onLeave(){nativeDepth--;}});
    enabled=true;captureBudget=options.captures??8;
    log('configured',{replace:!!options.replace});return {configured:true};
  },
  capture(count=2){captureBudget=Math.min(12,Math.max(0,count));return {captureBudget};},
  status(){return {enabled,kind,draws,replacements,attempts,frames,movie,hardwareDevice:Process.mainModule.base.add(0x8409c4).readPointer().toString(),softwareRasterizer:Process.mainModule.base.add(0x7bbcf8).readU32(),graphicsModules:Process.enumerateModules().filter(m=>/^(d3d11|d3d12|dxgi|ddraw|d3dimm)\.dll$/i.test(m.name)).map(m=>({name:m.name,path:m.path}))};},
  dispose(){enabled=false;observer?.detach();for(const h of hooks.values())h.detach();hooks.clear();contexts.clear();return {disposed:true};},
};
