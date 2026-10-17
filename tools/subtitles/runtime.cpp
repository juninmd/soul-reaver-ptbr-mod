// Experimental subtitles for the hash-verified classic PC executable.
// Build only for x86. Install into an isolated game copy; never replace another proxy.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define INITGUID
#define DIRECTINPUT_VERSION 0x0500
#include <windows.h>
#include <dinput.h>
#include <mmsystem.h>
#include <bcrypt.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

static_assert(sizeof(void*) == 4, "The classic game requires an x86 proxy");
static HMODULE self_module;
static INIT_ONCE once = INIT_ONCE_STATIC_INIT;
using InputCreate = HRESULT(WINAPI*)(HINSTANCE, DWORD, LPDIRECTINPUTA*, LPUNKNOWN);
static InputCreate real_create;
static std::array<std::string, 479> captions;
static std::array<ULONGLONG, 479> durations{};
static void (__cdecl* original_flush)();
static int (__cdecl* string_width)(const char*);
static void (__cdecl* print_text)(const char*, ...);
static int (__cdecl* is_playing)(int);
static DWORD base;

static std::wstring directory() {
    wchar_t name[32768];
    DWORD size = GetModuleFileNameW(self_module, name, ARRAYSIZE(name));
    if (!size || size >= ARRAYSIZE(name)) return {};
    std::wstring result(name, size);
    return result.substr(0, result.find_last_of(L"\\/") + 1);
}

static void log_line(const char* text) {
    const auto name = directory() + L".soul-reaver-ptbr\\subtitles-runtime.log";
    HANDLE file = CreateFileW(name.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD written;
    WriteFile(file, text, static_cast<DWORD>(strlen(text)), &written, nullptr);
    WriteFile(file, "\r\n", 2, &written, nullptr);
    CloseHandle(file);
}

static bool read_file(const std::wstring& path, std::vector<unsigned char>& bytes, DWORD limit) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
                              OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER length;
    bool ok = GetFileSizeEx(file, &length) && length.QuadPart > 0 && length.QuadPart <= limit;
    if (ok) {
        bytes.resize(static_cast<size_t>(length.QuadPart));
        DWORD count;
        ok = ReadFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &count, nullptr)
             && count == bytes.size();
    }
    CloseHandle(file);
    return ok;
}

static bool verified_executable() {
    wchar_t path[32768];
    DWORD count = GetModuleFileNameW(nullptr, path, ARRAYSIZE(path));
    if (!count || count >= ARRAYSIZE(path)) return false;
    std::vector<unsigned char> bytes;
    if (!read_file(path, bytes, 8 * 1024 * 1024)) return false;
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    unsigned char hash[32];
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0) return false;
    NTSTATUS result = BCryptHash(algorithm, nullptr, 0, bytes.data(),
                                 static_cast<ULONG>(bytes.size()), hash, sizeof(hash));
    BCryptCloseAlgorithmProvider(algorithm, 0);
    if (result < 0) return false;
    char hex[65];
    for (int i = 0; i < 32; ++i) sprintf_s(hex + i * 2, sizeof(hex) - i * 2, "%02x", hash[i]);
    return strcmp(hex, "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a") == 0
        || strcmp(hex, "396a757334daa8fdf8930de70a63929bbe0cb0d6bc3250ce5a2dd50056c1e243") == 0;
}

static bool load_captions() {
    std::vector<unsigned char> bytes;
    if (!read_file(directory() + L".soul-reaver-ptbr\\subtitles.tsv", bytes, 256 * 1024)) return false;
    std::string data(bytes.begin(), bytes.end());
    size_t begin = 0;
    std::array<bool, 479> seen{};
    while (begin < data.size()) {
        size_t end = data.find('\n', begin);
        if (end == std::string::npos) end = data.size();
        std::string line = data.substr(begin, end - begin);
        if (!line.empty() && line.back() == '\r') line.pop_back();
        size_t tab = line.find('\t');
        if (tab == std::string::npos || tab == 0 || tab > 3) return false;
        int id = 0;
        for (size_t i = 0; i < tab; ++i) {
            if (line[i] < '0' || line[i] > '9') return false;
            id = id * 10 + line[i] - '0';
        }
        if (id >= 479 || seen[id] || line.size() - tab < 2 || line.size() - tab > 4096) return false;
        size_t text_start = tab + 1;
        size_t timing = line.find('\t', text_start);
        if (timing != std::string::npos) {
            if (timing == text_start || timing - text_start > 6) return false;
            ULONGLONG milliseconds = 0;
            for (size_t i = text_start; i < timing; ++i) {
                if (line[i] < '0' || line[i] > '9') return false;
                milliseconds = milliseconds * 10 + line[i] - '0';
            }
            if (milliseconds < 100 || milliseconds > 60000) return false;
            durations[id] = milliseconds;
            text_start = timing + 1;
        }
        for (size_t i = text_start; i < line.size(); ++i)
            if (line[i] < 32 || line[i] > 126 || line[i] == '@') return false;
        if (line.find_first_not_of(' ', text_start) == std::string::npos) return false;
        captions[id] = line.substr(text_start);
        seen[id] = true;
        begin = end + 1;
    }
    return std::any_of(seen.begin(), seen.end(), [](bool value) { return value; });
}

static std::vector<std::string> wrap(const std::string& text) {
    std::vector<std::string> result;
    std::string line;
    size_t position = 0;
    while (position < text.size()) {
        size_t end = text.find(' ', position);
        if (end == std::string::npos) end = text.size();
        std::string word = text.substr(position, end - position);
        // Refuse malformed unbroken words before passing text to the game's formatter.
        if (word.size() > 60) return {"Legenda indisponivel: texto invalido."};
        std::string next = line.empty() ? word : line + " " + word;
        if (!line.empty() && string_width(next.c_str()) > 470) {
            result.push_back(line);
            line = word;
        } else line = next;
        position = end + 1;
    }
    if (!line.empty()) result.push_back(line);
    return result;
}

static void __cdecl subtitle_flush() {
    static int previous = -1;
    static ULONGLONG elapsed, previous_tick;
    static std::vector<std::string> lines;
    const int state = *reinterpret_cast<int*>(base + 0x858028);
    const int id = *reinterpret_cast<int*>(base + 0x85802c);
    const ULONGLONG now = GetTickCount64();
    const ULONGLONG delta = now - previous_tick;
    previous_tick = now;
    // These are the actual stream states, after the queued voice starts playing.
    const bool active = state >= 2 && state <= 4 && id >= 0 && id < 479 && !captions[id].empty();
    if (active) {
        if (id != previous) {
            previous = id;
            elapsed = 0;
            lines = wrap(captions[id]);
            char message[80];
            sprintf_s(message, "voice=%d state=%d subtitle-start", id, state);
            log_line(message);
        }
        const int channel = *reinterpret_cast<int*>(base + 0x857fdc);
        if (!is_playing(channel)) { original_flush(); return; }
        elapsed += std::min<ULONGLONG>(delta, 250);
        const DWORD bytes = *reinterpret_cast<DWORD*>(base + 0xfd814 + id * 8);
        const size_t pages = (lines.size() + 1) / 2;
        const ULONGLONG duration = durations[id] ? durations[id] : std::max<ULONGLONG>(1, bytes * 1000ULL / 44100);
        if (elapsed > duration + 150) { original_flush(); return; }
        std::vector<size_t> weights(pages, 0);
        size_t total = 0;
        for (size_t i = 0; i < lines.size(); ++i) { weights[i / 2] += lines[i].size(); total += lines[i].size(); }
        // Give dense pages more reading time, with a minimum for short trailing text.
        const size_t minimum = std::max<size_t>(1, total / pages / 3);
        total = 0;
        for (auto& weight : weights) { weight = std::max(weight, minimum); total += weight; }
        size_t page = 0, accumulated = weights[0];
        while (page + 1 < pages && elapsed * total >= duration * accumulated) accumulated += weights[++page];
        int& x = *reinterpret_cast<int*>(base + 0x8640a0);
        int& y = *reinterpret_cast<int*>(base + 0x8640a4);
        unsigned char& color = *reinterpret_cast<unsigned char*>(base + 0x8640bc);
        const int old_x = x, old_y = y;
        const unsigned char old_color = color;
        // Keep the existing game's buffer well below its 2048-character capacity.
        if (*reinterpret_cast<int*>(base + 0x8640a8) < 1700) {
            color = 0;
            for (size_t i = page * 2; i < std::min(lines.size(), page * 2 + 2); ++i) {
                x = std::max(10, (512 - string_width(lines[i].c_str())) / 2);
                y = 198 + static_cast<int>(i % 2) * 13;
                print_text("%s", lines[i].c_str());
            }
        }
        x = old_x; y = old_y; color = old_color;
    } else previous = -1;
    original_flush();
}

static bool install_hook() {
    base = reinterpret_cast<DWORD>(GetModuleHandleW(nullptr));
    auto target = reinterpret_cast<unsigned char*>(base + 0x9e580);
    const unsigned char expected[] = {0x51, 0xa1, 0xa8, 0x40, 0xc6, 0x00};
    if (base != 0x400000 || memcmp(target, expected, sizeof(expected)) != 0) return false;
    auto trampoline = static_cast<unsigned char*>(VirtualAlloc(nullptr, 11, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!trampoline) return false;
    memcpy(trampoline, expected, 6);
    trampoline[6] = 0xe9;
    *reinterpret_cast<DWORD*>(trampoline + 7) = reinterpret_cast<DWORD>(target + 6) - reinterpret_cast<DWORD>(trampoline + 11);
    DWORD old;
    if (!VirtualProtect(trampoline, 11, PAGE_EXECUTE_READ, &old)) { VirtualFree(trampoline, 0, MEM_RELEASE); return false; }
    original_flush = reinterpret_cast<void (__cdecl*)()>(trampoline);
    string_width = reinterpret_cast<int (__cdecl*)(const char*)>(base + 0x9e450);
    print_text = reinterpret_cast<void (__cdecl*)(const char*, ...)>(base + 0x9e2e0);
    is_playing = reinterpret_cast<int (__cdecl*)(int)>(base + 0x7c6f0);
    if (!VirtualProtect(target, 6, PAGE_EXECUTE_READWRITE, &old)) { VirtualFree(trampoline, 0, MEM_RELEASE); return false; }
    target[0] = 0xe9;
    *reinterpret_cast<DWORD*>(target + 1) = reinterpret_cast<DWORD>(&subtitle_flush) - reinterpret_cast<DWORD>(target + 5);
    target[5] = 0x90;
    DWORD ignored;
    VirtualProtect(target, 6, old, &ignored);
    FlushInstructionCache(GetCurrentProcess(), target, 6);
    FlushInstructionCache(GetCurrentProcess(), trampoline, 11);
    return true;
}

static bool patch_memory_bytes(DWORD addr, const void* expected, const void* patch, size_t size) {
    auto ptr = reinterpret_cast<unsigned char*>(addr);
    if (expected && memcmp(ptr, expected, size) != 0) return false;
    DWORD old;
    if (!VirtualProtect(ptr, size, PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(ptr, patch, size);
    DWORD ignored;
    VirtualProtect(ptr, size, old, &ignored);
    FlushInstructionCache(GetCurrentProcess(), ptr, size);
    return true;
}

static bool install_60fps_patches() {
    if (base != 0x400000) return false;
    const unsigned char exp_add_ecx[] = {0x83, 0xc1, 0x21};
    const unsigned char pat_add_ecx[] = {0x83, 0xc1, 0x10};
    const unsigned char exp_add_edx[] = {0x83, 0xc2, 0x21};
    const unsigned char pat_add_edx[] = {0x83, 0xc2, 0x10};
    const unsigned char exp_mov_ecx[] = {0xb9, 0x21, 0x00, 0x00, 0x00};
    const unsigned char pat_mov_ecx[] = {0xb9, 0x10, 0x00, 0x00, 0x00};

    bool ok = true;
    ok &= patch_memory_bytes(base + 0x390f5, exp_add_ecx, pat_add_ecx, sizeof(exp_add_ecx));
    ok &= patch_memory_bytes(base + 0x39107, exp_add_edx, pat_add_edx, sizeof(exp_add_edx));
    ok &= patch_memory_bytes(base + 0x39be4, exp_add_ecx, pat_add_ecx, sizeof(exp_add_ecx));
    ok &= patch_memory_bytes(base + 0x39bf6, exp_add_edx, pat_add_edx, sizeof(exp_add_edx));
    ok &= patch_memory_bytes(base + 0xac452, exp_mov_ecx, pat_mov_ecx, sizeof(exp_mov_ecx));
    ok &= patch_memory_bytes(base + 0xac49d, exp_mov_ecx, pat_mov_ecx, sizeof(exp_mov_ecx));
    return ok;
}

struct TextureSlot {
    DWORD last_access;
    int page_id;
    void* surface;
    DWORD flags;
};

static TextureSlot* __cdecl hook_upload_texture(int page_index, const void* src_buffer) {
    if (page_index < 0) return nullptr;
    auto slots = reinterpret_cast<TextureSlot*>(base + 0x840390);
    int num_slots = *reinterpret_cast<int*>(base + 0x8400dc);
    if (num_slots <= 0 || num_slots > 128) num_slots = 64;
    DWORD current_time = *reinterpret_cast<DWORD*>(base + 0x8409cc);

    int best_slot = 0;
    DWORD oldest_time = 0xFFFFFFFF;
    for (int i = 0; i < num_slots; ++i) {
        if (slots[i].page_id == -1) {
            best_slot = i;
            break;
        }
        if (slots[i].last_access < oldest_time) {
            oldest_time = slots[i].last_access;
            best_slot = i;
        }
    }

    TextureSlot* slot = &slots[best_slot];
    if (!slot->surface) return slot;

    void** vtbl = *reinterpret_cast<void***>(slot->surface);
    using LockFn = HRESULT(STDMETHODCALLTYPE*)(void*, LPRECT, void*, DWORD, HANDLE);
    using UnlockFn = HRESULT(STDMETHODCALLTYPE*)(void*, LPRECT);
    auto lock_fn = reinterpret_cast<LockFn>(vtbl[25]);
    auto unlock_fn = reinterpret_cast<UnlockFn>(vtbl[32]);

    unsigned char desc[124] = {0};
    *reinterpret_cast<DWORD*>(desc) = sizeof(desc);
    HRESULT hr = lock_fn(slot->surface, nullptr, desc, 0x00000821 /* DDLOCK_WAIT | DDLOCK_WRITEONLY */, nullptr);
    if (FAILED(hr)) return slot;

    void* lpSurface = *reinterpret_cast<void**>(desc + 0x24);
    DWORD pitch = *reinterpret_cast<DWORD*>(desc + 0x10);
    DWORD width = *reinterpret_cast<DWORD*>(desc + 0x0c);
    DWORD height = *reinterpret_cast<DWORD*>(desc + 0x08);

    bool loaded = false;
    if (width == 1024 && height == 1024 && lpSurface) {
        wchar_t path[MAX_PATH];
        swprintf_s(path, L"%shd-textures\\page-%04d.raw", directory().c_str(), page_index);
        HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file != INVALID_HANDLE_VALUE) {
            LARGE_INTEGER size;
            if (GetFileSizeEx(file, &size) && size.QuadPart == 1024 * 1024 * 2) {
                if (pitch == 2048) {
                    DWORD count = 0;
                    if (ReadFile(file, lpSurface, 1024 * 1024 * 2, &count, nullptr) && count == 1024 * 1024 * 2) {
                        loaded = true;
                    }
                } else {
                    static std::vector<unsigned char> temp(1024 * 1024 * 2);
                    DWORD count = 0;
                    if (ReadFile(file, temp.data(), static_cast<DWORD>(temp.size()), &count, nullptr) && count == temp.size()) {
                        for (DWORD y = 0; y < 1024; ++y) {
                            memcpy(reinterpret_cast<unsigned char*>(lpSurface) + y * pitch, temp.data() + y * 2048, 2048);
                        }
                        loaded = true;
                    }
                }
            }
            CloseHandle(file);
        }
    }

    if (!loaded && lpSurface && src_buffer) {
        const auto* src16 = reinterpret_cast<const uint16_t*>(src_buffer);
        if (width == 1024 && height == 1024) {
            for (DWORD y = 0; y < 1024; ++y) {
                DWORD sy = y >> 2;
                auto* dst_row = reinterpret_cast<uint16_t*>(reinterpret_cast<unsigned char*>(lpSurface) + y * pitch);
                for (DWORD x = 0; x < 1024; ++x) {
                    DWORD sx = x >> 2;
                    dst_row[x] = src16[sy * 256 + sx];
                }
            }
        } else {
            for (DWORD y = 0; y < 256; ++y) {
                memcpy(reinterpret_cast<unsigned char*>(lpSurface) + y * pitch, src16 + y * 256, 512);
            }
        }
    }

    unlock_fn(slot->surface, nullptr);
    slot->last_access = current_time;
    slot->page_id = page_index;
    return slot;
}

static bool install_hd_textures_hook() {
    if (base != 0x400000) return false;
    const unsigned char exp_surf[] = {0xb8, 0x00, 0x01, 0x00, 0x00};
    const unsigned char pat_surf[] = {0xb8, 0x00, 0x04, 0x00, 0x00};
    patch_memory_bytes(base + 0x72c21, exp_surf, pat_surf, sizeof(exp_surf));
    patch_memory_bytes(base + 0x72d31, exp_surf, pat_surf, sizeof(exp_surf));

    auto target = reinterpret_cast<unsigned char*>(base + 0x72e70);
    const unsigned char expected[] = {0x81, 0xec, 0x88, 0x00, 0x00, 0x00};
    if (memcmp(target, expected, sizeof(expected)) != 0) return false;

    DWORD old;
    if (!VirtualProtect(target, 6, PAGE_EXECUTE_READWRITE, &old)) return false;
    target[0] = 0xe9;
    *reinterpret_cast<DWORD*>(target + 1) = reinterpret_cast<DWORD>(&hook_upload_texture) - reinterpret_cast<DWORD>(target + 5);
    target[5] = 0x90;
    DWORD ignored;
    VirtualProtect(target, 6, old, &ignored);
    FlushInstructionCache(GetCurrentProcess(), target, 6);
    return true;
}

// DualSense Native Integration:
// Soul Reaver PC queries the keyboard message queue and PSX pad packet via DirectInput.
// We hook UpdateInput at base + 0x7a407 (which calls 0x478170).
// Each frame, right after the game's internal UpdateInput() finishes, we poll the DualSense controller
// directly via DirectInput with DISCL_BACKGROUND, and inject inputs directly into:
// 1) pad1 (base + 0x861040, pointed to by base + 0x8651c8) - native PSX pad struct
// 2) kbd buffer (base + 0x866900) - DirectInput 256-key scancode array
// 3) pause flag (base + 0x8542f4) - instant pause menu trigger

static LPDIRECTINPUTA g_pDirectInput = nullptr;
static LPDIRECTINPUTDEVICE2A g_dualsense_device = nullptr;
static ULONGLONG g_next_dualsense_search = 0;
static bool g_prev_start_pressed = false;
static void (__cdecl* original_UpdateInput)() = nullptr;

struct HapticState {
    ULONGLONG expire_tick = 0;
    WORD left_motor = 0;
    WORD right_motor = 0;
};
static HapticState g_haptic;

static void trigger_rumble(WORD left, WORD right, DWORD duration_ms) {
    g_haptic.left_motor = left;
    g_haptic.right_motor = right;
    g_haptic.expire_tick = GetTickCount64() + duration_ms;
}

static void update_haptics() {
    static HMODULE s_xinput = nullptr;
    using SetStateFn = DWORD(WINAPI*)(DWORD, void*);
    static SetStateFn s_set_state = nullptr;
    static bool s_tried_load = false;
    if (!s_tried_load) {
        s_tried_load = true;
        s_xinput = LoadLibraryA("xinput1_4.dll");
        if (!s_xinput) s_xinput = LoadLibraryA("xinput1_3.dll");
        if (!s_xinput) s_xinput = LoadLibraryA("xinput9_1_0.dll");
        if (s_xinput) {
            s_set_state = reinterpret_cast<SetStateFn>(GetProcAddress(s_xinput, "XInputSetState"));
            if (s_set_state) log_line("XInput haptic feedback driver initialized");
        }
    }

    if (!s_set_state) return;

    struct { WORD wLeftMotorSpeed; WORD wRightMotorSpeed; } vib{};
    const ULONGLONG now = GetTickCount64();
    if (now < g_haptic.expire_tick) {
        vib.wLeftMotorSpeed = g_haptic.left_motor;
        vib.wRightMotorSpeed = g_haptic.right_motor;
    }
    s_set_state(0, &vib);
}

static BOOL CALLBACK enum_dualsense_callback(LPCDIDEVICEINSTANCEA lpddi, LPVOID pvRef) {
    auto pGuid = reinterpret_cast<GUID*>(pvRef);
    *pGuid = lpddi->guidInstance;
    return DIENUM_STOP;
}

static void poll_dualsense_and_inject() {
    const ULONGLONG now = GetTickCount64();

    if (!g_dualsense_device && now >= g_next_dualsense_search) {
        g_next_dualsense_search = now + 1000;
        if (!g_pDirectInput && real_create) {
            real_create(GetModuleHandleW(nullptr), 0x0500, &g_pDirectInput, nullptr);
        }
        if (g_pDirectInput) {
            GUID target_guid{};
            g_pDirectInput->EnumDevices(4 /* DIDEVTYPE_JOYSTICK */, enum_dualsense_callback, &target_guid, DIEDFL_ATTACHEDONLY);

            if (target_guid != GUID{}) {
                LPDIRECTINPUTDEVICEA dev1 = nullptr;
                HRESULT hr = g_pDirectInput->CreateDevice(target_guid, &dev1, nullptr);
                if (SUCCEEDED(hr) && dev1) {
                    dev1->SetDataFormat(&c_dfDIJoystick);
                    dev1->SetCooperativeLevel(GetDesktopWindow(), DISCL_NONEXCLUSIVE | DISCL_BACKGROUND);
                    hr = dev1->QueryInterface(IID_IDirectInputDevice2A, reinterpret_cast<void**>(&g_dualsense_device));
                    dev1->Release();
                    if (SUCCEEDED(hr) && g_dualsense_device) {
                        g_dualsense_device->Acquire();
                        log_line("DualSense native controller connected and acquired");
                    }
                }
            }
        }
    }

    if (!g_dualsense_device) return;

    HWND fg = GetForegroundWindow();
    DWORD fg_pid = 0;
    if (fg) GetWindowThreadProcessId(fg, &fg_pid);
    if (fg_pid != 0 && fg_pid != GetCurrentProcessId()) return;

    g_dualsense_device->Poll();
    DIJOYSTATE js{};
    HRESULT hr = g_dualsense_device->GetDeviceState(sizeof(DIJOYSTATE), &js);
    if (hr == DIERR_NOTACQUIRED || hr == DIERR_INPUTLOST) {
        g_dualsense_device->Acquire();
        hr = g_dualsense_device->GetDeviceState(sizeof(DIJOYSTATE), &js);
    }
    if (FAILED(hr)) {
        g_dualsense_device->Release();
        g_dualsense_device = nullptr;
        log_line("DualSense controller disconnected");
        return;
    }

    constexpr LONG kCenter = 32768;
    constexpr LONG kDeadzone = 8000;
    const bool stick_left  = (js.lX < kCenter - kDeadzone);
    const bool stick_right = (js.lX > kCenter + kDeadzone);
    const bool stick_up    = (js.lY < kCenter - kDeadzone);
    const bool stick_down  = (js.lY > kCenter + kDeadzone);

    bool dpad_up = false, dpad_down = false, dpad_left = false, dpad_right = false;
    const DWORD pov = js.rgdwPOV[0];
    if (LOWORD(pov) != 0xFFFF) {
        dpad_up    = (pov >= 31500 || pov <= 4500);
        dpad_right = (pov >= 4500  && pov <= 13500);
        dpad_down  = (pov >= 13500 && pov <= 22500);
        dpad_left  = (pov >= 22500 && pov <= 31500);
    }

    const bool move_up    = stick_up    || dpad_up;
    const bool move_down  = stick_down  || dpad_down;
    const bool move_left  = stick_left  || dpad_left;
    const bool move_right = stick_right || dpad_right;

    const bool cam_left  = (js.lZ < kCenter - kDeadzone);
    const bool cam_right = (js.lZ > kCenter + kDeadzone);
    const bool cam_up    = (js.lRz < kCenter - kDeadzone);
    const bool cam_down  = (js.lRz > kCenter + kDeadzone);

    auto btn = [&](int idx) -> bool {
        return (idx >= 0 && idx < 32) && ((js.rgbButtons[idx] & 0x80) != 0);
    };

    const bool btn_square   = btn(0);
    const bool btn_cross    = btn(1);
    const bool btn_circle   = btn(2);
    const bool btn_triangle = btn(3);
    const bool btn_l1       = btn(4);
    const bool btn_r1       = btn(5);
    const bool btn_r3       = btn(11); // Right stick click: instant camera center
    const bool btn_l2       = btn(6) || cam_right || btn_r3; // Stick right -> camera looks right (in-game L2 orbit)
    const bool btn_r2       = btn(7) || cam_left  || btn_r3;  // Stick left -> camera looks left (in-game R2 orbit)
    const bool btn_select   = btn(8);
    const bool btn_start    = btn(9) || btn(12) || btn(13);

    const bool final_move_up   = move_up   || (btn_r1 && cam_up);
    const bool final_move_down = move_down || (btn_r1 && cam_down);

    if (base == 0x400000) {
        auto* cam = reinterpret_cast<unsigned char*>(base + 0x864560);
        if (cam) {
            short& pitch = *reinterpret_cast<short*>(cam + 0x136);
            if (btn_r3) {
                pitch = 0;
            } else if (!btn_r1) {
                if (cam_up && pitch > -500) pitch -= 12;
                if (cam_down && pitch < 500) pitch += 12;
            }
        }
    }

    auto pad1_ptr = *reinterpret_cast<unsigned char**>(base + 0x8651c8);
    if (!pad1_ptr) pad1_ptr = reinterpret_cast<unsigned char*>(base + 0x861040);
    if (pad1_ptr) {
        pad1_ptr[0] = 0;
        pad1_ptr[1] = 0x41;
        uint16_t& buttons = *reinterpret_cast<uint16_t*>(pad1_ptr + 2);

        if (btn_select)   buttons &= ~0x0001;
        if (btn_start)    buttons &= ~0x0008;
        if (final_move_up)   buttons &= ~0x0010;
        if (move_right)   buttons &= ~0x0020;
        if (final_move_down) buttons &= ~0x0040;
        if (move_left)    buttons &= ~0x0080;
        if (btn_l2)       buttons &= ~0x0100;
        if (btn_r2)       buttons &= ~0x0200;
        if (btn_l1)       buttons &= ~0x0400;
        if (btn_r1)       buttons &= ~0x0800;
        if (btn_triangle) buttons &= ~0x1000;
        if (btn_circle)   buttons &= ~0x2000;
        if (btn_cross)    buttons &= ~0x4000;
        if (btn_square)   buttons &= ~0x8000;
    }

    auto pad0_ptr = reinterpret_cast<unsigned char*>(base + 0x860f60);
    if (pad0_ptr) {
        uint16_t& buttons0 = *reinterpret_cast<uint16_t*>(pad0_ptr + 2);
        if (btn_select)   buttons0 &= ~0x0001;
        if (btn_start)    buttons0 &= ~0x0008;
        if (final_move_up)   buttons0 &= ~0x0010;
        if (move_right)   buttons0 &= ~0x0020;
        if (final_move_down) buttons0 &= ~0x0040;
        if (move_left)    buttons0 &= ~0x0080;
        if (btn_l2)       buttons0 &= ~0x0100;
        if (btn_r2)       buttons0 &= ~0x0200;
        if (btn_l1)       buttons0 &= ~0x0400;
        if (btn_r1)       buttons0 &= ~0x0800;
        if (btn_triangle) buttons0 &= ~0x1000;
        if (btn_circle)   buttons0 &= ~0x2000;
        if (btn_cross)    buttons0 &= ~0x4000;
        if (btn_square)   buttons0 &= ~0x8000;
    }

    auto kbd = reinterpret_cast<unsigned char*>(base + 0x866900);
    if (kbd) {
        if (final_move_up)   kbd[0xc8] |= 0x80;
        if (final_move_down) kbd[0xd0] |= 0x80;
        if (move_left)    kbd[0xcb] |= 0x80;
        if (move_right)   kbd[0xcd] |= 0x80;
        if (btn_square)   kbd[0x1e] |= 0x80;
        if (btn_cross)    kbd[0x2d] |= 0x80;
        if (btn_circle)   kbd[0x20] |= 0x80;
        if (btn_triangle) kbd[0x21] |= 0x80;
        if (btn_l1)       kbd[0x1f] |= 0x80;
        if (btn_r1)       kbd[0x2e] |= 0x80;
        if (btn_l2)       kbd[0x52] |= 0x80;
        if (btn_r2)       kbd[0x9d] |= 0x80;
        if (btn_start)    kbd[0x01] |= 0x80;
        if (btn_select)   kbd[0x1c] |= 0x80;
    }

    HWND target_wnd = fg ? fg : GetActiveWindow();
    static bool s_icon_set = false;
    if (!s_icon_set && target_wnd) {
        wchar_t icon_path[MAX_PATH];
        swprintf_s(icon_path, L"%ssoul-reaver.ico", directory().c_str());
        HICON hIcon = (HICON)LoadImageW(nullptr, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE);
        if (hIcon) {
            SendMessageW(target_wnd, WM_SETICON, ICON_BIG, (LPARAM)hIcon);
            SendMessageW(target_wnd, WM_SETICON, ICON_SMALL, (LPARAM)hIcon);
            SetClassLongPtrW(target_wnd, GCLP_HICON, (LONG_PTR)hIcon);
            SetClassLongPtrW(target_wnd, GCLP_HICONSM, (LONG_PTR)hIcon);
            s_icon_set = true;
            log_line("High-resolution window icon applied");
        }
    }

    static bool s_borderless_set = false;
    if (!s_borderless_set && target_wnd) {
        int screen_w = GetSystemMetrics(SM_CXSCREEN);
        int screen_h = GetSystemMetrics(SM_CYSCREEN);
        LONG_PTR style = GetWindowLongPtrW(target_wnd, GWL_STYLE);
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU);
        style |= WS_POPUP;
        SetWindowLongPtrW(target_wnd, GWL_STYLE, style);
        LONG_PTR ex_style = GetWindowLongPtrW(target_wnd, GWL_EXSTYLE);
        ex_style &= ~WS_EX_TOPMOST;
        SetWindowLongPtrW(target_wnd, GWL_EXSTYLE, ex_style);
        SetWindowPos(target_wnd, HWND_NOTOPMOST, 0, 0, screen_w, screen_h, SWP_FRAMECHANGED | SWP_SHOWWINDOW);
        s_borderless_set = true;
        log_line("Borderless windowed mode applied");
    }

    if (btn_start && !g_prev_start_pressed) {
        *reinterpret_cast<DWORD*>(base + 0x8542f4) = 1;
        if (target_wnd) PostMessageA(target_wnd, WM_KEYDOWN, VK_ESCAPE, 0x00010001);
    } else if (!btn_start && g_prev_start_pressed) {
        if (target_wnd) PostMessageA(target_wnd, WM_KEYUP, VK_ESCAPE, 0xc0010001);
    }
    g_prev_start_pressed = btn_start;

    if (btn_cross || btn_select) {
        if (target_wnd) PostMessageA(target_wnd, WM_KEYDOWN, VK_SPACE, 0x00390001);
    }

    static bool prev_sq = false, prev_cr = false, prev_tr = false, prev_r3 = false;
    if (btn_square && !prev_sq) trigger_rumble(0x6000, 0x9000, 90);    // Attack (claws/weapon slash)
    if (btn_cross && !prev_cr)  trigger_rumble(0x2000, 0x4000, 50);    // Jump / Glide leap
    if (btn_triangle && !prev_tr) trigger_rumble(0x9000, 0xb000, 160); // Shift Realm / Cast Glyph
    if (btn_r3 && !prev_r3) trigger_rumble(0x0000, 0xa000, 45);        // Camera snap click
    prev_sq = btn_square;
    prev_cr = btn_cross;
    prev_tr = btn_triangle;
    prev_r3 = btn_r3;

    update_haptics();
}

static void __cdecl hook_UpdateInput() {
    if (original_UpdateInput) {
        original_UpdateInput();
    }
    static bool s_aspect_fixed = false;
    if (!s_aspect_fixed && base == 0x400000) {
        int w = *reinterpret_cast<int*>(base + 0x840b5c);
        int h = *reinterpret_cast<int*>(base + 0x8409d4);
        if (w > 0 && h > 0) {
            float aspect = static_cast<float>(w) / static_cast<float>(h);
            if (aspect > 1.4f) {
                float fixed_ratio = (4.0f / 3.0f) * (4.0f / 3.0f) / aspect;
                DWORD old_p;
                auto* target_aspect = reinterpret_cast<float*>(base + 0xec358);
                if (VirtualProtect(target_aspect, sizeof(float), PAGE_EXECUTE_READWRITE, &old_p)) {
                    *target_aspect = fixed_ratio;
                    VirtualProtect(target_aspect, sizeof(float), old_p, &old_p);
                    s_aspect_fixed = true;
                    char msg[128];
                    sprintf_s(msg, "Widescreen 3D aspect ratio correction active (%dx%d, aspect=%.3f)", w, h, aspect);
                    log_line(msg);
                }
            }
        }
    }
    poll_dualsense_and_inject();
}

static bool install_engine_optimizations() {
    if (base != 0x400000) return false;

    // Multicore CPU Affinity lock to Core 0 (prevents timing desync, audio stutter and multithread crashes)
    SetProcessAffinityMask(GetCurrentProcess(), 1);

    // Expand default fog distance (Far=22000, Near=20000) to double draw distance and eliminate pop-in
    DWORD old_p;
    auto* fog_far = reinterpret_cast<uint16_t*>(base + 0xf5f40);
    auto* fog_near = reinterpret_cast<uint16_t*>(base + 0xf5f44);
    if (VirtualProtect(fog_far, sizeof(uint32_t) * 2, PAGE_EXECUTE_READWRITE, &old_p)) {
        *fog_far = 22000;
        *fog_near = 20000;
        VirtualProtect(fog_far, sizeof(uint32_t) * 2, old_p, &old_p);
    }
    return true;
}

static bool install_dualsense_hook() {
    if (base != 0x400000) return false;
    const unsigned char exp_call[] = {0xe8, 0x64, 0xdd, 0xff, 0xff};
    auto call_site = reinterpret_cast<unsigned char*>(base + 0x7a407);
    if (memcmp(call_site, exp_call, sizeof(exp_call)) != 0) return false;

    original_UpdateInput = reinterpret_cast<void(__cdecl*)()>(base + 0x78170);

    unsigned char pat_call[5] = {0xe8};
    *reinterpret_cast<DWORD*>(pat_call + 1) = reinterpret_cast<DWORD>(&hook_UpdateInput) - (base + 0x7a407 + 5);

    return patch_memory_bytes(base + 0x7a407, exp_call, pat_call, sizeof(exp_call));
}

static BOOL CALLBACK initialize(PINIT_ONCE, PVOID, PVOID*) {
    wchar_t system[32768];
    UINT length = GetSystemDirectoryW(system, ARRAYSIZE(system));
    if (!length || length + 12 >= ARRAYSIZE(system)) return TRUE;
    wcscat_s(system, L"\\dinput.dll");
    HMODULE library = LoadLibraryW(system);
    if (library) real_create = reinterpret_cast<InputCreate>(GetProcAddress(library, "DirectInputCreateA"));
    if (!real_create) { log_line("System DirectInput unavailable"); return TRUE; }
    if (!verified_executable()) { log_line("Unsupported executable; hooks disabled"); return TRUE; }
    if (load_captions()) {
        log_line(install_hook() ? "Experimental subtitle hook active" : "Hook guard failed; subtitles disabled");
    }
    log_line(install_60fps_patches() ? "60 FPS patches active" : "60 FPS patch guard failed");
    log_line(install_hd_textures_hook() ? "HD texture 1024x1024 hook active" : "HD texture hook guard failed");
    log_line(install_engine_optimizations() ? "Engine optimizations active (Affinity + Fog Far 22000)" : "Engine optimizations failed");
    log_line(install_dualsense_hook() ? "DualSense native input hook active" : "DualSense hook guard failed");
    return TRUE;
}

extern "C" HRESULT WINAPI DirectInputCreateA(HINSTANCE instance, DWORD version, LPDIRECTINPUTA* result, LPUNKNOWN outer) {
    InitOnceExecuteOnce(&once, initialize, nullptr, nullptr);
    if (!real_create) return E_FAIL;
    return real_create(instance, version, result, outer);
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        self_module = module;
        DisableThreadLibraryCalls(module);
        InitOnceExecuteOnce(&once, initialize, nullptr, nullptr);
    } else if (reason == DLL_PROCESS_DETACH) {
        if (g_dualsense_device) {
            g_dualsense_device->Unacquire();
            g_dualsense_device->Release();
            g_dualsense_device = nullptr;
        }
        if (g_pDirectInput) {
            g_pDirectInput->Release();
            g_pDirectInput = nullptr;
        }
    }
    return TRUE;
}
