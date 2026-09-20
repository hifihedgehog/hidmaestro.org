# Installation

Applications reference HIDMaestro.Core.dll and call HMContext.InstallDriver(). The SDK carries its driver payloads and installation tools.

v1.9.0 ships for x64 and ARM64. See [platform support](platform-support.md#validation) for what was measured on each.

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

## Build from source

~~~powershell
scripts\build_all.cmd
~~~

The native build creates both payloads before compiling the SDK. Missing native files stop the SDK build.

For one ARM64 application:

~~~powershell
dotnet build test\HIDMaestroTest.csproj -c Release -p:HMTargetArchitecture=arm64
~~~

See [Build and release](../reference/build-and-release.md) for output directories and validation.

## Composite profiles and upgrades

Composite profiles install the bundled USB/IP transport, usbip-win2 0.9.7.5, the first time one is created on a machine that has none. No separate download is required on the consumer's machine. The build verifies the upstream hashes, and the SDK verifies the installer again before running it.

A machine that already has a working usbip-win2, including 0.9.7.7 from an earlier HIDMaestro release, keeps the one it has. The interface HIDMaestro uses is the same in both, and the SDK does not reinstall or downgrade it. There is nothing for a user to do when moving to v1.9.0. USB devices blink once during a first-time install while Windows re-enumerates the root hubs.

See [platform support](platform-support.md) for the architecture matrix and measured results. ARM64 hardware has not run the battery.
