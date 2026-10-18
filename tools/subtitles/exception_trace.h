// First-chance exception tracer: logs where a fault originates (the game only reports 0xC000041D
// from DDRAW). Included by runtime.cpp after log_line/self_module; not standalone.
#pragma once

static LONG CALLBACK trace_exception(PEXCEPTION_POINTERS info) {
    static volatile LONG logged = 0;
    const DWORD code = info->ExceptionRecord->ExceptionCode;
    if ((code & 0xF0000000) != 0xC0000000) return EXCEPTION_CONTINUE_SEARCH;
    HMODULE module = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       static_cast<LPCWSTR>(info->ExceptionRecord->ExceptionAddress), &module);
    if (module == self_module) return EXCEPTION_CONTINUE_SEARCH; // deliberate __try probes
    if (InterlockedIncrement(&logged) > 20) return EXCEPTION_CONTINUE_SEARCH;
    wchar_t path[MAX_PATH] = L"?";
    if (module) GetModuleFileNameW(module, path, MAX_PATH);
    const wchar_t* leaf = wcsrchr(path, L'\\');
    char line[256];
    sprintf_s(line, "exception 0x%08lX at %p (%ls+0x%lX) thread=%lu", code, info->ExceptionRecord->ExceptionAddress,
              leaf ? leaf + 1 : path,
              static_cast<unsigned long>(reinterpret_cast<DWORD_PTR>(info->ExceptionRecord->ExceptionAddress) -
                                         reinterpret_cast<DWORD_PTR>(module)),
              GetCurrentThreadId());
    log_line(line);
    // x86 frame-pointer walk: names the game/proxy callers of the faulting module.
    auto* frame = reinterpret_cast<DWORD*>(info->ContextRecord->Ebp);
    for (int depth = 0; depth < 12 && frame; ++depth) {
        DWORD next = 0, ret = 0;
        __try { next = frame[0]; ret = frame[1]; } __except (EXCEPTION_EXECUTE_HANDLER) { break; }
        HMODULE owner = nullptr;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(ret), &owner);
        wchar_t owner_path[MAX_PATH] = L"?";
        if (owner) GetModuleFileNameW(owner, owner_path, MAX_PATH);
        const wchar_t* owner_leaf = wcsrchr(owner_path, L'\\');
        char frame_line[160];
        sprintf_s(frame_line, "  frame %d: %08lX (%ls+0x%lX)", depth, static_cast<unsigned long>(ret),
                  owner_leaf ? owner_leaf + 1 : owner_path,
                  static_cast<unsigned long>(ret - reinterpret_cast<DWORD>(owner)));
        log_line(frame_line);
        if (next <= reinterpret_cast<DWORD>(frame)) break;
        frame = reinterpret_cast<DWORD*>(next);
    }
    dump_traced_messages();
    return EXCEPTION_CONTINUE_SEARCH;
}
