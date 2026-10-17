#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <wrl/client.h>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <vector>

using Microsoft::WRL::ComPtr;
using Init=HRESULT(__stdcall*)(const wchar_t*,const wchar_t*);
using Render=HRESULT(__stdcall*)(ID3D11Device*,ID3D11DeviceContext*,ID3D11RenderTargetView*,UINT);
using Release=void(__stdcall*)();
static void PrintHr(const wchar_t* name,HRESULT hr){fwprintf(stderr,L"%ls: 0x%08lx\n",name,static_cast<unsigned long>(hr));}
static bool SaveBmp(const std::filesystem::path& path,const std::vector<BYTE>& rgba,UINT w,UINT h){
    BITMAPFILEHEADER fh{};BITMAPINFOHEADER ih{};ih.biSize=sizeof(ih);ih.biWidth=static_cast<LONG>(w);ih.biHeight=-static_cast<LONG>(h);ih.biPlanes=1;ih.biBitCount=32;ih.biCompression=BI_RGB;ih.biSizeImage=w*h*4;
    fh.bfType=0x4d42;fh.bfOffBits=sizeof(fh)+sizeof(ih);fh.bfSize=fh.bfOffBits+ih.biSizeImage;
    HANDLE f=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);if(f==INVALID_HANDLE_VALUE)return false;
    DWORD wrote=0;bool ok=WriteFile(f,&fh,sizeof(fh),&wrote,nullptr)&&wrote==sizeof(fh)&&WriteFile(f,&ih,sizeof(ih),&wrote,nullptr)&&wrote==sizeof(ih);
    std::vector<BYTE> bgra(rgba.size());for(size_t i=0;i<rgba.size();i+=4){bgra[i]=rgba[i+2];bgra[i+1]=rgba[i+1];bgra[i+2]=rgba[i];bgra[i+3]=255;}
    ok=ok&&WriteFile(f,bgra.data(),static_cast<DWORD>(bgra.size()),&wrote,nullptr)&&wrote==bgra.size();CloseHandle(f);return ok;
}
static bool SameCom(IUnknown* a,IUnknown* b){return a==b;}
static int RunOne(Render render,ID3D11Device* device,ID3D11DeviceContext* context,UINT which,UINT w,UINT h,const std::filesystem::path& capture){
    D3D11_TEXTURE2D_DESC td{};td.Width=w;td.Height=h;td.MipLevels=1;td.ArraySize=1;td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;td.SampleDesc.Count=1;td.Usage=D3D11_USAGE_DEFAULT;td.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> target;HRESULT hr=device->CreateTexture2D(&td,nullptr,&target);if(FAILED(hr)){PrintHr(L"target texture",hr);return 1;}
    ComPtr<ID3D11RenderTargetView> rtv;hr=device->CreateRenderTargetView(target.Get(),nullptr,&rtv);if(FAILED(hr)){PrintHr(L"RTV",hr);return 2;}
    D3D11_BLEND_DESC bd{};bd.RenderTarget[0].RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;ComPtr<ID3D11BlendState> blend;hr=device->CreateBlendState(&bd,&blend);if(FAILED(hr))return 3;
    D3D11_RASTERIZER_DESC rd{};rd.FillMode=D3D11_FILL_WIREFRAME;rd.CullMode=D3D11_CULL_FRONT;rd.DepthClipEnable=TRUE;ComPtr<ID3D11RasterizerState> raster;hr=device->CreateRasterizerState(&rd,&raster);if(FAILED(hr))return 4;
    float clear[4]={.08f,.16f,.24f,1};context->ClearRenderTargetView(rtv.Get(),clear);ID3D11RenderTargetView* targets[]={rtv.Get()};context->OMSetRenderTargets(1,targets,nullptr);
    D3D11_VIEWPORT vp{};vp.TopLeftX=7;vp.TopLeftY=9;vp.Width=static_cast<float>(w-14);vp.Height=static_cast<float>(h-18);vp.MinDepth=.1f;vp.MaxDepth=.9f;context->RSSetViewports(1,&vp);const float factors[4]={.2f,.3f,.4f,.5f};context->OMSetBlendState(blend.Get(),factors,0x12345678);context->RSSetState(raster.Get());context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_LINELIST);
    ID3D11RenderTargetView* beforeTarget=nullptr;context->OMGetRenderTargets(1,&beforeTarget,nullptr);UINT count=1;D3D11_VIEWPORT beforeVp{};context->RSGetViewports(&count,&beforeVp);ComPtr<ID3D11BlendState> beforeBlend;context->OMGetBlendState(&beforeBlend,nullptr,nullptr);ComPtr<ID3D11RasterizerState> beforeRaster;context->RSGetState(&beforeRaster);D3D11_PRIMITIVE_TOPOLOGY beforeTopo{};context->IAGetPrimitiveTopology(&beforeTopo);
    hr=render(device,context,rtv.Get(),which);if(FAILED(hr)){PrintHr(L"RenderMenuBackground",hr);if(beforeTarget)beforeTarget->Release();return 5;}
    ID3D11RenderTargetView* afterTarget=nullptr;context->OMGetRenderTargets(1,&afterTarget,nullptr);D3D11_VIEWPORT afterVp{};count=1;context->RSGetViewports(&count,&afterVp);ComPtr<ID3D11BlendState> afterBlend;context->OMGetBlendState(&afterBlend,nullptr,nullptr);ComPtr<ID3D11RasterizerState> afterRaster;context->RSGetState(&afterRaster);D3D11_PRIMITIVE_TOPOLOGY afterTopo{};context->IAGetPrimitiveTopology(&afterTopo);
    const bool restored=SameCom(beforeTarget,afterTarget)&&beforeVp.TopLeftX==afterVp.TopLeftX&&beforeVp.TopLeftY==afterVp.TopLeftY&&beforeVp.Width==afterVp.Width&&beforeVp.Height==afterVp.Height&&beforeVp.MinDepth==afterVp.MinDepth&&beforeVp.MaxDepth==afterVp.MaxDepth&&SameCom(beforeBlend.Get(),afterBlend.Get())&&SameCom(beforeRaster.Get(),afterRaster.Get())&&beforeTopo==afterTopo;
    if(beforeTarget)beforeTarget->Release();if(afterTarget)afterTarget->Release();if(!restored){fwprintf(stderr,L"D3D state restoration failed (%ux%u, image %u)\n",w,h,which);return 6;}
    D3D11_TEXTURE2D_DESC sd=td;sd.Usage=D3D11_USAGE_STAGING;sd.BindFlags=0;sd.CPUAccessFlags=D3D11_CPU_ACCESS_READ;ComPtr<ID3D11Texture2D> stage;hr=device->CreateTexture2D(&sd,nullptr,&stage);if(FAILED(hr))return 7;context->CopyResource(stage.Get(),target.Get());D3D11_MAPPED_SUBRESOURCE map{};hr=context->Map(stage.Get(),0,D3D11_MAP_READ,0,&map);if(FAILED(hr)){PrintHr(L"Map readback",hr);return 8;}
    std::vector<BYTE> rgba(static_cast<size_t>(w)*h*4);for(UINT y=0;y<h;++y)memcpy(rgba.data()+static_cast<size_t>(y)*w*4,static_cast<const BYTE*>(map.pData)+static_cast<size_t>(y)*map.RowPitch,w*4);context->Unmap(stage.Get(),0);
    size_t changed=0,outside=0;UINT left=0,top=0,right=w,bottom=h;if(static_cast<uint64_t>(w)*3>static_cast<uint64_t>(h)*4){UINT fit=h*4/3;left=(w-fit)/2;right=left+fit;}else{UINT fit=w*3/4;top=(h-fit)/2;bottom=top+fit;}
    for(UINT y=0;y<h;y+=3)for(UINT x=0;x<w;x+=3){const size_t i=(static_cast<size_t>(y)*w+x)*4;const bool isBg=rgba[i]==20&&rgba[i+1]==41&&rgba[i+2]==61;if(x>=left&&x<right&&y>=top&&y<bottom){if(!isBg)++changed;}else if(isBg)++outside;else{context->Unmap(stage.Get(),0);fwprintf(stderr,L"letterbox modified at %u,%u\n",x,y);return 9;}}
    if(changed<100||!SaveBmp(capture,rgba,w,h)){fwprintf(stderr,L"readback/capture failed changed=%zu\n",changed);return 10;}
    wprintf(L"PASS image=%u target=%ux%u changed_samples=%zu letterbox_samples_preserved=%zu capture=%ls\n",which,w,h,changed,outside,capture.c_str());return 0;
}
int wmain(int argc,wchar_t**argv){
    if(argc!=5){fwprintf(stderr,L"usage: menu_background_host.exe <dll> <title.png> <selection.png> <capture-dir>\n");return 2;}
    HMODULE dll=LoadLibraryW(argv[1]);if(!dll){PrintHr(L"LoadLibrary",HRESULT_FROM_WIN32(GetLastError()));return 3;}
    auto init=reinterpret_cast<Init>(GetProcAddress(dll,"InitializeMenuBackgrounds"));auto render=reinterpret_cast<Render>(GetProcAddress(dll,"RenderMenuBackground"));auto release=reinterpret_cast<Release>(GetProcAddress(dll,"ReleaseMenuBackgrounds"));if(!init||!render||!release){fwprintf(stderr,L"required DLL export missing\n");FreeLibrary(dll);return 4;}
    HRESULT hr=init(argv[2],argv[3]);if(FAILED(hr)){PrintHr(L"InitializeMenuBackgrounds",hr);FreeLibrary(dll);return 5;}
    D3D_FEATURE_LEVEL level{};ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;hr=D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device,&level,&context);if(FAILED(hr)){PrintHr(L"WARP device",hr);release();FreeLibrary(dll);return 6;}
    std::error_code ec;std::filesystem::create_directories(argv[4],ec);if(ec){fwprintf(stderr,L"capture directory create failed: %ls\n",argv[4]);release();FreeLibrary(dll);return 7;}
    int result=0;const UINT sizes[][2]={{1280,960},{3840,2160}};for(UINT image=0;image<2&&result==0;++image)for(const auto& size:sizes){wchar_t name[80]{};swprintf_s(name,L"menu-%u-%ux%u.bmp",image,size[0],size[1]);result=RunOne(render,device.Get(),context.Get(),image,size[0],size[1],std::filesystem::path(argv[4])/name);if(result)break;}
    release();if(!result){hr=init(argv[2],argv[3]);if(FAILED(hr)){PrintHr(L"reinitialize after Release",hr);result=8;}else{const auto capture=std::filesystem::path(argv[4])/L"menu-reinitialized-1280x960.bmp";result=RunOne(render,device.Get(),context.Get(),1,1280,960,capture);release();if(!result)wprintf(L"PASS release and reinitialize; WARP readback covered both PNGs at 1280x960 and 3840x2160.\n");}}
    FreeLibrary(dll);return result;
}
