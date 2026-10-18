// In-game settings (F10): internal resolution stored in .soul-reaver-ptbr/settings.ini and served to the
// game by hooking its RegQueryValueExA import, so no elevated HKLM write is needed.
// Included by runtime.cpp after map_render.h; not standalone.
#pragma once

static void render_vector_subtitle(const std::wstring& text);

namespace settings {

struct Mode { int width, height; const wchar_t* label; };

static const Mode kModes[] = {
    {1280, 960, L"1280 × 960  (4:3)"},   {1600, 1200, L"1600 × 1200  (4:3)"},
    {1920, 1440, L"1920 × 1440  (4:3, padrão)"},
    {1920, 1080, L"1920 × 1080  (16:9)"}, {2560, 1440, L"2560 × 1440  (16:9)"},
};
static const int kModeCount = static_cast<int>(sizeof(kModes) / sizeof(kModes[0]));

static std::atomic<int> g_applied_w{0};   // 0 = no override, keep the registry value
static std::atomic<int> g_applied_h{0};
static std::atomic<int> g_pending{2};     // index in kModes while the panel is open
static std::atomic<int> g_row{0};         // 0 = resolution, 1 = sound provider
static std::atomic<int> g_applied_sound{0}; // SoundDeviceID override, 0 = none
static std::atomic<int> g_pending_sound{0}; // index into g_sound_names
static std::vector<std::wstring> g_sound_names; // filled from the setup dialog
static std::atomic<int> g_sound_selected{0};
static std::atomic<bool> g_saved{false};  // "saved, restart" notice

// DualSense navigation, filled once per frame by the input hook (edges only): D-pad, cross = save, circle = close,
// Create = open/close while on a menu screen.
struct PadNav { bool up, down, left, right, confirm, back, toggle; };
static PadNav g_pad_nav{};

static std::wstring ini_path() { return directory() + L".soul-reaver-ptbr/settings.ini"; }

static int mode_index(int w, int h) {
    for (int i = 0; i < kModeCount; ++i)
        if (kModes[i].width == w && kModes[i].height == h) return i;
    return -1;
}

static void load() {
    const std::wstring path = ini_path();
    const int w = static_cast<int>(GetPrivateProfileIntW(L"Video", L"Width", 0, path.c_str()));
    const int h = static_cast<int>(GetPrivateProfileIntW(L"Video", L"Height", 0, path.c_str()));
    const int sound = static_cast<int>(GetPrivateProfileIntW(L"Audio", L"DeviceId", 0, path.c_str()));
    if (sound > 0) g_applied_sound = sound;
    if (mode_index(w, h) < 0) return; // only accept the values this panel can write
    g_applied_w = w;
    g_applied_h = h;
    char line[96];
    sprintf_s(line, "Settings: resolution override %dx%d from settings.ini", w, h);
    log_line(line);
}

static void save_sound(int index) {
    const std::wstring path = ini_path();
    WritePrivateProfileStringW(L"Audio", L"DeviceId", std::to_wstring(index + 1).c_str(), path.c_str());
    char line[96];
    sprintf_s(line, "Settings: saved sound provider index %d (SoundDeviceID=%d, applies on next start)", index, index + 1);
    log_line(line);
}

static void save(int index) {
    const std::wstring path = ini_path();
    WritePrivateProfileStringW(L"Video", L"Width", std::to_wstring(kModes[index].width).c_str(), path.c_str());
    WritePrivateProfileStringW(L"Video", L"Height", std::to_wstring(kModes[index].height).c_str(), path.c_str());
    char line[96];
    sprintf_s(line, "Settings: saved resolution %dx%d (applies on next start)", kModes[index].width, kModes[index].height);
    log_line(line);
}

static LSTATUS (WINAPI* g_original_query)(HKEY, LPCSTR, LPDWORD, LPDWORD, LPBYTE, LPDWORD) = nullptr;

static LSTATUS WINAPI hook_query(HKEY key, LPCSTR name, LPDWORD reserved, LPDWORD type, LPBYTE data, LPDWORD size) {
    int value = 0;
    if (name && !_stricmp(name, "ScreenWidth")) value = g_applied_w;
    else if (name && !_stricmp(name, "ScreenHeight")) value = g_applied_h;
    else if (name && !_stricmp(name, "SoundDeviceID")) value = g_applied_sound;
    if (value > 0) {
        static volatile LONG logged = 0;
        if (InterlockedIncrement(&logged) <= 4) {
            char line[96];
            sprintf_s(line, "Settings: game read %s -> %d (override)", name, value);
            log_line(line);
        }
        if (type) *type = REG_DWORD;
        if (data) {
            if (!size || *size < sizeof(DWORD)) return ERROR_MORE_DATA;
            *reinterpret_cast<DWORD*>(data) = static_cast<DWORD>(value);
        }
        if (size) *size = sizeof(DWORD);
        return ERROR_SUCCESS;
    }
    return g_original_query(key, name, reserved, type, data, size);
}

// kain2.exe imports RegQueryValueExA through the IAT slot at 0x4EC010.
static bool install_registry_override() {
    if (base != 0x400000) return false;
    auto* slot = reinterpret_cast<void**>(base + 0xEC010);
    if (!*slot) return false;
    DWORD old_protect = 0;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old_protect)) return false;
    g_original_query = reinterpret_cast<decltype(g_original_query)>(*slot);
    *slot = reinterpret_cast<void*>(&hook_query);
    VirtualProtect(slot, sizeof(void*), old_protect, &old_protect);
    return true;
}

static bool pressed_edge(int vk, bool& previous) {
    const bool down = (GetAsyncKeyState(vk) & 0x8000) != 0;
    const bool edge = down && !previous;
    previous = down;
    return edge;
}

// Called every frame from the input hook; returns true while the panel owns the keyboard.
static bool poll_keys(bool game_focused, std::atomic<bool>& visible) {
    static bool prev_up = false, prev_down = false;
    const bool key_up = pressed_edge(VK_UP, prev_up), key_down = pressed_edge(VK_DOWN, prev_down);
    static bool prev_f10 = false, prev_left = false, prev_right = false, prev_enter = false, prev_esc = false;
    const bool f10 = pressed_edge(VK_F10, prev_f10), key_left = pressed_edge(VK_LEFT, prev_left);
    const bool key_right = pressed_edge(VK_RIGHT, prev_right), key_enter = pressed_edge(VK_RETURN, prev_enter);
    const bool esc_key = pressed_edge(VK_ESCAPE, prev_esc);
    const PadNav pad = g_pad_nav;
    g_pad_nav = PadNav{};
    if (!game_focused) return visible;
    const bool esc = esc_key || (visible && pad.back);
    if (f10 || pad.toggle) {
        visible = !visible;
        if (visible) {
            const int current = mode_index(g_applied_w, g_applied_h);
            g_pending = current >= 0 ? current : 2;
            g_pending_sound = g_applied_sound > 0 ? g_applied_sound - 1 : g_sound_selected.load();
            g_row = 0;
            g_saved = false;
        }
        log_line(visible ? "Settings panel opened" : "Settings panel closed");
        render_vector_subtitle(L"");
        return visible;
    }
    if (!visible) return false;
    const bool up = key_up || pad.up, down = key_down || pad.down, left = key_left || pad.left, right = key_right || pad.right;
    const bool enter = key_enter || pad.confirm;
    const int sounds = static_cast<int>(g_sound_names.size());
    if (up || down) g_row = sounds > 0 ? 1 - g_row.load() : 0;
    if (g_row == 0) {
        if (left) g_pending = (g_pending + kModeCount - 1) % kModeCount;
        if (right) g_pending = (g_pending + 1) % kModeCount;
    } else if (sounds > 0) {
        if (left) g_pending_sound = (g_pending_sound + sounds - 1) % sounds;
        if (right) g_pending_sound = (g_pending_sound + 1) % sounds;
    }
    if (enter) {
        save(g_pending);
        if (sounds > 0) save_sound(g_pending_sound);
        g_saved = true;
    }
    if (esc) {
        visible = false;
        log_line("Settings panel closed");
    }
    if (left || right || enter || esc || up || down) render_vector_subtitle(L"");
    return true;
}

static void render(Gdiplus::Graphics& g, int screen_w, int screen_h) {
    using Gdiplus::Color;
    const float unit = std::max(16.0f, screen_h * 0.028f);
    const float w = screen_w * 0.46f, h = unit * 11.4f;
    const float x = (screen_w - w) * 0.5f, y = (screen_h - h) * 0.5f;

    Gdiplus::SolidBrush dim(Color(170, 4, 4, 8));
    g.FillRectangle(&dim, 0, 0, screen_w, screen_h);
    Gdiplus::LinearGradientBrush sheet(Gdiplus::PointF(x, y), Gdiplus::PointF(x, y + h), Color(255, 228, 204, 158), Color(255, 190, 150, 96));
    g.FillRectangle(&sheet, x, y, w, h);
    Gdiplus::Pen rim(Color(255, 80, 46, 20), 3.0f), inner(Color(200, 80, 46, 20), 1.2f);
    g.DrawRectangle(&rim, x, y, w, h);
    g.DrawRectangle(&inner, x + 9, y + 9, w - 18, h - 18);

    Gdiplus::StringFormat center;
    center.SetAlignment(Gdiplus::StringAlignmentCenter);
    center.SetLineAlignment(Gdiplus::StringAlignmentCenter);
    Gdiplus::Font title(L"Georgia", unit * 1.1f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::Font label(L"Georgia", unit * 0.72f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::Font value(L"Georgia", unit * 0.9f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::Font note(L"Georgia", unit * 0.6f, Gdiplus::FontStyleItalic, Gdiplus::UnitPixel);
    Gdiplus::SolidBrush red(Color(255, 122, 20, 16)), ink(Color(255, 58, 30, 12)), green(Color(255, 40, 100, 40));

    const bool res_row = g_row == 0;
    g.DrawString(L"CONFIGURAÇÕES", -1, &title, Gdiplus::RectF(x, y + unit * 0.6f, w, unit * 1.8f), &center, &red);
    g.DrawString(L"Resolução interna", -1, &label, Gdiplus::RectF(x, y + unit * 3.0f, w, unit), &center, res_row ? &red : &ink);
    const std::wstring shown = std::wstring(res_row ? L"◀   " : L"    ") + kModes[g_pending].label + (res_row ? L"   ▶" : L"");
    g.DrawString(shown.c_str(), -1, &value, Gdiplus::RectF(x, y + unit * 4.0f, w, unit * 1.4f), &center, &ink);
    if (!g_sound_names.empty()) {
        g.DrawString(L"Provedor de som", -1, &label, Gdiplus::RectF(x, y + unit * 5.7f, w, unit), &center, res_row ? &ink : &red);
        const std::wstring name = g_sound_names[g_pending_sound % g_sound_names.size()];
        const std::wstring snd = std::wstring(res_row ? L"    " : L"◀   ") + name + (res_row ? L"" : L"   ▶");
        Gdiplus::Font soundFont(L"Georgia", unit * 0.72f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
        g.DrawString(snd.c_str(), -1, &soundFont, Gdiplus::RectF(x + 12, y + unit * 6.7f, w - 24, unit * 1.3f), &center, &ink);
    }
    if (g_saved)
        g.DrawString(L"Salvo. Reinicie o jogo para aplicar.", -1, &label, Gdiplus::RectF(x, y + unit * 8.2f, w, unit), &center, &green);
    g.DrawString(L"[↑ ↓] linha   [← →] escolher   [Enter / ✕] salvar   [Esc / F10 / ○] fechar", -1, &note,
                 Gdiplus::RectF(x, y + unit * 9.5f, w, unit), &center, &ink);
}

} // namespace settings
