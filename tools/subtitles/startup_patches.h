// Startup flow patches for the hash-verified kain2.exe (image base 0x400000).
// Included by runtime.cpp after patch_memory_bytes/log_line; not standalone.
#pragma once

// Intro table at 0x4F44A8, 0x38-byte entries; word at +0x36 is the next entry.
// Original chain: publogo(0) -> crylogo(1) -> legal.pti(5, "press enter") -> end.
static bool install_single_intro_patch() {
    if (base != 0x400000) return false;
    const unsigned char expected_next[] = {0x01, 0x00};
    const unsigned char skip_crylogo[] = {0x05, 0x00};
    return patch_memory_bytes(base + 0xf44de, expected_next, skip_crylogo, sizeof(expected_next));
}

// The launcher dialog (resource 0x71) is shown on every start by 0x47AED0 via DialogBoxParamA.
// Skipping it outright crashes (its WM_INITDIALOG fills tables used later), so with a saved setup
// it still runs invisibly and is confirmed with IDOK. Holding Shift at launch keeps it interactive.
static DLGPROC g_setup_dialog_proc = nullptr;

// Logs every combo/list box of the setup dialog (device and mode lists) so the panel can mirror them.
static BOOL CALLBACK log_list_child(HWND child, LPARAM) {
    char cls[32] = {};
    GetClassNameA(child, cls, sizeof(cls) - 1);
    const bool combo = !_stricmp(cls, "ComboBox"), list = !_stricmp(cls, "ListBox");
    if (!combo && !list) return TRUE;
    const UINT get_count = combo ? CB_GETCOUNT : LB_GETCOUNT, get_text = combo ? CB_GETLBTEXT : LB_GETTEXT;
    const UINT get_sel = combo ? CB_GETCURSEL : LB_GETCURSEL;
    const int count = static_cast<int>(SendMessageA(child, get_count, 0, 0));
    const bool sound_list = GetDlgCtrlID(child) == 1010; // sound provider combo of the setup dialog
    if (sound_list) {
        settings::g_sound_names.clear();
        settings::g_sound_selected = static_cast<int>(SendMessageA(child, get_sel, 0, 0));
    }
    char line[200];
    sprintf_s(line, "Setup list id=%d class=%s items=%d selected=%d", GetDlgCtrlID(child), cls, count,
              static_cast<int>(SendMessageA(child, get_sel, 0, 0)));
    log_line(line);
    for (int i = 0; i < count && i < 40; ++i) {
        char text[120] = {};
        if (SendMessageA(child, get_text, i, reinterpret_cast<LPARAM>(text)) < 0) continue;
        sprintf_s(line, "  [%d] %s", i, text);
        log_line(line);
        if (sound_list) {
            wchar_t wide[120] = {};
            MultiByteToWideChar(CP_ACP, 0, text, -1, wide, 119);
            settings::g_sound_names.push_back(wide);
        }
    }
    return TRUE;
}

static void log_setup_dialog_lists(HWND dialog) { EnumChildWindows(dialog, log_list_child, 0); }

static INT_PTR CALLBACK auto_confirm_setup_proc(HWND dialog, UINT message, WPARAM wparam, LPARAM lparam) {
    const INT_PTR result = g_setup_dialog_proc(dialog, message, wparam, lparam);
    if (message == WM_INITDIALOG) {
        log_setup_dialog_lists(dialog);
        SetWindowLongW(dialog, GWL_EXSTYLE, GetWindowLongW(dialog, GWL_EXSTYLE) | WS_EX_LAYERED);
        SetLayeredWindowAttributes(dialog, 0, 0, LWA_ALPHA);
        PostMessageW(dialog, WM_COMMAND, IDOK, 0);
    }
    return result;
}

static INT_PTR WINAPI hook_setup_dialog(HINSTANCE instance, LPCSTR tmpl, HWND parent, DLGPROC proc, LPARAM param) {
    g_setup_dialog_proc = proc;
    log_line("Setup dialog invoked (auto-confirm)");
    return DialogBoxParamA(instance, tmpl, parent, auto_confirm_setup_proc, param);
}

static bool registry_has_saved_setup() {
    HKEY key = nullptr;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Crystal Dynamics\\Legacy of Kain: Soul Reaver\\1.00.000",
                      0, KEY_READ, &key) != ERROR_SUCCESS) return false;
    static const wchar_t* const names[] = {L"RenderDeviceID", L"SoundDeviceID", L"ScreenWidth", L"ScreenHeight"};
    bool ok = true;
    for (const wchar_t* name : names) {
        DWORD type = 0, value = 0, size = sizeof(value);
        ok &= RegQueryValueExW(key, name, nullptr, &type, reinterpret_cast<BYTE*>(&value), &size) == ERROR_SUCCESS
              && type == REG_DWORD;
    }
    RegCloseKey(key);
    return ok;
}

static bool install_skip_setup_dialog_patch() {
    if (base != 0x400000) return false;
    if (GetAsyncKeyState(VK_SHIFT) & 0x8000) { log_line("Setup dialog kept (Shift held)"); return false; }
    if (!registry_has_saved_setup()) { log_line("Setup dialog kept (no saved setup yet)"); return false; }
    const unsigned char expected_call[] = {0xff, 0x15, 0x1c, 0xc2, 0x4e, 0x00}; // call [DialogBoxParamA]
    unsigned char patched_call[6] = {0xe8, 0, 0, 0, 0, 0x90};                    // call hook_setup_dialog; nop
    const DWORD site = base + 0x7af10;
    *reinterpret_cast<DWORD*>(patched_call + 1) = reinterpret_cast<DWORD>(&hook_setup_dialog) - (site + 5);
    return patch_memory_bytes(site, expected_call, patched_call, sizeof(expected_call));
}
