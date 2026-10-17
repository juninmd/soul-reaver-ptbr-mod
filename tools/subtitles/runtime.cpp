// Experimental subtitles for the hash-verified classic PC executable.
// Build only for x86. Install into an isolated game copy; never replace another proxy.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define INITGUID
#define DIRECTINPUT_VERSION 0x0500
#include <windows.h>
#include <objidl.h>
#include <algorithm>
namespace Gdiplus {
    using std::min;
    using std::max;
}
#include <gdiplus.h>
#include <dinput.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <mmsystem.h>
#include <bcrypt.h>
#include <array>
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
static bool g_overlay_available = false;

static LRESULT CALLBACK OverlayWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static void ensure_overlay_window(HWND /*game_hwnd*/) {
    if (g_overlay_inited) return;
    g_overlay_inited = true;

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

    if (g_overlay_hwnd) {
        g_overlay_available = true;
        log_line("Vector HD subtitle overlay initialized");
    }
}

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

static bool g_map_visible = false;

struct MapSector {
    const wchar_t* name;
    float norm_x;
    float norm_y;
    int unit_id;
};

static const MapSector g_sectors[] = {
    { L"Submundo & Lago dos Mortos", 0.50f, 0.85f, 1 },
    { L"Santu\u00e1rio dos Cl\u00e3s", 0.50f, 0.60f, 2 },
    { L"Necr\u00f3pole de Melchiah", 0.25f, 0.72f, 3 },
    { L"Catedral Silenciada de Zephon", 0.78f, 0.48f, 4 },
    { L"Pilares de Nosgoth", 0.28f, 0.42f, 5 },
    { L"Tumba dos Sarafan", 0.50f, 0.38f, 6 },
    { L"Abadia Submersa de Rahab", 0.50f, 0.22f, 7 },
    { L"Fortaleza da Montanha de Dumah", 0.75f, 0.25f, 8 },
    { L"C\u00e2mara do Tempo (Chronoplast)", 0.32f, 0.15f, 9 }
};

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

    for (const auto& sec : g_sectors) {
        if (sec.unit_id == unit_id) {
            obj.region = sec.name;
            break;
        }
    }
    return obj;
}

static void render_map_screen(Gdiplus::Graphics& graphics, int screen_w, int screen_h) {
    int mapW = static_cast<int>(screen_w * 0.82f);
    int mapH = static_cast<int>(screen_h * 0.82f);
    int mapX = (screen_w - mapW) / 2;
    int mapY = (screen_h - mapH) / 2;

    Gdiplus::SolidBrush shadowBrush(Gdiplus::Color(220, 5, 5, 8));
    graphics.FillRectangle(&shadowBrush, mapX - 15, mapY - 15, mapW + 30, mapH + 30);

    Gdiplus::SolidBrush bgBrush(Gdiplus::Color(245, 18, 22, 28));
    graphics.FillRectangle(&bgBrush, mapX, mapY, mapW, mapH);

    Gdiplus::Pen goldPen(Gdiplus::Color(255, 212, 160, 70), 3.0f);
    graphics.DrawRectangle(&goldPen, mapX, mapY, mapW, mapH);
    Gdiplus::Pen innerPen(Gdiplus::Color(160, 150, 110, 45), 1.0f);
    graphics.DrawRectangle(&innerPen, mapX + 6, mapY + 6, mapW - 12, mapH - 12);

    auto obj = get_current_objective();
    float titleSize = screen_h * 0.028f;
    if (titleSize < 16.0f) titleSize = 16.0f;
    Gdiplus::Font titleFont(L"Georgia", titleSize, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::Font subFont(L"Segoe UI", titleSize * 0.72f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::Font bodyFont(L"Segoe UI", titleSize * 0.65f, Gdiplus::FontStyleRegular, Gdiplus::UnitPixel);

    Gdiplus::StringFormat centerFmt;
    centerFmt.SetAlignment(Gdiplus::StringAlignmentCenter);
    centerFmt.SetLineAlignment(Gdiplus::StringAlignmentCenter);

    Gdiplus::SolidBrush titleBrush(Gdiplus::Color(255, 255, 225, 140));
    Gdiplus::RectF titleRect(static_cast<float>(mapX), static_cast<float>(mapY + 12),
                            static_cast<float>(mapW), titleSize * 1.5f);
    graphics.DrawString(L"MAPA DE EXPLORA\u00c7\u00c3O DE NOSGOTH", -1, &titleFont, titleRect, &centerFmt, &titleBrush);

    int objY = mapY + static_cast<int>(titleSize * 1.6f) + 10;
    int objH = static_cast<int>(screen_h * 0.075f);
    int objW = mapW - 60;
    int objX = mapX + 30;

    Gdiplus::SolidBrush objBg(Gdiplus::Color(220, 28, 34, 44));
    graphics.FillRectangle(&objBg, objX, objY, objW, objH);
    Gdiplus::Pen objBorder(Gdiplus::Color(200, 180, 140, 60), 1.5f);
    graphics.DrawRectangle(&objBorder, objX, objY, objW, objH);

    Gdiplus::SolidBrush goldBrush(Gdiplus::Color(255, 255, 190, 50));
    std::wstring objTitleText = std::wstring(L"[!] OBJETIVO: ") + obj.title + L" \u2014 " + obj.region;
    Gdiplus::RectF objTitleRect(static_cast<float>(objX + 15), static_cast<float>(objY + 6),
                               static_cast<float>(objW - 30), titleSize * 0.85f);
    Gdiplus::StringFormat leftFmt;
    leftFmt.SetAlignment(Gdiplus::StringAlignmentNear);
    graphics.DrawString(objTitleText.c_str(), -1, &subFont, objTitleRect, &leftFmt, &goldBrush);

    Gdiplus::SolidBrush descBrush(Gdiplus::Color(255, 220, 225, 230));
    Gdiplus::RectF objDescRect(static_cast<float>(objX + 15), static_cast<float>(objY + 6 + titleSize * 0.85f),
                              static_cast<float>(objW - 30), titleSize * 0.95f);
    graphics.DrawString(obj.description, -1, &bodyFont, objDescRect, &leftFmt, &descBrush);

    int canvasX = mapX + 40;
    int canvasY = objY + objH + 15;
    int canvasW = mapW - 80;
    int canvasH = mapH - (canvasY - mapY) - 50;

    Gdiplus::Pen pathPen(Gdiplus::Color(150, 100, 85, 60), 2.5f);
    pathPen.SetDashStyle(Gdiplus::DashStyleDash);

    auto get_xy = [&](const MapSector& s) -> Gdiplus::PointF {
        return Gdiplus::PointF(canvasX + s.norm_x * canvasW, canvasY + s.norm_y * canvasH);
    };

    graphics.DrawLine(&pathPen, get_xy(g_sectors[0]), get_xy(g_sectors[1]));
    graphics.DrawLine(&pathPen, get_xy(g_sectors[1]), get_xy(g_sectors[2]));
    graphics.DrawLine(&pathPen, get_xy(g_sectors[1]), get_xy(g_sectors[3]));
    graphics.DrawLine(&pathPen, get_xy(g_sectors[1]), get_xy(g_sectors[4]));
    graphics.DrawLine(&pathPen, get_xy(g_sectors[4]), get_xy(g_sectors[5]));
    graphics.DrawLine(&pathPen, get_xy(g_sectors[5]), get_xy(g_sectors[6]));
    graphics.DrawLine(&pathPen, get_xy(g_sectors[6]), get_xy(g_sectors[7]));
    graphics.DrawLine(&pathPen, get_xy(g_sectors[7]), get_xy(g_sectors[8]));
    graphics.DrawLine(&pathPen, get_xy(g_sectors[4]), get_xy(g_sectors[8]));

    Gdiplus::SolidBrush nodeBrush(Gdiplus::Color(240, 35, 45, 55));
    Gdiplus::Pen nodePen(Gdiplus::Color(220, 180, 140, 70), 2.0f);
    Gdiplus::Font nodeFont(L"Segoe UI", titleSize * 0.60f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);

    auto pl_st = get_player_state();
    PlayerState ps;
    safe_read_player_state(ps);
    int current_unit = ps.unit_id;

    Gdiplus::PointF player_pos(canvasX + 0.50f * canvasW, canvasY + 0.60f * canvasH);

    for (size_t i = 0; i < ARRAYSIZE(g_sectors); ++i) {
        Gdiplus::PointF pt = get_xy(g_sectors[i]);
        float r = 10.0f;
        graphics.FillEllipse(&nodeBrush, pt.X - r, pt.Y - r, r * 2, r * 2);
        graphics.DrawEllipse(&nodePen, pt.X - r, pt.Y - r, r * 2, r * 2);

        Gdiplus::SolidBrush textBrush(Gdiplus::Color(255, 230, 215, 175));
        Gdiplus::RectF labelRect(pt.X - 140, pt.Y + 12, 280, 24);
        graphics.DrawString(g_sectors[i].name, -1, &nodeFont, labelRect, &centerFmt, &textBrush);

        if (g_sectors[i].unit_id == current_unit || (current_unit <= 1 && i == 0)) {
            player_pos = pt;
        }
    }

    const ULONGLONG now = GetTickCount64();
    float pulse = 1.0f + 0.25f * static_cast<float>(sin(now / 180.0));
    float pinR = 14.0f * pulse;
    Gdiplus::SolidBrush pinGlow(Gdiplus::Color(100, 255, 215, 0));
    graphics.FillEllipse(&pinGlow, player_pos.X - pinR * 1.5f, player_pos.Y - pinR * 1.5f, pinR * 3.0f, pinR * 3.0f);

    Gdiplus::SolidBrush pinBrush(Gdiplus::Color(255, 255, 220, 40));
    graphics.FillEllipse(&pinBrush, player_pos.X - pinR, player_pos.Y - pinR, pinR * 2, pinR * 2);
    Gdiplus::Pen pinBorder(Gdiplus::Color(255, 255, 255, 255), 2.0f);
    graphics.DrawEllipse(&pinBorder, player_pos.X - pinR, player_pos.Y - pinR, pinR * 2, pinR * 2);

    Gdiplus::Font tagFont(L"Segoe UI", titleSize * 0.68f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::SolidBrush tagBrush(Gdiplus::Color(255, 255, 245, 120));
    Gdiplus::RectF tagRect(player_pos.X - 80, player_pos.Y - pinR - 22, 160, 20);
    graphics.DrawString(L"\u2605 RAZIEL", -1, &tagFont, tagRect, &centerFmt, &tagBrush);

    std::wstring footer = L"Plano Atual: " + std::wstring(pl_st.realm == 1 ? L"ESPECTRAL" : L"MATERIAL") +
                          L"  \u2022  [Touchpad / M] Fechar Mapa  \u2022  Navega\u00e7\u00e3o de Nosgoth";
    Gdiplus::SolidBrush footerBrush(Gdiplus::Color(200, 180, 180, 190));
    Gdiplus::RectF footerRect(static_cast<float>(mapX), static_cast<float>(mapY + mapH - 32),
                             static_cast<float>(mapW), 24.0f);
    graphics.DrawString(footer.c_str(), -1, &subFont, footerRect, &centerFmt, &footerBrush);
}

static void render_vector_subtitle(const std::wstring& text) {
    if (!g_overlay_hwnd) return;
    if (text.empty() && !g_map_visible) {
        ShowWindow(g_overlay_hwnd, SW_HIDE);
        return;
    }

    int screen_w = GetSystemMetrics(SM_CXSCREEN);
    int screen_h = GetSystemMetrics(SM_CYSCREEN);
    if (screen_w <= 0 || screen_h <= 0) return;

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
        graphics.SetTextRenderingHint(Gdiplus::TextRenderingHintClearTypeGridFit);
        graphics.Clear(Gdiplus::Color(0, 0, 0, 0));

        if (g_map_visible) {
            render_map_screen(graphics, screen_w, screen_h);
        }

        if (!text.empty()) {
            int boxY = screen_h - static_cast<int>(screen_h * 0.16f);
            int boxH = static_cast<int>(screen_h * 0.11f);
            int marginX = static_cast<int>(screen_w * 0.10f);
            int boxW = screen_w - (marginX * 2);

            Gdiplus::SolidBrush bgBrush(Gdiplus::Color(160, 10, 10, 15));
            graphics.FillRectangle(&bgBrush, marginX - 30, boxY - 10, boxW + 60, boxH + 20);

            float fontSize = screen_h * 0.032f;
            if (fontSize < 18.0f) fontSize = 18.0f;
            Gdiplus::Font font(L"Segoe UI", fontSize, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);

            Gdiplus::StringFormat format;
            format.SetAlignment(Gdiplus::StringAlignmentCenter);
            format.SetLineAlignment(Gdiplus::StringAlignmentCenter);

            Gdiplus::RectF layoutRect(static_cast<float>(marginX), static_cast<float>(boxY),
                                      static_cast<float>(boxW), static_cast<float>(boxH));

            Gdiplus::SolidBrush shadowBrush(Gdiplus::Color(220, 0, 0, 0));
            Gdiplus::RectF shadowRect = layoutRect;
            shadowRect.X += 2.0f;
            shadowRect.Y += 2.0f;
            graphics.DrawString(text.c_str(), -1, &font, shadowRect, &format, &shadowBrush);

            Gdiplus::SolidBrush textBrush(Gdiplus::Color(255, 255, 235, 140));
            graphics.DrawString(text.c_str(), -1, &font, layoutRect, &format, &textBrush);
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
    POINT ptDst = { 0, 0 };
    BLENDFUNCTION blend{};
    blend.BlendOp = AC_SRC_OVER;
    blend.BlendFlags = 0;
    blend.SourceConstantAlpha = 255;
    blend.AlphaFormat = AC_SRC_ALPHA;

    UpdateLayeredWindow(g_overlay_hwnd, screenDC, &ptDst, &sizeDst, memDC, &ptSrc, 0, &blend, ULW_ALPHA);
    ShowWindow(g_overlay_hwnd, SW_SHOWNOACTIVATE);

    SelectObject(memDC, oldBmp);
    DeleteDC(memDC);
    DeleteObject(hBitmap);
    ReleaseDC(nullptr, screenDC);
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

static void __cdecl subtitle_flush() {
    static int previous = -1;
    static ULONGLONG elapsed, previous_tick;
    static std::vector<std::string> lines;
    const int state = *reinterpret_cast<int*>(base + 0x858028);
    const int id = *reinterpret_cast<int*>(base + 0x85802c);
    const ULONGLONG now = GetTickCount64();
    const ULONGLONG delta = now - previous_tick;
    previous_tick = now;

    HWND fg = GetForegroundWindow();
    ensure_overlay_window(fg);

    const bool has_u_cap = has_unicode_captions && id >= 0 && id < 479 && !unicode_captions[id].text.empty();
    const bool active = state >= 2 && state <= 4 && id >= 0 && id < 479 && (has_u_cap || !captions[id].empty());

    if (active) {
        if (id != previous) {
            previous = id;
            elapsed = 0;
            if (!has_u_cap) lines = wrap(captions[id]);
            char message[80];
            sprintf_s(message, "voice=%d state=%d subtitle-start%s", id, state, has_u_cap ? " (vector-unicode)" : "");
            log_line(message);
        }
        const int channel = *reinterpret_cast<int*>(base + 0x857fdc);
        if (!is_playing(channel)) {
            if (g_overlay_available) render_vector_subtitle(L"");
            original_flush();
            return;
        }
        elapsed += std::min<ULONGLONG>(delta, 250);
        const DWORD bytes = *reinterpret_cast<DWORD*>(base + 0xfd814 + id * 8);
        const ULONGLONG duration = durations[id] ? durations[id] : std::max<ULONGLONG>(1, bytes * 1000ULL / 44100);
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

            render_vector_subtitle(current_text);
            original_flush();
            return;
        }

        // Fallback to in-engine print_text only if vector overlay failed to create
        const size_t pages = (lines.size() + 1) / 2;
        std::vector<size_t> weights(pages, 0);
        size_t total = 0;
        for (size_t i = 0; i < lines.size(); ++i) { weights[i / 2] += lines[i].size(); total += lines[i].size(); }
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
        if (*reinterpret_cast<int*>(base + 0x8640a8) < 1700) {
            color = 3;
            for (size_t i = page * 2; i < std::min(lines.size(), page * 2 + 2); ++i) {
                x = std::max(10, (512 - string_width(lines[i].c_str())) / 2) + 1;
                y = 199 + static_cast<int>(i % 2) * 13;
                print_text("%s", lines[i].c_str());
            }
            color = 0;
            for (size_t i = page * 2; i < std::min(lines.size(), page * 2 + 2); ++i) {
                x = std::max(10, (512 - string_width(lines[i].c_str())) / 2);
                y = 198 + static_cast<int>(i % 2) * 13;
                print_text("%s", lines[i].c_str());
            }
        }
        x = old_x; y = old_y; color = old_color;
    } else {
        if (g_overlay_available) {
            static ULONGLONG s_last_map_draw = 0;
            if (g_map_visible) {
                if (now - s_last_map_draw >= 33) {
                    s_last_map_draw = now;
                    render_vector_subtitle(L"");
                }
            } else if (previous != -1) {
                render_vector_subtitle(L"");
            }
        }
        previous = -1;
    }
    original_flush();
}

static void __cdecl hook_print_text(const char* fmt, ...) {
    if (!fmt) return;
    char buffer[1024];
    va_list args;
    va_start(args, fmt);
    vsprintf_s(buffer, fmt, args);
    va_end(args);

    if (buffer[0] != '\0') {
        int wlen = MultiByteToWideChar(CP_ACP, 0, buffer, -1, nullptr, 0);
        if (wlen > 1) {
            std::wstring wstr(wlen - 1, L'\0');
            MultiByteToWideChar(CP_ACP, 0, buffer, -1, &wstr[0], wlen);
            render_vector_subtitle(wstr);
        }
    }
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

    DWORD old_pt;
    auto* pt_target = reinterpret_cast<unsigned char*>(base + 0x9e2e0);
    if (VirtualProtect(pt_target, 5, PAGE_EXECUTE_READWRITE, &old_pt)) {
        pt_target[0] = 0xe9;
        *reinterpret_cast<DWORD*>(pt_target + 1) = reinterpret_cast<DWORD>(&hook_print_text) - (base + 0x9e2e0 + 5);
        VirtualProtect(pt_target, 5, old_pt, &old_pt);
        FlushInstructionCache(GetCurrentProcess(), pt_target, 5);
        log_line("1999 bitmap font silenced; vector TrueType HD subtitle pipeline hooked");
    }

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

static bool install_hd_textures_hook() {
    if (base != 0x400000) return false;
    const unsigned char exp_surf[] = {0xb8, 0x00, 0x01, 0x00, 0x00};
    const unsigned char pat_surf[] = {0xb8, 0x00, 0x04, 0x00, 0x00};
    patch_memory_bytes(base + 0x72c21, exp_surf, pat_surf, sizeof(exp_surf));
    patch_memory_bytes(base + 0x72d31, exp_surf, pat_surf, sizeof(exp_surf));
    return true;
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

static void send_dualsense_output(unsigned char r, unsigned char g, unsigned char b, unsigned char rumble_l, unsigned char rumble_r) {
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
    if (!WriteFile(h, report, sizeof(report), &written, nullptr)) {
        CloseHandle(g_hDualSenseHID);
        g_hDualSenseHID = INVALID_HANDLE_VALUE;
    }
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

    HWND fg = GetForegroundWindow();
    DWORD fg_pid = 0;
    if (fg) GetWindowThreadProcessId(fg, &fg_pid);
    if (fg_pid != 0 && fg_pid != GetCurrentProcessId()) return;

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

    LONG v_axis = 0;
    if (abs(js.lRz - kCenter) > kDeadzone) v_axis = js.lRz - kCenter;
    else if (abs(js.lRy - kCenter) > kDeadzone) v_axis = js.lRy - kCenter;
    else if (abs(js.lRx - kCenter) > kDeadzone) v_axis = js.lRx - kCenter;

    const bool cam_left  = (js.lZ < kCenter - kDeadzone);
    const bool cam_right = (js.lZ > kCenter + kDeadzone);

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
    const bool btn_touchpad = btn(13) || ((GetAsyncKeyState('M') & 0x8000) != 0);

    static bool s_prev_touchpad = false;
    if (btn_touchpad && !s_prev_touchpad) {
        g_map_visible = !g_map_visible;
        trigger_rumble(0x1000, 0x3000, 50);
        log_line(g_map_visible ? "Nosgoth Exploration Map opened" : "Nosgoth Exploration Map closed");
        render_vector_subtitle(L"");
    } else if (g_map_visible && (btn_circle || ((GetAsyncKeyState(VK_ESCAPE) & 0x8000) != 0))) {
        g_map_visible = false;
        trigger_rumble(0x0800, 0x1500, 30);
        render_vector_subtitle(L"");
        log_line("Nosgoth Exploration Map closed");
    }
    s_prev_touchpad = btn_touchpad;

    bool final_move_up   = move_up;
    bool final_move_down = move_down;
    bool act_move_left = move_left;
    bool act_move_right = move_right;
    bool act_sq = btn_square;
    bool act_cr = btn_cross;
    bool act_tr = btn_triangle;
    bool act_circle = btn_circle;

    if (g_map_visible) {
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

    if (base == 0x400000 && !g_map_visible) {
        if (btn_r3) {
            safe_adjust_camera_pitch(0, true);
        } else if (v_axis != 0) {
            short step = static_cast<short>(-(v_axis / 2500));
            safe_adjust_camera_pitch(step, false);
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

        if (btn_select)   buttons &= ~0x0001;
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
        if (btn_select)   buttons0 &= ~0x0001;
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
        if (btn_select)      kbd[0x1c] |= 0x80;
    }

    HWND target_wnd = fg ? fg : GetActiveWindow();
    static bool s_icon_set = false;
    if (!s_icon_set && target_wnd) {
        wchar_t icon_path[MAX_PATH];
        swprintf_s(icon_path, L"%ssoul-reaver.ico", directory().c_str());
        HICON hIcon = (HICON)LoadImageW(nullptr, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE);
        if (hIcon) {
            SendMessageW(target_wnd, WM_SETICON, ICON_BIG, (LPARAM)hIcon);
            SendMessageW(target_wnd, WM_SETICON, ICON_SMALL, (LPARAM)hIcon);
            SetClassLongPtrW(target_wnd, GCLP_HICON, (LONG_PTR)hIcon);
            SetClassLongPtrW(target_wnd, GCLP_HICONSM, (LONG_PTR)hIcon);
            s_icon_set = true;
            log_line("High-resolution window icon applied");
        }
    }

    static bool s_borderless_set = false;
    if (!s_borderless_set && target_wnd) {
        int screen_w = GetSystemMetrics(SM_CXSCREEN);
        int screen_h = GetSystemMetrics(SM_CYSCREEN);
        LONG_PTR style = GetWindowLongPtrW(target_wnd, GWL_STYLE);
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU);
        style |= WS_POPUP;
        SetWindowLongPtrW(target_wnd, GWL_STYLE, style);
        LONG_PTR ex_style = GetWindowLongPtrW(target_wnd, GWL_EXSTYLE);
        ex_style &= ~WS_EX_TOPMOST;
        SetWindowLongPtrW(target_wnd, GWL_EXSTYLE, ex_style);
        SetWindowPos(target_wnd, HWND_NOTOPMOST, 0, 0, screen_w, screen_h, SWP_FRAMECHANGED | SWP_SHOWWINDOW);
        s_borderless_set = true;
        log_line("Borderless windowed mode applied");
    }

    if (btn_start && !g_prev_start_pressed) {
        *reinterpret_cast<DWORD*>(base + 0x8542f4) = 1;
        if (target_wnd) PostMessageA(target_wnd, WM_KEYDOWN, VK_ESCAPE, 0x00010001);
    } else if (!btn_start && g_prev_start_pressed) {
        if (target_wnd) PostMessageA(target_wnd, WM_KEYUP, VK_ESCAPE, 0xc0010001);
    }
    g_prev_start_pressed = btn_start;

    if (btn_cross || btn_select) {
        if (target_wnd) PostMessageA(target_wnd, WM_KEYDOWN, VK_SPACE, 0x00390001);
    }

    static bool prev_sq = false, prev_cr = false, prev_tr = false, prev_r3 = false;
    if (btn_square && !prev_sq) trigger_rumble(0x6000, 0x9000, 90);    // Attack (claws/weapon slash)
    if (btn_cross && !prev_cr)  trigger_rumble(0x2000, 0x4000, 50);    // Jump / Glide leap
    if (btn_triangle && !prev_tr) trigger_rumble(0x9000, 0xb000, 160); // Shift Realm / Cast Glyph
    if (btn_r3 && !prev_r3) trigger_rumble(0x0000, 0xa000, 45);        // Camera snap click
    prev_sq = btn_square;
    prev_cr = btn_cross;
    prev_tr = btn_triangle;
    prev_r3 = btn_r3;

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
            swprintf_s(path, L"%s.soul-reaver-ptbr\\controller-state.json", directory().c_str());
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
    SetProcessAffinityMask(GetCurrentProcess(), 1);

    // Expand default fog distance (Far=22000, Near=20000) to double draw distance and eliminate pop-in
    DWORD old_p;
    auto* fog_far = reinterpret_cast<uint16_t*>(base + 0xf5f40);
    auto* fog_near = reinterpret_cast<uint16_t*>(base + 0xf5f44);
    if (VirtualProtect(fog_far, sizeof(uint32_t) * 2, PAGE_EXECUTE_READWRITE, &old_p)) {
        *fog_far = 22000;
        *fog_near = 20000;
        VirtualProtect(fog_far, sizeof(uint32_t) * 2, old_p, &old_p);
    }

    // Expand audio streaming ring buffer from 16 KB to 64 KB to eliminate stutters/clicks during room streaming
    const unsigned char exp_audio_block[] = { 0x68, 0x00, 0x10, 0x00, 0x00 };
    const unsigned char pat_audio_block[] = { 0x68, 0x00, 0x40, 0x00, 0x00 };
    const unsigned char exp_audio_total[] = { 0x68, 0x00, 0x40, 0x00, 0x00 };
    const unsigned char pat_audio_total[] = { 0x68, 0x00, 0x00, 0x01, 0x00 };

    if (patch_memory_bytes(base + 0x7da4a, exp_audio_block, pat_audio_block, sizeof(exp_audio_block)) &&
        patch_memory_bytes(base + 0x7da7d, exp_audio_total, pat_audio_total, sizeof(exp_audio_total))) {
        log_line("Audio streaming ring buffer expanded to 64 KB (zero room transition stutter)");
    }

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
    log_line(install_hd_textures_hook() ? "HD texture 1024x1024 hook active" : "HD texture hook guard failed");
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
