// HD texture pages. The engine keeps its 256x256 texture pages in DirectDraw surfaces created by 0x472BC0 (system)
// and 0x472CD0 (device) and fills them in 0x472E70(page, data). UVs are normalized (scale 1/4096 at 0x4EC378), so
// the surfaces can be 1024x1024 as long as the page contents are too. The surface size immediates are patched to
// 0x400 and 0x472E70 is wrapped: the original still does the slot bookkeeping, then the surface is re-locked and
// rewritten from hd-textures/page-NNNN.raw (1024x1024 ARGB1555), or from the 256x256 page replicated 4x when that
// file is missing. Included by runtime.cpp after patch_memory_bytes; not standalone.
#pragma once

static void* (__cdecl* g_page_upload_original)(int, const void*) = nullptr;
static volatile LONG g_hd_pages_done = 0;

// The engine converts ARGB1555 into the surface format with its own scale tables (mirrors 0x472F92 / 0x473028).
static DWORD hd_convert_pixel(unsigned v, int bits) {
    const int mask_r = *reinterpret_cast<int*>(base + 0x8400c0), mask_g = *reinterpret_cast<int*>(base + 0x8400c4);
    const int mask_b = *reinterpret_cast<int*>(base + 0x8400c8);
    const int scale_b = *reinterpret_cast<int*>(base + 0x8400d8), scale_r = *reinterpret_cast<int*>(base + 0x8400e0);
    const int scale_g = *reinterpret_cast<int*>(base + 0x840100);
    const int b = ((v & 0x1f) * scale_b >> 8) & mask_b;
    const int g = ((v & 0x3e0) * scale_g >> 8) & mask_g;
    const int r = ((v & 0x7c00) * scale_r >> 8) & mask_r;
    if (bits == 16) return static_cast<DWORD>(((v >> 15) & 1) << 15) + b + g + r;
    return (v & 0x8000) ? (static_cast<DWORD>(b + g + r) | 0xff000000u) : 0u;
}

static bool hd_native_1555() {
    return *reinterpret_cast<int*>(base + 0x8400c0) == 0x7c00 && *reinterpret_cast<int*>(base + 0x8400c4) == 0x3e0 &&
           *reinterpret_cast<int*>(base + 0x8400c8) == 0x1f && *reinterpret_cast<int*>(base + 0x8400cc) == 0x8000;
}

static bool hd_load_page(int page, const unsigned short* page256, std::vector<unsigned short>& out) {
    out.resize(1024 * 1024);
    wchar_t name[48];
    swprintf_s(name, L"hd-textures\\page-%04d.raw", page);
    const std::wstring path = directory() + name;
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (file != INVALID_HANDLE_VALUE) {
        DWORD got = 0;
        const bool ok = ReadFile(file, out.data(), static_cast<DWORD>(out.size() * 2), &got, nullptr) && got == out.size() * 2;
        CloseHandle(file);
        if (ok) return true;
    }
    if (!page256) return false;
    for (int y = 0; y < 1024; ++y)
        for (int x = 0; x < 1024; ++x) out[static_cast<size_t>(y) * 1024 + x] = page256[(y >> 2) * 256 + (x >> 2)];
    return true;
}

// Plain loops only (no C++ objects) so the fault guard can live next to them and Unlock always runs afterwards.
static bool hd_copy_rows(unsigned char* pixels, LONG pitch, int bits, bool identity, const unsigned short* hd, const DWORD* lut) {
    __try {
        for (int y = 0; y < 1024; ++y) {
            const unsigned short* src = hd + static_cast<size_t>(y) * 1024;
            unsigned char* row = pixels + static_cast<ptrdiff_t>(y) * pitch;
            if (identity) {
                memcpy(row, src, 2048);
            } else if (bits == 16) {
                auto* dst = reinterpret_cast<unsigned short*>(row);
                for (int x = 0; x < 1024; ++x) dst[x] = static_cast<unsigned short>(lut[src[x]]);
            } else {
                auto* dst = reinterpret_cast<DWORD*>(row);
                for (int x = 0; x < 1024; ++x) dst[x] = lut[src[x]];
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
    return true;
}

// COM layout of IDirectDrawSurface7: Lock at vtable +0x64, Unlock at +0x80; ddpfPixelFormat.dwRGBBitCount is desc[21].
static void hd_rewrite_surface(void* surface, int page, const void* data) {
    using LockFn = HRESULT(__stdcall*)(void*, RECT*, void*, DWORD, HANDLE);
    using UnlockFn = HRESULT(__stdcall*)(void*, RECT*);
    const int bits = *reinterpret_cast<int*>(base + 0x8400bc);
    static thread_local std::vector<unsigned short> hd;
    static thread_local std::vector<DWORD> lut;
    static thread_local unsigned lut_key = 0;
    // Everything that allocates happens before Lock so a failure cannot leave the surface locked.
    if ((bits != 16 && bits != 32) || !hd_load_page(page, static_cast<const unsigned short*>(data), hd)) return;
    const bool identity = bits == 16 && hd_native_1555();
    if (!identity) {
        const unsigned key = static_cast<unsigned>(bits) ^ static_cast<unsigned>(*reinterpret_cast<int*>(base + 0x8400c0)) * 31u ^
                             static_cast<unsigned>(*reinterpret_cast<int*>(base + 0x8400d8)) * 131u ^
                             static_cast<unsigned>(*reinterpret_cast<int*>(base + 0x8400e0)) * 313u ^
                             static_cast<unsigned>(*reinterpret_cast<int*>(base + 0x840100)) * 733u;
        if (lut.size() != 65536 || key != lut_key) {
            lut.resize(65536);
            for (unsigned v = 0; v < 65536; ++v) lut[v] = hd_convert_pixel(v, bits);
            lut_key = key;
        }
    }
    auto** vtable = *reinterpret_cast<void***>(surface);
    DWORD desc[31] = {};
    desc[0] = 0x7c;
    if (reinterpret_cast<LockFn>(vtable[0x64 / 4])(surface, nullptr, desc, 0x821, nullptr) != 0) return;
    const LONG pitch = static_cast<LONG>(desc[4]);
    auto* pixels = reinterpret_cast<unsigned char*>(desc[9]);
    const bool fits = desc[2] == 1024 && desc[3] == 1024 && pixels && static_cast<int>(desc[21]) == bits && pitch >= 1024 * bits / 8;
    if (fits && hd_copy_rows(pixels, pitch, bits, identity, hd.data(), lut.empty() ? nullptr : lut.data())) {
        const LONG done = InterlockedIncrement(&g_hd_pages_done);
        if (done <= 40 || done % 25 == 0) {
            char line[96];
            sprintf_s(line, "HD textures: upload #%ld page %d", done, page);
            log_line(line);
        }
    } else if (fits) {
        log_line("HD texture upload faulted; page kept at native detail");
    }
    reinterpret_cast<UnlockFn>(vtable[0x80 / 4])(surface, nullptr);
}

static void hd_rewrite_guarded(void* surface, int page, const void* data) {
    __try {
        hd_rewrite_surface(surface, page, data);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        log_line("HD texture upload faulted before lock; page kept at native detail");
    }
}

static void* __cdecl hd_page_upload(int page, const void* data) {
    void* slot = g_page_upload_original(page, data);
    void* surface = slot ? reinterpret_cast<void**>(slot)[2] : nullptr;
    if (surface) hd_rewrite_guarded(surface, page, data);
    return slot;
}

static bool install_hd_textures_real() {
    if (base != 0x400000) return false;
    const std::wstring probe = directory() + L"hd-textures\\page-0000.raw";
    if (GetFileAttributesW(probe.c_str()) == INVALID_FILE_ATTRIBUTES) return false;
    if (GetFileAttributesW((directory() + L".soul-reaver-ptbr\\disable-hd-textures.flag").c_str()) != INVALID_FILE_ATTRIBUTES) return false;
    auto* upload = reinterpret_cast<unsigned char*>(base + 0x72e70);
    const unsigned char size_expected[] = {0xb8, 0x00, 0x01, 0x00, 0x00}, size_patch[] = {0xb8, 0x00, 0x04, 0x00, 0x00};
    const unsigned char prologue[] = {0x81, 0xec, 0x88, 0x00, 0x00, 0x00};  // 0x472E70: sub esp, 0x88
    if (memcmp(reinterpret_cast<void*>(base + 0x72c21), size_expected, 5) || memcmp(reinterpret_cast<void*>(base + 0x72d31), size_expected, 5) ||
        memcmp(upload, prologue, 6))
        return false;
    auto* trampoline = static_cast<unsigned char*>(VirtualAlloc(nullptr, 11, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!trampoline) return false;
    memcpy(trampoline, prologue, 6);
    trampoline[6] = 0xe9;
    *reinterpret_cast<DWORD*>(trampoline + 7) = reinterpret_cast<DWORD>(upload + 6) - reinterpret_cast<DWORD>(trampoline + 11);
    DWORD old = 0;
    DWORD upload_old = 0;
    if (!VirtualProtect(trampoline, 11, PAGE_EXECUTE_READ, &old) || !VirtualProtect(upload, 6, PAGE_EXECUTE_READWRITE, &upload_old)) {
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }
    g_page_upload_original = reinterpret_cast<void* (__cdecl*)(int, const void*)>(trampoline);
    if (!patch_memory_bytes(base + 0x72c21, size_expected, size_patch, 5)) return false;
    if (!patch_memory_bytes(base + 0x72d31, size_expected, size_patch, 5)) {
        patch_memory_bytes(base + 0x72c21, size_patch, size_expected, 5);
        return false;
    }
    upload[0] = 0xe9;
    *reinterpret_cast<DWORD*>(upload + 1) = reinterpret_cast<DWORD>(&hd_page_upload) - reinterpret_cast<DWORD>(upload + 5);
    upload[5] = 0x90;
    VirtualProtect(upload, 6, upload_old, &upload_old);
    FlushInstructionCache(GetCurrentProcess(), upload, 6);
    return true;
}
