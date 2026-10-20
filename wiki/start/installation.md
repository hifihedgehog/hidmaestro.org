# Installation

Applications reference HIDMaestro.Core.dll and call HMContext.InstallDriver(). The SDK carries its driver payloads and installation tools.

v2.0.0 ships for x64 and ARM64. See [platform support](platform-support.md#validation) for what was measured on each.

## Requirements

| Requirement | Details |
|---|---|
| Operating system | Windows 10 or 11 on x64, or Windows 11 on ARM64 |
| Consumer process | 64-bit .NET 10 process |
| Privileges | Administrator for installation and virtual device creation |
| Source build | Visual Studio C++ tools for x64 and ARM64, Windows SDK/WDK 10.0.26100.0, .NET 10 SDK |

The SDK assembly is AnyCPU and contains both native architectures. A 32-bit consumer is not supported. Read-only catalog operations do not require elevation.

## Reference the SDK

~~~xml
<PropertyGroup>
  <TargetFramework>net10.0-windows10.0.26100.0</TargetFramework>
  <RuntimeIdentifier>win-arm64</RuntimeIdentifier>
</PropertyGroup>
<ItemGroup>
  <Reference Include="HIDMaestro.Core">
    <HintPath>path\to\HIDMaestro.Core.dll</HintPath>
  </Reference>
</ItemGroup>
~~~

Use win-x64 for an x64 application. The same SDK DLL serves both targets. Native drivers follow the OS architecture.

The SDK also works in NativeAOT apps and in trimmed, self-contained, single-file apps (v2.0.0). Publish them as any app. Profiles load through source-generated JSON, so the catalog loads in both. See [platform support](platform-support.md#nativeaot-trimmed-and-single-file-apps).

## Create a controller

~~~csharp
using HIDMaestro;

using var ctx = new HMContext();
ctx.LoadDefaultProfiles();
ctx.InstallDriver();
using var controller = ctx.CreateController(ctx.GetProfile("xbox-360-wired")!);
controller.SubmitState(new HMGamepadState { Buttons = HMButton.A });
~~~

Dispose the controller to remove it. Dispose the context to release its controllers. See [Quickstart](quickstart.md) for output capture and additional inputs.

## Several programs on one machine

As of v2.0.0, two or more programs that embed HIDMaestro can run on one machine. Each program calls `InstallDriver()` itself. Only one deploys at a time, the driver is never downgraded, and the 2.0.0 driver is installed over any older one, whatever runs on it. `HMContext.LastDriverInstall` reports which of these happened. No program of this release registers a device while another removes one, so disposing several controllers takes about the sum of their removals. Everything the SDK runs elevated is staged under `%ProgramFiles%\HIDMaestro\Staging`, in directories only Administrators and SYSTEM can write. A running program built on v1.12.0 or older still removes every HIDMaestro device on the machine at its `InstallDriver` and at its first create, so programs built on HIDMaestro 1.x must move to 2.0.0. See [Programs Side by Side](../sdk/programs-side-by-side.md) and [Moving from 1.x](migration.md).

## Build from source

~~~powershell
scripts\build_all.cmd
~~~

The native build creates both payloads before compiling the SDK. Missing native files stop the SDK build. The driver, the companion and the OpenVR driver compile at `/W4` and hmswd at `/W3`, with the UMDF headers and Valve's `openvr_driver.h` marked external so their warnings stay off. Warnings print and do not stop the build. See [Build and Release](../reference/build-and-release.md).

As of v2.0.0 the build takes settings from environment variables or `-p:` properties. `HMSkipArm64=true` leaves out the ARM64 payload, `HMSkipUsbip=true` leaves out the USB/IP transport, and `HM_SDK_ROOT`, `HM_WDK_ROOT` and the rest point at the Windows SDK and WDK when they are not in their default places, as with the NuGet WDK. The defaults also read the variables an EWDK prompt sets. A build without the ARM64 payload or the transport refuses a controller that needs it with `HMPayloadMissingException`, before it changes anything on the machine, and `HMBuildInfo` says what the build carries. Official releases carry everything. See [Build and Release](../reference/build-and-release.md#build-settings-v200).

For one ARM64 application:

~~~powershell
dotnet build test\HIDMaestroTest.csproj -c Release -p:HMTargetArchitecture=arm64
~~~

See [Build and release](../reference/build-and-release.md) for output directories and validation.

## Composite profiles and upgrades

Composite profiles install the bundled USB/IP transport, usbip-win2 0.9.8.1, the first time one is created on a machine that has none. No separate download is required on the consumer's machine. The build checks the pinned hashes, and the SDK checks the installer again before running it. As of v2.0.0 the installer runs with the smallest set it allows (`/COMPONENTS=main,client /TASKS=vcredist /NOICONS`), so no GUI, SDK headers, debug symbols, desktop icon or Start menu folder are added, and a machine that holds the installer's uninstall record and its uninstaller file, without its driver package, gets a refusal, not the installer.

A machine that HIDMaestro put on an older usbip-win2, 0.9.7.7 through v1.8.1 or 0.9.7.5 in v1.9.0 and v1.9.1, is moved to 0.9.8.1 automatically. The SDK carries the host controller's own signed driver files and puts them on the existing controller with one Windows driver update. It never runs the vendor installer for this, and it leaves the root-hub filter alone, so no USB device drops and no window appears. It happens only in a Windows session where nothing has used the controller yet, because a used controller does not release its driver. Until then the older transport keeps working. Any other usbip-win2 version was installed by another program and is left as it is. `HIDMAESTRO_KEEP_TRANSPORT=1` turns the move off. There is nothing for a user to do. USB devices blink once during a first-time install on a machine with no transport, while Windows re-enumerates the root hubs.

See [platform support](platform-support.md) for the architecture matrix and measured results. ARM64 hardware has not run the battery.
