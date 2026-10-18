// Diagnostic: samples the game thread's EIP while it is stalled (level loads) and logs the hottest
// code buckets. Enabled by .soul-reaver-ptbr/profile-load.flag. Included by runtime.cpp; not standalone.
#pragma once

static volatile LONG g_profile_game_thread = 0;
static volatile ULONGLONG g_profile_last_flush = 0;

static DWORD WINAPI load_profiler_thread(LPVOID) {
    std::map<DWORD, int> buckets;
    int samples = 0;
    bool stalled = false;
    for (;;) {
        Sleep(4);
        const DWORD tid = static_cast<DWORD>(g_profile_game_thread);
        const ULONGLONG last = g_profile_last_flush;
        if (!tid || !last) continue;
        const bool now_stalled = GetTickCount64() - last > 400;
        if (stalled && !now_stalled && samples > 20) {
            std::vector<std::pair<int, DWORD>> top;
            for (const auto& b : buckets) top.emplace_back(b.second, b.first);
            std::sort(top.rbegin(), top.rend());
            char line[96];
            sprintf_s(line, "Load profile: %d samples", samples);
            log_line(line);
            for (size_t i = 0; i < top.size() && i < 12; ++i) {
                HMODULE owner = nullptr;
                wchar_t path[MAX_PATH] = L"?";
                GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                   reinterpret_cast<LPCWSTR>(top[i].second), &owner);
                if (owner) GetModuleFileNameW(owner, path, MAX_PATH);
                const wchar_t* leaf = wcsrchr(path, L'/');
                if (!leaf) leaf = wcsrchr(path, 92);
                sprintf_s(line, "  %5.1f%%  %08lX %ls+0x%lX", 100.0 * top[i].first / samples, static_cast<unsigned long>(top[i].second),
                          leaf ? leaf + 1 : path, static_cast<unsigned long>(top[i].second - reinterpret_cast<DWORD>(owner)));
                log_line(line);
            }
            buckets.clear();
            samples = 0;
        }
        stalled = now_stalled;
        if (!now_stalled) continue;
        HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, FALSE, tid);
        if (!thread) continue;
        CONTEXT ctx{};
        ctx.ContextFlags = CONTEXT_CONTROL;
        if (SuspendThread(thread) != static_cast<DWORD>(-1)) {
            if (GetThreadContext(thread, &ctx)) {
                ++buckets[static_cast<DWORD>(ctx.Eip) & ~0xFFu];
                ++samples;
            }
            ResumeThread(thread);
        }
        CloseHandle(thread);
    }
}

static void profile_note_flush() {
    g_profile_last_flush = GetTickCount64();
    if (g_profile_game_thread) return;
    g_profile_game_thread = static_cast<LONG>(GetCurrentThreadId());
    if (GetFileAttributesW((directory() + L".soul-reaver-ptbr/profile-load.flag").c_str()) == INVALID_FILE_ATTRIBUTES) return;
    if (HANDLE thread = CreateThread(nullptr, 0, load_profiler_thread, nullptr, 0, nullptr)) CloseHandle(thread);
}
