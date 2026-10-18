// Warms the OS file cache with the big game archives so level and cutscene loads hit RAM.
// Included by runtime.cpp after log_line/directory; not standalone.
#pragma once

static DWORD WINAPI prefetch_thread(LPVOID) {
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_IDLE);
    static const wchar_t* const files[] = {L"bigfile.dat", L"textures.big", L"voices.dat"};
    const ULONGLONG start = GetTickCount64();
    ULONGLONG total = 0;
    std::vector<char> buffer(1 << 20);
    for (const wchar_t* name : files) {
        HANDLE file = CreateFileW((directory() + name).c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
        if (file == INVALID_HANDLE_VALUE) continue;
        DWORD count = 0;
        while (ReadFile(file, buffer.data(), static_cast<DWORD>(buffer.size()), &count, nullptr) && count) total += count;
        CloseHandle(file);
    }
    char line[96];
    sprintf_s(line, "Archive prefetch: %llu MB warmed in %llu ms", total >> 20, GetTickCount64() - start);
    log_line(line);
    return 0;
}

static void start_archive_prefetch() {
    if (GetFileAttributesW((directory() + L".soul-reaver-ptbr/no-prefetch.flag").c_str()) != INVALID_FILE_ATTRIBUTES) return;
    if (HANDLE thread = CreateThread(nullptr, 0, prefetch_thread, nullptr, 0, nullptr)) CloseHandle(thread);
}
