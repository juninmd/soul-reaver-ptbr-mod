// Experimental subtitles for the hash-verified classic PC executable.
// Build only for x86. Install into an isolated game copy; never replace another proxy.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
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
using InputCreate = HRESULT(WINAPI*)(HINSTANCE, DWORD, void**, void*);
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
    HANDLE file = CreateFileW(name.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ,
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

static BOOL CALLBACK initialize(PINIT_ONCE, PVOID, PVOID*) {
    wchar_t system[32768];
    UINT length = GetSystemDirectoryW(system, ARRAYSIZE(system));
    if (!length || length + 12 >= ARRAYSIZE(system)) return TRUE;
    wcscat_s(system, L"\\dinput.dll");
    HMODULE library = LoadLibraryW(system);
    if (library) real_create = reinterpret_cast<InputCreate>(GetProcAddress(library, "DirectInputCreateA"));
    if (!real_create) { log_line("System DirectInput unavailable"); return TRUE; }
    if (!verified_executable()) { log_line("Unsupported executable; subtitles disabled"); return TRUE; }
    if (!load_captions()) { log_line("Missing/invalid captions; subtitles disabled"); return TRUE; }
    log_line(install_hook() ? "Experimental subtitle hook active" : "Hook guard failed; subtitles disabled");
    return TRUE;
}

extern "C" HRESULT WINAPI DirectInputCreateA(HINSTANCE instance, DWORD version, void** result, void* outer) {
    InitOnceExecuteOnce(&once, initialize, nullptr, nullptr);
    return real_create ? real_create(instance, version, result, outer) : E_FAIL;
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) { self_module = module; DisableThreadLibraryCalls(module); }
    return TRUE;
}
