// Records the last window messages seen by the game window (dumped with a trapped exception).
// Included by runtime.cpp after log_line; not standalone.
#pragma once

struct TracedMessage { UINT message; WPARAM wparam; LPARAM lparam; DWORD tick; };
static TracedMessage g_message_ring[32];
static volatile LONG g_message_next = 0;
static WNDPROC g_game_wndproc = nullptr;

static bool is_noisy_message(UINT m) {
    return m == WM_MOUSEMOVE || m == WM_NCMOUSEMOVE || m == WM_SETCURSOR || m == WM_NCHITTEST || m == WM_PAINT ||
           m == WM_TIMER || m == WM_ERASEBKGND || m == WM_GETICON || m == 0x0118 /* WM_SYSTIMER */ ||
           m == WM_INPUT || m == WM_KEYDOWN || m == WM_KEYUP;
}

// Deactivation is what makes dgVoodoo run its restyle/resize burst (WM_DISPLAYCHANGE, style changes,
// WM_SIZE) that faults in DDRAW. The game keeps believing it is active; the keyboard and pad hooks
// already ignore input while another window has focus.
static bool is_deactivation(UINT message, WPARAM wparam) {
    return (message == WM_ACTIVATEAPP && !wparam) || (message == WM_ACTIVATE && LOWORD(wparam) == WA_INACTIVE) ||
           message == WM_KILLFOCUS || (message == WM_NCACTIVATE && !wparam);
}

static LRESULT CALLBACK traced_game_wndproc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    if (!is_noisy_message(message)) {
        const LONG slot = (InterlockedIncrement(&g_message_next) - 1) & 31;
        g_message_ring[slot] = {message, wparam, lparam, GetTickCount()};
    }
    if (is_deactivation(message, wparam)) {
        static volatile LONG swallowed = 0;
        if (InterlockedIncrement(&swallowed) <= 3) log_line("Window deactivation hidden from the game (Alt+Tab containment)");
        return message == WM_NCACTIVATE ? TRUE : 0;
    }
    // dgVoodoo's DDRAW faults while handling the resize/style burst of an Alt+Tab; drop that one
    // message instead of letting the fault take the whole game down.
    __try {
        return CallWindowProcA(g_game_wndproc, hwnd, message, wparam, lparam);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        static volatile LONG reported = 0;
        if (InterlockedIncrement(&reported) <= 5) log_line("Window message handler faulted; message dropped");
        return DefWindowProcA(hwnd, message, wparam, lparam);
    }
}

static HWND g_traced_hwnd = nullptr;

static void install_window_trace(HWND hwnd) {
    if (g_game_wndproc || !hwnd) return;
    g_traced_hwnd = hwnd;
    g_game_wndproc = reinterpret_cast<WNDPROC>(SetWindowLongPtrA(hwnd, GWLP_WNDPROC,
                                               reinterpret_cast<LONG_PTR>(traced_game_wndproc)));
}

// dgVoodoo subclasses the window again on every display-mode change (each Alt+Tab), which puts its
// proc outside whatever guard we had. The guard is re-armed on top each time. dgVoodoo saves the guard
// as its "previous" proc, so a re-entrant call must skip g_guard_next and go to the proc that sat below
// the guard when it was first installed, otherwise guard -> dgVoodoo -> guard would loop forever.
static WNDPROC g_guard_next = nullptr;
static WNDPROC g_guard_first_next = nullptr;
static bool g_guard_installed = false;
static LONG g_guard_installs = 0;
static thread_local int t_guard_depth = 0;

static LRESULT CALLBACK guard_wndproc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    if (is_deactivation(message, wparam)) {
        static volatile LONG swallowed = 0;
        if (InterlockedIncrement(&swallowed) <= 3) log_line("Window deactivation hidden from the game (Alt+Tab containment)");
        return message == WM_NCACTIVATE ? TRUE : 0;
    }
    const bool reentrant = t_guard_depth > 0;
    ++t_guard_depth;
    __try {
        const LRESULT result = CallWindowProcA(reentrant ? g_guard_first_next : g_guard_next, hwnd, message, wparam, lparam);
        --t_guard_depth;
        return result;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        --t_guard_depth;
        static volatile LONG reported = 0;
        if (InterlockedIncrement(&reported) <= 5) log_line("Outer window guard caught a fault; message dropped");
        return DefWindowProcA(hwnd, message, wparam, lparam);
    }
}

static void keep_window_trace_outermost() {
    if (!g_traced_hwnd || !IsWindow(g_traced_hwnd)) return;
    const auto current = reinterpret_cast<WNDPROC>(GetWindowLongPtrA(g_traced_hwnd, GWLP_WNDPROC));
    if (current == traced_game_wndproc || current == guard_wndproc) return;
    if (!g_guard_installed) g_guard_first_next = current;
    g_guard_next = current;
    g_guard_installed = true;
    SetWindowLongPtrA(g_traced_hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(guard_wndproc));
    if (++g_guard_installs <= 8) log_line("Outer window guard (re)installed above a foreign window procedure");
}

static void dump_traced_messages() {
    const LONG end = g_message_next;
    for (LONG i = std::max<LONG>(0, end - 12); i < end; ++i) {
        const TracedMessage& m = g_message_ring[i & 31];
        char line[120];
        sprintf_s(line, "  msg 0x%04X w=%08lX l=%08lX t=%lu", m.message, static_cast<unsigned long>(m.wparam),
                  static_cast<unsigned long>(m.lparam), m.tick);
        log_line(line);
    }
}
