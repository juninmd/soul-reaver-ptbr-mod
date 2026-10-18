// Present hook shared by the in-frame overlay (frame_overlay.h, always on) and a dev aid that dumps the game's own back
// buffer to .soul-reaver-ptbr/frame-NNN.bmp when .soul-reaver-ptbr/capture-frame.flag exists (needs capture-enabled.flag). Screen capture (BitBlt, PrintWindow, Desktop Duplication) never sees the game window on the test machine, so the
// frame is read where dgVoodoo2 presents it: IDXGISwapChain::Present (and Present1) share one vtable per DXGI class, so a
// throw-away swap chain gives the slot to patch. The overlay is a separate window and is not part of this image.
// Included by runtime.cpp after startup_profiler.h; not standalone.
#pragma once

#include <d3d11.h>
#include <dxgi1_2.h>

static HRESULT(STDMETHODCALLTYPE* g_present_original)(IDXGISwapChain*, UINT, UINT) = nullptr;
static HRESULT(STDMETHODCALLTYPE* g_present1_original)(IDXGISwapChain1*, UINT, UINT, const DXGI_PRESENT_PARAMETERS*) = nullptr;

// Raw pointers and no C++ objects here so the SEH guard in capture_back_buffer_guarded is legal.
static bool write_back_buffer_bmp(IDXGISwapChain* swap_chain, const wchar_t* path) {
    ID3D11Texture2D* back = nullptr;
    if (FAILED(swap_chain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&back))) || !back) return false;
    ID3D11Device* device = nullptr;
    back->GetDevice(&device);
    ID3D11DeviceContext* context = nullptr;
    if (device) device->GetImmediateContext(&context);
    D3D11_TEXTURE2D_DESC desc{};
    back->GetDesc(&desc);
    bool ok = false;
    const bool rgba = desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM || desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
    const bool bgra = desc.Format == DXGI_FORMAT_B8G8R8A8_UNORM || desc.Format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
    if (context && desc.SampleDesc.Count == 1 && (rgba || bgra)) {
        D3D11_TEXTURE2D_DESC staging_desc = desc;
        staging_desc.Usage = D3D11_USAGE_STAGING;
        staging_desc.BindFlags = 0;
        staging_desc.MiscFlags = 0;
        staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ID3D11Texture2D* staging = nullptr;
        if (SUCCEEDED(device->CreateTexture2D(&staging_desc, nullptr, &staging)) && staging) {
            context->CopyResource(staging, back);
            D3D11_MAPPED_SUBRESOURCE mapped{};
            if (SUCCEEDED(context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped))) {
                FILE* file = nullptr;
                if (_wfopen_s(&file, path, L"wb") == 0 && file) {
                    BITMAPFILEHEADER file_header{};
                    BITMAPINFOHEADER info{};
                    file_header.bfType = 0x4d42;
                    file_header.bfOffBits = sizeof(file_header) + sizeof(info);
                    file_header.bfSize = file_header.bfOffBits + desc.Width * desc.Height * 4;
                    info.biSize = sizeof(info);
                    info.biWidth = static_cast<LONG>(desc.Width);
                    info.biHeight = -static_cast<LONG>(desc.Height);
                    info.biPlanes = 1;
                    info.biBitCount = 32;
                    fwrite(&file_header, sizeof(file_header), 1, file);
                    fwrite(&info, sizeof(info), 1, file);
                    static thread_local unsigned char* row = nullptr;
                    if (!row) row = static_cast<unsigned char*>(malloc(16384 * 4));
                    for (UINT y = 0; y < desc.Height && row && desc.Width <= 16384; ++y) {
                        const unsigned char* src = static_cast<const unsigned char*>(mapped.pData) + static_cast<size_t>(y) * mapped.RowPitch;
                        for (UINT x = 0; x < desc.Width; ++x) {
                            row[x * 4 + 0] = rgba ? src[x * 4 + 2] : src[x * 4 + 0];
                            row[x * 4 + 1] = src[x * 4 + 1];
                            row[x * 4 + 2] = rgba ? src[x * 4 + 0] : src[x * 4 + 2];
                            row[x * 4 + 3] = 255;
                        }
                        fwrite(row, 4, desc.Width, file);
                    }
                    fclose(file);
                    ok = true;
                }
                context->Unmap(staging, 0);
            }
            staging->Release();
        }
    }
    if (context) context->Release();
    if (device) device->Release();
    back->Release();
    return ok;
}

static bool capture_back_buffer_guarded(IDXGISwapChain* swap_chain, const wchar_t* path) {
    __try {
        return write_back_buffer_bmp(swap_chain, path);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

static bool g_capture_enabled = false;

static void maybe_capture_frame(IDXGISwapChain* swap_chain) {
    if (!g_capture_enabled) return;
    static unsigned s_calls = 0;
    static int s_index = 0;
    if (++s_calls % 20) return;
    const std::wstring flag = directory() + L".soul-reaver-ptbr\\capture-frame.flag";
    if (GetFileAttributesW(flag.c_str()) == INVALID_FILE_ATTRIBUTES) return;
    DeleteFileW(flag.c_str());
    wchar_t name[64];
    swprintf_s(name, L".soul-reaver-ptbr\\frame-%03d.bmp", s_index++);
    const bool ok = capture_back_buffer_guarded(swap_chain, (directory() + name).c_str());
    char line[96];
    sprintf_s(line, "Frame capture %s", ok ? "saved" : "failed (unsupported back buffer)");
    log_line(line);
}

static HRESULT STDMETHODCALLTYPE present_hook(IDXGISwapChain* swap_chain, UINT sync, UINT flags) {
    frame_overlay::on_present(swap_chain);
    maybe_capture_frame(swap_chain);
    return g_present_original(swap_chain, sync, flags);
}

static HRESULT STDMETHODCALLTYPE present1_hook(IDXGISwapChain1* swap_chain, UINT sync, UINT flags, const DXGI_PRESENT_PARAMETERS* params) {
    frame_overlay::on_present(swap_chain);
    maybe_capture_frame(swap_chain);
    return g_present1_original(swap_chain, sync, flags, params);
}

static bool patch_vtable_slot(void** vtable, size_t index, void* replacement, void** original) {
    DWORD old = 0;
    if (!VirtualProtect(&vtable[index], sizeof(void*), PAGE_READWRITE, &old)) return false;
    *original = vtable[index];
    vtable[index] = replacement;
    VirtualProtect(&vtable[index], sizeof(void*), old, &old);
    return true;
}

static DWORD WINAPI frame_capture_installer(LPVOID) {
    Sleep(300);  // stay out of the loader lock held while DllMain runs
    HWND window = CreateWindowExW(0, L"STATIC", L"sr-capture-probe", WS_POPUP, 0, 0, 64, 64, nullptr, nullptr, nullptr, nullptr);
    DXGI_SWAP_CHAIN_DESC desc{};
    desc.BufferCount = 1;
    desc.BufferDesc.Width = 64;
    desc.BufferDesc.Height = 64;
    desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.OutputWindow = window;
    desc.SampleDesc.Count = 1;
    desc.Windowed = TRUE;
    desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    IDXGISwapChain* swap_chain = nullptr;
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    const HRESULT hr = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION,
                                                     &desc, &swap_chain, &device, nullptr, &context);
    if (SUCCEEDED(hr) && swap_chain) {
        auto** vtable = *reinterpret_cast<void***>(swap_chain);
        const bool a = patch_vtable_slot(vtable, 8, reinterpret_cast<void*>(&present_hook), reinterpret_cast<void**>(&g_present_original));
        bool b = false;
        IDXGISwapChain1* chain1 = nullptr;
        if (SUCCEEDED(swap_chain->QueryInterface(__uuidof(IDXGISwapChain1), reinterpret_cast<void**>(&chain1))) && chain1) {
            auto** vtable1 = *reinterpret_cast<void***>(chain1);
            if (vtable1 != vtable) b = patch_vtable_slot(vtable1, 22, reinterpret_cast<void*>(&present1_hook), reinterpret_cast<void**>(&g_present1_original));
            chain1->Release();
        }
        char line[96];
        sprintf_s(line, "Frame capture hook installed (Present=%d Present1=%d)", a ? 1 : 0, b ? 1 : 0);
        log_line(line);
    } else {
        log_line("Frame capture hook: probe swap chain failed");
    }
    if (swap_chain) swap_chain->Release();
    if (context) context->Release();
    if (device) device->Release();
    if (window) DestroyWindow(window);
    return 0;
}

static void start_frame_capture() {
    g_capture_enabled = GetFileAttributesW((directory() + L".soul-reaver-ptbr\\capture-enabled.flag").c_str()) != INVALID_FILE_ATTRIBUTES;
    if (GetFileAttributesW((directory() + L".soul-reaver-ptbr\\disable-frame-overlay.flag").c_str()) != INVALID_FILE_ATTRIBUTES) {
        if (!g_capture_enabled) return;
        frame_overlay::g_failed = true;
    }
    if (HANDLE thread = CreateThread(nullptr, 0, frame_capture_installer, nullptr, 0, nullptr)) CloseHandle(thread);
}
