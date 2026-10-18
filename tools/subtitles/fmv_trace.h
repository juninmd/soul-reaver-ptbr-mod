// FMV player (0x47D920, cdecl, one char* argument): logs every movie with its wall-clock length and makes it
// skippable with Enter, Space or the pad's cross/circle/options.
// Winplay.dll's Player_InitMovie plays the whole movie in one call and only leaves its message loop on
// WM_KEYDOWN Esc/Ctrl/Win or WM_SYSKEYDOWN, so a watcher thread posts an Esc to the game thread on release.
// Included by runtime.cpp after g_dualsense_device; not standalone.
#pragma once

static void (__cdecl* g_fmv_original)(const char*) = nullptr;

struct FmvWatch {
    DWORD game_thread;
    volatile LONG stop;
};

static bool fmv_confirm_down() {
    if (!game_is_foreground()) return false;
    if ((GetAsyncKeyState(VK_RETURN) & 0x8000) || (GetAsyncKeyState(VK_SPACE) & 0x8000)) return true;
    DIJOYSTATE js{};
    // The game thread is blocked inside the movie, so nothing else polls the pad; the watcher is joined before it resumes.
    if (g_dualsense_device) g_dualsense_device->Poll();
    if (g_dualsense_device && SUCCEEDED(g_dualsense_device->GetDeviceState(sizeof(DIJOYSTATE), &js)))
        return (js.rgbButtons[1] & 0x80) || (js.rgbButtons[2] & 0x80) || (js.rgbButtons[9] & 0x80);
    return false;
}

// Skips on release so the same press does not also confirm the next screen ("press enter").
static DWORD WINAPI fmv_watch(LPVOID param) {
    auto* watch = static_cast<FmvWatch*>(param);
    const ULONGLONG begin = GetTickCount64();
    bool armed = false, pending = false, hint_cleared = false;
    while (!watch->stop) {
        Sleep(20);
        const ULONGLONG elapsed = GetTickCount64() - begin;
        if (!hint_cleared && elapsed > 6000) {
            hint_cleared = true;
            render_vector_subtitle(L"");
        }
        const bool down = fmv_confirm_down();
        if (!down) {
            armed = true;
            if (pending) {
                log_line("FMV skipped by player");
                PostThreadMessageW(watch->game_thread, WM_KEYDOWN, VK_ESCAPE, 0);
                break;
            }
        } else if (armed && elapsed > 300) {
            pending = true;
        }
    }
    return 0;
}

static void copy_fmv_name(const char* name, char (&safe)[64]) {
    __try {
        for (int i = 0; name && i < 63 && name[i] >= 0x20 && name[i] < 0x7f; ++i) safe[i] = name[i];
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

static void __cdecl fmv_hook(const char* name) {
    char safe[64] = {};
    copy_fmv_name(name, safe);
    char line[128];
    sprintf_s(line, "FMV start: %s", safe);
    log_line(line);
    g_menu_hint = false;  // the menu hint must not show over a movie (re-evaluated by subtitle_flush afterwards)
    render_vector_subtitle(L"Enter / Esc / ✕: pular vídeo");
    FmvWatch watch{GetCurrentThreadId(), 0};
    HANDLE thread = CreateThread(nullptr, 0, fmv_watch, &watch, 0, nullptr);
    const ULONGLONG begin = GetTickCount64();
    g_fmv_original(name);
    watch.stop = 1;
    if (thread) {
        WaitForSingleObject(thread, INFINITE);  // the loop wakes every 20 ms; `watch` lives on this stack frame
        CloseHandle(thread);
    }
    render_vector_subtitle(L"");
    sprintf_s(line, "FMV end: %s after %llu ms", safe, GetTickCount64() - begin);
    log_line(line);
}

static void install_fmv_trace() {
    if (base != 0x400000) return;
    auto* target = reinterpret_cast<unsigned char*>(base + 0x7d920);
    const unsigned char expected[] = {0x81, 0xec, 0x40, 0x01, 0x00, 0x00};
    if (memcmp(target, expected, sizeof(expected)) != 0) return;
    auto* trampoline = static_cast<unsigned char*>(VirtualAlloc(nullptr, 11, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!trampoline) return;
    memcpy(trampoline, expected, sizeof(expected));
    trampoline[6] = 0xe9;
    *reinterpret_cast<DWORD*>(trampoline + 7) = reinterpret_cast<DWORD>(target + 6) - reinterpret_cast<DWORD>(trampoline + 11);
    DWORD old = 0;
    if (!VirtualProtect(trampoline, 11, PAGE_EXECUTE_READ, &old)) { VirtualFree(trampoline, 0, MEM_RELEASE); return; }
    if (!VirtualProtect(target, 6, PAGE_EXECUTE_READWRITE, &old)) { VirtualFree(trampoline, 0, MEM_RELEASE); return; }
    g_fmv_original = reinterpret_cast<void (__cdecl*)(const char*)>(trampoline);
    target[0] = 0xe9;
    *reinterpret_cast<DWORD*>(target + 1) = reinterpret_cast<DWORD>(&fmv_hook) - reinterpret_cast<DWORD>(target + 5);
    target[5] = 0x90;
    VirtualProtect(target, 6, old, &old);
    FlushInstructionCache(GetCurrentProcess(), target, 6);
    log_line("FMV trace + skip installed");
}
