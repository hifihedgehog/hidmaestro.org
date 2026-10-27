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
| NativeAOT and trimmed single-file apps (v2.0.0) | `win-x64` | `win-arm64` |

Virtual device creation requires a 64-bit process and administrator privileges. The x64 target supports Windows 10 and 11. The ARM64 target is Windows 11. The OpenVR plugin follows the SteamVR host's architecture, independently of the SDK process.

## Build

Install the .NET 10 SDK, Windows SDK/WDK 10.0.26100.0, and Visual Studio C++ build tools for both x64 and ARM64. The ARM64 compiler and C runtime libraries are a separate Visual Studio component.

```powershell
scripts\build_all.cmd
```

`build_all.cmd` builds both native payloads and the x64 OpenVR plugin, then the SDK. The native scripts compile the driver, the companion and the OpenVR driver at `/W4`, and hmswd at `/W3`. The UMDF headers and Valve's `openvr_driver.h` are passed with `/external:I` and `/external:W0`, which turn warnings off in those headers and the headers they include, while every warning in HIDMaestro's own sources still prints. No `/WX` is set, so a new warning prints and does not stop the build. A full `build_all.cmd` printed 70 compiler warnings at commit c5c0f05 and none at a6fbbe8, development measurements. Native x64 files are under `build/`, and ARM64 files are under `build/arm64/`. A missing native payload fails the SDK build with a message naming the script.

A source build can leave the ARM64 payload out with `HMSkipArm64=true`, the USB/IP transport out with `HMSkipUsbip=true`, and can take its Windows SDK and WDK from an installed kit, the NuGet WDK or an EWDK prompt. See [Build and Release](../reference/build-and-release.md#build-settings-v200). `HMBuildInfo.DriverArchitectures` and `UsbipArchitectures` report what a built `HIDMaestro.Core.dll` carries.

To build a single application for ARM64:

```powershell
dotnet build test\HIDMaestroTest.csproj -c Release -p:HMTargetArchitecture=arm64
dotnet build tools\HIDMaestroProfileExtractor\HIDMaestroProfileExtractor.csproj -c Release -p:HMTargetArchitecture=arm64
```

## NativeAOT, trimmed and single-file apps

As of v2.0.0 `HIDMaestro.Core.dll` works in NativeAOT apps and in trimmed, self-contained, single-file apps, for x64 and ARM64. Profiles load through source-generated JSON, every Win32 call goes through `LibraryImport`, and `hmswd.exe` always comes from the embedded resource, since `Assembly.Location` is empty in a single-file app. At v1.12.0 both kinds of app loaded 0 of the 336 catalog profiles, because reflection-based JSON is switched off in them. The `aot_smoke` probe publishes one source four ways, NativeAOT and trimmed single-file for each architecture. Each app loads the catalog, installs the driver, creates a `dualshock-4-v2` on the UMDF2 driver and a `dualsense-composite` on USB/IP, submits input, reads it back, writes an output report, waits for `OutputReceived` and disposes. Battery scenarios S74 and S75 run the two apps for the machine's architecture, so the ARM64 apps are built and published and have not run on ARM64 hardware. See [Build and Release](../reference/build-and-release.md#nativeaot-trimming-and-single-file).

`InstallDriver()` builds a catalog for each driver INF with Inf2Cat before it signs the package and adds it to the driver store. Inf2Cat's ARM64 values name a Windows release, from `10_RS3_ARM64` on, and it has no bare `10_ARM64`. v1.9.0 asked for `10_ARM64`, which Inf2Cat rejects, so on ARM64 `InstallDriver()` failed before any driver reached the store. v1.9.1 asks for `10_RS3_ARM64`, version 1709, the first Windows 10 release on ARM64. x64 keeps `10_X64`.

One Inf2Cat serves both architectures. It is an x64 .NET program, which Windows 11 on ARM64 runs under its x64 emulation.

Battery scenario S61 extracts each architecture's payload with the embedded Inf2Cat, runs Inf2Cat with the value the SDK picks for that architecture, and requires one catalog per INF. Inf2Cat only parses the INFs and hashes the files, so the check runs on x64 for both architectures.

## USB/IP 0.9.8.1

Composite personas use the bundled usbip-win2 0.9.8.1. It is the first release with the fix for the attach work item that blocked driver unload in 0.9.8.0 ([usbip-win2#188](https://github.com/vadimgrn/usbip-win2/pull/188)). The [release page](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.8.1) carries the x64 installer only. The ARM64 installer is the same tag's build that the project's signing service posted in [usbip-win2#13](https://github.com/vadimgrn/usbip-win2/issues/13). Both installers ship the 0.9.8.1 tag's own headers, and neither carries the development branch's later changes.

As of v2.0.1 the SDK DLL holds the host controller's driver package for each architecture, `usbip2_ude.inf`, `.sys` and `.cat`, unpacked at build time from those installers, and no longer the installers themselves. That brought `HIDMaestro.Core.dll` from 63.1 MB to 18.1 MB. The build checks each installer against its pinned SHA-256 and each unpacked file against its own, and the SDK checks the staged files again before Windows installs them. Both drivers are signed by Microsoft: the x64 one after hardware certification testing, the ARM64 one by attestation.

The driver's request layout changed in 0.9.8.0 and again in 0.9.8.1. The SDK speaks 0.9.7.x, 0.9.8.0 and 0.9.8.1 and asks the driver which one it has.

Where no host controller exists, the SDK installs one silently, with no window and no prompt. As of v2.0.1 it registers the `ROOT\USB` devnode usbip-win2's own `devnode.exe` would and installs the driver on it through Windows' driver update. It never runs usbip-win2's installer and never installs its root-hub filter, so no USB root hub restarts and no USB device drops, and it adds no Apps entry, program folder, scheduled task, shortcut or VC++ runtime. Without the filter the host controller passes no SET_CONFIGURATION or SET_INTERFACE to the device, and a composite persona reads its audio streams' state from their traffic, as it has beside an older filter since v1.10.0. The install is recorded under `HKLM\SOFTWARE\HIDMaestroUsbip`, so a [removal](removing-hidmaestro.md#usbip-win2) takes HIDMaestro's install and leaves another program's. See [Driver Install and Signing](../reference/driver-install-and-signing.md#usbip-transport). Through v2.0.0 the SDK ran usbip-win2's installer, which adds the filter and restarts every USB root hub. If a host controller is present and not answering, the SDK restarts that device and never adds a second one.

Handheld Companion's and VIIPER's installers look for usbip-win2's Apps entry, find none after HIDMaestro's install, and run usbip-win2's installer. That adds the root-hub filter, so every USB device drops once, and a second host controller. HIDMaestro works with two host controllers.

A machine that HIDMaestro put on an older usbip-win2, 0.9.7.7 through v1.8.1 or 0.9.7.5 in v1.9.0 and v1.9.1, is moved to 0.9.8.1 automatically. The SDK carries the host controller's own signed driver files and puts them on the existing controller with one Windows driver update. It never runs the vendor installer for this, and it leaves the root-hub filter alone, so no USB device drops and no window appears. It happens only in a Windows session where nothing has used the controller yet, because a used controller does not release its driver. Until then the older transport keeps working. Any other usbip-win2 version was installed by another program and is left as it is. `HIDMAESTRO_KEEP_TRANSPORT=1` turns the move off.

## Validation

The v2.1.0 release gate ran on x64: the full 101-scenario battery passed all 101 scenarios on the release binaries on the development laptop, a Lenovo Legion Pro 7 16AFR10H with a 16-core AMD Ryzen 9 9955HX3D, 64 GB of DDR5-5600 and an NVIDIA GeForce RTX 5080 Laptop GPU on Windows 11 build 26200, in 30 minutes. On a 4-core Intel Celeron J4125 mini PC with Windows 10 IoT Enterprise LTSC 19044, at `HIDMAESTRO_TIMEOUT_SCALE=2` over SSH, 97 passed in 42 minutes and 4 skipped their probes: S54 and S62 need a Steam client, S70 a desktop session's Raw Input devices, and S73 the `wsb` command for Windows Sandbox, which this machine lacks. Inside passing scenarios, the checks that need a desktop session or a Steam client skip too: the Raw Input checks in S37 and S71, S50's legacy reader app, section Y of S71 and the Steam client checks in S65. S101 removes HIDMaestro from that machine itself, reads it clean and installs the driver again, and only its run inside Windows Sandbox skips.

The v1.12.0 release gate ran on x64: the full 70-scenario battery passed all 70 scenarios on the release binaries on Windows 11 26200. The gate machine's host controller runs 0.9.8.1, put there by the v1.9.2 move, so every composite scenario ran through the client's 0.9.8.1 request format against the live driver. The DualSense composite passed 26/26 end to end, and the Switch 2 Pro composite 255/255, with Windows binding WinUSB to its vendor interface from the persona's own descriptors. Its root-hub filter is still the older one the move leaves alone, so SET_INTERFACE never reaches a composite there, and audio stream state comes from the traffic instead ([USB audio composite](../sdk/usb-audio-composite.md)).

The 0.9.8.0 request format was checked by compiling that version's own header with MSVC for x64 and ARM64, and the client sends its exact sizes and offsets. It has not run against a live driver. The move from 0.9.7.5 to 0.9.8.1 uses the same Windows driver update that moved machines from 0.9.7.7 to 0.9.7.5 in v1.9.0, which took 878 ms on 26200.

0.9.8.1 rounds a full-speed device's interrupt polling interval up where 0.9.7.5 rounded it down. Windows does not pace interrupt reads by that interval. Measured on 26200 by giving the DualShock 4 composite an interval that 0.9.7.5 converts to the same 8 ms period, the composite delivered 146 to 158 reports per second either way.

Both native payloads and the ARM64 applications compile, link and stamp as ARM64, and both bundled transport drivers are verified as the right architecture with valid Microsoft signatures.

ARM64 hardware has not run the battery. On ARM64, the steps after the catalog, signing it and adding the package to the driver store, have not run.
