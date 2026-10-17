#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <dinput.h>
#include <cstdio>
#include <vector>

#pragma comment(lib, "setupapi.lib")
#pragma comment(lib, "hid.lib")
#pragma comment(lib, "dinput8.lib")
#pragma comment(lib, "dxguid.lib")
#pragma comment(lib, "user32.lib")

int main() {
    printf("=== DUALSENSE DETECTOR & TESTER ===\n");
    GUID hidGuid;
    HidD_GetHidGuid(&hidGuid);

    HDEVINFO hDevInfo = SetupDiGetClassDevsW(&hidGuid, nullptr, nullptr, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (hDevInfo == INVALID_HANDLE_VALUE) {
        printf("SetupDiGetClassDevsW failed\n");
        return 1;
    }

    SP_DEVICE_INTERFACE_DATA ifData{};
    ifData.cbSize = sizeof(SP_DEVICE_INTERFACE_DATA);

    HANDLE hDualSense = INVALID_HANDLE_VALUE;

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
                        wprintf(L"Found DualSense! VID=0x%04X PID=0x%04X Path=%s\n", attr.VendorID, attr.ProductID, detail->DevicePath);
                        hDualSense = h;
                        break;
                    }
                }
                CloseHandle(h);
            }
        }
    }
    SetupDiDestroyDeviceInfoList(hDevInfo);

    if (hDualSense == INVALID_HANDLE_VALUE) {
        printf("DualSense HID handle could not be opened (trying read-only or shared)...\n");
    } else {
        printf("Successfully opened DualSense HID handle! Testing LED (Emerald Green #00FF66) and Rumble...\n");
        // DualSense USB output report 0x02 (48 bytes)
        unsigned char report[48] = {0};
        report[0] = 0x02; // Report ID
        report[1] = 0xFF; // Valid flags 1: enable rumble motors, lightbar, etc.
        report[2] = 0xF7; // Valid flags 2
        report[3] = 0x50; // Right motor (high frequency rumble)
        report[4] = 0x50; // Left motor (heavy low frequency rumble)
        report[9] = 0;    // R
        report[10] = 255; // G
        report[11] = 102; // B (Emerald green)

        DWORD written = 0;
        BOOL ok = WriteFile(hDualSense, report, sizeof(report), &written, nullptr);
        printf("WriteFile USB Report 0x02 result=%d, bytes written=%lu (err=%lu)\n", ok, written, GetLastError());

        // Also test HidD_SetOutputReport
        BOOL okHid = HidD_SetOutputReport(hDualSense, report, sizeof(report));
        printf("HidD_SetOutputReport result=%d (err=%lu)\n", okHid, GetLastError());

        Sleep(500);
        // Turn off rumble, keep green LED
        report[3] = 0;
        report[4] = 0;
        WriteFile(hDualSense, report, sizeof(report), &written, nullptr);
        HidD_SetOutputReport(hDualSense, report, sizeof(report));
        CloseHandle(hDualSense);
    }

    // Now test DirectInput axes
    printf("\n--- DirectInput Axis Mapping ---\n");
    LPDIRECTINPUT8A pDI = nullptr;
    DirectInput8Create(GetModuleHandleW(nullptr), DIRECTINPUT_VERSION, IID_IDirectInput8A, reinterpret_cast<void**>(&pDI), nullptr);
    if (pDI) {
        GUID padGuid{};
        pDI->EnumDevices(DI8DEVCLASS_GAMECTRL, [](LPCDIDEVICEINSTANCEA d, LPVOID ref) -> BOOL {
            *reinterpret_cast<GUID*>(ref) = d->guidInstance;
            printf("Found DirectInput Gamepad: %s (GUID: %08lX)\n", d->tszProductName, d->guidInstance.Data1);
            return DIENUM_STOP;
        }, &padGuid, DIEDFL_ATTACHEDONLY);

        if (padGuid != GUID{}) {
            LPDIRECTINPUTDEVICE8A dev = nullptr;
            pDI->CreateDevice(padGuid, &dev, nullptr);
            if (dev) {
                dev->SetDataFormat(&c_dfDIJoystick);
                dev->SetCooperativeLevel(GetDesktopWindow(), DISCL_NONEXCLUSIVE | DISCL_BACKGROUND);
                dev->Acquire();
                for (int loop = 0; loop < 15; ++loop) {
                    dev->Poll();
                    DIJOYSTATE js{};
                    if (SUCCEEDED(dev->GetDeviceState(sizeof(js), &js))) {
                        printf("[%d] LX=%ld LY=%ld | Z=%ld Rx=%ld Ry=%ld Rz=%ld\n",
                               loop, js.lX, js.lY, js.lZ, js.lRx, js.lRy, js.lRz);
                    }
                    Sleep(200);
                }
                dev->Release();
            }
        }
        pDI->Release();
    }
    return 0;
}
