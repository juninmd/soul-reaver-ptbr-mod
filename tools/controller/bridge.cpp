#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <mmsystem.h>
#include <shellapi.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cwchar>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#if !defined(_WIN32_WINNT) || _WIN32_WINNT < 0x0601
#error _WIN32_WINNT must be at least Windows 7
#endif

namespace {
struct Key { WORD scan; bool extended; bool operator<(const Key& o) const { return scan < o.scan || (scan == o.scan && extended < o.extended); } bool operator==(const Key& o) const { return scan == o.scan && extended == o.extended; } };
struct State { DWORD buttons=0, x=0, y=0, z=0, r=0, u=0, v=0, pov=JOY_POVCENTERED; };
constexpr int kDeadzone = 9000;
constexpr Key K(WORD scan, bool ext=false) { return Key{scan,ext}; }
constexpr Key kUp=K(0x48,true), kDown=K(0x50,true), kLeft=K(0x4b,true), kRight=K(0x4d,true);
constexpr Key kX=K(0x2d), kA=K(0x1e), kD=K(0x20), kF=K(0x21), kS=K(0x1f), kC=K(0x2e), kCtrl=K(0x1d,true), kNum0=K(0x52), kEsc=K(0x01), kEnter=K(0x1c);

int AxisDelta(DWORD value, DWORD minimum, DWORD maximum) {
    if (maximum <= minimum) return 0;
    const int64_t center = (static_cast<int64_t>(minimum) + maximum) / 2;
    const int64_t half = (static_cast<int64_t>(maximum) - minimum) / 2;
    if (half <= 0) return 0;
    return static_cast<int>((static_cast<int64_t>(value) - center) * 32767 / half);
}
bool PovUp(DWORD p) { return p != JOY_POVCENTERED && (p >= 31500 || p <= 4500); }
bool PovRight(DWORD p) { return p >= 4500 && p <= 13500; }
bool PovDown(DWORD p) { return p >= 13500 && p <= 22500; }
bool PovLeft(DWORD p) { return p >= 22500 && p <= 31500; }
bool Pressed(const State& s, unsigned n) { return (s.buttons & (1u << (n-1))) != 0; }
std::vector<Key> Desired(const State& s, const JOYCAPSW* caps) {
    std::vector<Key> keys;
    auto add=[&](bool on, Key k){if(on) keys.push_back(k);};
    int dx=AxisDelta(s.x, caps?caps->wXmin:0, caps?caps->wXmax:65535);
    int dy=AxisDelta(s.y, caps?caps->wYmin:0, caps?caps->wYmax:65535);
    int camera=AxisDelta(s.z, caps?caps->wZmin:0, caps?caps->wZmax:65535);
    add(dx < -kDeadzone,kLeft); add(dx > kDeadzone,kRight); add(dy < -kDeadzone,kUp); add(dy > kDeadzone,kDown);
    add(PovUp(s.pov),kUp); add(PovRight(s.pov),kRight); add(PovDown(s.pov),kDown); add(PovLeft(s.pov),kLeft);
    add(Pressed(s,1),kA); add(Pressed(s,2),kX); add(Pressed(s,3),kD); add(Pressed(s,4),kF);
    add(Pressed(s,5),kS); add(Pressed(s,6),kC);
    // The game's camera orbit controls are opposite the desired look direction.
    add(camera < -kDeadzone,kNum0); add(camera > kDeadzone,kCtrl);
    add(Pressed(s,10),kEsc); add(Pressed(s,9),kEnter);
    std::sort(keys.begin(),keys.end()); keys.erase(std::unique(keys.begin(),keys.end()),keys.end()); return keys;
}
bool Has(const std::vector<Key>& v, Key k) { return std::find(v.begin(),v.end(),k)!=v.end(); }
std::string JsonEscape(const wchar_t* value) {
    std::string out;
    for (const wchar_t* p=value; *p; ++p) {
        wchar_t c=*p;
        if (c==L'"' || c==L'\\') { out.push_back('\\'); out.push_back(static_cast<char>(c)); }
        else if (c>=0x20 && c<0x7f) out.push_back(static_cast<char>(c));
        else if (c<0x80) { char b[7]; std::snprintf(b,sizeof(b),"\\u%04x",static_cast<unsigned>(c)); out+=b; }
        else { wchar_t pair[2]={c,0}; char utf8[8]{}; WideCharToMultiByte(CP_UTF8,0,pair,1,utf8,sizeof(utf8),nullptr,nullptr); out+=utf8; }
    }
    return out;
}
struct Device { UINT id=0; JOYCAPSW caps{}; };
bool IsSupported(const JOYCAPSW& c) { return c.wMid==0x054c && (c.wPid==0x0ce6 || c.wPid==0x0df2); }
const wchar_t* DeviceName(const JOYCAPSW& c) { return c.wPid==0x0ce6?L"DualSense Wireless Controller":L"DualSense Edge Wireless Controller"; }
bool FindDevice(Device& d) {
    UINT count=std::min<UINT>(joyGetNumDevs(),16);
    for(UINT i=0;i<count;++i) { JOYCAPSW c{}; if(joyGetDevCapsW(i,&c,sizeof(c))==JOYERR_NOERROR && IsSupported(c)) { d.id=i; d.caps=c; return true; } }
    return false;
}
bool ReadState(UINT id, State& s) {
    JOYINFOEX info{}; info.dwSize=sizeof(info); info.dwFlags=JOY_RETURNALL;
    if(joyGetPosEx(id,&info)!=JOYERR_NOERROR) return false;
    s={info.dwButtons,info.dwXpos,info.dwYpos,info.dwZpos,info.dwRpos,info.dwUpos,info.dwVpos,info.dwPOV}; return true;
}
void PrintJsonProbe() {
    Device d{}; bool connected=FindDevice(d); State s{};
    std::string name=connected?JsonEscape(DeviceName(d.caps)):std::string();
    std::string json="{\"connected\":"+std::string(connected?"true":"false")+",\"deviceName\":\""+name+"\"}\n";
    HANDLE h=GetStdHandle(STD_OUTPUT_HANDLE); DWORD wrote=0; if(h && h!=INVALID_HANDLE_VALUE) WriteFile(h,json.data(),static_cast<DWORD>(json.size()),&wrote,nullptr);
}
bool SelfTest() {
    JOYCAPSW caps{}; caps.wXmin=0; caps.wXmax=65535; caps.wYmin=0; caps.wYmax=65535; caps.wZmin=0; caps.wZmax=65535; caps.wRmin=0; caps.wRmax=65535;
    State s{}; s.x=32768; s.y=32768; s.z=32768; s.pov=JOY_POVCENTERED;
    auto neutral=Desired(s,&caps); if(!neutral.empty()) return false;
    s.buttons=0x3ff; auto allButtons=Desired(s,&caps); if(allButtons.size()!=8 || !Has(allButtons,kX) || !Has(allButtons,kA) || !Has(allButtons,kD) || !Has(allButtons,kF) || !Has(allButtons,kS) || !Has(allButtons,kC) || Has(allButtons,kCtrl) || Has(allButtons,kNum0) || !Has(allButtons,kEsc) || !Has(allButtons,kEnter)) return false;
    s.buttons=1u<<1; auto cross=Desired(s,&caps); if(cross.size()!=1 || !Has(cross,kX) || Has(cross,kEnter)) return false;
    s.buttons=(1u<<6)|(1u<<7); auto triggers=Desired(s,&caps); if(!triggers.empty()) return false;
    s.buttons=0; s.z=15000; auto cameraLeft=Desired(s,&caps); if(cameraLeft.size()!=1 || !Has(cameraLeft,kNum0) || Has(cameraLeft,kCtrl)) return false;
    s.z=50000; auto cameraRight=Desired(s,&caps); if(cameraRight.size()!=1 || !Has(cameraRight,kCtrl) || Has(cameraRight,kNum0)) return false;
    s.z=33768; if(!Desired(s,&caps).empty()) return false;
    s.z=32768; if(!Desired(s,&caps).empty()) return false;
    s.buttons=0; s.x=32768+1000; auto dead=Desired(s,&caps); if(!dead.empty()) return false;
    s.x=50000; auto right=Desired(s,&caps); if(!Has(right,kRight)) return false;
    s.x=32768; s.y=15000; auto up=Desired(s,&caps); if(!Has(up,kUp)) return false;
    s.x=32768; s.y=32768; s.pov=0; auto pov=Desired(s,&caps); if(pov.size()!=1 || !Has(pov,kUp)) return false;
    s.pov=JOY_POVCENTERED; s.buttons=1; auto held=Desired(s,&caps); s.buttons=0; auto released=Desired(s,&caps);
    if(!Has(held,kA) || Has(released,kA)) return false;
    fwprintf(stdout,L"{\"ok\":true,\"checks\":[\"neutral\",\"button-mask\",\"triggers-unmapped\",\"right-stick-camera-left-right-deadzone-release\",\"left-stick-deadzone-and-directions\",\"pov\",\"key-release\"],\"sendInput\":false,\"processAccess\":false}\n"); return true;
}

std::wofstream* g_log=nullptr;
State g_eventState{};
void Log(const wchar_t* type, DWORD buttons=0, DWORD x=0, DWORD y=0, const wchar_t* detail=L"", DWORD z=0, DWORD r=0, DWORD u=0, DWORD v=0, DWORD pov=JOY_POVCENTERED) {
    if(!g_log) return;
    *g_log << L"{\"tick\":" << GetTickCount64() << L",\"type\":\"" << type << L"\",\"buttons\":" << buttons << L",\"axis\":[" << x << L"," << y << L"," << z << L"," << r << L"," << u << L"," << v << L"],\"pov\":" << pov << L",\"detail\":\"" << detail << L"\"}\n"; g_log->flush();
}
bool Inject(Key key, bool down) {
    INPUT in{}; in.type=INPUT_KEYBOARD; in.ki.wScan=key.scan; in.ki.dwFlags=KEYEVENTF_SCANCODE | (key.extended?KEYEVENTF_EXTENDEDKEY:0) | (down?0:KEYEVENTF_KEYUP);
    UINT n=SendInput(1,&in,sizeof(in)); wchar_t detail[80]{}; swprintf_s(detail,L"%ls;scan=0x%02x;extended=%u",n==1?(down?L"down-ok":L"up-ok"):(down?L"down-failed":L"up-failed"),key.scan,key.extended?1u:0u); Log(L"input",g_eventState.buttons,g_eventState.x,g_eventState.y,detail,g_eventState.z,g_eventState.r,g_eventState.u,g_eventState.v,g_eventState.pov); return n==1;
}
bool IsTargetForeground(DWORD pid) {
    HWND fg=GetForegroundWindow(); DWORD fgPid=0; if(fg) GetWindowThreadProcessId(fg,&fgPid); return fgPid==pid;
}
bool Reconcile(std::vector<Key>& current, const std::vector<Key>& desired, DWORD pid) {
    for(auto it=current.begin();it!=current.end();) {
        if(!Has(desired,*it)) { if(Inject(*it,false)) it=current.erase(it); else ++it; }
        else ++it;
    }
    for(Key k:desired) if(!Has(current,k)) { if(!IsTargetForeground(pid)) return false; if(Inject(k,true)) current.push_back(k); }
    std::sort(current.begin(),current.end());
    return true;
}

HWND g_overlay=nullptr; DWORD g_overlayButtons=0;
constexpr COLORREF kTransparent=RGB(1,2,3);
LRESULT CALLBACK OverlayProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if(msg==WM_NCHITTEST) return HTTRANSPARENT;
    if(msg==WM_PAINT) {
        PAINTSTRUCT ps{}; HDC dc=BeginPaint(hwnd,&ps); RECT rc{}; GetClientRect(hwnd,&rc);
        HBRUSH bg=CreateSolidBrush(kTransparent); FillRect(dc,&rc,bg); DeleteObject(bg);
        SetBkMode(dc,TRANSPARENT); HFONT font=CreateFontW(-17,0,0,0,FW_BOLD,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH|FF_DONTCARE,L"Segoe UI"); HFONT old=static_cast<HFONT>(SelectObject(dc,font));
        const wchar_t* labels[]={L"□  Ação",L"×  Pulo",L"○  Almas",L"△  Mirar"}; COLORREF colors[]={RGB(255,110,145),RGB(80,170,255),RGB(245,90,100),RGB(110,230,160)}; unsigned masks[]={0,1,2,3}; int colWidth=std::max(72,(static_cast<int>(rc.right)-24)/4);
        for(int i=0;i<4;++i) { RECT item{12+i*colWidth,7,12+(i+1)*colWidth,34}; bool active=(g_overlayButtons & (1u<<masks[i]))!=0; HBRUSH brush=CreateSolidBrush(active?RGB(50,70,96):RGB(20,26,36)); FillRect(dc,&item,brush); DeleteObject(brush); SetTextColor(dc,colors[i]); DrawTextW(dc,labels[i],-1,&item,DT_CENTER|DT_VCENTER|DT_SINGLELINE|DT_END_ELLIPSIS); }
        HFONT small=CreateFontW(-13,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH|FF_DONTCARE,L"Segoe UI"); SelectObject(dc,small); SetTextColor(dc,RGB(235,240,250)); RECT help{14,40,rc.right-14,rc.bottom-3}; DrawTextW(dc,L"Analógico direito: câmera   |   Create: confirmar   |   Options: pausa   |   L1: focar   |   R1: agachar",-1,&help,DT_LEFT|DT_VCENTER|DT_WORDBREAK|DT_END_ELLIPSIS); SelectObject(dc,old); DeleteObject(small); DeleteObject(font); EndPaint(hwnd,&ps); return 0;
    }
    return DefWindowProcW(hwnd,msg,wp,lp);
}
void EnsureOverlayClass() {
    static bool registered=false; if(registered) return;
    WNDCLASSEXW wc{}; wc.cbSize=sizeof(wc); wc.lpfnWndProc=OverlayProc; wc.hInstance=GetModuleHandleW(nullptr); wc.lpszClassName=L"SrDualSenseOverlayV1"; RegisterClassExW(&wc); registered=true;
}
void UpdateOverlay(bool visible, HWND target, DWORD buttons) {
    EnsureOverlayClass();
    if(!visible) { if(g_overlay) ShowWindow(g_overlay,SW_HIDE); return; }
    RECT cr{}; if(!GetClientRect(target,&cr)) return;
    POINT p{cr.left,cr.bottom}; ClientToScreen(target,&p);
    int width=std::clamp(cr.right-cr.left,360L,760L), height=88;
    int x=p.x+std::max(0,(static_cast<int>(cr.right-cr.left)-width)/2), y=p.y-height-12;
    if(!g_overlay) g_overlay=CreateWindowExW(WS_EX_TOPMOST|WS_EX_TRANSPARENT|WS_EX_NOACTIVATE|WS_EX_TOOLWINDOW|WS_EX_LAYERED,L"SrDualSenseOverlayV1",L"",WS_POPUP,0,0,width,height,target,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!g_overlay) return;
    g_overlayButtons=buttons; SetLayeredWindowAttributes(g_overlay,kTransparent,0,LWA_COLORKEY);
    SetWindowPos(g_overlay,HWND_TOPMOST,x,y,width,height,SWP_NOACTIVATE|SWP_SHOWWINDOW); InvalidateRect(g_overlay,nullptr,TRUE);
}
BOOL WINAPI ConsoleHandler(DWORD type) { if(type==CTRL_C_EVENT||type==CTRL_BREAK_EVENT||type==CTRL_CLOSE_EVENT||type==CTRL_LOGOFF_EVENT||type==CTRL_SHUTDOWN_EVENT) { return TRUE; } return FALSE; }
int Attach(DWORD pid, const std::wstring& logPath) {
    wchar_t mutexName[96]{}; swprintf_s(mutexName,L"Local\\SoulReaverDualSense_%lu",static_cast<unsigned long>(pid));
    HANDLE mutex=CreateMutexW(nullptr,FALSE,mutexName); if(!mutex) return 3; if(GetLastError()==ERROR_ALREADY_EXISTS) { CloseHandle(mutex); return 4; }
    HANDLE process=OpenProcess(SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid); if(!process) { CloseHandle(mutex); return 5; }
    wchar_t imagePath[32768]{}; DWORD imageChars=static_cast<DWORD>(_countof(imagePath));
    if(!QueryFullProcessImageNameW(process,0,imagePath,&imageChars)) { CloseHandle(process); CloseHandle(mutex); return 7; }
    const wchar_t* base=wcsrchr(imagePath,L'\\'); base=base?base+1:imagePath;
    if(_wcsicmp(base,L"kain2.exe")!=0) { CloseHandle(process); CloseHandle(mutex); return 8; }
    if(!logPath.empty()) { static std::wofstream file; file.open(logPath,std::ios::out|std::ios::app); if(!file) { CloseHandle(process); CloseHandle(mutex); return 6; } g_log=&file; }
    SetConsoleCtrlHandler(ConsoleHandler,TRUE);
    Device device{}; bool connected=false,focused=false; std::vector<Key> owned; ULONGLONG nextSearch=0; State lastState{}; bool haveLastState=false;
    while(WaitForSingleObject(process,0)==WAIT_TIMEOUT) {
        MSG msg{}; while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        ULONGLONG now=GetTickCount64();
        if(!connected && now>=nextSearch) { nextSearch=now+1000; Device found{}; if(FindDevice(found)) { State probe{}; if(ReadState(found.id,probe)) { device=found; connected=true; g_eventState=probe; Log(L"connected",probe.buttons,probe.x,probe.y,DeviceName(device.caps),probe.z,probe.r,probe.u,probe.v,probe.pov); } } }
        HWND fg=GetForegroundWindow(); DWORD fgPid=0; if(fg) GetWindowThreadProcessId(fg,&fgPid); bool isFocused=(fgPid==pid);
        if(isFocused!=focused) { focused=isFocused; Log(L"focus",0,0,0,focused?L"gained":L"lost"); }
        if(!focused || !connected) { if(!owned.empty()) { const std::vector<Key> none; Reconcile(owned,none,pid); } }
        if(!focused) { UpdateOverlay(false,nullptr,0); }
        else if(connected) {
            State state{}; if(!ReadState(device.id,state)) { Log(L"connected",0,0,0,L"disconnected"); connected=false; haveLastState=false; UpdateOverlay(false,nullptr,0); nextSearch=now+1000; }
            else { g_eventState=state; auto desired=Desired(state,&device.caps); if(!Reconcile(owned,desired,pid)) { const std::vector<Key> none; Reconcile(owned,none,pid); focused=false; Log(L"focus",0,0,0,L"lost-during-input"); UpdateOverlay(false,nullptr,0); } else { if(!haveLastState || state.buttons!=lastState.buttons || state.x!=lastState.x || state.y!=lastState.y || state.z!=lastState.z || state.r!=lastState.r || state.u!=lastState.u || state.v!=lastState.v || state.pov!=lastState.pov) Log(L"input",state.buttons,state.x,state.y,L"state",state.z,state.r,state.u,state.v,state.pov); lastState=state; haveLastState=true; UpdateOverlay(true,fg,state.buttons); } }
        } else UpdateOverlay(false,nullptr,0);
        Sleep(8);
    }
    if(!owned.empty()) { const std::vector<Key> none; for(int retry=0;retry<5 && !owned.empty();++retry) { Reconcile(owned,none,pid); if(!owned.empty()) Sleep(8); } }
    if(g_overlay) { DestroyWindow(g_overlay); g_overlay=nullptr; }
    Log(L"focus",0,0,0,L"process-exit");
    if(g_log) { g_log->flush(); g_log=nullptr; }
    CloseHandle(process); CloseHandle(mutex); return 0;
}
}

int wmain(int argc, wchar_t** argv) {
    if(argc==2 && _wcsicmp(argv[1],L"--probe")==0) { PrintJsonProbe(); return 0; }
    if(argc==2 && _wcsicmp(argv[1],L"--self-test")==0) return SelfTest()?0:1;
    if(argc>=3 && _wcsicmp(argv[1],L"--attach")==0) {
        wchar_t* end=nullptr; unsigned long pid=wcstoul(argv[2],&end,10); if(!end||*end||pid==0||pid>0xfffffffful) return 2;
        std::wstring logPath; for(int i=3;i<argc;++i) { if(_wcsicmp(argv[i],L"--log")==0 && i+1<argc) logPath=argv[++i]; else return 2; }
        return Attach(static_cast<DWORD>(pid),logPath);
    }
    fwprintf(stderr,L"usage: sr-dualsense.exe --probe | --self-test | --attach <PID> [--log <path>]\n"); return 2;
}
