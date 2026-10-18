// In-frame overlay: composes the subtitle/map/settings bitmap onto the game's own back buffer right before Present.
// A separate topmost window depends on z-order, focus and DWM; pixels inside the frame cannot be hidden by any of them.
// The GDI+ side publishes a premultiplied BGRA bitmap; the Present hook (frame_capture.h) draws it with a tiny shader
// through a deferred context, so the game's own pipeline state is restored untouched. Any failure disables this path
// and the layered window takes over again. Included by runtime.cpp before the overlay code; not standalone.
#pragma once

#include <d3d11.h>
#include <dxgi.h>

namespace frame_overlay {

static SRWLOCK g_lock = SRWLOCK_INIT;
static std::vector<unsigned char> g_pixels;
static int g_w = 0, g_h = 0;
static float g_ratio = 1.0f;  // bitmap height / game window height: the bitmap is the bottom strip or the whole frame
static unsigned g_gen = 0;
static bool g_active = false;
static std::atomic<bool> g_ready{false};
static std::atomic<bool> g_failed{false};
static std::atomic<ULONGLONG> g_last_present{0};
static int g_faults = 0;

// The window path stands in whenever the game is not presenting through this swap chain (loading, some videos).
static bool ready() {
    return g_ready.load() && !g_failed.load() && GetTickCount64() - g_last_present.load() < 400;
}

static void publish(const void* bits, int w, int h, float ratio) {
    AcquireSRWLockExclusive(&g_lock);
    g_pixels.resize(static_cast<size_t>(w) * h * 4);
    memcpy(g_pixels.data(), bits, g_pixels.size());
    g_w = w;
    g_h = h;
    g_ratio = ratio;
    g_active = true;
    ++g_gen;
    ReleaseSRWLockExclusive(&g_lock);
}

static void clear() {
    AcquireSRWLockExclusive(&g_lock);
    g_active = false;
    ReleaseSRWLockExclusive(&g_lock);
}

struct Gpu {
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* deferred = nullptr;
    ID3D11VertexShader* vs = nullptr;
    ID3D11PixelShader* ps = nullptr;
    ID3D11SamplerState* sampler = nullptr;
    ID3D11BlendState* blend = nullptr;
    ID3D11RasterizerState* raster = nullptr;
    ID3D11Texture2D* texture = nullptr;
    ID3D11ShaderResourceView* srv = nullptr;
    int tex_w = 0, tex_h = 0;
    unsigned uploaded_gen = 0;
};
static Gpu gpu;

template <class T>
static void release(T*& p) {
    if (p) p->Release();
    p = nullptr;
}

static void release_texture() {
    release(gpu.srv);
    release(gpu.texture);
    gpu.tex_w = gpu.tex_h = 0;
    gpu.uploaded_gen = 0;
}

static void release_all() {
    release_texture();
    release(gpu.raster);
    release(gpu.blend);
    release(gpu.sampler);
    release(gpu.ps);
    release(gpu.vs);
    release(gpu.deferred);
    release(gpu.device);
}

static const char kShader[] =
    "struct V { float4 p : SV_Position; float2 uv : TEXCOORD0; };\n"
    "V vs(uint id : SV_VertexID) { V o; float2 uv = float2((id << 1) & 2, id & 2); o.uv = uv;\n"
    "  o.p = float4(uv * float2(2, -2) + float2(-1, 1), 0, 1); return o; }\n"
    "Texture2D t : register(t0); SamplerState s : register(s0);\n"
    "float4 ps(V i) : SV_Target { return t.Sample(s, i.uv); }\n";

static ID3DBlob* compile(const char* entry, const char* profile) {
    using CompileFn = HRESULT(WINAPI*)(LPCVOID, SIZE_T, LPCSTR, const D3D_SHADER_MACRO*, ID3DInclude*, LPCSTR, LPCSTR, UINT, UINT,
                                       ID3DBlob**, ID3DBlob**);
    static CompileFn fn = nullptr;
    if (!fn) {
        HMODULE module = LoadLibraryW(L"d3dcompiler_47.dll");
        if (module) fn = reinterpret_cast<CompileFn>(GetProcAddress(module, "D3DCompile"));
    }
    if (!fn) return nullptr;
    ID3DBlob* code = nullptr;
    ID3DBlob* errors = nullptr;
    const HRESULT hr = fn(kShader, sizeof(kShader) - 1, nullptr, nullptr, nullptr, entry, profile, 0, 0, &code, &errors);
    release(errors);
    if (FAILED(hr)) release(code);
    return code;
}

static bool init(ID3D11Device* device) {
    gpu.device = device;
    device->AddRef();
    ID3DBlob* vs_code = compile("vs", "vs_4_0");
    ID3DBlob* ps_code = compile("ps", "ps_4_0");
    bool ok = vs_code && ps_code &&
              SUCCEEDED(device->CreateVertexShader(vs_code->GetBufferPointer(), vs_code->GetBufferSize(), nullptr, &gpu.vs)) &&
              SUCCEEDED(device->CreatePixelShader(ps_code->GetBufferPointer(), ps_code->GetBufferSize(), nullptr, &gpu.ps));
    release(vs_code);
    release(ps_code);
    if (!ok) return false;
    D3D11_SAMPLER_DESC sampler{};
    sampler.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    D3D11_BLEND_DESC blend{};
    blend.RenderTarget[0].BlendEnable = TRUE;
    blend.RenderTarget[0].SrcBlend = D3D11_BLEND_ONE;  // the bitmap is premultiplied
    blend.RenderTarget[0].DestBlend = D3D11_BLEND_INV_SRC_ALPHA;
    blend.RenderTarget[0].BlendOp = D3D11_BLEND_OP_ADD;
    blend.RenderTarget[0].SrcBlendAlpha = D3D11_BLEND_ONE;
    blend.RenderTarget[0].DestBlendAlpha = D3D11_BLEND_INV_SRC_ALPHA;
    blend.RenderTarget[0].BlendOpAlpha = D3D11_BLEND_OP_ADD;
    blend.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    D3D11_RASTERIZER_DESC raster{};
    raster.FillMode = D3D11_FILL_SOLID;
    raster.CullMode = D3D11_CULL_NONE;
    raster.DepthClipEnable = TRUE;
    return SUCCEEDED(device->CreateSamplerState(&sampler, &gpu.sampler)) && SUCCEEDED(device->CreateBlendState(&blend, &gpu.blend)) &&
           SUCCEEDED(device->CreateRasterizerState(&raster, &gpu.raster)) && SUCCEEDED(device->CreateDeferredContext(0, &gpu.deferred));
}

// Caller holds g_lock; uploads only when the published bitmap changed.
static bool upload(ID3D11DeviceContext* immediate) {
    if (gpu.uploaded_gen == g_gen && gpu.texture) return true;
    if (!gpu.texture || gpu.tex_w != g_w || gpu.tex_h != g_h) {
        release_texture();
        D3D11_TEXTURE2D_DESC desc{};
        desc.Width = static_cast<UINT>(g_w);
        desc.Height = static_cast<UINT>(g_h);
        desc.MipLevels = desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DYNAMIC;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        if (FAILED(gpu.device->CreateTexture2D(&desc, nullptr, &gpu.texture)) ||
            FAILED(gpu.device->CreateShaderResourceView(gpu.texture, nullptr, &gpu.srv)))
            return false;
        gpu.tex_w = g_w;
        gpu.tex_h = g_h;
    }
    D3D11_MAPPED_SUBRESOURCE mapped{};
    if (FAILED(immediate->Map(gpu.texture, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped))) return false;
    const size_t row = static_cast<size_t>(g_w) * 4;
    for (int y = 0; y < g_h; ++y)
        memcpy(static_cast<unsigned char*>(mapped.pData) + static_cast<size_t>(y) * mapped.RowPitch, g_pixels.data() + y * row, row);
    immediate->Unmap(gpu.texture, 0);
    gpu.uploaded_gen = g_gen;
    return true;
}

// Raw pointers only, so the SEH guard in draw_guarded stays legal.
static bool draw(IDXGISwapChain* swap_chain) {
    ID3D11Texture2D* back = nullptr;
    if (FAILED(swap_chain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&back))) || !back) return false;
    ID3D11Device* device = nullptr;
    back->GetDevice(&device);
    bool ok = device != nullptr;
    if (ok && gpu.device != device) {
        release_all();
        ok = init(device);
        if (!ok) {
            release_all();
            g_failed = true;
            log_line("In-frame overlay unavailable (shader or state creation failed); layered window fallback active");
        }
    }
    ID3D11DeviceContext* immediate = nullptr;
    if (ok) device->GetImmediateContext(&immediate);
    D3D11_TEXTURE2D_DESC bd{};
    back->GetDesc(&bd);
    if (ok && immediate) {
        g_ready = true;
        g_last_present = GetTickCount64();
        AcquireSRWLockExclusive(&g_lock);
        const bool drawable = g_active && g_w > 0 && g_h > 0 && bd.SampleDesc.Count == 1 && upload(immediate);
        const float ratio = g_ratio;
        ReleaseSRWLockExclusive(&g_lock);
        if (drawable) {
            ID3D11RenderTargetView* rtv = nullptr;
            ok = SUCCEEDED(device->CreateRenderTargetView(back, nullptr, &rtv)) && rtv;
            if (ok) {
                const float height = bd.Height * ratio;
                const D3D11_VIEWPORT viewport = {0.0f, bd.Height - height, static_cast<float>(bd.Width), height, 0.0f, 1.0f};
                ID3D11DeviceContext* dc = gpu.deferred;
                dc->OMSetRenderTargets(1, &rtv, nullptr);
                dc->RSSetViewports(1, &viewport);
                dc->RSSetState(gpu.raster);
                dc->OMSetBlendState(gpu.blend, nullptr, 0xffffffffu);
                dc->IASetInputLayout(nullptr);
                dc->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
                dc->VSSetShader(gpu.vs, nullptr, 0);
                dc->PSSetShader(gpu.ps, nullptr, 0);
                dc->PSSetShaderResources(0, 1, &gpu.srv);
                dc->PSSetSamplers(0, 1, &gpu.sampler);
                dc->Draw(3, 0);
                ID3D11CommandList* list = nullptr;
                if (SUCCEEDED(dc->FinishCommandList(FALSE, &list)) && list) {
                    immediate->ExecuteCommandList(list, TRUE);  // TRUE restores the game's pipeline state
                    list->Release();
                } else {
                    ok = false;
                }
            }
            release(rtv);
        }
    }
    release(immediate);
    release(device);
    back->Release();
    return ok;
}

static bool draw_guarded(IDXGISwapChain* swap_chain) {
    __try {
        return draw(swap_chain);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

static void on_present(IDXGISwapChain* swap_chain) {
    if (g_failed.load()) return;
    if (draw_guarded(swap_chain)) return;
    if (++g_faults >= 3) {
        g_failed = true;
        log_line("In-frame overlay disabled after repeated failures; layered window fallback active");
    }
}

}  // namespace frame_overlay
