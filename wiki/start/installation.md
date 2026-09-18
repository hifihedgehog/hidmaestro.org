# Installation

Applications reference HIDMaestro.Core.dll and call HMContext.InstallDriver(). The SDK carries its driver payloads and installation tools.

The ARM64 and usbip-win2 0.9.8.0 changes remain under validation. The transport upgrade failed driver-lifecycle tests and is not ready for deployment. Published v1.8.1 downloads predate those additions. See [validation results](platform-support.md#validation).

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
scripts\build_tests.ps1 -Architecture x64
~~~

Use -Architecture arm64 when preparing ARM64 test applications. The native build creates both payloads before compiling the SDK. One SDK build embeds the prepared files. Missing native files stop the build.

For one ARM64 application:

~~~powershell
dotnet build test\HIDMaestroTest.csproj -r win-arm64
~~~

See [Build and release](../reference/build-and-release.md) for output directories and validation.

## Composite profiles and upgrades

Composite profiles install the bundled USB/IP transport when needed. No separate download is required on the consumer's machine. The build verifies upstream hashes, and the runtime checks package hashes and loaded images.

Close USB/IP consumers before an update. USB devices can briefly reconnect during PnP installation. Older HIDMaestro SDKs use a different attach layout and cannot create composites through the new driver. Update their SDKs before changing a shared host.

See [platform support](platform-support.md) for the architecture matrix and measured results. ARM64 hardware execution has not yet been tested.
