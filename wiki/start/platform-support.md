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

## USB/IP 0.9.7.5

Composite personas use the bundled [usbip-win2 0.9.7.5 release](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.7.5). It is the last release with an ARM64 build before 0.9.8.0. 0.9.7.8 has two open kernel-pool-corruption reports, and 0.9.8.0 has an attach bug that blocks driver unload. Nothing between 0.9.7.5 and 0.9.7.7 touches the interface HIDMaestro uses, which was checked against the upstream source tag by tag.

Both installers are inside the SDK DLL. The build verifies each against the SHA-256 the upstream release publishes, and the SDK verifies the extracted copy again before running it. The x64 driver carries Microsoft's hardware verification signature, and the ARM64 driver is attestation-signed by Microsoft.

Where no usbip-win2 exists, the SDK runs the bundled installer silently, with no window and no prompt. Windows re-enumerates the USB root hubs once during that install, so USB devices blink for a moment. If usbip-win2 is installed and its host controller is not answering, the SDK restarts that device and does not reinstall.

A machine that HIDMaestro put on usbip-win2 0.9.7.7, which is what releases through v1.8.1 installed, is moved to 0.9.7.5 automatically. The SDK carries the host controller's own signed driver files and puts them on the existing controller with one Windows driver update. It never runs the vendor installer for this, and it leaves the root-hub filter alone, so no USB device drops and no window appears. Measured on 26200, the move took 878 ms. It happens only in a Windows session where nothing has used the controller yet, because a used controller does not release its driver. Until then 0.9.7.7 keeps working. Any other usbip-win2 version was installed by another program and is left as it is. `HIDMAESTRO_KEEP_TRANSPORT=1` turns the move off.

## Validation

The v1.9.1 release gate ran on x64: the full 62-scenario battery passed 62/62 on the tagged binaries on Windows 11 26200, in 1,047.0 s. S61 built the driver catalogs for both architectures. S62 ran Steam's own firmware updater, which saw the 2026 Steam Controller persona at Steam's current firmware build and offered it no update. A copy of the persona answering with the old captured build was offered one in the same run.

The move from 0.9.7.7 was measured before the v1.9.0 gate. A genuine 0.9.7.7 host controller was bound on that machine, and the SDK moved it to 0.9.7.5 on its own in 878 ms. The DualSense composite passed 26/26 in the same run.

Both native payloads and the ARM64 applications compile, link and stamp as ARM64, and the bundled ARM64 transport driver is verified as an ARM64 binary with a valid Microsoft signature.

ARM64 hardware has not run the battery. On ARM64, the steps after the catalog, signing it and adding the package to the driver store, have not run. The Atom fixture was not reachable for this release.
