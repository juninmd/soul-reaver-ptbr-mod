// Diagnostic: with .soul-reaver-ptbr/profile-startup.flag, samples the main thread's EIP and nearest kain2.exe
// return address for the first 30 s after the proxy loads, then logs the hottest buckets and the thread's
// user/kernel CPU time. Included by runtime.cpp after load_profiler.h; not standalone.
#pragma once

static DWORD nearest_exe_return(DWORD esp) {
    const DWORD* stack = reinterpret_cast<const DWORD*>(esp);
    __try {
        for (int i = 0; i < 4096; ++i)
            if (stack[i] >= 0x401000 && stack[i] < 0x4f0000) return stack[i];
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
    return 0;
}

static DWORD WINAPI startup_profiler_thread(LPVOID param) {
    HANDLE thread = static_cast<HANDLE>(param);
    std::vector<std::pair<DWORD, DWORD>> raw;  // resolved after resume: the main thread may hold the loader lock
    raw.reserve(6001);  // nothing may allocate while the main thread is suspended (it may hold the heap lock)
    const ULONGLONG begin = GetTickCount64();
    while (GetTickCount64() - begin < 30000) {
        Sleep(5);
        CONTEXT ctx{};
        ctx.ContextFlags = CONTEXT_CONTROL;
        if (SuspendThread(thread) == static_cast<DWORD>(-1)) break;
        if (raw.size() < 6000 && GetThreadContext(thread, &ctx)) raw.emplace_back(ctx.Eip, nearest_exe_return(ctx.Esp));
        ResumeThread(thread);
    }
    std::map<std::string, int> eip_buckets, caller_buckets;
    for (const auto& sample : raw) {
        char key[96];
        HMODULE owner = nullptr;
        wchar_t path[MAX_PATH] = L"?";
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(sample.first), &owner);
        if (owner) GetModuleFileNameW(owner, path, MAX_PATH);
        const wchar_t* leaf = wcsrchr(path, L'\\');
        sprintf_s(key, "%ls+0x%lX", leaf ? leaf + 1 : path, static_cast<unsigned long>((sample.first - reinterpret_cast<DWORD>(owner)) & ~0xFFu));
        ++eip_buckets[key];
        if (sample.second) {
            sprintf_s(key, "kain2.exe:%08lX", static_cast<unsigned long>(sample.second & ~0xFu));
            ++caller_buckets[key];
        }
    }
    const int samples = static_cast<int>(raw.size());
    FILETIME created, exited, kernel, user;
    char line[160];
    if (GetThreadTimes(thread, &created, &exited, &kernel, &user)) {
        const auto ms = [](FILETIME t) { return ((static_cast<ULONGLONG>(t.dwHighDateTime) << 32) | t.dwLowDateTime) / 10000; };
        sprintf_s(line, "Startup profile: %d samples, main thread kernel=%llu ms user=%llu ms", samples, ms(kernel), ms(user));
        log_line(line);
    }
    for (auto* buckets : {&eip_buckets, &caller_buckets}) {
        std::vector<std::pair<int, std::string>> top;
        for (const auto& b : *buckets) top.emplace_back(b.second, b.first);
        std::sort(top.rbegin(), top.rend());
        for (size_t i = 0; i < top.size() && i < 10; ++i) {
            sprintf_s(line, "  %5.1f%%  %s", 100.0 * top[i].first / std::max(1, samples), top[i].second.c_str());
            log_line(line);
        }
    }
    CloseHandle(thread);
    return 0;
}

static void start_startup_profiler() {
    if (GetFileAttributesW((directory() + L".soul-reaver-ptbr/profile-startup.flag").c_str()) == INVALID_FILE_ATTRIBUTES) return;
    HANDLE self = nullptr;
    if (!DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &self, THREAD_ALL_ACCESS, FALSE, 0)) return;
    if (HANDLE thread = CreateThread(nullptr, 0, startup_profiler_thread, self, 0, nullptr)) CloseHandle(thread);
}
