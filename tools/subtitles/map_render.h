// Parchment-style Nosgoth map drawn with GDI+. Included by runtime.cpp after get_current_objective;
// not standalone. The static art is cached; only the player marker and footer are drawn per frame.
#pragma once

#include <cmath>

namespace mapart {

using Gdiplus::Color;
using Gdiplus::PointF;

struct Lcg {
    unsigned state;
    explicit Lcg(unsigned seed) : state(seed) {}
    float next() { // [0,1)
        state = state * 1664525u + 1013904223u;
        return static_cast<float>((state >> 8) & 0xFFFF) / 65536.0f;
    }
    float range(float lo, float hi) { return lo + (hi - lo) * next(); }
};

struct Layout {
    int w, h, x, y, mw, mh;
    float canvasX, canvasY, canvasW, canvasH, unit;
};

static Layout make_layout(int screen_w, int screen_h) {
    Layout l{};
    l.w = screen_w;
    l.h = screen_h;
    l.mw = static_cast<int>(screen_w * 0.82f);
    l.mh = static_cast<int>(screen_h * 0.84f);
    l.x = (screen_w - l.mw) / 2;
    l.y = (screen_h - l.mh) / 2;
    l.unit = std::max(16.0f, screen_h * 0.028f);
    l.canvasX = static_cast<float>(l.x) + l.mw * 0.04f;
    l.canvasY = static_cast<float>(l.y) + l.unit * 4.6f + screen_h * 0.075f;
    l.canvasW = l.mw * 0.92f;
    l.canvasH = static_cast<float>(l.y + l.mh) - l.canvasY - l.unit * 2.4f;
    return l;
}

static PointF sector_point(const Layout& l, const MapSector& s) {
    return PointF(l.canvasX + s.norm_x * l.canvasW, l.canvasY + s.norm_y * l.canvasH);
}

// Jittered rectangle outline, like a torn sheet.
static void tattered_sheet(Gdiplus::GraphicsPath& path, const Layout& l, Lcg& rng) {
    std::vector<PointF> pts;
    const float x0 = static_cast<float>(l.x), y0 = static_cast<float>(l.y);
    const float x1 = x0 + l.mw, y1 = y0 + l.mh;
    const float step = 38.0f, j = 5.0f;
    for (float x = x0; x < x1; x += step) pts.emplace_back(x, y0 + rng.range(-j, j));
    for (float y = y0; y < y1; y += step) pts.emplace_back(x1 + rng.range(-j, j), y);
    for (float x = x1; x > x0; x -= step) pts.emplace_back(x, y1 + rng.range(-j, j));
    for (float y = y1; y > y0; y -= step) pts.emplace_back(x0 + rng.range(-j, j), y);
    path.AddPolygon(pts.data(), static_cast<INT>(pts.size()));
}

static void paint_parchment(Gdiplus::Graphics& g, const Layout& l, bool spectral) {
    Lcg rng(7u);
    Gdiplus::GraphicsPath sheet;
    tattered_sheet(sheet, l, rng);

    Gdiplus::GraphicsPath shadow;
    Lcg rng2(7u);
    tattered_sheet(shadow, l, rng2);
    Gdiplus::Matrix lift;
    lift.Translate(14.0f, 18.0f);
    shadow.Transform(&lift);
    Gdiplus::SolidBrush shadowBrush(Color(150, 0, 0, 0));
    g.FillPath(&shadowBrush, &shadow);

    Gdiplus::PathGradientBrush aging(&sheet);
    aging.SetCenterPoint(PointF(l.x + l.mw * 0.5f, l.y + l.mh * 0.46f));
    aging.SetCenterColor(spectral ? Color(255, 176, 190, 190) : Color(255, 226, 201, 153));
    const Color edge = spectral ? Color(255, 66, 84, 98) : Color(255, 128, 86, 44);
    INT count = 1;
    aging.SetSurroundColors(&edge, &count);
    aging.SetFocusScales(0.55f, 0.55f);
    g.FillPath(&aging, &sheet);

    g.SetClip(&sheet);
    for (int i = 0; i < 46; ++i) { // water stains and foxing
        const float r = rng.range(20.0f, 120.0f);
        Gdiplus::SolidBrush stain(Color(static_cast<BYTE>(rng.range(6.0f, 20.0f)), 96, 62, 28));
        g.FillEllipse(&stain, l.x + rng.next() * l.mw - r, l.y + rng.next() * l.mh - r, r * 1.6f, r);
    }
    Gdiplus::Pen fiber(Color(16, 70, 45, 20), 1.0f);
    for (int i = 0; i < 700; ++i) {
        const float fx = l.x + rng.next() * l.mw, fy = l.y + rng.next() * l.mh;
        g.DrawLine(&fiber, fx, fy, fx + rng.range(-14.0f, 14.0f), fy + rng.range(-5.0f, 5.0f));
    }
    // Creases: one vertical, one horizontal.
    Gdiplus::Pen crease(Color(34, 60, 38, 16), 2.0f);
    g.DrawLine(&crease, l.x + l.mw * 0.5f, static_cast<float>(l.y), l.x + l.mw * 0.5f + 6.0f, static_cast<float>(l.y + l.mh));
    g.DrawLine(&crease, static_cast<float>(l.x), l.y + l.mh * 0.52f, static_cast<float>(l.x + l.mw), l.y + l.mh * 0.52f - 5.0f);
    g.ResetClip();

    Gdiplus::Pen burnt(Color(210, 70, 40, 18), 3.0f);
    g.DrawPath(&burnt, &sheet);
}

static void paint_terrain(Gdiplus::Graphics& g, const Layout& l) {
    const float cx = l.canvasX, cy = l.canvasY, cw = l.canvasW, ch = l.canvasH;
    auto P = [&](float nx, float ny) { return PointF(cx + nx * cw, cy + ny * ch); };

    // Sea wash, then the continent on top.
    const PointF coast[] = {P(0.05f, 0.30f), P(0.14f, 0.08f), P(0.34f, 0.03f), P(0.58f, 0.07f), P(0.80f, 0.04f),
                            P(0.94f, 0.18f), P(0.97f, 0.46f), P(0.90f, 0.72f), P(0.78f, 0.90f), P(0.58f, 0.97f),
                            P(0.36f, 0.94f), P(0.16f, 0.86f), P(0.04f, 0.64f)};
    Gdiplus::GraphicsPath land;
    land.AddClosedCurve(coast, ARRAYSIZE(coast), 0.5f);
    // Coastal shelf: a larger, fainter copy of the coast reads as shallow sea without a hard edge.
    for (int i = 3; i >= 1; --i) {
        Gdiplus::Matrix swell;
        swell.Translate(-cx - cw * 0.5f, -cy - ch * 0.5f);
        swell.Scale(1.0f + 0.035f * i, 1.0f + 0.045f * i, Gdiplus::MatrixOrderAppend);
        swell.Translate(cx + cw * 0.5f, cy + ch * 0.5f, Gdiplus::MatrixOrderAppend);
        Gdiplus::GraphicsPath shelf;
        shelf.AddClosedCurve(coast, ARRAYSIZE(coast), 0.5f);
        shelf.Transform(&swell);
        Gdiplus::SolidBrush sea(Color(static_cast<BYTE>(26 + 6 * (3 - i)), 80, 112, 116));
        g.FillPath(&sea, &shelf);
    }
    Gdiplus::SolidBrush landBrush(Color(130, 214, 186, 132));
    g.FillPath(&landBrush, &land);
    Gdiplus::Pen coastInk(Color(230, 74, 44, 20), 3.2f);
    coastInk.SetLineJoin(Gdiplus::LineJoinRound);
    g.DrawPath(&coastInk, &land);
    Gdiplus::Pen coastEcho(Color(110, 74, 44, 20), 1.4f);
    coastEcho.SetDashStyle(Gdiplus::DashStyleDot);
    Gdiplus::Matrix grow;
    grow.Translate(-cx - cw * 0.5f, -cy - ch * 0.5f);
    grow.Scale(1.025f, 1.025f, Gdiplus::MatrixOrderAppend);
    grow.Translate(cx + cw * 0.5f, cy + ch * 0.5f, Gdiplus::MatrixOrderAppend);
    Gdiplus::GraphicsPath echo;
    echo.AddClosedCurve(coast, ARRAYSIZE(coast), 0.5f);
    echo.Transform(&grow);
    g.DrawPath(&coastEcho, &echo);

    // Lake of the Dead: filled water with ripples.
    const PointF lakeC = P(0.50f, 0.84f);
    Gdiplus::SolidBrush lake(Color(150, 70, 104, 120));
    g.FillEllipse(&lake, lakeC.X - cw * 0.14f, lakeC.Y - ch * 0.10f, cw * 0.28f, ch * 0.20f);
    Gdiplus::Pen lakeInk(Color(200, 40, 70, 84), 2.0f);
    g.DrawEllipse(&lakeInk, lakeC.X - cw * 0.14f, lakeC.Y - ch * 0.10f, cw * 0.28f, ch * 0.20f);
    Gdiplus::Pen ripple(Color(120, 220, 235, 235), 1.6f);
    for (int i = 0; i < 6; ++i) {
        const float ry = lakeC.Y - ch * 0.06f + i * ch * 0.022f;
        g.DrawArc(&ripple, lakeC.X - cw * 0.08f + (i % 2) * 18.0f, ry, 46.0f, 8.0f, 0.0f, 180.0f);
    }

    // Mountains in the north and east, forests in the middle band.
    Lcg rng(31u);
    Gdiplus::Pen peakInk(Color(210, 66, 40, 18), 1.8f);
    Gdiplus::SolidBrush peakLight(Color(190, 234, 214, 172)), peakDark(Color(170, 120, 88, 52));
    for (int i = 0; i < 38; ++i) {
        const bool east = i % 3 == 0;
        const PointF p = east ? P(rng.range(0.80f, 0.89f), rng.range(0.28f, 0.62f))
                              : P(rng.range(0.10f, 0.92f), rng.range(0.06f, 0.18f));
        const float s = rng.range(14.0f, 26.0f);
        const PointF tri[] = {PointF(p.X - s, p.Y + s * 0.8f), PointF(p.X, p.Y - s), PointF(p.X + s, p.Y + s * 0.8f)};
        const PointF shade[] = {PointF(p.X, p.Y - s), PointF(p.X + s, p.Y + s * 0.8f), PointF(p.X + s * 0.1f, p.Y + s * 0.8f)};
        g.FillPolygon(&peakLight, tri, 3);
        g.FillPolygon(&peakDark, shade, 3);
        g.DrawPolygon(&peakInk, tri, 3);
    }
    Gdiplus::SolidBrush leaf(Color(150, 70, 96, 48));
    Gdiplus::Pen trunk(Color(170, 60, 40, 20), 1.4f);
    for (int i = 0; i < 70; ++i) {
        const PointF p = P(rng.range(0.07f, 0.88f), rng.range(0.30f, 0.76f));
        if (std::fabs(p.X - (cx + 0.5f * cw)) < cw * 0.04f && p.Y > cy + 0.55f * ch) continue;
        const float s = rng.range(5.0f, 9.0f);
        g.DrawLine(&trunk, p.X, p.Y, p.X, p.Y + s);
        g.FillEllipse(&leaf, p.X - s, p.Y - s * 1.2f, s * 2.0f, s * 1.6f);
    }
}

static void paint_roads(Gdiplus::Graphics& g, const Layout& l) {
    static const int links[][2] = {{0, 1}, {1, 2}, {1, 3}, {1, 4}, {4, 5}, {5, 6}, {6, 7}, {7, 8}, {4, 8}};
    Gdiplus::Pen road(Color(215, 92, 52, 22), 2.6f);
    road.SetDashStyle(Gdiplus::DashStyleDash);
    road.SetLineJoin(Gdiplus::LineJoinRound);
    for (const auto& link : links) {
        const PointF a = sector_point(l, g_sectors[link[0]]), b = sector_point(l, g_sectors[link[1]]);
        const float bend = ((link[0] + link[1]) % 2 ? 1.0f : -1.0f) * 26.0f;
        const PointF mid((a.X + b.X) * 0.5f + bend, (a.Y + b.Y) * 0.5f - bend * 0.6f);
        const PointF curve[] = {a, mid, b};
        g.DrawCurve(&road, curve, 3, 0.6f);
    }
}

static void halo_text(Gdiplus::Graphics& g, const wchar_t* text, const Gdiplus::Font& font, const Gdiplus::RectF& r,
                      const Gdiplus::StringFormat& fmt, const Gdiplus::Brush& ink) {
    Gdiplus::SolidBrush halo(Color(190, 232, 210, 162));
    static const float d[8][2] = {{-1.5f, 0}, {1.5f, 0}, {0, -1.5f}, {0, 1.5f}, {-1.1f, -1.1f}, {1.1f, -1.1f}, {-1.1f, 1.1f}, {1.1f, 1.1f}};
    for (const auto& off : d) g.DrawString(text, -1, &font, Gdiplus::RectF(r.X + off[0], r.Y + off[1], r.Width, r.Height), &fmt, &halo);
    g.DrawString(text, -1, &font, r, &fmt, &ink);
}

static void paint_sectors(Gdiplus::Graphics& g, const Layout& l, int current_sector) {
    Gdiplus::StringFormat center;
    center.SetAlignment(Gdiplus::StringAlignmentCenter);
    Gdiplus::Font label(L"Georgia", l.unit * 0.62f, Gdiplus::FontStyleBold | Gdiplus::FontStyleItalic, Gdiplus::UnitPixel);
    Gdiplus::SolidBrush ink(Color(255, 58, 30, 12));
    Gdiplus::SolidBrush plate(Color(255, 214, 184, 128));
    Gdiplus::Pen rim(Color(255, 80, 46, 20), 2.4f);
    Gdiplus::SolidBrush seal(Color(255, 138, 28, 24));
    for (int si = 0; si < static_cast<int>(ARRAYSIZE(g_sectors)); ++si) {
        const auto& s = g_sectors[si];
        const PointF p = sector_point(l, s);
        const float r = l.unit * 0.55f;
        // Tower glyph on a round plate.
        g.FillEllipse(&plate, p.X - r, p.Y - r, r * 2, r * 2);
        g.DrawEllipse(&rim, p.X - r, p.Y - r, r * 2, r * 2);
        const float t = r * 0.55f;
        const PointF keep[] = {PointF(p.X - t, p.Y + t), PointF(p.X - t, p.Y - t * 0.5f), PointF(p.X - t * 0.5f, p.Y - t * 0.5f),
                               PointF(p.X - t * 0.5f, p.Y - t), PointF(p.X, p.Y - t), PointF(p.X, p.Y - t * 0.5f),
                               PointF(p.X + t * 0.5f, p.Y - t * 0.5f), PointF(p.X + t * 0.5f, p.Y - t),
                               PointF(p.X + t, p.Y - t), PointF(p.X + t, p.Y + t)};
        g.FillPolygon(&ink, keep, ARRAYSIZE(keep));
        if (si == current_sector) { // red wax ring marks the current region
            Gdiplus::Pen wax(Color(255, 150, 24, 20), 4.0f);
            g.DrawEllipse(&wax, p.X - r - 6, p.Y - r - 6, (r + 6) * 2, (r + 6) * 2);
        }
        halo_text(g, s.name, label, Gdiplus::RectF(p.X - 260, p.Y + r + 4, 520, l.unit), center, ink);
    }
}

static void paint_compass(Gdiplus::Graphics& g, const Layout& l) {
    const PointF c(l.x + l.mw - l.unit * 4.6f, l.y + l.mh - l.unit * 5.4f);
    const float R = l.unit * 2.2f;
    Gdiplus::Pen ring(Color(220, 70, 40, 18), 2.0f);
    g.DrawEllipse(&ring, c.X - R, c.Y - R, R * 2, R * 2);
    g.DrawEllipse(&ring, c.X - R * 0.78f, c.Y - R * 0.78f, R * 1.56f, R * 1.56f);
    Gdiplus::SolidBrush dark(Color(235, 78, 40, 18)), light(Color(235, 232, 208, 160)), red(Color(240, 150, 28, 22));
    for (int i = 0; i < 4; ++i) { // cardinal points: half dark, half light
        const float a = static_cast<float>(i) * 1.5707963f;
        const PointF tip(c.X + std::sin(a) * R * 1.12f, c.Y - std::cos(a) * R * 1.12f);
        const PointF l1(c.X + std::sin(a + 0.35f) * R * 0.2f, c.Y - std::cos(a + 0.35f) * R * 0.2f);
        const PointF l2(c.X + std::sin(a - 0.35f) * R * 0.2f, c.Y - std::cos(a - 0.35f) * R * 0.2f);
        const PointF half1[] = {c, tip, l1}, half2[] = {c, tip, l2};
        g.FillPolygon(i == 0 ? &red : &dark, half1, 3);
        g.FillPolygon(&light, half2, 3);
        g.DrawPolygon(&ring, half1, 3);
        g.DrawPolygon(&ring, half2, 3);
    }
    Gdiplus::StringFormat center;
    center.SetAlignment(Gdiplus::StringAlignmentCenter);
    Gdiplus::Font n(L"Georgia", l.unit * 0.8f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    g.DrawString(L"N", -1, &n, Gdiplus::RectF(c.X - 20, c.Y - R * 1.12f - l.unit * 1.15f, 40, l.unit * 1.1f), &center, &dark);
}

static void paint_frame_and_text(Gdiplus::Graphics& g, const Layout& l, const ObjectiveInfo& obj) {
    Gdiplus::Pen outer(Color(240, 70, 38, 16), 3.0f), inner(Color(190, 70, 38, 16), 1.2f);
    g.DrawRectangle(&outer, l.x + 18, l.y + 18, l.mw - 36, l.mh - 36);
    g.DrawRectangle(&inner, l.x + 26, l.y + 26, l.mw - 52, l.mh - 52);
    Gdiplus::SolidBrush gem(Color(240, 138, 28, 24));
    const float corners[4][2] = {{18, 18}, {static_cast<float>(l.mw - 18), 18}, {18, static_cast<float>(l.mh - 18)},
                                 {static_cast<float>(l.mw - 18), static_cast<float>(l.mh - 18)}};
    for (const auto& c : corners) {
        const float px = l.x + c[0], py = l.y + c[1], d = 11.0f;
        const PointF diamond[] = {PointF(px, py - d), PointF(px + d, py), PointF(px, py + d), PointF(px - d, py)};
        g.FillPolygon(&gem, diamond, 4);
        g.DrawPolygon(&outer, diamond, 4);
    }

    // Title ribbon.
    const float rw = l.mw * 0.46f, rh = l.unit * 2.3f, rx = l.x + (l.mw - rw) * 0.5f, ry = l.y + l.unit * 0.9f;
    const PointF ribbon[] = {PointF(rx - 40, ry + 6), PointF(rx, ry), PointF(rx + rw, ry), PointF(rx + rw + 40, ry + 6),
                             PointF(rx + rw + 22, ry + rh * 0.5f), PointF(rx + rw + 40, ry + rh - 6), PointF(rx + rw, ry + rh),
                             PointF(rx, ry + rh), PointF(rx - 40, ry + rh - 6), PointF(rx - 22, ry + rh * 0.5f)};
    Gdiplus::LinearGradientBrush cloth(PointF(rx, ry), PointF(rx, ry + rh), Color(255, 150, 40, 32), Color(255, 88, 18, 16));
    g.FillPolygon(&cloth, ribbon, ARRAYSIZE(ribbon));
    Gdiplus::Pen gold(Color(255, 214, 168, 72), 2.4f);
    g.DrawPolygon(&gold, ribbon, ARRAYSIZE(ribbon));
    Gdiplus::StringFormat center;
    center.SetAlignment(Gdiplus::StringAlignmentCenter);
    center.SetLineAlignment(Gdiplus::StringAlignmentCenter);
    Gdiplus::Font title(L"Georgia", l.unit * 1.05f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::SolidBrush shadow(Color(200, 30, 6, 4)), cream(Color(255, 246, 226, 170));
    g.DrawString(L"MAPA DE NOSGOTH", -1, &title, Gdiplus::RectF(rx + 2, ry + 2, rw, rh), &center, &shadow);
    g.DrawString(L"MAPA DE NOSGOTH", -1, &title, Gdiplus::RectF(rx, ry, rw, rh), &center, &cream);

    // Objective card, pinned under the ribbon on the left.
    const float ox = l.x + l.mw * 0.06f, oy = ry + rh + l.unit * 0.6f, ow = l.mw * 0.52f, oh = l.h * 0.075f;
    Gdiplus::SolidBrush card(Color(225, 232, 210, 160));
    g.FillRectangle(&card, ox, oy, ow, oh);
    Gdiplus::Pen cardRim(Color(235, 110, 70, 30), 1.8f);
    g.DrawRectangle(&cardRim, ox, oy, ow, oh);
    Gdiplus::StringFormat left;
    left.SetAlignment(Gdiplus::StringAlignmentNear);
    Gdiplus::Font head(L"Georgia", l.unit * 0.74f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::Font body(L"Georgia", l.unit * 0.6f, Gdiplus::FontStyleItalic, Gdiplus::UnitPixel);
    Gdiplus::SolidBrush redInk(Color(255, 122, 20, 16)), brown(Color(255, 58, 30, 12));
    const std::wstring heading = std::wstring(L"Objetivo: ") + obj.title + L" — " + obj.region;
    g.DrawString(heading.c_str(), -1, &head, Gdiplus::RectF(ox + 14, oy + 6, ow - 28, l.unit), &left, &redInk);
    g.DrawString(obj.description, -1, &body, Gdiplus::RectF(ox + 14, oy + 8 + l.unit * 0.95f, ow - 28, oh - l.unit), &left, &brown);
}

struct StaticKey {
    int w, h, realm, unit;
    const wchar_t* objective;
    bool operator==(const StaticKey& o) const {
        return w == o.w && h == o.h && realm == o.realm && unit == o.unit && objective == o.objective;
    }
};

} // namespace mapart

static void render_map_screen(Gdiplus::Graphics& graphics, int screen_w, int screen_h) {
    using namespace mapart;
    static Gdiplus::Bitmap* cache = nullptr;
    static StaticKey cached_key{};
    const auto obj = get_current_objective();
    PlayerState ps{};
    safe_read_player_state(ps);
    const auto player = get_player_state();
    const StaticKey key{screen_w, screen_h, player.realm == 1 ? 1 : 0, current_sector_index(), obj.title};
    const Layout l = make_layout(screen_w, screen_h);

    if (!cache || !(key == cached_key)) {
        delete cache;
        cache = new Gdiplus::Bitmap(screen_w, screen_h, PixelFormat32bppPARGB);
        Gdiplus::Graphics g(cache);
        g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
        g.SetTextRenderingHint(Gdiplus::TextRenderingHintAntiAlias);
        g.Clear(Color(0, 0, 0, 0));
        Gdiplus::SolidBrush dim(Color(165, 4, 4, 8)); // the game stays faintly visible behind the sheet
        g.FillRectangle(&dim, 0, 0, screen_w, screen_h);
        paint_parchment(g, l, key.realm == 1);
        paint_terrain(g, l);
        paint_roads(g, l);
        paint_sectors(g, l, current_sector_index());
        paint_compass(g, l);
        paint_frame_and_text(g, l, obj);
        cached_key = key;
    }
    graphics.DrawImage(cache, 0, 0, screen_w, screen_h);

    // Player marker: pulsing soul glow over the current sector (hidden while the area is not identified).
    const int here = current_sector_index();
    if (here >= 0) {
        const PointF pos = sector_point(l, g_sectors[here]);
        const float pulse = 1.0f + 0.22f * static_cast<float>(std::sin(GetTickCount64() / 260.0));
        const float r = l.unit * 0.5f * pulse;
        for (int i = 3; i >= 1; --i) {
            Gdiplus::SolidBrush glow(Color(static_cast<BYTE>(34 * (4 - i)), 90, 210, 255));
            graphics.FillEllipse(&glow, pos.X - r * i * 1.5f, pos.Y - r * i * 1.5f, r * i * 3.0f, r * i * 3.0f);
        }
        Gdiplus::SolidBrush core(Color(255, 190, 240, 255));
        graphics.FillEllipse(&core, pos.X - r * 0.7f, pos.Y - r * 0.7f, r * 1.4f, r * 1.4f);
        Gdiplus::Pen coreRim(Color(255, 20, 70, 110), 2.0f);
        graphics.DrawEllipse(&coreRim, pos.X - r * 0.7f, pos.Y - r * 0.7f, r * 1.4f, r * 1.4f);

        Gdiplus::StringFormat tagFormat;
        tagFormat.SetAlignment(Gdiplus::StringAlignmentCenter);
        tagFormat.SetLineAlignment(Gdiplus::StringAlignmentCenter);
        Gdiplus::Font tag(L"Georgia", l.unit * 0.78f, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
        Gdiplus::SolidBrush tagInk(Color(255, 20, 60, 100));
        halo_text(graphics, L"RAZIEL", tag, Gdiplus::RectF(pos.X - 80, pos.Y - r * 2.4f - l.unit, 160, l.unit), tagFormat, tagInk);
    }

    Gdiplus::StringFormat center;
    center.SetAlignment(Gdiplus::StringAlignmentCenter);
    center.SetLineAlignment(Gdiplus::StringAlignmentCenter);
    const std::wstring footer = std::wstring(L"Plano: ") + (player.realm == 1 ? L"Espectral" : L"Material") +
                                L"   •   [M] ou [Touchpad] para fechar";
    Gdiplus::Font footerFont(L"Georgia", l.unit * 0.66f, Gdiplus::FontStyleItalic, Gdiplus::UnitPixel);
    Gdiplus::SolidBrush brown(Color(255, 70, 38, 16));
    graphics.DrawString(footer.c_str(), -1, &footerFont,
                        Gdiplus::RectF(static_cast<float>(l.x), static_cast<float>(l.y + l.mh) - l.unit * 2.6f,
                                       static_cast<float>(l.mw), l.unit * 1.2f), &center, &brown);
}
