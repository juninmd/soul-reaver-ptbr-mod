#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>

// Exercise fail-closed executable verification while preserving system DirectInput.
int main() {
    CreateDirectoryW(L"staging\\subtitles-v1\\.soul-reaver-ptbr", nullptr);
    HMODULE module = LoadLibraryW(L"staging\\subtitles-v1\\DINPUT.dll");
    if (!module) return 1;
    using Create = HRESULT(WINAPI*)(HINSTANCE, DWORD, void**, void*);
    auto create = reinterpret_cast<Create>(GetProcAddress(module, "DirectInputCreateA"));
    if (!create) return 2;
    void* input = nullptr;
    HRESULT status = create(GetModuleHandleW(nullptr), 0x0700, &input, nullptr);
    printf("System DirectInput result=0x%08lx interface=%s\n", status, input ? "created" : "missing");
    if (FAILED(status) || !input) return 3;
    using Release = ULONG(WINAPI*)(void*);
    auto table = *reinterpret_cast<void***>(input);
    reinterpret_cast<Release>(table[2])(input);
    FreeLibrary(module);
    return 0;
}
