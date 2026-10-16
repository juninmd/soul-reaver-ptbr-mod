#pragma once
#include <windows.h>
#include <d3d11.h>
extern "C" __declspec(dllimport) HRESULT __stdcall RegisterTexturePage(const wchar_t*,const wchar_t*,const wchar_t*,const wchar_t*,UINT);
extern "C" __declspec(dllimport) HRESULT __stdcall ResolveTextureReplacement(ID3D11DeviceContext*,ID3D11ShaderResourceView*,ID3D11ShaderResourceView**);
extern "C" __declspec(dllimport) HRESULT __stdcall InvalidateTextureResource(ID3D11Resource*);
extern "C" __declspec(dllimport) HRESULT __stdcall ClearTexturePages();
