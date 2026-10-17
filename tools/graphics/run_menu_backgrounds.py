"""Explicitly authorized, isolated menu renderer prototype. No Steam writes."""
from __future__ import annotations
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--runtime-authorized',action='store_true')
    p.add_argument('--observe-only',action='store_true')
    p.add_argument('--navigate-menu',action='store_true')
    p.add_argument('--seconds',type=int,default=90)
    p.add_argument('--keep-open',action='store_true')
    a=p.parse_args()
    if not a.runtime_authorized: p.error('A execução requer autorização explícita para esta rodada')
    if not 10<=a.seconds<=180: p.error('--seconds deve ficar entre 10 e 180')
    game,out=a.game.resolve(),a.output.resolve()
    if not game.is_relative_to((ROOT/'staging').resolve()): p.error('Use uma cópia isolada em staging/')
    if not out.is_relative_to((ROOT/'validate').resolve()) or out.exists(): p.error('Use uma pasta nova em validate/')
    exe=game/'kain2.exe'
    assert sha(exe)=='9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a'
    journal=json.loads((game/'.soul-reaver-ptbr/assets-state.json').read_bytes())
    archive=next(row for row in journal['assets'] if row['file']=='bigfile.dat')
    assert journal['phase']=='installed' and sha(game/'bigfile.dat')==archive['result_sha256']
    dll=ROOT/'staging/menu-background-overlay-v1/menu_background_overlay.dll'
    bridge=Path(__file__).with_name('menu_background_bridge.js')
    title,selection=(ROOT/'content/art'/name for name in ('menu-nosgoth.png','menu-itens-nosgoth.png'))
    inputs={str(path):sha(path) for path in (exe,bridge,title,selection)}
    if not a.observe_only: inputs[str(dll)]=sha(dll)
    out.mkdir(parents=True)
    sys.path.insert(0,str(ROOT/'staging/integration-probe/python-packages'))
    import frida
    from PIL import Image
    events=(out/'events.jsonl').open('x',encoding='utf-8')
    state={'kind':-1,'frames':0,'movie':None,'last_status':None}
    def message(m,data):
        event=m.get('payload',{})
        if event.get('event')=='menu-resource': state['kind']=event['kind']
        if event.get('event')=='movie-open': state['movie']=event['name']
        if event.get('event')=='movie-close': state['movie']=None
        if event.get('event')=='menu-gpu-frame' and data:
            mode='RGBA' if event['format'] in (27,28,29) else 'BGRA'
            Image.frombytes('RGBA',(event['width'],event['height']),data,'raw',mode,event['pitch']).convert('RGB').save(out/f"frame-{event['index']:02}-kind-{event['kind']}.png")
            state['frames']+=1
        events.write(json.dumps(m,ensure_ascii=False)+'\n');events.flush()
        if event.get('event') in ('menu-resource','menu-hd-draw','menu-hd-error','capture-error','configured') or m.get('type')=='error':
            print(json.dumps(m,ensure_ascii=True),flush=True)
    u=c.WinDLL('user32',use_last_error=True)
    u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
    u.GetDlgItem.argtypes=[w.HWND,c.c_int];u.GetDlgItem.restype=w.HWND
    u.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,c.c_int]
    u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,c.c_int]
    u.IsWindowVisible.argtypes=[w.HWND]
    u.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    u.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    u.SetForegroundWindow.argtypes=[w.HWND];u.GetForegroundWindow.restype=w.HWND
    u.ShowWindow.argtypes=[w.HWND,c.c_int]
    callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    u.EnumWindows.argtypes=[callback,w.LPARAM]
    device=frida.get_local_device()
    if any(process.name.lower()=='kain2.exe' for process in device.enumerate_processes()):
        raise RuntimeError('Já há um Soul Reaver aberto; feche antes desta rodada')
    pid=device.spawn([str(exe),'under','1','-mainmenu','-voice','-inspectral'],cwd=str(game))
    session=None;script=None;detached=[]
    result={'pid':pid,'game':str(game),'authorized':True,'inputs':inputs,'archiveSha256':archive['result_sha256'],'observeOnly':a.observe_only,'runtimeVerified':False}
    (out/'process.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'startedPid':pid,'observeOnly':a.observe_only}),flush=True)
    def windows():
        found=[]
        @callback
        def visit(hwnd,_):
            owner=w.DWORD();u.GetWindowThreadProcessId(hwnd,c.byref(owner))
            if owner.value==pid and u.IsWindowVisible(hwnd):
                kind=c.create_unicode_buffer(128);u.GetClassNameW(hwnd,kind,len(kind));found.append((hwnd,kind.value))
            return True
        u.EnumWindows(visit,0)
        return found
    def key(scan):
        for hwnd,cls in windows():
            if cls!='G2WndClass':continue
            u.ShowWindow(hwnd,9);u.SetForegroundWindow(hwnd)
            owner=w.DWORD();u.GetWindowThreadProcessId(u.GetForegroundWindow(),c.byref(owner))
            if owner.value!=pid:return False
            u.keybd_event(0,scan,8,0);time.sleep(.02);u.keybd_event(0,scan,10,0)
            return True
        return False
    try:
        session=device.attach(pid);session.on('detached',lambda *args:detached.append(str(args)))
        script=session.create_script(bridge.read_text(encoding='utf-8'));script.on('message',message);script.load()
        script.exports_sync.configure({'externalHostHashVerified':True,'replace':not a.observe_only,'dllPath':str(dll),'titlePng':str(title),'selectionPng':str(selection),'captures':0})
        device.resume(pid)
        started=time.monotonic();title_at=None;selection_at=None;entered=False;armed=set();last_status=0;last_skip=0
        while not detached:
            time.sleep(.25);now=time.monotonic()
            for hwnd,cls in windows():
                if cls=='#32770' and all(u.GetDlgItem(hwnd,i) for i in (1,1003,1005)):
                    button=u.GetDlgItem(hwnd,1);label=c.create_unicode_buffer(64);u.GetWindowTextW(button,label,len(label))
                    if label.value.replace('&','').strip().lower()=='ok':u.SendMessageW(button,0xF5,0,0)
            if now-last_status>3:
                state['last_status']=script.exports_sync.status();last_status=now
                (out/'status.json').write_text(json.dumps(state['last_status'],indent=2),encoding='utf-8')
                print(json.dumps({key:value for key,value in state['last_status'].items() if key!='graphicsModules'}),flush=True)
            k=state['last_status']['kind'] if state['last_status'] else -1
            if k>=0 and k not in armed:
                script.exports_sync.capture(3);armed.add(k)
                if k==0:title_at=now
                if k==1:selection_at=now
            if a.navigate_menu and title_at and not entered and k==0 and now-title_at>5:
                entered=key(0x1c)
            if a.navigate_menu and state['movie'] and 'intro' in state['movie'].lower() and now-last_skip>5:
                if key(1):last_skip=now
            if not a.keep_open and ((selection_at and now-selection_at>10) or now-started>a.seconds):break
        result.update(lastStatus=state['last_status'],frames=state['frames'],enteredMenu=entered,detached=detached)
    finally:
        if not a.keep_open or not detached:
            for hwnd,_ in windows():u.PostMessageW(hwnd,0x10,0,0)
            time.sleep(1)
            try: device.kill(pid)
            except frida.ProcessNotFoundError:pass
        if script:
            try:script.exports_sync.dispose()
            except Exception:pass
        if session:
            try:session.detach()
            except Exception:pass
        events.close()
        (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
