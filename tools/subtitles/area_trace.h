// Diagnostic: logs the area name the engine formats into "\kain2\area\%s\bin\%s.crm" (sprintf at 0x43A3C0, called
// from 0x4CF99E and 0x4D700E), so the map's "you are here" can be tied to real names. Included by
// runtime.cpp after startup_patches.h; not standalone. Read-only: the original sprintf still runs.
#pragma once

static DWORD g_area_sprintf_original = 0;
static char g_last_area_name[32] = {};

static void __cdecl note_area_name(const char* name) {
    __try {
        if (!name || !name[0]) return;
        char copy[32] = {};
        for (int i = 0; i < 31 && name[i] >= 0x20 && name[i] < 0x7f; ++i) copy[i] = name[i];
        if (!copy[0] || !strcmp(copy, g_last_area_name)) return;
        strcpy_s(g_last_area_name, copy);
        char line[96];
        sprintf_s(line, "Area load: %s", copy);
        log_line(line);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

// Stack on entry: [ret][buffer][format][area][name]. Registers are preserved around the log call.
__declspec(naked) static void area_sprintf_stub() {
    __asm {
        mov eax, dword ptr [esp + 12]
        pushad
        push eax
        call note_area_name
        add esp, 4
        popad
        jmp dword ptr [g_area_sprintf_original]
    }
}

static bool redirect_area_call(DWORD offset) {
    auto* site = reinterpret_cast<unsigned char*>(base + offset);
    const DWORD sprintf_va = base + 0x3a3c0;
    const DWORD expected_rel = sprintf_va - (reinterpret_cast<DWORD>(site) + 5);
    if (site[0] != 0xE8 || *reinterpret_cast<DWORD*>(site + 1) != expected_rel) return false;
    DWORD old_protect = 0;
    if (!VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &old_protect)) return false;
    *reinterpret_cast<DWORD*>(site + 1) = reinterpret_cast<DWORD>(&area_sprintf_stub) - (reinterpret_cast<DWORD>(site) + 5);
    VirtualProtect(site, 5, old_protect, &old_protect);
    FlushInstructionCache(GetCurrentProcess(), site, 5);
    return true;
}

static void install_area_trace() {
    if (base != 0x400000) return;
    g_area_sprintf_original = base + 0x3a3c0;
    const bool a = redirect_area_call(0xcf99e), b = redirect_area_call(0xd700e);
    char line[96];
    sprintf_s(line, "Area trace installed (sites: %d, %d)", a ? 1 : 0, b ? 1 : 0);
    log_line(line);
}
