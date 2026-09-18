# Platform support

The [ARM64 validation branch](https://github.com/hifihedgehog/HIDMaestro/tree/arm64-usbip-0980) builds one `HIDMaestro.Core.dll` for x64 and ARM64 Windows. The SDK contains native driver and helper payloads for both architectures and selects them from the operating system's architecture. An emulated x64 consumer on ARM64 Windows therefore selects ARM64 drivers.

The published v1.7.3 release predates this change. This implementation remains under validation and is not ready for deployment. A separate correction to the USB/IP driver passed targeted kernel tests. Production signing and the full integration gate remain pending.

| Component | x64 Windows | ARM64 Windows |
|---|---|---|
| Managed SDK | AnyCPU assembly | Same assembly |
| HID and XInput drivers | Native x64 | Native ARM64 |
| Device helper and signing tool | Native x64 | Native ARM64 |
| USB/IP transport | Microsoft-signed x64 package | Microsoft-signed ARM64 package |
| Test app, example, ProfileExtractor | `win-x64` | `win-arm64` |
| OpenVR driver | x64 SteamVR plugin | Same x64 plugin for an x64 SteamVR host |

Virtual device creation requires a 64-bit process and administrator privileges. The x64 target supports Windows 10 and 11. The ARM64 target is Windows 11, matching the upstream USB/IP package requirements. The OpenVR plugin follows the SteamVR host's architecture, independently of the SDK process.

## Build

Install the .NET 10 SDK, Windows SDK/WDK 10.0.26100.0, and Visual Studio C++ build tools for both x64 and ARM64. The ARM64 compiler and C runtime libraries are separate Visual Studio components.

```powershell
scripts\build_all.cmd
scripts\build_tests.ps1 -Architecture x64
scripts\build_tests.ps1 -Architecture arm64
```

`build_all.cmd` builds both native payloads and the x64 OpenVR plugin before compiling the SDK. Native x64 files are under `build/`, and ARM64 files are under `build/arm64/`. Resource files are declared explicitly, so one SDK build embeds the prepared payloads. A missing native payload fails the build.

The OpenVR smoke probe runs as x64 because it loads SteamVR's x64 client DLL. ARM64 test fixtures need the x64 .NET 10 runtime for that probe. SDL probes need a stock SDL3 build matching their process architecture.

To build a single application for ARM64:

```powershell
dotnet build test\HIDMaestroTest.csproj -r win-arm64
dotnet build tools\HIDMaestroProfileExtractor\HIDMaestroProfileExtractor.csproj -r win-arm64
dotnet build example\SdkDemo\SdkDemo.csproj -r win-arm64
```

## USB/IP 0.9.8.0

Composite personas use the bundled [usbip-win2 0.9.8.0 release](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.8.0). The build verifies each release installer's SHA-256, extracts its signed INF/SYS/CAT files, and verifies their hashes against `sdk/HIDMaestro.Core/UsbipPackage.json`. Both architecture packages remain inside the SDK DLL.

At runtime, the SDK stages the package in an administrator-only directory and adds it through Windows PnP. It does not invoke the vendor uninstaller or remove an existing shared root-hub filter. Installation waits for device notifications and checks the configured file hashes, loaded driver paths, and supported IOCTL layout before reporting readiness. USB devices can briefly reconnect during a PnP update.

The driver protocol changed. Old SDKs that send the 0.9.7.7 attach structure cannot use the new driver. Update every consumer's SDK before upgrading a shared host. Existing imports must be detached before an update. HIDMaestro retains the zero-copy receive mode and leaves serial overrides empty, preserving the profile's identity.

## Validation

Both native payloads and the ARM64 managed applications cross-compile. Native static assertions check the Windows notification layout, shared-memory structures, and upstream USB/IP ABI for both architectures.

Run `scripts\verify_native_layout.cmd <usbip-win2-checkout>` with the reference checkout at tag `v.0.9.8.0` to compile those assertions for both architectures.

On September 9, 2026, x64 Windows Sandbox tests passed fresh installation, 49 package checks, and wire tests for Steam Deck, the 2015 Steam Controller, and Triton. An earlier upgrade from an unused 0.9.7.7 installation also passed.

The active-import guard passed all four checks in a separate guest. After that legacy device was released and its process exited, upgrading the used installation failed with PnP error 481. Rebinding the current 0.9.8.0 driver after device use also failed with error 481. A kernel live dump showed USB/IP worker callbacks blocked during work-item deletion while driver unload waited for them. This was a live diagnostic dump, not a system crash.

A correction to the USB/IP work-item lifetime passed 22 targeted kernel checks in isolated x64 Windows 11 VMs. An unpatched source build with the same compiler, WDK, and certificate still timed out after 300 seconds. The corrected build completed the same operation in 138 ms.

These tests used development certificates confined to the VMs. The SDK still contains the unmodified upstream release packages. A production-signed corrected package and the full HIDMaestro validation gate are required before deployment or release.

ARM64 hardware execution has not been tested. The Atom fixture was unavailable. No new release has been published.
