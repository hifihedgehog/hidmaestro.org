# Platform support

HIDMaestro runs on x64 and ARM64 Windows. Use v1.9.1 or later on ARM64. One `HIDMaestro.Core.dll` serves both. It carries a native driver and helper payload for each architecture and picks the set matching the operating system, so an x64 consumer running under emulation on ARM64 Windows still gets ARM64 drivers.

| Component | x64 Windows | ARM64 Windows |
|---|---|---|
| Managed SDK | AnyCPU assembly | Same assembly |
| HID and XInput drivers | Native x64 | Native ARM64 |
| Device helper and signing tool | Native x64 | Native ARM64 |
| USB/IP transport | Microsoft-signed x64 package | Microsoft-signed ARM64 package |
| Test app, example, ProfileExtractor | `win-x64` | `win-arm64` |
| OpenVR driver | x64 SteamVR plugin | Same x64 plugin for an x64 SteamVR host |

Virtual device creation requires a 64-bit process and administrator privileges. The x64 target supports Windows 10 and 11. The ARM64 target is Windows 11. The OpenVR plugin follows the SteamVR host's architecture, independently of the SDK process.

## Build

Install the .NET 10 SDK, Windows SDK/WDK 10.0.26100.0, and Visual Studio C++ build tools for both x64 and ARM64. The ARM64 compiler and C runtime libraries are a separate Visual Studio component.

```powershell
scripts\build_all.cmd
```

`build_all.cmd` builds both native payloads and the x64 OpenVR plugin, then the SDK. Native x64 files are under `build/`, and ARM64 files are under `build/arm64/`. A missing native payload fails the SDK build with a message naming the script.

To build a single application for ARM64:

```powershell
dotnet build test\HIDMaestroTest.csproj -c Release -p:HMTargetArchitecture=arm64
dotnet build tools\HIDMaestroProfileExtractor\HIDMaestroProfileExtractor.csproj -c Release -p:HMTargetArchitecture=arm64
```

## The ARM64 driver catalog

`InstallDriver()` builds a catalog for each driver INF with Inf2Cat before it signs the package and adds it to the driver store. Inf2Cat's ARM64 values name a Windows release, from `10_RS3_ARM64` on, and it has no bare `10_ARM64`. v1.9.0 asked for `10_ARM64`, which Inf2Cat rejects, so on ARM64 `InstallDriver()` failed before any driver reached the store. v1.9.1 asks for `10_RS3_ARM64`, version 1709, the first Windows 10 release on ARM64. x64 keeps `10_X64`.

One Inf2Cat serves both architectures. It is an x64 .NET program, which Windows 11 on ARM64 runs under its x64 emulation.

Battery scenario S61 extracts each architecture's payload with the embedded Inf2Cat, runs Inf2Cat with the value the SDK picks for that architecture, and requires one catalog per INF. Inf2Cat only parses the INFs and hashes the files, so the check runs on x64 for both architectures.

## USB/IP 0.9.8.1

Composite personas use the bundled usbip-win2 0.9.8.1. It is the first release with the fix for the attach work item that blocked driver unload in 0.9.8.0 ([usbip-win2#188](https://github.com/vadimgrn/usbip-win2/pull/188)). The [release page](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.8.1) carries the x64 installer only. The ARM64 installer is the same tag's build that the project's signing service posted in [usbip-win2#13](https://github.com/vadimgrn/usbip-win2/issues/13). Both installers ship the 0.9.8.1 tag's own headers, and neither carries the development branch's later changes.

Both installers are inside the SDK DLL. The build checks each against its pinned SHA-256, and the SDK checks the extracted copy again before running it. Both drivers are signed by Microsoft: the x64 one after hardware certification testing, the ARM64 one by attestation.

The driver's request layout changed in 0.9.8.0 and again in 0.9.8.1. The SDK speaks 0.9.7.x, 0.9.8.0 and 0.9.8.1 and asks the driver which one it has.

Where no usbip-win2 exists, the SDK runs the bundled installer silently, with no window and no prompt. Windows re-enumerates the USB root hubs once during that install, so USB devices blink for a moment. If usbip-win2 is installed and its host controller is not answering, the SDK restarts that device and does not reinstall.

A machine that HIDMaestro put on an older usbip-win2, 0.9.7.7 through v1.8.1 or 0.9.7.5 in v1.9.0 and v1.9.1, is moved to 0.9.8.1 automatically. The SDK carries the host controller's own signed driver files and puts them on the existing controller with one Windows driver update. It never runs the vendor installer for this, and it leaves the root-hub filter alone, so no USB device drops and no window appears. It happens only in a Windows session where nothing has used the controller yet, because a used controller does not release its driver. Until then the older transport keeps working. Any other usbip-win2 version was installed by another program and is left as it is. `HIDMAESTRO_KEEP_TRANSPORT=1` turns the move off.

## Validation

The v1.10.1 release gate ran on x64: the full 64-scenario battery passed 64/64 on the tagged binaries on Windows 11 26200, in 997.0 s. The gate machine's host controller runs 0.9.8.1, put there by the v1.9.2 move, so every composite scenario ran through the client's 0.9.8.1 request format against the live driver. The DualSense composite passed 26/26 end to end. Its root-hub filter is still the older one the move leaves alone, so SET_INTERFACE never reaches a composite there, and audio stream state comes from the traffic instead ([USB audio composite](../sdk/usb-audio-composite.md)).

The 0.9.8.0 request format was checked by compiling that version's own header with MSVC for x64 and ARM64, and the client sends its exact sizes and offsets. It has not run against a live driver. The move from 0.9.7.5 to 0.9.8.1 uses the same Windows driver update that moved machines from 0.9.7.7 to 0.9.7.5 in v1.9.0, which took 878 ms on 26200.

0.9.8.1 rounds a full-speed device's interrupt polling interval up where 0.9.7.5 rounded it down. Windows does not pace interrupt reads by that interval. Measured on 26200 by giving the DualShock 4 composite an interval that 0.9.7.5 converts to the same 8 ms period, the composite delivered 146 to 158 reports per second either way.

Both native payloads and the ARM64 applications compile, link and stamp as ARM64, and both bundled transport drivers are verified as the right architecture with valid Microsoft signatures.

ARM64 hardware has not run the battery. On ARM64, the steps after the catalog, signing it and adding the package to the driver store, have not run. The Atom fixture was not reachable for this release.
