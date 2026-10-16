#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11_1.h>
#include <d3dcompiler.h>
#include <wincodec.h>
#include <winnls.h>
#include <wrl/client.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
static std::wstring g_atlasPath;
static ComPtr<ID3D11Device> g_device;
static ComPtr<ID3D11ShaderResourceView> g_atlas;
static ComPtr<ID3D11ShaderResourceView> g_dynamic;
static ComPtr<ID3D11VertexShader> g_vs;
static ComPtr<ID3D11PixelShader> g_ps;
static ComPtr<ID3D11SamplerState> g_sampler;
static std::mutex g_mutex;
static std::wstring g_caption;
static bool g_dynamicMode = false;
static UINT g_textWidth = 0, g_textHeight = 0;
struct UiItem { std::wstring text; int x,y,fontPx; uint32_t rgba; bool operator==(const UiItem& o) const { return text==o.text&&x==o.x&&y==o.y&&fontPx==o.fontPx&&rgba==o.rgba; } };
static bool g_uiMode=false;
static std::vector<UiItem> g_uiItems,g_uiCommitted;
static std::vector<BYTE> g_uiRgba;
static constexpr int kUiMaxItems=128,kUiMaxChars=4000;
struct ComApartment {
    bool owns;
    explicit ComApartment(HRESULT hr) : owns(SUCCEEDED(hr)) {}
    ~ComApartment() { if (owns) CoUninitialize(); }
};

static HRESULT LoadAtlas(ID3D11Device* device) {
    if (g_device.Get() == device && g_atlas && g_vs && g_ps) return S_OK;
    g_atlas.Reset(); g_vs.Reset(); g_ps.Reset(); g_sampler.Reset(); g_device = device;
    const HRESULT comHr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(comHr) && comHr != RPC_E_CHANGED_MODE) return comHr;
    const ComApartment apartment(comHr);
    ComPtr<IWICImagingFactory> factory;
    HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory));
    if (FAILED(hr)) return hr;
    ComPtr<IWICBitmapDecoder> decoder;
    hr = factory->CreateDecoderFromFilename(g_atlasPath.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnLoad, &decoder);
    if (FAILED(hr)) return hr;
    ComPtr<IWICBitmapFrameDecode> frame;
    hr = decoder->GetFrame(0, &frame); if (FAILED(hr)) return hr;
    UINT width = 0, height = 0; hr = frame->GetSize(&width, &height); if (FAILED(hr)) return hr;
    if (width != 3840 || height != 2160) return HRESULT_FROM_WIN32(ERROR_BAD_FORMAT);
    ComPtr<IWICFormatConverter> converter;
    hr = factory->CreateFormatConverter(&converter); if (FAILED(hr)) return hr;
    hr = converter->Initialize(frame.Get(), GUID_WICPixelFormat32bppRGBA, WICBitmapDitherTypeNone, nullptr, 0, WICBitmapPaletteTypeCustom);
    if (FAILED(hr)) return hr;
    std::vector<BYTE> pixels(static_cast<size_t>(width) * height * 4);
    hr = converter->CopyPixels(nullptr, width * 4, static_cast<UINT>(pixels.size()), pixels.data()); if (FAILED(hr)) return hr;
    D3D11_TEXTURE2D_DESC td{}; td.Width = width; td.Height = height; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_R8G8B8A8_UNORM; td.SampleDesc.Count = 1; td.Usage = D3D11_USAGE_IMMUTABLE; td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA initial{}; initial.pSysMem = pixels.data(); initial.SysMemPitch = width * 4;
    ComPtr<ID3D11Texture2D> texture; hr = device->CreateTexture2D(&td, &initial, &texture); if (FAILED(hr)) return hr;
    hr = device->CreateShaderResourceView(texture.Get(), nullptr, &g_atlas); if (FAILED(hr)) return hr;
    static const char shader[] =
        "Texture2D t:register(t0);SamplerState s:register(s0);"
        "struct V{float4 p:SV_Position;float2 u:TEXCOORD0;};"
        "V vs(uint id:SV_VertexID){V o;float2 p=id==0?float2(-1,-1):(id==1?float2(-1,3):float2(3,-1));"
        "o.p=float4(p,0,1);o.u=float2((p.x+1)*0.5,1-(p.y+1)*0.5);return o;}"
        "float4 ps(V i):SV_Target{return t.Sample(s,i.u);} ";
    ComPtr<ID3DBlob> vsCode, psCode, errors;
    hr = D3DCompile(shader, sizeof(shader)-1, "unicode_overlay", nullptr, nullptr, "vs", "vs_4_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &vsCode, &errors);
    if (FAILED(hr)) return hr;
    hr = D3DCompile(shader, sizeof(shader)-1, "unicode_overlay", nullptr, nullptr, "ps", "ps_4_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &psCode, &errors);
    if (FAILED(hr)) return hr;
    hr = device->CreateVertexShader(vsCode->GetBufferPointer(), vsCode->GetBufferSize(), nullptr, &g_vs); if (FAILED(hr)) return hr;
    hr = device->CreatePixelShader(psCode->GetBufferPointer(), psCode->GetBufferSize(), nullptr, &g_ps); if (FAILED(hr)) return hr;
    D3D11_SAMPLER_DESC sd{}; sd.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR; sd.AddressU = sd.AddressV = sd.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP; sd.MaxLOD = D3D11_FLOAT32_MAX;
    return device->CreateSamplerState(&sd, &g_sampler);
}

static HRESULT BuildTextTexture(ID3D11Device* device) {
    constexpr UINT width = 3840, height = 2160;
    const size_t bytes = static_cast<size_t>(width) * height * 4;
    std::vector<BYTE> rgba(bytes, 0);
    if(g_uiMode) {
        if(g_uiItems!=g_uiCommitted)return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);
        if(g_uiRgba.size()!=bytes)return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);
        D3D11_TEXTURE2D_DESC td{};td.Width=width;td.Height=height;td.MipLevels=1;td.ArraySize=1;td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;td.SampleDesc.Count=1;td.Usage=D3D11_USAGE_IMMUTABLE;td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA data{};data.pSysMem=g_uiRgba.data();data.SysMemPitch=width*4;ComPtr<ID3D11Texture2D> texture;HRESULT hr=device->CreateTexture2D(&td,&data,&texture);if(FAILED(hr))return hr;
        hr=device->CreateShaderResourceView(texture.Get(),nullptr,&g_dynamic);if(FAILED(hr))return hr;
        // The UI mode shares RenderOverlay's state-preserving D3D11 draw path.
        if(!g_vs||!g_ps||!g_sampler){
            static const char shader[]="Texture2D t:register(t0);SamplerState s:register(s0);struct V{float4 p:SV_Position;float2 u:TEXCOORD0;};V vs(uint id:SV_VertexID){V o;float2 p=id==0?float2(-1,-1):(id==1?float2(-1,3):float2(3,-1));o.p=float4(p,0,1);o.u=float2((p.x+1)*0.5,1-(p.y+1)*0.5);return o;}float4 ps(V i):SV_Target{return t.Sample(s,i.u);} ";
            ComPtr<ID3DBlob> vsCode,psCode,errors;HRESULT r=D3DCompile(shader,sizeof(shader)-1,"unicode_overlay",nullptr,nullptr,"vs","vs_4_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&vsCode,&errors);if(FAILED(r))return r;r=D3DCompile(shader,sizeof(shader)-1,"unicode_overlay",nullptr,nullptr,"ps","ps_4_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&psCode,&errors);if(FAILED(r))return r;r=device->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&g_vs);if(FAILED(r))return r;r=device->CreatePixelShader(psCode->GetBufferPointer(),psCode->GetBufferSize(),nullptr,&g_ps);if(FAILED(r))return r;D3D11_SAMPLER_DESC sd{};sd.Filter=D3D11_FILTER_MIN_MAG_MIP_LINEAR;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;r=device->CreateSamplerState(&sd,&g_sampler);if(FAILED(r))return r;
        }
        return S_OK;
    }
    if (!g_caption.empty()) {
        std::vector<BYTE> dib(bytes, 0);
        BITMAPINFO bi{}; bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER); bi.bmiHeader.biWidth = width;
        bi.bmiHeader.biHeight = -static_cast<LONG>(height); bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
        HDC screen = GetDC(nullptr); if (!screen) return HRESULT_FROM_WIN32(GetLastError());
        void* bits = nullptr; HBITMAP bitmap = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
        if (!bitmap || !bits) { DWORD err = GetLastError(); if (bitmap) DeleteObject(bitmap); ReleaseDC(nullptr, screen); return HRESULT_FROM_WIN32(err ? err : ERROR_NOT_ENOUGH_MEMORY); }
        HDC dc = CreateCompatibleDC(screen); if (!dc) { DWORD err = GetLastError(); DeleteObject(bitmap); ReleaseDC(nullptr, screen); return HRESULT_FROM_WIN32(err); }
        HGDIOBJ oldBitmap = SelectObject(dc, bitmap);
        RECT panel{180, 1640, 3660, 2130}; HBRUSH black = CreateSolidBrush(RGB(0,0,0));
        if (!black) { DWORD err=GetLastError(); SelectObject(dc,oldBitmap); DeleteDC(dc); DeleteObject(bitmap); ReleaseDC(nullptr,screen); return HRESULT_FROM_WIN32(err); }
        FillRect(dc, &panel, black); DeleteObject(black);
        SetBkMode(dc, TRANSPARENT); SetTextColor(dc, RGB(255,255,255));
        HFONT font = CreateFontW(88,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,ANTIALIASED_QUALITY,DEFAULT_PITCH|FF_DONTCARE,L"Arial");
        if (!font) { DWORD err=GetLastError(); SelectObject(dc,oldBitmap); DeleteDC(dc); DeleteObject(bitmap); ReleaseDC(nullptr,screen); return HRESULT_FROM_WIN32(err); }
        HGDIOBJ oldFont=SelectObject(dc,font); RECT text{230,1670,3610,2100};
        DrawTextW(dc,g_caption.c_str(),static_cast<int>(g_caption.size()),&text,DT_CENTER|DT_WORDBREAK|DT_NOPREFIX|DT_EDITCONTROL);
        memcpy(dib.data(),bits,bytes);
        SelectObject(dc,oldFont); DeleteObject(font); SelectObject(dc,oldBitmap); DeleteDC(dc); DeleteObject(bitmap); ReleaseDC(nullptr,screen);
        UINT minX=width,minY=height,maxX=0,maxY=0; bool any=false;
        for(UINT y=1670;y<2100;++y) for(UINT x=230;x<3610;++x){size_t i=(static_cast<size_t>(y)*width+x)*4; BYTE gray=(std::max)((std::max)(dib[i],dib[i+1]),dib[i+2]); if(gray){any=true; minX=(std::min)(minX,x);maxX=(std::max)(maxX,x);minY=(std::min)(minY,y);maxY=(std::max)(maxY,y);}}
        if(any){g_textWidth=maxX-minX+1;g_textHeight=maxY-minY+1;
            for(UINT y=1640;y<2130;++y)for(UINT x=180;x<3660;++x){size_t i=(static_cast<size_t>(y)*width+x)*4;BYTE coverage=(std::max)((std::max)(dib[i],dib[i+1]),dib[i+2]);const UINT panelAlpha=150;const UINT alpha=coverage+(panelAlpha*(255-coverage)+127)/255;rgba[i]=rgba[i+1]=rgba[i+2]=alpha?static_cast<BYTE>((255*coverage+alpha/2)/alpha):0;rgba[i+3]=static_cast<BYTE>(alpha);}
        } else {g_textWidth=g_textHeight=0;}
    } else { g_textWidth=g_textHeight=0; }
    D3D11_TEXTURE2D_DESC td{}; td.Width=width; td.Height=height; td.MipLevels=1; td.ArraySize=1; td.Format=DXGI_FORMAT_R8G8B8A8_UNORM; td.SampleDesc.Count=1; td.Usage=D3D11_USAGE_IMMUTABLE; td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA data{}; data.pSysMem=rgba.data(); data.SysMemPitch=width*4;
    ComPtr<ID3D11Texture2D> texture; HRESULT hr=device->CreateTexture2D(&td,&data,&texture); if(FAILED(hr))return hr;
    hr=device->CreateShaderResourceView(texture.Get(),nullptr,&g_dynamic); if(FAILED(hr))return hr;
    if(!g_vs||!g_ps||!g_sampler){
        static const char shader[]="Texture2D t:register(t0);SamplerState s:register(s0);struct V{float4 p:SV_Position;float2 u:TEXCOORD0;};V vs(uint id:SV_VertexID){V o;float2 p=id==0?float2(-1,-1):(id==1?float2(-1,3):float2(3,-1));o.p=float4(p,0,1);o.u=float2((p.x+1)*0.5,1-(p.y+1)*0.5);return o;}float4 ps(V i):SV_Target{return t.Sample(s,i.u);} ";
        ComPtr<ID3DBlob> vsCode,psCode,errors; hr=D3DCompile(shader,sizeof(shader)-1,"unicode_overlay",nullptr,nullptr,"vs","vs_4_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&vsCode,&errors);if(FAILED(hr))return hr;
        hr=D3DCompile(shader,sizeof(shader)-1,"unicode_overlay",nullptr,nullptr,"ps","ps_4_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&psCode,&errors);if(FAILED(hr))return hr;
        hr=device->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&g_vs);if(FAILED(hr))return hr;
        hr=device->CreatePixelShader(psCode->GetBufferPointer(),psCode->GetBufferSize(),nullptr,&g_ps);if(FAILED(hr))return hr;
        D3D11_SAMPLER_DESC sd{};sd.Filter=D3D11_FILTER_MIN_MAG_MIP_LINEAR;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;hr=device->CreateSamplerState(&sd,&g_sampler);if(FAILED(hr))return hr;
    }
    return S_OK;
}

static HRESULT ValidateCaptionLayout(const std::wstring& caption) {
    if(caption.empty())return S_OK;
    HDC screen=GetDC(nullptr);if(!screen)return HRESULT_FROM_WIN32(GetLastError());
    HDC dc=CreateCompatibleDC(screen);if(!dc){DWORD err=GetLastError();ReleaseDC(nullptr,screen);return HRESULT_FROM_WIN32(err);}
    HFONT font=CreateFontW(88,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,ANTIALIASED_QUALITY,DEFAULT_PITCH|FF_DONTCARE,L"Arial");
    if(!font){DWORD err=GetLastError();DeleteDC(dc);ReleaseDC(nullptr,screen);return HRESULT_FROM_WIN32(err);}
    HGDIOBJ oldFont=SelectObject(dc,font);TEXTMETRICW metrics{};HRESULT result=S_OK;
    if(!GetTextMetricsW(dc,&metrics)){result=HRESULT_FROM_WIN32(GetLastError());}
    else {
        for(size_t start=0;start<caption.size();){size_t end=caption.find(L'\n',start);if(end==std::wstring::npos)end=caption.size();
            if(end>start){WORD glyphs[4000]{};DWORD count=GetGlyphIndicesW(dc,caption.data()+start,static_cast<int>(end-start),glyphs,GGI_MARK_NONEXISTING_GLYPHS);if(count==GDI_ERROR){result=HRESULT_FROM_WIN32(GetLastError());break;}for(DWORD i=0;i<count;++i)if(glyphs[i]==0xffff){result=HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);break;}if(FAILED(result))break;}
            start=end+1;
        }
        RECT measured{230,0,3610,0};int measuredHeight=DrawTextW(dc,caption.c_str(),static_cast<int>(caption.size()),&measured,DT_CENTER|DT_WORDBREAK|DT_NOPREFIX|DT_EDITCONTROL|DT_CALCRECT);
        const LONG maxHeight=metrics.tmHeight*4;
        if(SUCCEEDED(result)&&(measuredHeight<=0||measured.right-measured.left>3380||measured.bottom-measured.top>maxHeight||measured.bottom-measured.top>430))result=HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);
    }
    SelectObject(dc,oldFont);DeleteObject(font);DeleteDC(dc);ReleaseDC(nullptr,screen);return result;
}

extern "C" __declspec(dllexport) HRESULT __stdcall InitializeOverlay(const wchar_t* atlasPath) {
    if (!atlasPath || !*atlasPath) return E_INVALIDARG;
    if (wcslen(atlasPath) >= MAX_PATH) return HRESULT_FROM_WIN32(ERROR_FILENAME_EXCED_RANGE);
    DWORD attrs = GetFileAttributesW(atlasPath); if (attrs == INVALID_FILE_ATTRIBUTES) { DWORD err=GetLastError(); return HRESULT_FROM_WIN32(err); } if (attrs & FILE_ATTRIBUTE_DIRECTORY) return HRESULT_FROM_WIN32(ERROR_DIRECTORY);
    std::lock_guard<std::mutex> lock(g_mutex); g_atlasPath = atlasPath; g_dynamicMode=false;g_uiMode=false;g_uiItems.clear();g_uiCommitted.clear();g_uiRgba.clear(); g_caption.clear(); g_textWidth=g_textHeight=0; g_device.Reset(); g_atlas.Reset(); g_dynamic.Reset(); g_vs.Reset(); g_ps.Reset(); g_sampler.Reset(); return S_OK;
}

extern "C" __declspec(dllexport) HRESULT __stdcall InitializeTextOverlay() {
    std::lock_guard<std::mutex> lock(g_mutex); g_dynamicMode=true;g_uiMode=false;g_uiItems.clear();g_uiCommitted.clear();g_uiRgba.clear(); g_caption.clear(); g_textWidth=g_textHeight=0; g_device.Reset(); g_atlas.Reset(); g_dynamic.Reset(); g_vs.Reset(); g_ps.Reset(); g_sampler.Reset(); return S_OK;
}
extern "C" __declspec(dllexport) HRESULT __stdcall SetCaptionUtf8(const char* text) {
    if(!text)return E_INVALIDARG; size_t len=strnlen_s(text,16001); if(len>16000)return HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);
    int chars=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,static_cast<int>(len),nullptr,0); if(len&&chars<=0)return HRESULT_FROM_WIN32(ERROR_NO_UNICODE_TRANSLATION);
    std::wstring wide(static_cast<size_t>(chars),L'\0'); if(chars&&MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,static_cast<int>(len),wide.data(),chars)!=chars)return HRESULT_FROM_WIN32(ERROR_NO_UNICODE_TRANSLATION);
    if(wide.size()>4000)return HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);
    for(wchar_t c:wide)if((c<0x20&&c!=L'\n')||c==0x7f||c==L'\t')return E_INVALIDARG;
    HRESULT layout=ValidateCaptionLayout(wide);if(FAILED(layout))return layout;
    std::lock_guard<std::mutex> lock(g_mutex); if(!g_dynamicMode||g_uiMode)return HRESULT_FROM_WIN32(ERROR_INVALID_STATE); g_caption=std::move(wide); g_dynamic.Reset(); return S_OK;
}

static HRESULT ValidateUiItem(const std::wstring& text,int x,int y,int fontPx) {
    if(text.empty()||x<0||y<0||fontPx<24||fontPx>160||x>=3840||y>=2160)return E_INVALIDARG;
    HDC screen=GetDC(nullptr);if(!screen)return HRESULT_FROM_WIN32(GetLastError());HDC dc=CreateCompatibleDC(screen);if(!dc){DWORD e=GetLastError();ReleaseDC(nullptr,screen);return HRESULT_FROM_WIN32(e);}
    HFONT font=CreateFontW(fontPx,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,ANTIALIASED_QUALITY,DEFAULT_PITCH|FF_DONTCARE,L"Arial");if(!font){DWORD e=GetLastError();DeleteDC(dc);ReleaseDC(nullptr,screen);return HRESULT_FROM_WIN32(e);}HGDIOBJ old=SelectObject(dc,font);HRESULT hr=S_OK;WORD glyphs[4000]{};DWORD n=GetGlyphIndicesW(dc,text.data(),static_cast<int>(text.size()),glyphs,GGI_MARK_NONEXISTING_GLYPHS);if(n==GDI_ERROR)hr=HRESULT_FROM_WIN32(GetLastError());else for(DWORD i=0;i<n;++i)if(glyphs[i]==0xffff){hr=HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);break;}
    RECT r{0,0,3840-x,2160-y};int h=DrawTextW(dc,text.c_str(),static_cast<int>(text.size()),&r,DT_LEFT|DT_TOP|DT_SINGLELINE|DT_NOPREFIX|DT_CALCRECT);if(SUCCEEDED(hr)&&(h<=0||r.right<=0||r.bottom<=0||r.right>3840-x||r.bottom>2160-y))hr=HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);SelectObject(dc,old);DeleteObject(font);DeleteDC(dc);ReleaseDC(nullptr,screen);return hr;
}
extern "C" __declspec(dllexport) HRESULT __stdcall InitializeUiOverlay(){std::lock_guard<std::mutex> lock(g_mutex);g_dynamicMode=true;g_uiMode=true;g_caption.clear();g_uiItems.clear();g_uiCommitted.clear();g_uiRgba.clear();g_device.Reset();g_atlas.Reset();g_dynamic.Reset();g_vs.Reset();g_ps.Reset();g_sampler.Reset();return S_OK;}
extern "C" __declspec(dllexport) HRESULT __stdcall BeginUiFrame(){std::lock_guard<std::mutex> lock(g_mutex);if(!g_uiMode)return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);g_uiItems.clear();return S_OK;}
extern "C" __declspec(dllexport) HRESULT __stdcall AddUiTextUtf8(const char* text,int x,int y,int fontPx,uint32_t rgba){if(!text)return E_INVALIDARG;size_t len=strnlen_s(text,16001);if(len==0||len>16000)return HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,static_cast<int>(len),nullptr,0);if(count<=0)return HRESULT_FROM_WIN32(ERROR_NO_UNICODE_TRANSLATION);std::wstring decoded(static_cast<size_t>(count),L'\0');if(MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,static_cast<int>(len),decoded.data(),count)!=count)return HRESULT_FROM_WIN32(ERROR_NO_UNICODE_TRANSLATION);if(decoded.size()>4000)return HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);for(wchar_t c:decoded)if(c<0x20||c==0x7f)return E_INVALIDARG;if(decoded.find(L"[icon")!=std::wstring::npos)return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);for(wchar_t c:decoded)if(c>=0x0300&&c<=0x036f)return HRESULT_FROM_WIN32(ERROR_NO_UNICODE_TRANSLATION);std::wstring wide=std::move(decoded);HRESULT hr=ValidateUiItem(wide,x,y,fontPx);if(FAILED(hr))return hr;std::lock_guard<std::mutex> lock(g_mutex);if(!g_uiMode)return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);size_t total=wide.size();for(const auto&i:g_uiItems)total+=i.text.size();if(g_uiItems.size()>=128||total>4000)return HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);g_uiItems.push_back({std::move(wide),x,y,fontPx,rgba});return S_OK;}
extern "C" __declspec(dllexport) HRESULT __stdcall CommitUiFrame(){
    std::lock_guard<std::mutex> lock(g_mutex);if(!g_uiMode)return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);constexpr UINT w=3840,h=2160;const size_t bytes=static_cast<size_t>(w)*h*4;if(g_uiItems==g_uiCommitted&&g_uiRgba.size()==bytes)return S_OK;
    std::vector<BYTE> rgba(bytes,0);HDC screen=GetDC(nullptr);if(!screen)return HRESULT_FROM_WIN32(GetLastError());
    for(const auto& item:g_uiItems){
        HDC dc=CreateCompatibleDC(screen);if(!dc){DWORD e=GetLastError();ReleaseDC(nullptr,screen);return HRESULT_FROM_WIN32(e);}HFONT font=CreateFontW(item.fontPx,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,ANTIALIASED_QUALITY,DEFAULT_PITCH|FF_DONTCARE,L"Arial");if(!font){DWORD e=GetLastError();DeleteDC(dc);ReleaseDC(nullptr,screen);return HRESULT_FROM_WIN32(e);}HGDIOBJ oldFont=SelectObject(dc,font);RECT measured{0,0,3840-item.x,2160-item.y};int textHeight=DrawTextW(dc,item.text.c_str(),static_cast<int>(item.text.size()),&measured,DT_LEFT|DT_TOP|DT_SINGLELINE|DT_NOPREFIX|DT_CALCRECT);if(textHeight<=0||measured.right<=0||measured.bottom<=0){SelectObject(dc,oldFont);DeleteObject(font);DeleteDC(dc);ReleaseDC(nullptr,screen);return HRESULT_FROM_WIN32(ERROR_BUFFER_OVERFLOW);}const UINT tw=static_cast<UINT>(measured.right),th=static_cast<UINT>(measured.bottom);BITMAPINFO bi{};bi.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);bi.bmiHeader.biWidth=static_cast<LONG>(tw);bi.bmiHeader.biHeight=-static_cast<LONG>(th);bi.bmiHeader.biPlanes=1;bi.bmiHeader.biBitCount=32;bi.bmiHeader.biCompression=BI_RGB;void* bits=nullptr;HBITMAP bitmap=CreateDIBSection(screen,&bi,DIB_RGB_COLORS,&bits,nullptr,0);if(!bitmap||!bits){DWORD e=GetLastError();if(bitmap)DeleteObject(bitmap);SelectObject(dc,oldFont);DeleteObject(font);DeleteDC(dc);ReleaseDC(nullptr,screen);return HRESULT_FROM_WIN32(e?e:ERROR_NOT_ENOUGH_MEMORY);}HGDIOBJ oldBitmap=SelectObject(dc,bitmap);SetBkMode(dc,TRANSPARENT);SetTextColor(dc,RGB(255,255,255));RECT draw{0,0,static_cast<LONG>(tw),static_cast<LONG>(th)};DrawTextW(dc,item.text.c_str(),static_cast<int>(item.text.size()),&draw,DT_LEFT|DT_TOP|DT_SINGLELINE|DT_NOPREFIX);const BYTE sourceAlpha=static_cast<BYTE>(item.rgba&255);const BYTE sr=static_cast<BYTE>(item.rgba>>24),sg=static_cast<BYTE>(item.rgba>>16),sb=static_cast<BYTE>(item.rgba>>8);const auto* mask=static_cast<const BYTE*>(bits);
        for(UINT y=0;y<th;++y)for(UINT x=0;x<tw;++x){const size_t m=(static_cast<size_t>(y)*tw+x)*4;const BYTE coverage=(std::max)((std::max)(mask[m],mask[m+1]),mask[m+2]);const BYTE sa=static_cast<BYTE>((static_cast<unsigned>(coverage)*sourceAlpha+127)/255);if(!sa)continue;const size_t d=(static_cast<size_t>(item.y+y)*w+static_cast<UINT>(item.x)+x)*4;const unsigned da=rgba[d+3],oa=sa+(da*(255-sa)+127)/255;if(!oa)continue;rgba[d]=static_cast<BYTE>((static_cast<unsigned>(sr)*sa*255+static_cast<unsigned>(rgba[d])*da*(255-sa)+oa*127)/(oa*255));rgba[d+1]=static_cast<BYTE>((static_cast<unsigned>(sg)*sa*255+static_cast<unsigned>(rgba[d+1])*da*(255-sa)+oa*127)/(oa*255));rgba[d+2]=static_cast<BYTE>((static_cast<unsigned>(sb)*sa*255+static_cast<unsigned>(rgba[d+2])*da*(255-sa)+oa*127)/(oa*255));rgba[d+3]=static_cast<BYTE>(oa);}
        SelectObject(dc,oldBitmap);DeleteObject(bitmap);SelectObject(dc,oldFont);DeleteObject(font);DeleteDC(dc);
    }
    ReleaseDC(nullptr,screen);g_uiRgba=std::move(rgba);g_uiCommitted=g_uiItems;g_dynamic.Reset();return S_OK;
}
extern "C" __declspec(dllexport) HRESULT __stdcall RenderOverlay(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Texture2D* target) {
    if (!device || !context || !target) return E_INVALIDARG;
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!g_dynamicMode && g_atlasPath.empty()) return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);
    D3D11_TEXTURE2D_DESC desc{}; target->GetDesc(&desc);
    if (desc.Width != 3840 || desc.Height != 2160 || (desc.Format != DXGI_FORMAT_R8G8B8A8_UNORM && desc.Format != DXGI_FORMAT_R8G8B8A8_TYPELESS) || desc.SampleDesc.Count != 1) return E_INVALIDARG;
    ComPtr<ID3D11Device> contextDevice; context->GetDevice(&contextDevice);
    if (device != contextDevice.Get()) return E_INVALIDARG;
    ComPtr<ID3D11Device> targetDevice; target->GetDevice(&targetDevice); if(device!=targetDevice.Get())return E_INVALIDARG;
    if(g_device.Get()!=device){g_device.Reset();g_atlas.Reset();g_dynamic.Reset();g_vs.Reset();g_ps.Reset();g_sampler.Reset();g_device=device;}
    HRESULT hr = S_OK;
    if (g_dynamicMode) { if(g_device.Get()!=device||!g_dynamic||!g_vs||!g_ps||!g_sampler){g_device=device;hr=BuildTextTexture(device);if(FAILED(hr))return hr;} g_atlas=g_dynamic; }
    else { hr = LoadAtlas(device); if (FAILED(hr)) return hr; }
    ComPtr<ID3D11Device1> device1; ComPtr<ID3D11DeviceContext1> context1;
    hr = device->QueryInterface(IID_PPV_ARGS(&device1)); if (FAILED(hr)) return E_NOINTERFACE;
    hr = context->QueryInterface(IID_PPV_ARGS(&context1)); if (FAILED(hr)) return E_NOINTERFACE;
    D3D11_BLEND_DESC bd{}; bd.RenderTarget[0].BlendEnable = TRUE; bd.RenderTarget[0].SrcBlend = D3D11_BLEND_SRC_ALPHA; bd.RenderTarget[0].DestBlend = D3D11_BLEND_INV_SRC_ALPHA;
    bd.RenderTarget[0].BlendOp = D3D11_BLEND_OP_ADD; bd.RenderTarget[0].SrcBlendAlpha = D3D11_BLEND_ONE; bd.RenderTarget[0].DestBlendAlpha = D3D11_BLEND_INV_SRC_ALPHA;
    bd.RenderTarget[0].BlendOpAlpha = D3D11_BLEND_OP_ADD; bd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    ComPtr<ID3D11BlendState> blend; hr = device->CreateBlendState(&bd, &blend); if (FAILED(hr)) return hr;
    D3D11_RASTERIZER_DESC rd{}; rd.FillMode = D3D11_FILL_SOLID; rd.CullMode = D3D11_CULL_NONE; rd.ScissorEnable = FALSE; rd.DepthClipEnable = TRUE;
    ComPtr<ID3D11RasterizerState> raster; hr = device->CreateRasterizerState(&rd, &raster); if (FAILED(hr)) return hr;
    D3D11_DEPTH_STENCIL_DESC dd{}; dd.DepthEnable = FALSE; dd.StencilEnable = FALSE;
    ComPtr<ID3D11DepthStencilState> depth; hr = device->CreateDepthStencilState(&dd, &depth); if (FAILED(hr)) return hr;
    D3D11_RENDER_TARGET_VIEW_DESC vd{}; vd.Format = DXGI_FORMAT_R8G8B8A8_UNORM; vd.ViewDimension = D3D11_RTV_DIMENSION_TEXTURE2D;
    ComPtr<ID3D11RenderTargetView> rtv; hr = device->CreateRenderTargetView(target, &vd, &rtv); if (FAILED(hr)) return hr;
    ComPtr<ID3DDeviceContextState> saved; D3D_FEATURE_LEVEL chosen{}; const D3D_FEATURE_LEVEL feature = device->GetFeatureLevel();
    hr = device1->CreateDeviceContextState(0, &feature, 1, D3D11_SDK_VERSION, __uuidof(ID3D11Device), &chosen, &saved); if (FAILED(hr)) return hr;
    ComPtr<ID3DDeviceContextState> previous;
    context1->SwapDeviceContextState(saved.Get(), &previous);
    ID3D11RenderTargetView* views[] = { rtv.Get() }; context->OMSetRenderTargets(1, views, nullptr);
    D3D11_VIEWPORT vp{}; vp.Width = static_cast<float>(desc.Width); vp.Height = static_cast<float>(desc.Height); vp.MinDepth = 0; vp.MaxDepth = 1; context->RSSetViewports(1, &vp);
    context->RSSetState(raster.Get()); context->OMSetDepthStencilState(depth.Get(), 0); const float factor[4]{}; context->OMSetBlendState(blend.Get(), factor, 0xffffffff);
    context->IASetInputLayout(nullptr); context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->VSSetShader(g_vs.Get(), nullptr, 0); context->PSSetShader(g_ps.Get(), nullptr, 0);
    ID3D11ShaderResourceView* resources[] = { g_atlas.Get() }; context->PSSetShaderResources(0, 1, resources);
    ID3D11SamplerState* samplers[] = { g_sampler.Get() }; context->PSSetSamplers(0, 1, samplers);
    context->Draw(3, 0);
    ID3D11ShaderResourceView* nullResources[] = { nullptr }; context->PSSetShaderResources(0, 1, nullResources);
    context1->SwapDeviceContextState(previous.Get(), nullptr);
    return S_OK;
}
