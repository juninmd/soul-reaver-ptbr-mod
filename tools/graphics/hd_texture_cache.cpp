#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <dxgiformat.h>
#include <wrl/client.h>
#include <bcrypt.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <vector>

#pragma comment(lib, "bcrypt.lib")
using Microsoft::WRL::ComPtr;
namespace {
constexpr UINT kOriginalSide = 256, kHdSide = 1024, kMaxPages = 32, kCacheEntries = 128;
constexpr size_t kMaxBytes = static_cast<size_t>(kHdSide) * kHdSide * 2;
struct Page { std::wstring sourcePath, hdPath; std::array<BYTE,32> sourceHash{}, hdHash{}; };
struct CacheEntry { ComPtr<ID3D11Resource> resource; ComPtr<ID3D11ShaderResourceView> view; bool checked=false, matched=false; };
std::mutex g_mutex;
std::vector<Page> g_pages;
std::array<CacheEntry,kCacheEntries> g_cache{};
size_t g_next=0;

bool IsHash(const wchar_t* s, std::array<BYTE,32>& out) {
  if(!s || wcslen(s)!=64) return false;
  for(size_t i=0;i<32;i++){ wchar_t a=s[i*2],b=s[i*2+1]; auto nib=[](wchar_t c)->int{if(c>=L'0'&&c<=L'9')return c-L'0';if(c>=L'a'&&c<=L'f')return c-L'a'+10;if(c>=L'A'&&c<=L'F')return c-L'A'+10;return -1;}; int x=nib(a),y=nib(b);if(x<0||y<0)return false;out[i]=static_cast<BYTE>((x<<4)|y); }
  return true;
}
bool HashBytes(const BYTE* p,size_t n,std::array<BYTE,32>& out){BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;std::vector<BYTE> object;DWORD cb=0,got=0;bool ok=false;if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0)return false;if(BCryptGetProperty(alg,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&cb),sizeof(cb),&got,0)>=0){object.resize(cb);if(BCryptCreateHash(alg,&hash,object.data(),cb,nullptr,0,0)>=0&&BCryptHashData(hash,const_cast<PUCHAR>(p),static_cast<ULONG>(n),0)>=0&&BCryptFinishHash(hash,out.data(),static_cast<ULONG>(out.size()),0)>=0)ok=true;}if(hash)BCryptDestroyHash(hash);object.clear();BCryptCloseAlgorithmProvider(alg,0);return ok;}
bool ReadPlane(const std::wstring& path,UINT side,const std::array<BYTE,32>& expected,std::vector<BYTE>& bytes){std::error_code ec;auto st=std::filesystem::status(path,ec);if(ec||!std::filesystem::is_regular_file(st))return false;auto n=std::filesystem::file_size(path,ec);const size_t want=static_cast<size_t>(side)*side*2;if(ec||n!=want||n>kMaxBytes)return false;std::ifstream f(path,std::ios::binary);if(!f)return false;bytes.resize(want);f.read(reinterpret_cast<char*>(bytes.data()),static_cast<std::streamsize>(want));if(!f||f.peek()!=std::char_traits<char>::eof())return false;std::array<BYTE,32> got{};return HashBytes(bytes.data(),bytes.size(),got)&&got==expected;}
bool ValidPath(const wchar_t* p,std::wstring& out){if(!p||!*p)return false;std::filesystem::path q(p);if(q.native().size()>32767||!q.is_absolute())return false;std::error_code ec;auto s=std::filesystem::status(q,ec);if(ec||!std::filesystem::is_regular_file(s))return false;out=q.lexically_normal().native();return true;}
void EraseResource(ID3D11Resource* r){for(auto& e:g_cache)if(e.resource.Get()==r)e=CacheEntry{};}
}

extern "C" __declspec(dllexport) HRESULT __stdcall RegisterTexturePage(const wchar_t* originalRAW,const wchar_t* originalSHA256,const wchar_t* hdRAW,const wchar_t* hdSHA256,UINT side){
 if(side!=kHdSide)return E_INVALIDARG;std::array<BYTE,32> oh{},hh{};std::wstring op,hp;if(!IsHash(originalSHA256,oh)||!IsHash(hdSHA256,hh)||!ValidPath(originalRAW,op)||!ValidPath(hdRAW,hp))return E_INVALIDARG;
 std::vector<BYTE> raw;if(!ReadPlane(op,kOriginalSide,oh,raw)||!ReadPlane(hp,kHdSide,hh,raw))return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
 std::lock_guard<std::mutex> lock(g_mutex);for(const auto& p:g_pages)if(p.sourceHash==oh){if(p.hdHash==hh&&p.sourcePath==op&&p.hdPath==hp)return S_FALSE;return HRESULT_FROM_WIN32(ERROR_DUP_NAME);}if(g_pages.size()>=kMaxPages)return HRESULT_FROM_WIN32(ERROR_TOO_MANY_NAMES);g_pages.push_back(Page{op,hp,oh,hh});for(auto& e:g_cache)if(e.checked&&!e.matched)e=CacheEntry{};return S_OK;
}
extern "C" __declspec(dllexport) HRESULT __stdcall ResolveTextureReplacement(ID3D11DeviceContext* context,ID3D11ShaderResourceView* original,ID3D11ShaderResourceView** out){
 if(!out)return E_POINTER;*out=nullptr;if(!context||!original)return E_INVALIDARG;if(context->GetType()!=D3D11_DEVICE_CONTEXT_IMMEDIATE)return E_INVALIDARG;ComPtr<ID3D11Device> contextDevice,sourceDevice;context->GetDevice(&contextDevice);original->GetDevice(&sourceDevice);if(contextDevice.Get()!=sourceDevice.Get())return E_INVALIDARG;D3D11_SHADER_RESOURCE_VIEW_DESC vd{};original->GetDesc(&vd);if(vd.Format!=DXGI_FORMAT_R16_UINT||vd.ViewDimension!=D3D11_SRV_DIMENSION_TEXTURE2D||vd.Texture2D.MipLevels!=1||vd.Texture2D.MostDetailedMip!=0)return S_FALSE;
 ComPtr<ID3D11Resource> res;original->GetResource(&res);ComPtr<ID3D11Texture2D> tex;if(FAILED(res.As(&tex)))return S_FALSE;D3D11_TEXTURE2D_DESC td{};tex->GetDesc(&td);if(td.Width!=kOriginalSide||td.Height!=kOriginalSide||td.MipLevels!=1||td.ArraySize!=1||td.SampleDesc.Count!=1||(td.Format!=DXGI_FORMAT_R16_TYPELESS&&td.Format!=DXGI_FORMAT_R16_UINT))return S_FALSE;
 std::lock_guard<std::mutex> lock(g_mutex);for(auto& e:g_cache)if(e.resource.Get()==res.Get()&&e.checked){if(e.matched){*out=e.view.Get();(*out)->AddRef();return S_OK;}return S_FALSE;}
 const size_t slotIndex=g_next++%kCacheEntries;auto& slot=g_cache[slotIndex];slot=CacheEntry{};slot.resource=res;std::vector<BYTE> pixels(static_cast<size_t>(kOriginalSide)*kOriginalSide*2);D3D11_TEXTURE2D_DESC sd=td;sd.Usage=D3D11_USAGE_STAGING;sd.BindFlags=0;sd.CPUAccessFlags=D3D11_CPU_ACCESS_READ;sd.MiscFlags=0;ComPtr<ID3D11Texture2D> staging;HRESULT hr=S_OK;
 ComPtr<ID3D11Device> device;tex->GetDevice(&device);hr=device->CreateTexture2D(&sd,nullptr,&staging);if(FAILED(hr))return hr;context->CopyResource(staging.Get(),tex.Get());D3D11_MAPPED_SUBRESOURCE map{};hr=context->Map(staging.Get(),0,D3D11_MAP_READ,0,&map);if(FAILED(hr))return hr;for(UINT y=0;y<kOriginalSide;y++)memcpy(pixels.data()+static_cast<size_t>(y)*kOriginalSide*2,static_cast<const BYTE*>(map.pData)+static_cast<size_t>(y)*map.RowPitch,kOriginalSide*2);context->Unmap(staging.Get(),0);
 std::array<BYTE,32> got{};if(!HashBytes(pixels.data(),pixels.size(),got)){slot=CacheEntry{};return E_FAIL;}const Page* match=nullptr;for(const auto& p:g_pages)if(p.sourceHash==got){match=&p;break;}slot.checked=true;if(!match){slot.matched=false;return S_FALSE;}
 std::vector<BYTE> hd;if(!ReadPlane(match->hdPath,kHdSide,match->hdHash,hd)){slot=CacheEntry{};return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);}D3D11_TEXTURE2D_DESC hdDesc{};hdDesc.Width=kHdSide;hdDesc.Height=kHdSide;hdDesc.MipLevels=1;hdDesc.ArraySize=1;hdDesc.Format=DXGI_FORMAT_R16_TYPELESS;hdDesc.SampleDesc.Count=1;hdDesc.Usage=D3D11_USAGE_IMMUTABLE;hdDesc.BindFlags=D3D11_BIND_SHADER_RESOURCE;D3D11_SUBRESOURCE_DATA initial{hd.data(),kHdSide*2,0};ComPtr<ID3D11Texture2D> hdTex;hr=device->CreateTexture2D(&hdDesc,&initial,&hdTex);if(FAILED(hr)){slot=CacheEntry{};return hr;}D3D11_SHADER_RESOURCE_VIEW_DESC hdViewDesc{};hdViewDesc.Format=DXGI_FORMAT_R16_UINT;hdViewDesc.ViewDimension=D3D11_SRV_DIMENSION_TEXTURE2D;hdViewDesc.Texture2D.MipLevels=1;ComPtr<ID3D11ShaderResourceView> view;hr=device->CreateShaderResourceView(hdTex.Get(),&hdViewDesc,&view);if(FAILED(hr)){slot=CacheEntry{};return hr;}slot.view=view;slot.matched=true;*out=view.Get();(*out)->AddRef();return S_OK;
}
extern "C" __declspec(dllexport) HRESULT __stdcall InvalidateTextureResource(ID3D11Resource* resource){if(!resource)return E_INVALIDARG;std::lock_guard<std::mutex> lock(g_mutex);EraseResource(resource);return S_OK;}
extern "C" __declspec(dllexport) HRESULT __stdcall ClearTexturePages(){std::lock_guard<std::mutex> lock(g_mutex);g_pages.clear();for(auto& e:g_cache)e=CacheEntry{};g_next=0;return S_OK;}
