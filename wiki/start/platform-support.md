# Platform support

v1.9.0 runs on x64 and ARM64 Windows. One `HIDMaestro.Core.dll` serves both. It carries a native driver and helper payload for each architecture and picks the set matching the operating system, so an x64 consumer running under emulation on ARM64 Windows still gets ARM64 drivers.

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

## USB/IP 0.9.7.5

Composite personas use the bundled [usbip-win2 0.9.7.5 release](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.7.5). It is the last release with an ARM64 build before 0.9.8.0. 0.9.7.8 has two open kernel-pool-corruption reports, and 0.9.8.0 has an attach bug that blocks driver unload. Nothing between 0.9.7.5 and 0.9.7.7 touches the interface HIDMaestro uses, which was checked against the upstream source tag by tag.

Both installers are inside the SDK DLL. The build verifies each against the SHA-256 the upstream release publishes, and the SDK verifies the extracted copy again before running it. The x64 driver carries Microsoft's hardware verification signature, and the ARM64 driver is attestation-signed by Microsoft.

The SDK never checks which version of the transport a machine has. If a usbip-win2 host controller answers, the SDK uses it, so a machine already on 0.9.7.7 keeps 0.9.7.7 and nothing is reinstalled. If usbip-win2 is installed and its host controller is not answering, the SDK restarts that device and does not reinstall. Only where no usbip-win2 exists does it run the bundled installer, silently, with no window and no prompt. Windows re-enumerates the USB root hubs once during that install, so USB devices blink for a moment.

## Validation

The v1.9.0 release gate ran on x64: the full 60-scenario battery passed 60/60 on the tagged binaries on Windows 11 26200. usbip-win2 0.9.7.5 ran on that machine for the gate. The SDK deployed it unattended in 2.6 s on a machine that had carried 0.9.7.7, and the DualSense composite passed 26/26 on it before the battery's own USB/IP scenarios did.

Both native payloads and the ARM64 applications compile, link and stamp as ARM64, and the bundled ARM64 transport driver is verified as an ARM64 binary with a valid Microsoft signature.

ARM64 hardware has not run the battery. The Atom fixture was unavailable for this release.
