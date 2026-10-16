#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <limits>

static_assert(sizeof(void*) == 4, "Probe the game's x86 codec");
struct BinkHeader {
    uint32_t width, height, frames, frameNum, lastFrameNum, frameRate, frameRateDiv;
};
using OpenFn = BinkHeader* (__stdcall*)(const char*, uint32_t);
using FrameFn = int32_t (__stdcall*)(BinkHeader*);
using NextFn = void (__stdcall*)(BinkHeader*);
using CloseFn = void (__stdcall*)(BinkHeader*);
using ErrorFn = const char* (__stdcall*)();

int main(int argc, char** argv) {
    if (argc != 4) { fprintf(stderr, "Usage: probe codec.dll movie.bik output.json\n"); return 2; }
    HMODULE dll = LoadLibraryA(argv[1]);
    if (!dll) { fprintf(stderr, "LoadLibrary failed: %lu\n", GetLastError()); return 3; }
    auto open = reinterpret_cast<OpenFn>(GetProcAddress(dll, "_BinkOpen@8"));
    auto frame = reinterpret_cast<FrameFn>(GetProcAddress(dll, "_BinkDoFrame@4"));
    auto next = reinterpret_cast<NextFn>(GetProcAddress(dll, "_BinkNextFrame@4"));
    auto close = reinterpret_cast<CloseFn>(GetProcAddress(dll, "_BinkClose@4"));
    auto error = reinterpret_cast<ErrorFn>(GetProcAddress(dll, "_BinkGetError@0"));
    if (!open || !frame || !next || !close || !error) {
        fprintf(stderr, "Missing legacy stdcall exports\n"); FreeLibrary(dll); return 4;
    }
    BinkHeader* movie = open(argv[2], 0);
    if (!movie) { fprintf(stderr, "BinkOpen failed: %s\n", error()); FreeLibrary(dll); return 5; }
    const BinkHeader header = *movie;
    if (!header.width || header.width > 8192 || !header.height || header.height > 8192 ||
        !header.frames || !header.frameRate || !header.frameRateDiv) {
        fprintf(stderr, "Unexpected public BINK metadata layout\n"); close(movie); FreeLibrary(dll); return 6;
    }
    LARGE_INTEGER frequency{}, begin{}, end{};
    QueryPerformanceFrequency(&frequency); QueryPerformanceCounter(&begin);
    const uint32_t count = std::min<uint32_t>(180, header.frames);
    int32_t minResult = std::numeric_limits<int32_t>::max(), maxResult = std::numeric_limits<int32_t>::min();
    uint32_t last = 0; double maxMs = 0;
    for (uint32_t i = 0; i < count; ++i) {
        LARGE_INTEGER a{}, b{}; QueryPerformanceCounter(&a);
        const int32_t result = frame(movie); QueryPerformanceCounter(&b);
        minResult = std::min(minResult, result); maxResult = std::max(maxResult, result);
        maxMs = std::max(maxMs, 1000.0 * static_cast<double>(b.QuadPart - a.QuadPart) / static_cast<double>(frequency.QuadPart));
        last = movie->frameNum;
        if (i + 1 < count) next(movie);
    }
    QueryPerformanceCounter(&end);
    const double elapsed = static_cast<double>(end.QuadPart - begin.QuadPart) / static_cast<double>(frequency.QuadPart);
    close(movie); FreeLibrary(dll);
    FILE* output = nullptr;
    if (fopen_s(&output, argv[3], "wb") || !output) { fprintf(stderr, "Cannot create report\n"); return 7; }
    fprintf(output, "{\"width\":%u,\"height\":%u,\"declared_frames\":%u,\"fps_numerator\":%u,\"fps_denominator\":%u,"
        "\"decode_calls_completed\":%u,\"first_frame_number\":%u,\"last_frame_number\":%u,\"elapsed_seconds\":%.9f,"
        "\"decode_calls_per_second\":%.4f,\"max_decode_ms\":%.4f,\"min_return\":%d,\"max_return\":%d,"
        "\"pixel_copy_verified\":false,\"game_playback\":false}\n",
        header.width, header.height, header.frames, header.frameRate, header.frameRateDiv,
        count, header.frameNum, last, elapsed, count / elapsed, maxMs, minResult, maxResult);
    fclose(output);
    printf("%ux%u: %u decode calls, frame %u to %u, %.2f decode calls/s; game playback unverified\n",
        header.width, header.height, count, header.frameNum, last, count / elapsed);
    return last == header.frameNum + count - 1 ? 0 : 8;
}
