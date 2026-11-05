// Dev-only screen grab through DXGI Desktop Duplication, which sees flip-model/DirectX windows that GDI
// BitBlt misses. Usage: dxgi_grab.exe out.bmp [output_index]. Writes a 32-bit top-down BMP of one monitor.
#include <d3d11.h>
#include <dxgi1_2.h>
#include <cstdio>
#include <vector>
#include <wrl/client.h>

using Microsoft::WRL::ComPtr;

int wmain(int argc, wchar_t** argv) {
    if (argc < 2) return 2;
    const UINT output_index = argc > 2 ? static_cast<UINT>(_wtoi(argv[2])) : 0;
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &device, nullptr, &context))) return 3;
    ComPtr<IDXGIDevice> dxgi_device;
    device.As(&dxgi_device);
    ComPtr<IDXGIAdapter> adapter;
    dxgi_device->GetAdapter(&adapter);
    ComPtr<IDXGIOutput> output;
    if (FAILED(adapter->EnumOutputs(output_index, &output))) return 4;
    ComPtr<IDXGIOutput1> output1;
    output.As(&output1);
    ComPtr<IDXGIOutputDuplication> duplication;
    if (FAILED(output1->DuplicateOutput(device.Get(), &duplication))) return 5;

    for (int attempt = 0; attempt < 20; ++attempt) {
        DXGI_OUTDUPL_FRAME_INFO info{};
        ComPtr<IDXGIResource> resource;
        const HRESULT hr = duplication->AcquireNextFrame(500, &info, &resource);
        if (hr == DXGI_ERROR_WAIT_TIMEOUT) continue;
        if (FAILED(hr)) return 6;
        ComPtr<ID3D11Texture2D> frame;
        resource.As(&frame);
        D3D11_TEXTURE2D_DESC desc{};
        frame->GetDesc(&desc);
        desc.Usage = D3D11_USAGE_STAGING;
        desc.BindFlags = 0;
        desc.MiscFlags = 0;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Texture2D> staging;
        if (FAILED(device->CreateTexture2D(&desc, nullptr, &staging))) return 7;
        context->CopyResource(staging.Get(), frame.Get());
        D3D11_MAPPED_SUBRESOURCE mapped{};
        if (FAILED(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped))) return 8;
        FILE* file = nullptr;
        if (_wfopen_s(&file, argv[1], L"wb") != 0 || !file) return 9;
        const UINT w = desc.Width, h = desc.Height;
        BITMAPFILEHEADER bf{};
        BITMAPINFOHEADER bi{};
        bf.bfType = 0x4d42;
        bf.bfOffBits = sizeof(bf) + sizeof(bi);
        bf.bfSize = bf.bfOffBits + w * h * 4;
        bi.biSize = sizeof(bi);
        bi.biWidth = static_cast<LONG>(w);
        bi.biHeight = -static_cast<LONG>(h);
        bi.biPlanes = 1;
        bi.biBitCount = 32;
        fwrite(&bf, sizeof(bf), 1, file);
        fwrite(&bi, sizeof(bi), 1, file);
        for (UINT y = 0; y < h; ++y) fwrite(static_cast<unsigned char*>(mapped.pData) + static_cast<size_t>(y) * mapped.RowPitch, 4, w, file);
        fclose(file);
        context->Unmap(staging.Get(), 0);
        duplication->ReleaseFrame();
        wprintf(L"saved %ux%u\n", w, h);
        return 0;
    }
    return 10;
}
