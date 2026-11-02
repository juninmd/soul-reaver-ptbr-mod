// Experimental subtitles for the hash-verified classic PC executable.
// Build only for x86. Install into an isolated game copy; never replace another proxy.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define INITGUID
#define DIRECTINPUT_VERSION 0x0500
#include <windows.h>
#include <objidl.h>
#include <algorithm>
#include <map>
namespace Gdiplus {
    using std::min;
    using std::max;
}
#include <gdiplus.h>
#include <dwmapi.h>
#include <dinput.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <mmsystem.h>
#include <bcrypt.h>
#include <array>
#include <atomic>
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
    static const ULONGLONG s_log_epoch = GetTickCount64();
    char stamp[24];
    const int stamp_len = sprintf_s(stamp, "[+%7llu] ", GetTickCount64() - s_log_epoch);
    if (stamp_len > 0) WriteFile(file, stamp, static_cast<DWORD>(stamp_len), &written, nullptr);
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

struct UnicodePage {
    std::wstring text;
    ULONGLONG start_ms = 0;
    ULONGLONG end_ms = 0;
};

struct UnicodeCaption {
    std::wstring text;
    ULONGLONG duration_ms = 0;
    std::vector<UnicodePage> pages;
};

static std::array<UnicodeCaption, 479> unicode_captions;
static bool has_unicode_captions = false;

static bool parse_unicode_captions(const std::string& json) {
    size_t pos = json.find("\"captions\"");
    if (pos == std::string::npos) return false;

    while ((pos = json.find("\"id\":", pos)) != std::string::npos) {
        pos += 5;
        while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
        int id = 0;
        while (pos < json.size() && json[pos] >= '0' && json[pos] <= '9') {
            id = id * 10 + (json[pos] - '0');
            pos++;
        }
        if (id < 0 || id >= 479) continue;

        size_t next_id = json.find("\"id\":", pos);

        ULONGLONG duration = 0;
        size_t dur_pos = json.find("\"duration_ms\":", pos);
        if (dur_pos != std::string::npos && (next_id == std::string::npos || dur_pos < next_id)) {
            dur_pos += 14;
            while (dur_pos < json.size() && (json[dur_pos] == ' ' || json[dur_pos] == '\t')) dur_pos++;
            while (dur_pos < json.size() && json[dur_pos] >= '0' && json[dur_pos] <= '9') {
                duration = duration * 10 + (json[dur_pos] - '0');
                dur_pos++;
            }
        }

        std::string full_text;
        size_t text_pos = json.find("\"text\":", pos);
        if (text_pos != std::string::npos && (next_id == std::string::npos || text_pos < next_id)) {
            text_pos = json.find('"', text_pos + 7);
            if (text_pos != std::string::npos) {
                text_pos++;
                size_t text_end = text_pos;
                while (text_end < json.size() && json[text_end] != '"') {
                    if (json[text_end] == '\\' && text_end + 1 < json.size()) text_end += 2;
                    else text_end++;
                }
                full_text = json.substr(text_pos, text_end - text_pos);
            }
        }

        UnicodeCaption cap;
        cap.duration_ms = duration;
        if (!full_text.empty()) {
            int wlen = MultiByteToWideChar(CP_UTF8, 0, full_text.c_str(), static_cast<int>(full_text.size()), nullptr, 0);
            if (wlen > 0) {
                cap.text.resize(wlen);
                MultiByteToWideChar(CP_UTF8, 0, full_text.c_str(), static_cast<int>(full_text.size()), &cap.text[0], wlen);
            }
        }

        size_t pages_pos = json.find("\"pages\":", pos);
        if (pages_pos != std::string::npos && (next_id == std::string::npos || pages_pos < next_id)) {
            size_t pages_end = json.find(']', pages_pos);
            if (pages_end != std::string::npos) {
                size_t p_cur = pages_pos;
                while ((p_cur = json.find('{', p_cur)) != std::string::npos && p_cur < pages_end) {
                    size_t p_obj_end = json.find('}', p_cur);
                    if (p_obj_end == std::string::npos || p_obj_end > pages_end) break;
                    std::string obj = json.substr(p_cur, p_obj_end - p_cur + 1);

                    std::string p_text;
                    size_t pt = obj.find("\"text\":");
                    if (pt != std::string::npos) {
                        pt = obj.find('"', pt + 7);
                        if (pt != std::string::npos) {
                            pt++;
                            size_t pte = pt;
                            while (pte < obj.size() && obj[pte] != '"') {
                                if (obj[pte] == '\\' && pte + 1 < obj.size()) pte += 2;
                                else pte++;
                            }
                            p_text = obj.substr(pt, pte - pt);
                        }
                    }

                    ULONGLONG s_ms = 0, e_ms = 0;
                    size_t ps = obj.find("\"start_ms\":");
                    if (ps != std::string::npos) {
                        ps += 11;
                        while (ps < obj.size() && (obj[ps] == ' ' || obj[ps] == '\t')) ps++;
                        while (ps < obj.size() && obj[ps] >= '0' && obj[ps] <= '9') {
                            s_ms = s_ms * 10 + (obj[ps] - '0');
                            ps++;
                        }
                    }
                    size_t pe = obj.find("\"end_ms\":");
                    if (pe != std::string::npos) {
                        pe += 9;
                        while (pe < obj.size() && (obj[pe] == ' ' || obj[pe] == '\t')) pe++;
                        while (pe < obj.size() && obj[pe] >= '0' && obj[pe] <= '9') {
                            e_ms = e_ms * 10 + (obj[pe] - '0');
                            pe++;
                        }
                    }

                    if (!p_text.empty()) {
                        UnicodePage page;
                        page.start_ms = s_ms;
                        page.end_ms = e_ms;
                        int pwlen = MultiByteToWideChar(CP_UTF8, 0, p_text.c_str(), static_cast<int>(p_text.size()), nullptr, 0);
                        if (pwlen > 0) {
                            page.text.resize(pwlen);
                            MultiByteToWideChar(CP_UTF8, 0, p_text.c_str(), static_cast<int>(p_text.size()), &page.text[0], pwlen);
                        }
                        cap.pages.push_back(page);
                    }
                    p_cur = p_obj_end + 1;
                }
            }
        }

        if (cap.pages.empty() && !cap.text.empty()) {
            UnicodePage page;
            page.text = cap.text;
            page.start_ms = 0;
            page.end_ms = cap.duration_ms ? cap.duration_ms : 3000;
            cap.pages.push_back(page);
        }

        if (!cap.text.empty()) {
            unicode_captions[id] = cap;
            durations[id] = cap.duration_ms;
            has_unicode_captions = true;
        }
    }
    return has_unicode_captions;
}

static bool load_unicode_captions() {
    std::vector<unsigned char> bytes;
    bool ok = read_file(directory() + L".soul-reaver-ptbr\\subtitles-unicode-v1.json", bytes, 2 * 1024 * 1024)
           || read_file(directory() + L".soul-reaver-ptbr\\asset-captions-unicode-v1.json", bytes, 2 * 1024 * 1024);
    if (!ok) return false;
    std::string data(bytes.begin(), bytes.end());
    return parse_unicode_captions(data);
}

static ULONG_PTR g_gdiplus_token = 0;
static HWND g_overlay_hwnd = nullptr;
static bool g_overlay_inited = false;
static std::atomic<bool> g_overlay_available{false};

static LRESULT CALLBACK OverlayWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static HANDLE g_overlay_wake = nullptr;
static CRITICAL_SECTION g_overlay_lock;
static std::wstring g_overlay_request;

// The overlay is rendered off the game thread: a full-screen GDI+ redraw costs 80-500 ms.
static DWORD WINAPI overlay_thread(LPVOID);

static void ensure_overlay_window(HWND /*game_hwnd*/) {
    if (g_overlay_inited) return;
    g_overlay_inited = true;
    InitializeCriticalSection(&g_overlay_lock);
    g_overlay_wake = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    HANDLE thread = g_overlay_wake ? CreateThread(nullptr, 0, overlay_thread, nullptr, 0, nullptr) : nullptr;
    if (thread) CloseHandle(thread);
}

static bool create_overlay_window() {
    Gdiplus::GdiplusStartupInput gdiplusStartupInput;
    Gdiplus::GdiplusStartup(&g_gdiplus_token, &gdiplusStartupInput, nullptr);

    WNDCLASSEXW wc = { sizeof(WNDCLASSEXW) };
    wc.lpfnWndProc = OverlayWndProc;
    wc.hInstance = self_module;
    wc.lpszClassName = L"SR_VectorSubtitleOverlay";
    RegisterClassExW(&wc);

    int screen_w = GetSystemMetrics(SM_CXSCREEN);
    int screen_h = GetSystemMetrics(SM_CYSCREEN);

    g_overlay_hwnd = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        L"SR_VectorSubtitleOverlay",
        L"",
        WS_POPUP,
        0, 0, screen_w, screen_h,
        nullptr, nullptr, self_module, nullptr
    );

    if (!g_overlay_hwnd) return false;
    g_overlay_available = true;
    log_line("Vector HD subtitle overlay initialized");
    return true;
}

#include "area_trace.h"

struct PlayerState {
    int realm = 0;
    int health = 100;
    int unit_id = 2;
    int abilities = 0;
};

static bool safe_read_player_state(PlayerState& out) {
    out.realm = 0;
    out.health = 100;
    out.unit_id = 2;
    out.abilities = 0;

    if (base != 0x400000) return false;

    __try {
        auto player_ptr = *reinterpret_cast<unsigned char**>(base + 0x866d4c);
        if (!player_ptr) return false;

        out.unit_id = *reinterpret_cast<int*>(player_ptr + 0x18);

        auto extra = *reinterpret_cast<unsigned char**>(player_ptr + 0x14);
        if (extra) {
            out.realm = *reinterpret_cast<int*>(extra + 0x00) & 1;
            int balls = *reinterpret_cast<int*>(extra + 0x04);
            if (balls >= 1 && balls <= 5) out.health = balls * 20;
            out.abilities = *reinterpret_cast<int*>(extra + 0x08);
        }
        return true;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

struct RealmHealthState {
    int realm = 0;
    int health = 100;
};

static RealmHealthState get_player_state() {
    RealmHealthState state;
    PlayerState ps;
    if (safe_read_player_state(ps)) {
        state.realm = ps.realm;
        state.health = ps.health;
    }
    return state;
}

static std::atomic<bool> g_map_visible{false};
static std::atomic<bool> g_settings_visible{false};
static bool modal_open() { return g_map_visible || g_settings_visible; }
// Shown on menu screens (no player in the scene) so the F10 settings panel is discoverable from the main menu.
static std::atomic<bool> g_menu_hint{false};
static const wchar_t kMenuHintText[] = L"F10 / Create  ·  Resolução e som";
static std::atomic<bool> g_test_subtitle_active{false};

struct MapSector {
    const wchar_t* name;
    float norm_x;
    float norm_y;
    const char* areas; // '|'-separated engine area prefixes (e.g. "under"); empty = not yet identified in game
};

static const MapSector g_sectors[] = {
    { L"Submundo & Lago dos Mortos", 0.50f, 0.85f, "under" },
    { L"Santu\u00e1rio dos Cl\u00e3s", 0.50f, 0.60f, "hub" },
    { L"Necr\u00f3pole de Melchiah", 0.25f, 0.72f, "" },
    { L"Catedral Silenciada de Zephon", 0.78f, 0.48f, "cathy" },
    { L"Pilares de Nosgoth", 0.28f, 0.42f, "clfpil" },
    { L"Tumba dos Sarafan", 0.50f, 0.38f, "" },
    { L"Abadia Submersa de Rahab", 0.50f, 0.22f, "" },
    { L"Fortaleza da Montanha de Dumah", 0.75f, 0.25f, "" },
    { L"C\u00e2mara do Tempo (Chronoplast)", 0.32f, 0.15f, "chrono" }
};

// The area name the loader formats most recently ("under", "cathy", ...) selects the current sector. Only
// prefixes confirmed in game are listed; an unidentified area shows no marker instead of a wrong one.
static int current_sector_index() {
    char area[32];
    memcpy(area, g_last_area_name, sizeof(area));
    area[31] = 0;
    if (!area[0]) return -1;
    for (int i = 0; i < static_cast<int>(sizeof(g_sectors) / sizeof(g_sectors[0])); ++i) {
        const char* list = g_sectors[i].areas;
        while (*list) {
            const char* end = strchr(list, '|');
            const size_t len = end ? static_cast<size_t>(end - list) : strlen(list);
            if (len && !strncmp(area, list, len)) return i;
            if (!end) break;
            list = end + 1;
        }
    }
    return -1;
}

struct ObjectiveInfo {
    const wchar_t* region;
    const wchar_t* title;
    const wchar_t* description;
};

static ObjectiveInfo get_current_objective() {
    ObjectiveInfo obj;
    obj.region = L"Nosgoth";
    obj.title = L"Jornada de Vingan\u00e7a de Raziel";
    obj.description = L"Explore os ermos de Nosgoth e destrua o imp\u00e9rio parasita de Kain.";

    PlayerState ps;
    if (!safe_read_player_state(ps)) return obj;

    int unit_id = ps.unit_id;
    int abilities = ps.abilities;

    if ((abilities & 0x01) == 0) {
        obj.region = L"Necr\u00f3pole dos Mortos";
        obj.title = L"Cace Melchiah";
        obj.description = L"Adentre as catacumbas da Necr\u00f3pole e destrua Melchiah para obter o dom de atravessar grades.";
    } else if ((abilities & 0x02) == 0) {
        obj.region = L"Catedral Silenciada";
        obj.title = L"Elimine Zephon";
        obj.description = L"Atravesse as grades de ferro da Catedral e elimine Zephon para obter o dom de escalar paredes.";
    } else if ((abilities & 0x04) == 0) {
        obj.region = L"Pilares de Nosgoth";
        obj.title = L"Confronte Kain nos Pilares";
        obj.description = L"Escale at\u00e9 o cume dos Pilares de Nosgoth, enfrente Kain e desperte a l\u00e2mina espiritual Soul Reaver.";
    } else if ((abilities & 0x08) == 0) {
        obj.region = L"Abadia Submersa & Tumba Sarafan";
        obj.title = L"Derrote Rahab";
        obj.description = L"Mergulhe na abadia profanada de Rahab ao norte e absorva sua imunidade \u00e0 \u00e1gua para nadar.";
    } else if ((abilities & 0x10) == 0) {
        obj.region = L"Fortaleza da Montanha";
        obj.title = L"Destrua Dumah";
        obj.description = L"Nade atrav\u00e9s dos canais gelados at\u00e9 a cidadela de Dumah, empale-o na fornalha e consuma sua alma.";
    } else {
        obj.region = L"C\u00e2mara do Tempo (Chronoplast)";
        obj.title = L"Batalha Final com Kain";
        obj.description = L"Atravesse as montanhas geladas, adentre o dispositivo temporal de Moebius e alcance Kain no tear do destino.";
    }

    (void)unit_id;
    const int sector = current_sector_index();
    if (sector >= 0) obj.region = g_sectors[sector].name;
    return obj;
}

#include "map_render.h"
#include "settings_panel.h"

static BOOL CALLBACK find_game_hwnd_cb(HWND hwnd, LPARAM lParam) {
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != GetCurrentProcessId()) return TRUE;
    if (hwnd == g_overlay_hwnd) return TRUE;
    if (!IsWindowVisible(hwnd)) return TRUE;
    wchar_t cls[64] = {};
    GetClassNameW(hwnd, cls, 63);
    if (wcscmp(cls, L"#32770") == 0) return TRUE;
    if (wcscmp(cls, L"SR_VectorSubtitleOverlay") == 0) return TRUE;
    *reinterpret_cast<HWND*>(lParam) = hwnd;
    return FALSE;
}

static HWND get_game_hwnd() {
    HWND hwnd = nullptr;
    EnumWindows(find_game_hwnd_cb, reinterpret_cast<LPARAM>(&hwnd));
    return hwnd;
}

#include "frame_overlay.h"

static bool g_overlay_visible = false;
static bool g_last_map_state = false;
static std::wstring g_last_subtitle_text;

// The overlay covers the game window itself, so it lands on the right monitor and size even when the
// game is not on the primary display; the primary screen is only the fallback.
static RECT overlay_target_rect() {
    RECT rect{0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)};
    HWND game = FindWindowW(L"G2WndClass", nullptr);
    DWORD pid = 0;
    if (game) GetWindowThreadProcessId(game, &pid);
    RECT window{};
    if (game && pid == GetCurrentProcessId() && IsWindowVisible(game) && !IsIconic(game) && GetWindowRect(game, &window) &&
        window.right - window.left >= 320 && window.bottom - window.top >= 240)
        rect = window;
    return rect;
}

// Global key/pad polling must not react to other apps (Alt+Tab, typing elsewhere).
static bool game_is_foreground() {
    DWORD pid = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &pid);
    return pid == GetCurrentProcessId();
}

// The game is often launched by the installer or a launcher and never becomes the foreground window,
// yet it is what the player sees. Subtitles only need it to be the top visible window at its centre.
struct TopWindowProbe { POINT center; bool found; bool ours; };

static BOOL CALLBACK probe_top_window(HWND hwnd, LPARAM param) {
    auto* probe = reinterpret_cast<TopWindowProbe*>(param);
    if (hwnd == g_overlay_hwnd || !IsWindowVisible(hwnd) || IsIconic(hwnd)) return TRUE;
    const LONG ex_style = GetWindowLongW(hwnd, GWL_EXSTYLE);
    if (ex_style & WS_EX_TRANSPARENT) return TRUE;
    DWORD cloaked = 0;
    if (SUCCEEDED(DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, &cloaked, sizeof(cloaked))) && cloaked) return TRUE;
    RECT rect{};
    if (!GetWindowRect(hwnd, &rect) || !PtInRect(&rect, probe->center)) return TRUE;
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    probe->found = true;
    probe->ours = pid == GetCurrentProcessId();
    return FALSE;
}

static bool game_visible_to_user() {
    const RECT rect = overlay_target_rect();
    TopWindowProbe probe{{(rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2}, false, false};
    EnumWindows(probe_top_window, reinterpret_cast<LPARAM>(&probe));
    return probe.found && probe.ours;
}

static void render_overlay_now(const std::wstring& requested_text) {
    if (!g_overlay_hwnd) return;

    const std::wstring flag = directory() + L".soul-reaver-ptbr\\capture.flag";
    const bool want_capture = (GetFileAttributesW(flag.c_str()) != INVALID_FILE_ATTRIBUTES);

    // Hide only after the game has been in the background for a while (loading and window
    // switches briefly report another foreground window).
    static ULONGLONG s_background_since = 0;
    if (!want_capture) {
        if (game_is_foreground() || game_visible_to_user()) {
            s_background_since = 0;
        } else {
            const ULONGLONG now_tick = GetTickCount64();
            if (!s_background_since) s_background_since = now_tick;
            if (now_tick - s_background_since >= 1500) {
                if (g_overlay_visible || modal_open()) {
                    DWORD fg_pid = 0;
                    const HWND fg = GetForegroundWindow();
                    GetWindowThreadProcessId(fg, &fg_pid);
                    wchar_t fg_class[64] = L"?";
                    if (fg) GetClassNameW(fg, fg_class, 63);
                    char msg[160];
                    sprintf_s(msg, "Overlay hidden: game in background (foreground pid=%lu class=%ls)", fg_pid, fg_class);
                    log_line(msg);
                }
                g_map_visible = false;
                g_settings_visible = false;
                frame_overlay::clear();
                if (g_overlay_visible) {
                    ShowWindow(g_overlay_hwnd, SW_HIDE);
                    g_overlay_visible = false;
                }
                g_last_map_state = false;
                g_last_subtitle_text.clear();
                return;
            }
        }
    }

    const std::wstring text = (requested_text.empty() && g_menu_hint && !modal_open()) ? std::wstring(kMenuHintText) : requested_text;
    if (text.empty() && !modal_open()) {
        frame_overlay::clear();
        if (g_overlay_visible) {
            ShowWindow(g_overlay_hwnd, SW_HIDE);
            g_overlay_visible = false;
        }
        g_last_map_state = false;
        g_last_subtitle_text.clear();
        return;
    }

    if (!modal_open() && !want_capture && g_overlay_visible && !g_last_map_state && text == g_last_subtitle_text) {
        if (frame_overlay::ready()) return;
        SetWindowPos(g_overlay_hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
        return;
    }
    g_last_map_state = modal_open();
    g_last_subtitle_text = text;

    const RECT target = overlay_target_rect();
    int screen_w = target.right - target.left;
    int screen_h = target.bottom - target.top;
    if (screen_w <= 0 || screen_h <= 0) return;
    const ULONGLONG draw_start = GetTickCount64();
    // Subtitles only need the bottom quarter; a full-screen layered bitmap costs ~80 ms per page change at 1440p.
    const int full_h = screen_h;
    const bool strip = !modal_open() && !want_capture;
    if (strip) screen_h = std::max(1, full_h / 4);
    const int origin_y = full_h - screen_h;

    BITMAPINFO bi{};
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = screen_w;
    bi.bmiHeader.biHeight = -screen_h;
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;

    void* pvBits = nullptr;
    HDC screenDC = GetDC(nullptr);
    if (!screenDC) return;
    HBITMAP hBitmap = CreateDIBSection(screenDC, &bi, DIB_RGB_COLORS, &pvBits, nullptr, 0);
    if (!hBitmap || !pvBits) {
        ReleaseDC(nullptr, screenDC);
        return;
    }

    {
        Gdiplus::Bitmap bmp(screen_w, screen_h, PixelFormat32bppPARGB);
        Gdiplus::Graphics graphics(&bmp);
        graphics.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
        graphics.SetCompositingQuality(Gdiplus::CompositingQualityHighQuality);
        graphics.SetTextRenderingHint(Gdiplus::TextRenderingHintAntiAliasGridFit);
        graphics.Clear(Gdiplus::Color(0, 0, 0, 0));
        if (strip) graphics.TranslateTransform(0.0f, -static_cast<float>(origin_y));

        if (g_map_visible) {
            render_map_screen(graphics, screen_w, screen_h);
        }
        if (g_settings_visible) settings::render(graphics, screen_w, screen_h);

        // The map is modal and owns the bottom edge, so subtitles wait for it to close.
        if (!text.empty() && !modal_open()) {
            const int marginX = static_cast<int>(screen_w * 0.10f);
            const int boxW = screen_w - (marginX * 2);
            const int maxH = static_cast<int>(full_h * 0.16f);
            const int bottom = full_h - static_cast<int>(full_h * 0.05f);

            Gdiplus::StringFormat format;
            format.SetAlignment(Gdiplus::StringAlignmentCenter);
            format.SetLineAlignment(Gdiplus::StringAlignmentCenter);

            // Shrink long lines until they fit the box instead of clipping them.
            float fontSize = std::max(20.0f, full_h * 0.033f);
            const float minSize = std::max(16.0f, full_h * 0.022f);
            Gdiplus::RectF measured;
            Gdiplus::Font* fitted = nullptr;
            for (;; fontSize *= 0.92f) {
                delete fitted;
                fitted = new Gdiplus::Font(L"Segoe UI", fontSize, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
                graphics.MeasureString(text.c_str(), -1, fitted, Gdiplus::RectF(0, 0, static_cast<float>(boxW), 0),
                                       &format, &measured);
                if (measured.Height <= maxH || fontSize * 0.92f < minSize) break;
            }
            Gdiplus::Font& font = *fitted;
            const int boxH = std::min(maxH, static_cast<int>(measured.Height) + 8);
            const int boxY = bottom - boxH;

            Gdiplus::SolidBrush bgBrush(Gdiplus::Color(185, 8, 10, 16));
            Gdiplus::Pen borderPen(Gdiplus::Color(140, 180, 150, 85), 1.5f);
            graphics.FillRectangle(&bgBrush, marginX - 30, boxY - 10, boxW + 60, boxH + 20);
            graphics.DrawRectangle(&borderPen, marginX - 30, boxY - 10, boxW + 60, boxH + 20);

            Gdiplus::RectF layoutRect(static_cast<float>(marginX), static_cast<float>(boxY),
                                      static_cast<float>(boxW), static_cast<float>(boxH));

            Gdiplus::SolidBrush shadowBrush(Gdiplus::Color(235, 0, 0, 0));
            const float offsets[8][2] = {
                {-2.0f, 0.0f}, {2.0f, 0.0f}, {0.0f, -2.0f}, {0.0f, 2.0f},
                {-1.5f, -1.5f}, {1.5f, -1.5f}, {-1.5f, 1.5f}, {2.5f, 2.5f}
            };
            for (const auto& off : offsets) {
                Gdiplus::RectF oRect = layoutRect;
                oRect.X += off[0];
                oRect.Y += off[1];
                graphics.DrawString(text.c_str(), -1, &font, oRect, &format, &shadowBrush);
            }

            Gdiplus::SolidBrush textBrush(Gdiplus::Color(255, 255, 240, 155));
            graphics.DrawString(text.c_str(), -1, &font, layoutRect, &format, &textBrush);
            delete fitted;
        }

        if (want_capture) {
            UINT n = 0, sz = 0;
            Gdiplus::GetImageEncodersSize(&n, &sz);
            std::vector<unsigned char> buf(sz);
            auto* enc = reinterpret_cast<Gdiplus::ImageCodecInfo*>(buf.data());
            if (sz && Gdiplus::GetImageEncoders(n, sz, enc) == Gdiplus::Ok) {
                for (UINT i = 0; i < n; ++i) {
                    if (wcscmp(enc[i].MimeType, L"image/png") == 0) {
                        const std::wstring out = directory() + L".soul-reaver-ptbr\\overlay-capture.png";
                        bmp.Save(out.c_str(), &enc[i].Clsid, nullptr);
                        break;
                    }
                }
            }
            DeleteFileW(flag.c_str());
            log_line("Overlay capture saved");
        }

        Gdiplus::BitmapData bmpData{};
        Gdiplus::Rect lockRect(0, 0, screen_w, screen_h);
        if (bmp.LockBits(&lockRect, Gdiplus::ImageLockModeRead, PixelFormat32bppPARGB, &bmpData) == Gdiplus::Ok) {
            memcpy(pvBits, bmpData.Scan0, static_cast<size_t>(screen_w) * screen_h * 4);
            bmp.UnlockBits(&bmpData);
        }
    }

    HDC memDC = CreateCompatibleDC(screenDC);
    HGDIOBJ oldBmp = SelectObject(memDC, hBitmap);

    POINT ptSrc = { 0, 0 };
    SIZE sizeDst = { screen_w, screen_h };
    POINT ptDst = { target.left, target.top + origin_y };
    BLENDFUNCTION blend{};
    blend.BlendOp = AC_SRC_OVER;
    blend.BlendFlags = 0;
    blend.SourceConstantAlpha = 255;
    blend.AlphaFormat = AC_SRC_ALPHA;

    if (frame_overlay::ready() && !want_capture) {
        // Drawn inside the game's own frame: no z-order, focus or DWM dependency. The window stays hidden.
        frame_overlay::publish(pvBits, screen_w, screen_h, static_cast<float>(screen_h) / static_cast<float>(full_h));
        ShowWindow(g_overlay_hwnd, SW_HIDE);
    } else {
        frame_overlay::clear();
        UpdateLayeredWindow(g_overlay_hwnd, screenDC, &ptDst, &sizeDst, memDC, &ptSrc, 0, &blend, ULW_ALPHA);
        SetWindowPos(g_overlay_hwnd, HWND_TOPMOST, target.left, target.top + origin_y, screen_w, screen_h, SWP_NOACTIVATE | SWP_SHOWWINDOW);
    }
    g_overlay_visible = true;
    {
        static int s_slow_logged = 0;
        const ULONGLONG took = GetTickCount64() - draw_start;
        if (took >= 20 && s_slow_logged < 10) {
            ++s_slow_logged;
            char msg[96];
            sprintf_s(msg, "Overlay draw took %llu ms (%dx%d map=%d)", took, screen_w, screen_h, g_map_visible ? 1 : 0);
            log_line(msg);
        }
    }

    SelectObject(memDC, oldBmp);
    DeleteDC(memDC);
    DeleteObject(hBitmap);
    ReleaseDC(nullptr, screenDC);
}

static void render_vector_subtitle(const std::wstring& text) {
    ensure_overlay_window(nullptr);
    if (!g_overlay_wake) return;
    EnterCriticalSection(&g_overlay_lock);
    g_overlay_request = text;
    LeaveCriticalSection(&g_overlay_lock);
    SetEvent(g_overlay_wake);
}

static DWORD WINAPI overlay_thread(LPVOID) {
    if (!create_overlay_window()) return 0;
    for (;;) {
        const DWORD woke = MsgWaitForMultipleObjects(1, &g_overlay_wake, FALSE, 100, QS_ALLINPUT);
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        if (woke == WAIT_TIMEOUT) {
            // The game window is borderless/always-on-top too; keep the overlay above it.
            if (g_overlay_visible) {
                const bool in_frame = frame_overlay::ready();
                const bool shown = IsWindowVisible(g_overlay_hwnd) != FALSE;
                if (in_frame && shown) {
                    ShowWindow(g_overlay_hwnd, SW_HIDE);
                } else if (!in_frame && !shown) {
                    // The game stopped presenting through the swap chain (loading, video): bring the window path back.
                    EnterCriticalSection(&g_overlay_lock);
                    const std::wstring again = g_overlay_request;
                    LeaveCriticalSection(&g_overlay_lock);
                    g_last_subtitle_text.clear();
                    render_overlay_now(again);
                } else if (!in_frame) {
                    SetWindowPos(g_overlay_hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
                }
            }
            continue;
        }
        if (woke != WAIT_OBJECT_0) continue;
        EnterCriticalSection(&g_overlay_lock);
        const std::wstring text = g_overlay_request;
        LeaveCriticalSection(&g_overlay_lock);
        render_overlay_now(text);
    }
}

static bool load_captions() {
    load_unicode_captions();

    std::vector<unsigned char> bytes;
    if (!read_file(directory() + L".soul-reaver-ptbr\\subtitles.tsv", bytes, 256 * 1024)) return has_unicode_captions;
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
            if (!durations[id]) durations[id] = milliseconds;
            text_start = timing + 1;
        }
        for (size_t i = text_start; i < line.size(); ++i)
            if (line[i] < 32 || line[i] > 126 || line[i] == '@') return false;
        if (line.find_first_not_of(' ', text_start) == std::string::npos) return false;
        captions[id] = line.substr(text_start);
        seen[id] = true;
        begin = end + 1;
    }
    return has_unicode_captions || std::any_of(seen.begin(), seen.end(), [](bool value) { return value; });
}

static std::vector<std::string> wrap(const std::string& text) {
    std::vector<std::string> result;
    std::string line;
    size_t position = 0;
    while (position < text.size()) {
        size_t end = text.find(' ', position);
        if (end == std::string::npos) end = text.size();
        std::string word = text.substr(position, end - position);
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

#include "load_profiler.h"
#include "startup_profiler.h"
#include "frame_capture.h"
#include "speakers.h"

static int s_play_id_last = -1;
static void __cdecl subtitle_flush() {
    static int previous = -1;
    static ULONGLONG elapsed, previous_tick;
    static std::vector<std::string> lines;
    const int state = *reinterpret_cast<int*>(base + 0x858028);
    const int id = *reinterpret_cast<int*>(base + 0x85802c);
    const ULONGLONG now = GetTickCount64();
    const ULONGLONG delta = now - previous_tick;
    previous_tick = now;

    profile_note_flush();
    ensure_overlay_window(nullptr);

    {
        static ULONGLONG s_prev_flush = 0;
        static int s_gaps_logged = 0;
        if (s_prev_flush && delta >= 100 && s_gaps_logged < 12) {
            ++s_gaps_logged;
            char msg[96];
            sprintf_s(msg, "Frame gap %llu ms (map=%d overlay=%d)", delta, g_map_visible ? 1 : 0, g_overlay_visible ? 1 : 0);
            log_line(msg);
        }
        s_prev_flush = now;
    }

    const bool has_u_cap = has_unicode_captions && id >= 0 && id < 479 && !unicode_captions[id].text.empty();
    const bool active = state >= 2 && state <= 4 && id >= 0 && id < 479 && (has_u_cap || !captions[id].empty());

    if (active) {
        if (id != previous) {
            previous = id;
            elapsed = 0;
            if (!has_u_cap) lines = wrap(captions[id]);
            char message[120];
            sprintf_s(message, "voice=%d state=%d subtitle-start%s speaker=%ls", id, state, has_u_cap ? " (vector-unicode)" : "",
                      kSpeakerLabels[kSpeakerOfVoice[id]]);
            log_line(message);
        }
        const int channel = *reinterpret_cast<int*>(base + 0x857fdc);
        static ULONGLONG s_play_start = 0;
        static bool s_play_logged = false;
        if (!is_playing(channel)) {
            if (s_play_start && !s_play_logged) {
                s_play_logged = true;
                char timing[120];
                sprintf_s(timing, "voice=%d audio stopped after %llu ms real (subtitle clock %llu ms)", id, now - s_play_start, elapsed);
                log_line(timing);
            }
            if (g_overlay_available) render_vector_subtitle(L"");
            original_flush();
            return;
        }
        if (id != s_play_id_last || !s_play_start) { s_play_start = now; s_play_logged = false; s_play_id_last = id; }
        elapsed += std::min<ULONGLONG>(delta, 250);
        const DWORD bytes = *reinterpret_cast<DWORD*>(base + 0xfd814 + id * 8);
        const ULONGLONG duration = durations[id] ? durations[id] : std::max<ULONGLONG>(1, bytes * 1000ULL / 44100);
        {
            static int s_logged_id = -1;
            if (s_logged_id != id) {
                s_logged_id = id;
                char timing[140];
                sprintf_s(timing, "voice=%d playing: caption %llu ms, sample %llu ms (%lu bytes)", id, durations[id],
                          bytes * 1000ULL / 44100, static_cast<unsigned long>(bytes));
                log_line(timing);
            }
        }
        if (elapsed > duration + 150) {
            if (g_overlay_available) render_vector_subtitle(L"");
            original_flush();
            return;
        }

        if (g_overlay_available) {
            std::wstring current_text;
            if (has_u_cap) {
                const auto& cap = unicode_captions[id];
                for (const auto& pg : cap.pages) {
                    if (elapsed >= pg.start_ms && elapsed <= pg.end_ms) {
                        current_text = pg.text;
                        break;
                    }
                }
                if (current_text.empty() && !cap.pages.empty()) {
                    current_text = cap.pages.back().text;
                }
            } else if (!captions[id].empty()) {
                int wlen = MultiByteToWideChar(CP_ACP, 0, captions[id].c_str(), -1, nullptr, 0);
                if (wlen > 0) {
                    current_text.resize(wlen - 1);
                    MultiByteToWideChar(CP_ACP, 0, captions[id].c_str(), -1, &current_text[0], wlen);
                }
            }

            if (!current_text.empty() && kSpeakerOfVoice[id]) current_text = std::wstring(kSpeakerLabels[kSpeakerOfVoice[id]]) + L": " + current_text;
            render_vector_subtitle(current_text);
            original_flush();
            return;
        }

    } else {
        {
            // Menu screens have no player instance; require ~1 s of it so loading blips do not flash the hint.
            static int s_menu_frames = 0;
            const bool menu_now = *reinterpret_cast<void**>(base + 0x866d4c) == nullptr;
            s_menu_frames = menu_now ? std::min(s_menu_frames + 1, 100000) : 0;
            const bool want_hint = s_menu_frames > 60;
            if (want_hint != g_menu_hint.load()) {
                g_menu_hint = want_hint;
                log_line(want_hint ? "Menu hint shown (no player in scene)" : "Menu hint hidden");
                if (g_overlay_available) render_vector_subtitle(L"");
            }
        }
        if (g_overlay_available) {
            static ULONGLONG s_last_map_draw = 0;
            if (modal_open()) {
                if (now - s_last_map_draw >= 33) {
                    s_last_map_draw = now;
                    render_vector_subtitle(L"");
                }
            } else if (!g_test_subtitle_active && (previous != -1 || g_overlay_visible)) {
                render_vector_subtitle(L"");
            }
        }
        previous = -1;
    }
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

    log_line("Vector TrueType HD subtitle pipeline hooked; native engine menu bitmaps preserved");
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

#include "startup_patches.h"
#include "window_trace.h"
#include "exception_trace.h"
#include "prefetch.h"

static bool g_hd_textures_active = false;
#include "hd_textures.h"
static bool install_hd_textures_hook() {
    g_hd_textures_active = install_hd_textures_real();
    return base == 0x400000;
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
#include "fmv_trace.h"
static ULONGLONG g_next_dualsense_search = 0;
static bool g_prev_start_pressed = false;
static void (__cdecl* original_UpdateInput)() = nullptr;

static HANDLE g_hDualSenseHID = INVALID_HANDLE_VALUE;
static unsigned char g_led_r = 0, g_led_g = 110, g_led_b = 255;

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

static HANDLE open_dualsense_hid() {
    if (g_hDualSenseHID != INVALID_HANDLE_VALUE) return g_hDualSenseHID;

    GUID hidGuid;
    HidD_GetHidGuid(&hidGuid);
    HDEVINFO hDevInfo = SetupDiGetClassDevsW(&hidGuid, nullptr, nullptr, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (hDevInfo == INVALID_HANDLE_VALUE) return INVALID_HANDLE_VALUE;

    SP_DEVICE_INTERFACE_DATA ifData{};
    ifData.cbSize = sizeof(SP_DEVICE_INTERFACE_DATA);

    for (DWORD i = 0; SetupDiEnumDeviceInterfaces(hDevInfo, nullptr, &hidGuid, i, &ifData); ++i) {
        DWORD reqSize = 0;
        SetupDiGetDeviceInterfaceDetailW(hDevInfo, &ifData, nullptr, 0, &reqSize, nullptr);
        if (reqSize == 0) continue;

        std::vector<BYTE> buf(reqSize);
        auto* detail = reinterpret_cast<PSP_DEVICE_INTERFACE_DETAIL_DATA_W>(buf.data());
        detail->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);

        if (SetupDiGetDeviceInterfaceDetailW(hDevInfo, &ifData, detail, reqSize, nullptr, nullptr)) {
            HANDLE h = CreateFileW(detail->DevicePath, GENERIC_READ | GENERIC_WRITE,
                                   FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
            if (h != INVALID_HANDLE_VALUE) {
                HIDD_ATTRIBUTES attr{};
                attr.Size = sizeof(attr);
                if (HidD_GetAttributes(h, &attr)) {
                    if (attr.VendorID == 0x054C && (attr.ProductID == 0x0CE6 || attr.ProductID == 0x0DF2)) {
                        SetupDiDestroyDeviceInfoList(hDevInfo);
                        g_hDualSenseHID = h;
                        log_line("DualSense native HID output handle connected (lightbar + rumble ready)");
                        return g_hDualSenseHID;
                    }
                }
                CloseHandle(h);
            }
        }
    }
    SetupDiDestroyDeviceInfoList(hDevInfo);
    return INVALID_HANDLE_VALUE;
}

static void write_dualsense_output(unsigned char r, unsigned char g, unsigned char b, unsigned char rumble_l, unsigned char rumble_r) {
    HANDLE h = open_dualsense_hid();
    if (h == INVALID_HANDLE_VALUE) return;

    unsigned char report[48] = {0};
    report[0] = 0x02; // DualSense USB output report ID
    report[1] = 0xFF; // Valid flags 1: enable rumble motors, lightbar
    report[2] = 0xF7; // Valid flags 2
    report[3] = rumble_r; // High frequency rumble motor
    report[4] = rumble_l; // Low frequency heavy rumble motor
    report[9] = r;        // Lightbar Red
    report[10] = g;       // Lightbar Green
    report[11] = b;       // Lightbar Blue

    DWORD written = 0;
    const BOOL ok = WriteFile(h, report, sizeof(report), &written, nullptr);
    static volatile LONG s_rumble_logged = 0, s_fail_logged = 0;
    if ((rumble_l || rumble_r) && InterlockedIncrement(&s_rumble_logged) <= 6) {
        char line[120];
        sprintf_s(line, "DualSense rumble write L=%u R=%u -> %s (bytes=%lu err=%lu)", rumble_l, rumble_r, ok ? "ok" : "FAILED",
                  written, ok ? 0ul : GetLastError());
        log_line(line);
    } else if (!ok && InterlockedIncrement(&s_fail_logged) <= 3) {
        char line[96];
        sprintf_s(line, "DualSense HID write failed (err=%lu)", GetLastError());
        log_line(line);
    }
    if (!ok) {
        CloseHandle(g_hDualSenseHID);
        g_hDualSenseHID = INVALID_HANDLE_VALUE;
    }
}

// HID enumeration and WriteFile can block for milliseconds to seconds, so they run off the game thread.
static std::atomic<unsigned long long> g_hid_request{0};
static HANDLE g_hid_wake = nullptr;
static std::atomic<bool> g_hid_started{false};

static DWORD WINAPI hid_thread(LPVOID) {
    ULONGLONG next_retry = 0;
    for (;;) {
        WaitForSingleObject(g_hid_wake, 250); // heartbeat keeps the lightbar after controller resets
        const ULONGLONG now = GetTickCount64();
        if (now < next_retry) continue;
        const unsigned long long req = g_hid_request.load();
        write_dualsense_output(static_cast<unsigned char>(req), static_cast<unsigned char>(req >> 8),
                               static_cast<unsigned char>(req >> 16), static_cast<unsigned char>(req >> 24),
                               static_cast<unsigned char>(req >> 32));
        if (g_hDualSenseHID == INVALID_HANDLE_VALUE) next_retry = now + 3000;
    }
}

static void send_dualsense_output(unsigned char r, unsigned char g, unsigned char b, unsigned char rumble_l, unsigned char rumble_r) {
    const unsigned long long packed = static_cast<unsigned long long>(r) | (static_cast<unsigned long long>(g) << 8) |
                                      (static_cast<unsigned long long>(b) << 16) |
                                      (static_cast<unsigned long long>(rumble_l) << 24) |
                                      (static_cast<unsigned long long>(rumble_r) << 32);
    const unsigned long long previous = g_hid_request.exchange(packed);
    if (!g_hid_started.exchange(true)) {
        g_hid_wake = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        HANDLE thread = g_hid_wake ? CreateThread(nullptr, 0, hid_thread, nullptr, 0, nullptr) : nullptr;
        if (thread) CloseHandle(thread);
    }
    if (previous != packed && g_hid_wake) SetEvent(g_hid_wake);
}

static void update_haptics() {
    const ULONGLONG now = GetTickCount64();
    unsigned char rumble_l = 0;
    unsigned char rumble_r = 0;
    if (now < g_haptic.expire_tick) {
        rumble_l = static_cast<unsigned char>(g_haptic.left_motor >> 8);
        rumble_r = static_cast<unsigned char>(g_haptic.right_motor >> 8);
    }
    send_dualsense_output(g_led_r, g_led_g, g_led_b, rumble_l, rumble_r);
}

static BOOL CALLBACK enum_dualsense_callback(LPCDIDEVICEINSTANCEA lpddi, LPVOID pvRef) {
    auto pGuid = reinterpret_cast<GUID*>(pvRef);
    *pGuid = lpddi->guidInstance;
    return DIENUM_STOP;
}

static void safe_adjust_camera_pitch(short tilt_delta, bool reset) {
    if (base != 0x400000) return;
    __try {
        auto* cam = reinterpret_cast<unsigned char*>(base + 0x864560);
        if (cam) {
            short& tilt = *reinterpret_cast<short*>(cam + 0xFE);  // Camera tilt angle
            short& rot_x = *reinterpret_cast<short*>(cam + 0xB0); // Camera rotation X (pitch)
            if (reset) {
                tilt = 0;
                rot_x = 0;
            } else if (tilt_delta != 0) {
                int new_tilt = tilt + tilt_delta;
                if (new_tilt < -600) new_tilt = -600;
                if (new_tilt > 600) new_tilt = 600;
                tilt = static_cast<short>(new_tilt);
                rot_x = tilt;
            }
        }
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {}
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

    {   // One-off diagnostic: raw axes tell which DirectInput axis is the right stick and which are the triggers.
        static ULONGLONG s_next_axes_log = 0;
        static int s_axes_logged = 0;
        const ULONGLONG axes_now = GetTickCount64();
        if (s_axes_logged < 4 && axes_now >= s_next_axes_log) {
            s_next_axes_log = axes_now + 3000;
            ++s_axes_logged;
            char line[140];
            sprintf_s(line, "DualSense axes lX=%ld lY=%ld lZ=%ld lRx=%ld lRy=%ld lRz=%ld", js.lX, js.lY, js.lZ, js.lRx, js.lRy, js.lRz);
            log_line(line);
        }
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

    // Right stick: lZ = X, lRz = Y. lRx/lRy are the analog triggers (rest value 0), never camera axes.
    const auto stick_unit = [&](LONG raw) -> double { // -1..1 after the dead zone, 0 inside it
        const LONG offset = raw - kCenter;
        if (std::abs(offset) <= kDeadzone) return 0.0;
        const double scaled = (std::abs(offset) - kDeadzone) / static_cast<double>(kCenter - kDeadzone);
        return std::min(1.0, scaled) * (offset < 0 ? -1.0 : 1.0);
    };
    const double cam_x = stick_unit(js.lZ);
    const double cam_y = stick_unit(js.lRz);
    const LONG v_axis = static_cast<LONG>(cam_y * 32768.0);

    // The engine only orbits at one fixed speed (L2/R2), so deflection sets how often those presses fire.
    static double s_orbit_accum = 0.0;
    bool cam_left = false, cam_right = false;
    if (cam_x != 0.0) {
        s_orbit_accum += std::fabs(cam_x) * std::fabs(cam_x);
        if (s_orbit_accum >= 1.0) {
            s_orbit_accum -= 1.0;
            (cam_x < 0 ? cam_left : cam_right) = true;
        }
    } else {
        s_orbit_accum = 0.0;
    }

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
    const bool btn_start    = btn(9) || btn(12);
    const bool btn_touchpad = btn(13) || btn_select;

    static bool s_prev_ds_map = false;
    {   // Settings panel by pad: Create opens/closes it on menu screens, D-pad moves, cross saves, circle closes.
        static bool p_up = false, p_down = false, p_left = false, p_right = false, p_cross = false, p_circle = false, p_create = false;
        auto edge = [](bool now, bool& prev) { const bool e = now && !prev; prev = now; return e; };
        const bool fg = game_is_foreground();
        const bool e_up = edge(dpad_up, p_up), e_down = edge(dpad_down, p_down), e_left = edge(dpad_left, p_left);
        const bool e_right = edge(dpad_right, p_right), e_cross = edge(btn_cross, p_cross), e_circle = edge(btn_circle, p_circle);
        const bool e_create = edge(btn_select, p_create);
        if (fg && g_settings_visible) {
            settings::g_pad_nav = {e_up, e_down, e_left, e_right, e_cross, e_circle, e_create};
        } else if (fg && g_menu_hint && e_create) {
            settings::g_pad_nav.toggle = true;
        }
    }
    if (!game_is_foreground()) {
        // edge state still updates below, so a button held while refocusing does not toggle
    } else if (g_menu_hint || g_settings_visible) {
        // Create belongs to the settings panel on menu screens; the map only makes sense in the world
    } else if (btn_touchpad && !s_prev_ds_map) {
        g_map_visible = !g_map_visible;
        log_line(g_map_visible ? "Nosgoth Exploration Map opened" : "Nosgoth Exploration Map closed");
        render_vector_subtitle(L"");
    } else if (g_map_visible && btn_circle) {
        g_map_visible = false;
        render_vector_subtitle(L"");
        log_line("Nosgoth Exploration Map closed");
    }
    s_prev_ds_map = btn_touchpad;

    bool final_move_up   = move_up;
    bool final_move_down = move_down;
    bool act_move_left = move_left;
    bool act_move_right = move_right;
    bool act_sq = btn_square;
    bool act_cr = btn_cross;
    bool act_tr = btn_triangle;
    bool act_circle = btn_circle;

    if (g_map_visible || g_settings_visible) {
        final_move_up = false;
        final_move_down = false;
        act_move_left = false;
        act_move_right = false;
        act_sq = false;
        act_cr = false;
        act_tr = false;
        act_circle = false;
    }

    bool analog_walk = false;
    LONG stick_dx = js.lX - kCenter;
    LONG stick_dy = js.lY - kCenter;
    double stick_dist = sqrt(static_cast<double>(stick_dx * stick_dx + stick_dy * stick_dy));

    if (base == 0x400000 && !g_map_visible && !g_settings_visible) {
        if (btn_r3) {
            safe_adjust_camera_pitch(0, true);
        } else if (v_axis != 0) {
            const double eased = cam_y * std::fabs(cam_y); // fine control near the center
            const short step = static_cast<short>(std::lround(-eased * 26.0));
            if (step != 0) safe_adjust_camera_pitch(step, false);
        }

        auto* cam = reinterpret_cast<unsigned char*>(base + 0x864560);
        auto* player = *reinterpret_cast<unsigned char**>(base + 0x866d4c);
        if (player && stick_dist > kDeadzone && !btn_r1) {
            double angle_rad = atan2(static_cast<double>(stick_dx), -static_cast<double>(stick_dy));
            short stick_psx = static_cast<short>((angle_rad / (2.0 * 3.14159265358979323846)) * 4096.0);
            short cam_yaw = cam ? *reinterpret_cast<short*>(cam + 0x138) : 0;
            short target_yaw = (cam_yaw + stick_psx) & 0x0FFF;

            short& player_yaw = *reinterpret_cast<short*>(player + 0x50);
            short diff = (target_yaw - player_yaw) & 0x0FFF;
            if (diff > 2048) diff -= 4096;
            player_yaw = (player_yaw + (diff / 4)) & 0x0FFF;

            if (stick_dist < 18000) {
                analog_walk = true;
            }
        }
    }

    auto pad1_ptr = *reinterpret_cast<unsigned char**>(base + 0x8651c8);
    if (!pad1_ptr) pad1_ptr = reinterpret_cast<unsigned char*>(base + 0x861040);
    if (pad1_ptr) {
        pad1_ptr[0] = 0;
        pad1_ptr[1] = 0x41;
        uint16_t& buttons = *reinterpret_cast<uint16_t*>(pad1_ptr + 2);

        if (btn_start)    buttons &= ~0x0008;
        if (final_move_up)   buttons &= ~0x0010;
        if (act_move_right)  buttons &= ~0x0020;
        if (final_move_down) buttons &= ~0x0040;
        if (act_move_left)   buttons &= ~0x0080;
        if (btn_l2)       buttons &= ~0x0100;
        if (btn_r2)       buttons &= ~0x0200;
        if (btn_l1)       buttons &= ~0x0400;
        if (btn_r1)       buttons &= ~0x0800;
        if (act_tr)       buttons &= ~0x1000;
        if (act_circle)   buttons &= ~0x2000;
        if (act_cr)       buttons &= ~0x4000;
        if (act_sq)       buttons &= ~0x8000;
    }

    auto pad0_ptr = reinterpret_cast<unsigned char*>(base + 0x860f60);
    if (pad0_ptr) {
        uint16_t& buttons0 = *reinterpret_cast<uint16_t*>(pad0_ptr + 2);
        if (btn_start)    buttons0 &= ~0x0008;
        if (final_move_up)   buttons0 &= ~0x0010;
        if (act_move_right)  buttons0 &= ~0x0020;
        if (final_move_down) buttons0 &= ~0x0040;
        if (act_move_left)   buttons0 &= ~0x0080;
        if (btn_l2)       buttons0 &= ~0x0100;
        if (btn_r2)       buttons0 &= ~0x0200;
        if (btn_l1)       buttons0 &= ~0x0400;
        if (btn_r1)       buttons0 &= ~0x0800;
        if (act_tr)       buttons0 &= ~0x1000;
        if (act_circle)   buttons0 &= ~0x2000;
        if (act_cr)       buttons0 &= ~0x4000;
        if (act_sq)       buttons0 &= ~0x8000;
    }

    auto kbd = reinterpret_cast<unsigned char*>(base + 0x866900);
    if (kbd) {
        if (final_move_up)   kbd[0xc8] |= 0x80;
        if (final_move_down) kbd[0xd0] |= 0x80;
        if (act_move_left)   kbd[0xcb] |= 0x80;
        if (act_move_right)  kbd[0xcd] |= 0x80;
        if (act_sq)          kbd[0x1e] |= 0x80;
        if (act_cr)          kbd[0x2d] |= 0x80;
        if (act_circle)      kbd[0x20] |= 0x80;
        if (act_tr)          kbd[0x21] |= 0x80;
        if (btn_l1)          kbd[0x1f] |= 0x80;
        if (btn_r1 || analog_walk) kbd[0x2e] |= 0x80;
        if (btn_l2)          kbd[0x52] |= 0x80;
        if (btn_r2)          kbd[0x9d] |= 0x80;
        if (btn_start)       kbd[0x01] |= 0x80;
    }

    HWND target_wnd = get_game_hwnd();
    if (btn_start && !g_prev_start_pressed) {
        *reinterpret_cast<DWORD*>(base + 0x8542f4) = 1;
        if (target_wnd) PostMessageA(target_wnd, WM_KEYDOWN, VK_ESCAPE, 0x00010001);
    } else if (!btn_start && g_prev_start_pressed) {
        if (target_wnd) PostMessageA(target_wnd, WM_KEYUP, VK_ESCAPE, 0xc0010001);
    }
    g_prev_start_pressed = btn_start;

    if (act_cr) {
        if (target_wnd) PostMessageA(target_wnd, WM_KEYDOWN, VK_SPACE, 0x00390001);
    }

    static bool prev_cr = false;
    if (btn_cross && !prev_cr && !g_map_visible && game_is_foreground()) trigger_rumble(0x4000, 0x8000, 90); // Jump
    prev_cr = btn_cross;

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

    static int s_hook_frames = 0;
    ++s_hook_frames;
    HWND game_wnd = get_game_hwnd();
    if (game_wnd && s_hook_frames > 60) {
        static HWND s_styled_wnd = nullptr;
        if (s_styled_wnd != game_wnd) {
            s_styled_wnd = game_wnd;
            wchar_t icon_path[MAX_PATH];
            swprintf_s(icon_path, L"%ssoul-reaver.ico", directory().c_str());
            HICON hIcon = (HICON)LoadImageW(nullptr, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE);
            if (hIcon) {
                SendMessageW(game_wnd, WM_SETICON, ICON_BIG, (LPARAM)hIcon);
                SendMessageW(game_wnd, WM_SETICON, ICON_SMALL, (LPARAM)hIcon);
                SetClassLongPtrW(game_wnd, GCLP_HICON, (LONG_PTR)hIcon);
                SetClassLongPtrW(game_wnd, GCLP_HICONSM, (LONG_PTR)hIcon);
                log_line("High-resolution window icon applied");
            }

            log_line("Borderless windowed mode active via dgVoodoo2");
            install_window_trace(game_wnd);
        }
    }

    keep_window_trace_outermost();

    // Keyboard map toggle ('M', only while the game is focused) & smoke-test map flag
    const bool in_focus = game_is_foreground();
    const bool kbd_map = in_focus && ((GetAsyncKeyState('M') & 0x8000) != 0);
    static bool s_prev_kbd_map = false;
    const std::wstring map_flag = directory() + L".soul-reaver-ptbr\\toggle-map.flag";
    const bool has_map_flag = (GetFileAttributesW(map_flag.c_str()) != INVALID_FILE_ATTRIBUTES);
    if (has_map_flag) DeleteFileW(map_flag.c_str());

    if ((kbd_map && !s_prev_kbd_map) || has_map_flag) {
        g_map_visible = !g_map_visible;
        log_line(g_map_visible ? "Nosgoth Exploration Map opened" : "Nosgoth Exploration Map closed");
        render_vector_subtitle(L"");
    } else if (g_map_visible && in_focus && ((GetAsyncKeyState(VK_ESCAPE) & 0x8000) != 0)) {
        g_map_visible = false;
        render_vector_subtitle(L"");
        log_line("Nosgoth Exploration Map closed");
    }
    s_prev_kbd_map = kbd_map;

    {   // Smoke-test aid: test-padnav.flag replays Create, right, cross, circle through the pad navigation path once.
        static int s_step = -1;
        static ULONGLONG s_next = 0;
        const ULONGLONG tick = GetTickCount64();
        const std::wstring nav_flag = directory() + L".soul-reaver-ptbr/test-padnav.flag";
        if (s_step < 0 && GetFileAttributesW(nav_flag.c_str()) != INVALID_FILE_ATTRIBUTES) {
            DeleteFileW(nav_flag.c_str());
            s_step = 0;
            s_next = tick;
        }
        if (s_step >= 0 && tick >= s_next) {
            settings::PadNav nav{};
            if (s_step == 0) nav.toggle = true;
            else if (s_step == 1) nav.right = true;
            else if (s_step == 2) nav.confirm = true;
            else if (s_step == 3) nav.back = true;
            settings::g_pad_nav = nav;
            log_line("Pad navigation test step");
            s_next = tick + 700;
            if (++s_step > 3) s_step = -1;
        }
    }

    const bool settings_owns_keys = settings::poll_keys(in_focus, g_settings_visible);
    if (settings_owns_keys) {
        g_map_visible = false;
        memset(reinterpret_cast<void*>(base + 0x866900), 0, 256); // keep arrows/Enter away from the game
    }

    // Smoke-test aid: while test-subtitle.flag exists, show a sample subtitle through the normal overlay path.
    {
        static ULONGLONG s_last_test_check = 0;
        static bool s_test_subtitle_on = false;
        const ULONGLONG tick = GetTickCount64();
        if (tick - s_last_test_check >= 250) {
            s_last_test_check = tick;
            const std::wstring flag = directory() + L".soul-reaver-ptbr\\test-subtitle.flag";
            const bool want = GetFileAttributesW(flag.c_str()) != INVALID_FILE_ATTRIBUTES;
            if (want) render_vector_subtitle(L"Conheço você, Raziel. É digno.");
            else if (s_test_subtitle_on) render_vector_subtitle(L"");
            s_test_subtitle_on = want;
            g_test_subtitle_active = want;
        }
    }

    {   // Smoke-test aid: test-rumble.flag fires one soul-absorb pulse and is consumed.
        const std::wstring rumble_flag = directory() + L".soul-reaver-ptbr/test-rumble.flag";
        if (GetFileAttributesW(rumble_flag.c_str()) != INVALID_FILE_ATTRIBUTES) {
            DeleteFileW(rumble_flag.c_str());
            trigger_rumble(0x6000, 0xd000, 400);
        }
    }

    {   // Smoke-test aid: test-camera.flag nudges the camera pitch down by 100 like a right-stick push and logs the tilt.
        static ULONGLONG s_camera_check_at = 0;
        static short s_tilt_before = 0;
        const auto read_tilt = []() -> short {
            short value = 0;
            __try { value = *reinterpret_cast<short*>(base + 0x864560 + 0xFE); } __except (EXCEPTION_EXECUTE_HANDLER) {}
            return value;
        };
        const std::wstring camera_flag = directory() + L".soul-reaver-ptbr/test-camera.flag";
        if (GetFileAttributesW(camera_flag.c_str()) != INVALID_FILE_ATTRIBUTES) {
            DeleteFileW(camera_flag.c_str());
            s_tilt_before = read_tilt();
            safe_adjust_camera_pitch(-100, false);
            s_camera_check_at = GetTickCount64() + 600;
            char line[96];
            sprintf_s(line, "Camera test: tilt %d -> %d right after push", s_tilt_before, read_tilt());
            log_line(line);
        } else if (s_camera_check_at && GetTickCount64() >= s_camera_check_at) {
            s_camera_check_at = 0;
            char line[96];
            sprintf_s(line, "Camera test: tilt %d 600 ms later (before=%d)", read_tilt(), s_tilt_before);
            log_line(line);
        }
    }

    static bool s_prev_space = false;
    const bool space_down = (GetAsyncKeyState(VK_SPACE) & 0x8000) != 0;
    if (space_down && !s_prev_space && !g_map_visible && game_is_foreground()) {
        trigger_rumble(0x4000, 0x8000, 90); // Jump (global key state: never react to typing in other apps)
    }
    s_prev_space = space_down;

    poll_dualsense_and_inject();

    // DualSense Dynamic Lightbar & Haptics: Soul Absorption (Emerald Green), Realm & Health
    static ULONGLONG s_last_lightbar_update = 0;
    static ULONGLONG s_soul_absorb_expire = 0;
    static int s_prev_health = -1;
    const ULONGLONG now = GetTickCount64();
    if (now - s_last_lightbar_update >= 100) {
        s_last_lightbar_update = now;

        PlayerState ps;
        safe_read_player_state(ps);
        int realm = ps.realm;
        int health = ps.health;

        // Detect soul absorption / health recovery
        if (s_prev_health != -1 && health > s_prev_health) {
            s_soul_absorb_expire = now + 900; // 900 ms Soul Absorption active window
            trigger_rumble(0x6000, 0xd000, 400); // Crescendo haptic pulse
            log_line("Soul absorbed: DualSense crescendo haptic pulse and Soul Green LED triggered");
        }
        s_prev_health = health;

        unsigned char r = 0, g = 110, b = 255;
        if (now < s_soul_absorb_expire) {
            // Soul Absorption: Brilliant Emerald Green (#00FF66)
            r = 0;
            g = 255;
            b = 102;
        } else if (health < 25) {
            bool pulse = ((now / 250) % 2) == 0;
            r = pulse ? 255 : 80;
            g = pulse ? 15 : 0;
            b = pulse ? 20 : 0;
        } else if (realm == 1) {
            r = 0;
            g = 255;
            b = 180;
        } else {
            r = 0;
            g = 110;
            b = 255;
        }

        g_led_r = r; g_led_g = g; g_led_b = b;

        static unsigned char prev_r = 0, prev_g = 0, prev_b = 0;
        if (r != prev_r || g != prev_g || b != prev_b) {
            prev_r = r; prev_g = g; prev_b = b;
            send_dualsense_output(r, g, b, 0, 0);

            wchar_t path[MAX_PATH];
            // Live status only: the ownership journal lives in controller-journal.json.
            swprintf_s(path, L"%s.soul-reaver-ptbr\\controller-runtime.json", directory().c_str());
            HANDLE hFile = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
            if (hFile != INVALID_HANDLE_VALUE) {
                char json[256];
                sprintf_s(json, "{\"connected\":true,\"realm\":%d,\"health\":%d,\"lightbar\":{\"r\":%d,\"g\":%d,\"b\":%d}}\r\n",
                          realm, health, r, g, b);
                DWORD written = 0;
                WriteFile(hFile, json, static_cast<DWORD>(strlen(json)), &written, nullptr);
                CloseHandle(hFile);
            }
        }
    }
}

static bool install_engine_optimizations() {
    if (base != 0x400000) return false;

    // Multicore CPU Affinity lock to Core 0 (prevents timing desync, audio stutter and multithread crashes)
    // Only the game thread is pinned; overlay/HID worker threads must run on other cores.
    SetThreadAffinityMask(GetCurrentThread(), 1);

    // Expand default fog distance (Far=22000, Near=20000) to double draw distance and eliminate pop-in
    DWORD old_p;
    auto* fog_far = reinterpret_cast<uint16_t*>(base + 0xf5f40);
    auto* fog_near = reinterpret_cast<uint16_t*>(base + 0xf5f44);
    if (VirtualProtect(fog_far, sizeof(uint32_t) * 2, PAGE_EXECUTE_READWRITE, &old_p)) {
        *fog_far = 22000;
        *fog_near = 20000;
        VirtualProtect(fog_far, sizeof(uint32_t) * 2, old_p, &old_p);
    }

    // The former 0x47DA4A/0x47DA7D "audio ring buffer" patch was removed: both sites live in the FMV player
    // (0x47D920), not room streaming, and a 64 KB movie sound buffer can delay cutscene audio against video.

    // Restore Spectral Realm Vertex Mesh Morphing (GTE Per-Vertex Sine Distortion)
    const unsigned char exp_morph_jump[] = { 0x74, 0x31 };
    const unsigned char pat_morph_jump[] = { 0x90, 0x90 };
    if (patch_memory_bytes(base + 0x5a18a, exp_morph_jump, pat_morph_jump, sizeof(exp_morph_jump))) {
        log_line("Spectral Realm vertex mesh morphing restored (continuous geometry warp)");
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
    AddVectoredExceptionHandler(1, trace_exception);
    start_startup_profiler();
    start_frame_capture();
    start_archive_prefetch();
    install_area_trace();
    install_fmv_trace();
    settings::load();
    log_line(settings::install_registry_override() ? "Settings override hook active (ScreenWidth/ScreenHeight)" : "Settings override hook guard failed");
    log_line(install_single_intro_patch() ? "Single intro patch active (publisher logo only)" : "Single intro patch guard failed");
    if (install_skip_setup_dialog_patch()) log_line("Launcher setup dialog auto-confirmed (saved setup reused)");
    log_line(install_hd_textures_hook() ? (g_hd_textures_active ? "HD textures: 1024x1024 pages active (hd-textures/page-NNNN.raw)" : "HD textures: not installed (no hd-textures/page-0000.raw, disable flag, or guard mismatch)")
                                        : "HD texture hook guard failed");
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
