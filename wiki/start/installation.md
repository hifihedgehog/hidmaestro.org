# Installation

HIDMaestro is a C# SDK plus a UMDF2 driver. There is no end-user installer because there is no end-user app &mdash; consumers like [PadForge](https://github.com/hifihedgehog/PadForge) reference the SDK and call `HMContext.InstallDriver()` themselves on first run.

This page covers the three reasons you'd be installing anything:

1. You're **building an app on top of the SDK** &rarr; reference `HIDMaestro.Core` and call `InstallDriver`.
2. You're **building HIDMaestro from source** &rarr; clone, run `scripts\build_all.cmd`.
3. You **already have a consumer that uses HIDMaestro** (PadForge etc.) &rarr; that consumer handles install for you, nothing to do here. See [Driver Install and Signing](../reference/driver-install-and-signing.md) for what's actually happening behind the scenes.

---

## Requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Windows 10 or 11, x64. UMDF2 framework version 2.15. Validated on Windows 11 26100 / 26200 (IoT Enterprise LTSC 2024). Windows 10 19044 (LTSC) tested as a slow-hardware fixture for `swap_regression`. |
| **Privilege** | `CreateController` and `InstallDriver` need `SeLoadDriverPrivilege` &mdash; standard admin elevation. Read-only operations (`HMDeviceExtractor.ListDevices`, `LoadProfilesFromDirectory`, `GetProfile`) work as a standard user. |
| **Runtime** | .NET 10 (`net10.0-windows10.0.26100.0` for the SDK). Targets `[SupportedOSPlatform("windows10.0.26100.0")]`. |
| **Driver-store space** | ~40 MB per installed driver package. The DriverStore caches every install regardless of whether you uninstall &mdash; budget for it on dev machines that iterate. |

No EV certificate. No `bcdedit /set testsigning`. No reboot. The driver self-signs at install time using a locally generated certificate trusted by the target machine; see [Driver Install and Signing](../reference/driver-install-and-signing.md) for the full sequence.

---

## Adding the SDK to your app

The SDK is distributed as `HIDMaestro.Core.dll`. Until a NuGet feed is published, reference it from a release ZIP or build it from source.

```xml
<ItemGroup>
  <Reference Include="HIDMaestro.Core">
    <HintPath>..\HIDMaestro\sdk\HIDMaestro.Core\bin\Release\net10.0-windows10.0.26100.0\HIDMaestro.Core.dll</HintPath>
  </Reference>
</ItemGroup>
```

The DLL is single-file: 225 profile JSONs, the UMDF2 driver binaries (`HIDMaestro.dll`, `HMXInput.dll`), the helper EXE (`hmswd.exe`), the signing toolchain (`signtool.exe`, `Inf2Cat.exe`, the Microsoft hardware-workflow catalog assemblies), and both INFs are all embedded as resources. You ship the SDK; the SDK ships everything else.

Target frameworks the consuming `csproj` needs:

```xml
<PropertyGroup>
  <TargetFramework>net10.0-windows10.0.26100.0</TargetFramework>
  <Platforms>x64</Platforms>
</PropertyGroup>
```

x86 / Any CPU are not supported &mdash; the driver is x64-only and the SDK's signing toolchain calls 64-bit native binaries.

---

## Three lines to a live virtual controller

```csharp
using var ctx = new HMContext();
ctx.LoadDefaultProfiles();
ctx.InstallDriver();
using var ctrl = ctx.CreateController(ctx.GetProfile("xbox-360-wired")!);
ctrl.SubmitState(new HMGamepadState
{
    Axes = HMGamepadStateHelpers.StandardAxes(ctrl.Profile, leftStickX: 1.0f),
});
```

That's the whole thing. `InstallDriver` is idempotent &mdash; if the package is already in the DriverStore at the same version it returns immediately. The controller is removed when `using` falls out of scope. `joy.cpl` shows "Controller (XBOX 360 For Windows)" while the process is alive.

For a richer walkthrough including output capture and PID FFB, see [Quickstart](quickstart.md).

---

## Building from source

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Visual Studio 2022+** | with the "Desktop development with C++" workload | `cl.exe` and `link.exe` for `driver.c`, `companion.c`, `hmswd.c` |
| **Windows SDK / WDK** | 10.0.26100.0 | `hidport.h`, `wdf.h`, UMDF 2.15 libs |
| **.NET 10 SDK** | latest | `dotnet build` for the C# SDK and test app |

### One-shot build

```cmd
cd HIDMaestro
scripts\build_all.cmd
```

`build_all.cmd` runs four steps in order:

1. `scripts\build.cmd` &mdash; compiles `driver.c` &rarr; `build\HIDMaestro.dll`, builds `hmswd.exe`, stamps both INFs with a fresh `1.x.y.HHmm` `DriverVer`.
2. `scripts\build_companion.cmd` &mdash; compiles `companion.c` &rarr; `build\HMXInput.dll`.
3. `dotnet build sdk\HIDMaestro.Core` (phase 1) &mdash; copies the freshly built native binaries into `Resources/`.
4. `dotnet build sdk\HIDMaestro.Core` (phase 2) &mdash; rebuilds with the populated `Resources/` so the embedded payload is current.

Two phases exist because MSBuild evaluates the embedded-resource glob before the `PackResources` pre-build target runs. On a fresh clone with empty `build\`, a one-phase build produces an SDK assembly with no driver inside. The two-phase variant is idempotent &mdash; re-run any time you touch `driver/` or `sdk/`.

After this completes:

```cmd
:: Smallest possible SDK consumer (5 seconds)
dotnet run --project example\SdkDemo

:: Full test app (admin required for create; cleans up on exit)
dotnet build test
test\bin\Release\net10.0-windows10.0.26100.0\win-x64\HIDMaestroTest.exe emulate xbox-360-wired
```

The test app self-elevates via UAC if launched non-elevated. To launch from an elevated terminal directly so stdin remains live (required for the regression battery), use `gsudo` or run from an Administrator PowerShell.

### Debug builds are blocked

`Directory.Build.props` declares `<Configurations>Release</Configurations>` and a `FailOnDebug` MSBuild target that hard-fails any `dotnet build -c Debug`. This was a real incident: the embedded `HMXInput.dll` and INFs came from a stale `Resources/` snapshot when a Debug build's `BeforeBuild` ran against an older `build/` payload while a parallel Release rebuild had moved on. Single-config builds eliminate the failure mode.

---

## Driver install internals (high-level)

`HMContext.InstallDriver()` does this on every call:

1. **Sweep ghost devices first.** Calls `RemoveAllVirtualControllers` to evict any virtuals left behind by a previous crashed session that's still bound to the old INF. Without this, `pnputil /delete-driver /uninstall /force` would refuse to delete the package and the install would silently restore the stale binary from `pnputil`'s internal cache.
2. **Check the driver-store hash.** If the embedded payload's SHA-256 matches what's currently installed, return immediately. No work, no UAC, no PnP churn.
3. **Extract the embedded payload to `%TEMP%\HIDMaestro\<hash>\`.** Idempotent on the hash &mdash; same payload reuses the directory.
4. **Generate a self-signed certificate** if one isn't in `Cert:\LocalMachine\Root` already. Adds it to Root and TrustedPublisher. The certificate is per-machine and survives reboots. `bcdedit /set testsigning` is **not** required.
5. **Generate `.cat` catalogs** via `Inf2Cat.exe` and **sign** the INFs and binaries with `signtool.exe`.
6. **`pnputil /add-driver hidmaestro.inf /install`** and the same for `hidmaestro_xusb.inf`. After this returns, the driver is in the DriverStore and ready to bind to virtual devices.
7. **Delete the temp extraction.** Nothing is left in the consuming app's directory.

The full breakdown is in [Driver Install and Signing](../reference/driver-install-and-signing.md). Consumers don't need to understand any of it &mdash; one call, idempotent, self-healing.

---

## Uninstalling

There is no global uninstaller. The driver is removed by the consumer via:

```csharp
HMContext.RemoveAllVirtualControllers();   // evict every live + ghost devnode
DriverBuilder.Uninstall();                 // pnputil /delete-driver hidmaestro.inf
```

Or through the test app:

```cmd
HIDMaestroTest.exe cleanup
```

The cleanup command sweeps every `HIDMAESTRO*` PnP devnode (plain HID, XUSB companion, and SWD-enumerated parents), removes the driver packages, and deletes the certificate from Root + TrustedPublisher.

> **NEVER `pnputil /delete-driver /uninstall /force` on the active driver.** It leaves devices in Code 14 ("restart required"). Always run `HIDMaestroTest cleanup` (or `HMContext.RemoveAllVirtualControllers`) FIRST to evict the devices, then plain `pnputil /delete-driver` (no `/uninstall`) if a package delete is even needed. `InstallDriver` is idempotent across version bumps &mdash; manual uninstall before reinstall is almost never the right move.

---

## See also

- [Quickstart](quickstart.md) &mdash; first-controller walkthrough using `example/SdkDemo`.
- [Driver Install and Signing](../reference/driver-install-and-signing.md) &mdash; full breakdown of the embedded payload, certificate management, and `pnputil` mechanics.
- [Build and Release](../reference/build-and-release.md) &mdash; the two-phase build, INF stamping, and release ZIP recipe.
- [Troubleshooting](../troubleshooting.md) &mdash; `pnputil` errors, stale binaries, devnode ghosts.
