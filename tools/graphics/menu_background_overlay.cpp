#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11_1.h>
#include <d3dcompiler.h>
#include <wincodec.h>
#include <wrl/client.h>
#include <array>
#include <cstdint>
#include <limits>
#include <mutex>
#include <vector>
#undef max

using Microsoft::WRL::ComPtr;
namespace {
constexpr UINT kMaxDimension = 8192;
constexpr size_t kMaxDecodedBytes = 256u * 1024u * 1024u;
struct Image { UINT width=0, height=0; std::vector<BYTE> rgba; };
std::mutex g_mutex;
std::array<Image,2> g_images;
ComPtr<ID3D11Device> g_device;
std::array<ComPtr<ID3D11ShaderResourceView>,2> g_views;
ComPtr<ID3D11VertexShader> g_vs;
ComPtr<ID3D11PixelShader> g_ps;
ComPtr<ID3D11SamplerState> g_sampler;

HRESULT Decode(const wchar_t* path, Image& out) {
    if(!path || !*path) return E_INVALIDARG;
    LARGE_INTEGER fileSize{}; HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE) return HRESULT_FROM_WIN32(GetLastError());
    const BOOL sizeOk=GetFileSizeEx(file,&fileSize); const DWORD sizeErr=GetLastError(); CloseHandle(file);
    if(!sizeOk) return HRESULT_FROM_WIN32(sizeErr);
    if(fileSize.QuadPart<=0 || fileSize.QuadPart>64ll*1024*1024) return HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);
    HRESULT com=CoInitializeEx(nullptr,COINIT_MULTITHREADED); const bool owns=SUCCEEDED(com);
    if(FAILED(com) && com!=RPC_E_CHANGED_MODE) return com;
    struct Uninit { bool owns; ~Uninit(){if(owns)CoUninitialize();} } uninit{owns};
    ComPtr<IWICImagingFactory> factory; HRESULT hr=CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&factory)); if(FAILED(hr)) return hr;
    ComPtr<IWICBitmapDecoder> decoder; hr=factory->CreateDecoderFromFilename(path,nullptr,GENERIC_READ,WICDecodeMetadataCacheOnLoad,&decoder); if(FAILED(hr)) return hr;
    ComPtr<IWICBitmapFrameDecode> frame; hr=decoder->GetFrame(0,&frame); if(FAILED(hr)) return hr;
    UINT w=0,h=0; hr=frame->GetSize(&w,&h); if(FAILED(hr)) return hr;
    if(!w||!h||w>kMaxDimension||h>kMaxDimension || static_cast<uint64_t>(w)*3!=static_cast<uint64_t>(h)*4) return HRESULT_FROM_WIN32(ERROR_BAD_FORMAT);
    const uint64_t byteCount=static_cast<uint64_t>(w)*h*4; if(byteCount>kMaxDecodedBytes || byteCount>std::numeric_limits<UINT>::max()) return HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);
    ComPtr<IWICFormatConverter> converter; hr=factory->CreateFormatConverter(&converter); if(FAILED(hr)) return hr;
    hr=converter->Initialize(frame.Get(),GUID_WICPixelFormat32bppRGBA,WICBitmapDitherTypeNone,nullptr,0,WICBitmapPaletteTypeCustom); if(FAILED(hr)) return hr;
    Image image; image.width=w; image.height=h; image.rgba.resize(static_cast<size_t>(byteCount));
    hr=converter->CopyPixels(nullptr,w*4,static_cast<UINT>(byteCount),image.rgba.data()); if(FAILED(hr)) return hr;
    for(size_t i=3;i<image.rgba.size();i+=4) if(image.rgba[i]!=255) return HRESULT_FROM_WIN32(ERROR_BAD_FORMAT);
    out=std::move(image); return S_OK;
}
void ResetDevice() { for(auto& view:g_views)view.Reset(); g_vs.Reset();g_ps.Reset();g_sampler.Reset();g_device.Reset(); }
HRESULT EnsureDeviceResources(ID3D11Device* device) {
    if(g_device.Get()==device && g_views[0] && g_views[1] && g_vs && g_ps && g_sampler) return S_OK;
    ResetDevice(); g_device=device;
    for(size_t i=0;i<g_images.size();++i) {
        const auto& image=g_images[i]; if(image.rgba.empty()) return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);
        D3D11_TEXTURE2D_DESC td{};td.Width=image.width;td.Height=image.height;td.MipLevels=1;td.ArraySize=1;td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;td.SampleDesc.Count=1;td.Usage=D3D11_USAGE_IMMUTABLE;td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA data{};data.pSysMem=image.rgba.data();data.SysMemPitch=image.width*4;
        ComPtr<ID3D11Texture2D> texture; HRESULT hr=device->CreateTexture2D(&td,&data,&texture);if(FAILED(hr))return hr;
        hr=device->CreateShaderResourceView(texture.Get(),nullptr,&g_views[i]);if(FAILED(hr))return hr;
    }
    static constexpr char shader[]="Texture2D t:register(t0);SamplerState s:register(s0);struct V{float4 p:SV_Position;float2 u:TEXCOORD0;};V vs(uint id:SV_VertexID){V o;float2 p=id==0?float2(-1,-1):(id==1?float2(-1,3):float2(3,-1));o.p=float4(p,0,1);o.u=float2((p.x+1)*.5,1-(p.y+1)*.5);return o;}float4 ps(V i):SV_Target{return t.Sample(s,i.u);} ";
    ComPtr<ID3DBlob> vs,ps,errors;HRESULT hr=D3DCompile(shader,sizeof(shader)-1,"menu_background",nullptr,nullptr,"vs","vs_4_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&vs,&errors);if(FAILED(hr))return hr;
    hr=D3DCompile(shader,sizeof(shader)-1,"menu_background",nullptr,nullptr,"ps","ps_4_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&ps,&errors);if(FAILED(hr))return hr;
    hr=device->CreateVertexShader(vs->GetBufferPointer(),vs->GetBufferSize(),nullptr,&g_vs);if(FAILED(hr))return hr;
    hr=device->CreatePixelShader(ps->GetBufferPointer(),ps->GetBufferSize(),nullptr,&g_ps);if(FAILED(hr))return hr;
    D3D11_SAMPLER_DESC sd{};sd.Filter=D3D11_FILTER_MIN_MAG_MIP_LINEAR;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;
    return device->CreateSamplerState(&sd,&g_sampler);
}
}

extern "C" __declspec(dllexport) HRESULT __stdcall InitializeMenuBackgrounds(const wchar_t* titlePng,const wchar_t* selectionPng) {
    Image title,selection; HRESULT hr=Decode(titlePng,title);if(FAILED(hr))return hr;hr=Decode(selectionPng,selection);if(FAILED(hr))return hr;
    std::lock_guard<std::mutex> lock(g_mutex);ResetDevice();g_images[0]=std::move(title);g_images[1]=std::move(selection);return S_OK;
}
extern "C" __declspec(dllexport) HRESULT __stdcall RenderMenuBackground(ID3D11Device* device,ID3D11DeviceContext* context,ID3D11RenderTargetView* target,UINT which) {
    if(!device||!context||!target||which>1)return E_INVALIDARG;
    if(context->GetType()!=D3D11_DEVICE_CONTEXT_IMMEDIATE)return E_INVALIDARG;
    ComPtr<ID3D11Device> contextDevice;context->GetDevice(&contextDevice);if(contextDevice.Get()!=device)return E_INVALIDARG;
    ComPtr<ID3D11Device> targetDevice;target->GetDevice(&targetDevice);if(targetDevice.Get()!=device)return E_INVALIDARG;
    D3D11_RENDER_TARGET_VIEW_DESC viewDesc{};target->GetDesc(&viewDesc);if(viewDesc.ViewDimension!=D3D11_RTV_DIMENSION_TEXTURE2D)return E_INVALIDARG;
    ComPtr<ID3D11Resource> resource;target->GetResource(&resource);ComPtr<ID3D11Texture2D> texture;if(FAILED(resource.As(&texture)))return E_INVALIDARG;
    auto is_supported_fmt = [](DXGI_FORMAT f) {
        return f == DXGI_FORMAT_R8G8B8A8_UNORM || f == DXGI_FORMAT_B8G8R8A8_UNORM ||
               f == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB || f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
               f == DXGI_FORMAT_R8G8B8A8_TYPELESS || f == DXGI_FORMAT_UNKNOWN;
    };
    D3D11_TEXTURE2D_DESC td{};texture->GetDesc(&td);if(td.SampleDesc.Count!=1||td.Width==0||td.Height==0||!is_supported_fmt(viewDesc.Format))return E_INVALIDARG;
    std::lock_guard<std::mutex> lock(g_mutex);if(g_images[0].rgba.empty()||g_images[1].rgba.empty())return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);
    HRESULT hr=EnsureDeviceResources(device);if(FAILED(hr))return hr;
    ComPtr<ID3D11Device1> device1;ComPtr<ID3D11DeviceContext1> context1;
    ComPtr<ID3DDeviceContextState> saved;ComPtr<ID3DDeviceContextState> previous;
    bool usedContextState = false;
    if(SUCCEEDED(device->QueryInterface(IID_PPV_ARGS(&device1))) && SUCCEEDED(context->QueryInterface(IID_PPV_ARGS(&context1)))) {
        const D3D_FEATURE_LEVEL feature=device->GetFeatureLevel();D3D_FEATURE_LEVEL chosen{};
        if(SUCCEEDED(device1->CreateDeviceContextState(0,&feature,1,D3D11_SDK_VERSION,__uuidof(ID3D11Device),&chosen,&saved))) {
            context1->SwapDeviceContextState(saved.Get(),&previous);
            usedContextState = true;
        }
    }
    ComPtr<ID3D11RenderTargetView> oldRtv; ComPtr<ID3D11DepthStencilView> oldDsv;
    D3D11_VIEWPORT oldVp{}; UINT numVp = 1;
    if(!usedContextState) { context->OMGetRenderTargets(1,&oldRtv,&oldDsv); context->RSGetViewports(&numVp,&oldVp); }
    struct Cleanup {
        bool used; ID3D11DeviceContext1* ctx1; ComPtr<ID3DDeviceContextState> prev;
        ID3D11DeviceContext* ctx; ComPtr<ID3D11RenderTargetView> rtv; ComPtr<ID3D11DepthStencilView> dsv; D3D11_VIEWPORT vp; UINT nvp;
        ~Cleanup() {
            if(used && ctx1) ctx1->SwapDeviceContextState(prev.Get(),nullptr);
            else if(!used && ctx) { ID3D11RenderTargetView* r=rtv.Get(); ctx->OMSetRenderTargets(1,&r,dsv.Get()); if(nvp>0) ctx->RSSetViewports(nvp,&vp); }
        }
    } cleanup{usedContextState,context1.Get(),std::move(previous),context,oldRtv,oldDsv,oldVp,numVp};
    const float targetAspect=static_cast<float>(td.Width)/static_cast<float>(td.Height);D3D11_VIEWPORT vp{};
    if(targetAspect>4.0f/3.0f){vp.Height=static_cast<float>(td.Height);vp.Width=vp.Height*(4.0f/3.0f);vp.TopLeftX=(static_cast<float>(td.Width)-vp.Width)*.5f;}
    else {vp.Width=static_cast<float>(td.Width);vp.Height=vp.Width*(3.0f/4.0f);vp.TopLeftY=(static_cast<float>(td.Height)-vp.Height)*.5f;}
    vp.MinDepth=0;vp.MaxDepth=1;context->OMSetRenderTargets(1,&target,nullptr);context->RSSetViewports(1,&vp);
    context->IASetInputLayout(nullptr);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);context->VSSetShader(g_vs.Get(),nullptr,0);context->PSSetShader(g_ps.Get(),nullptr,0);
    ID3D11ShaderResourceView* srv=g_views[which].Get();context->PSSetShaderResources(0,1,&srv);ID3D11SamplerState* sampler=g_sampler.Get();context->PSSetSamplers(0,1,&sampler);context->Draw(3,0);
    return S_OK;
}
extern "C" __declspec(dllexport) void __stdcall ReleaseMenuBackgrounds() { std::lock_guard<std::mutex> lock(g_mutex);ResetDevice();g_images={}; }
