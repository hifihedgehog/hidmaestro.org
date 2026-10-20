# Build and release

HIDMaestro builds and ships for x64 and ARM64 from one source tree. See [platform support](../start/platform-support.md).

## Prerequisites

Install the .NET 10 SDK, Visual Studio C++ tools for x64 and ARM64, and Windows SDK/WDK 10.0.26100.0. The ARM64 compiler is a separate Visual Studio component. PowerShell 5.1 or later runs the build scripts.

## Build

~~~powershell
scripts\build_all.cmd
~~~

The native build compiles the HID driver, XInput companion, and hmswd helper for x64 and again for ARM64. It also builds the x64 OpenVR plugin. The SDK build embeds both payload sets and both signed USB/IP installers.

The native scripts compile the driver, the companion and the OpenVR driver at `/W4`, and hmswd at `/W3`. Since v2.0.0 they compile the driver and the companion with `/Ox /Os`, the release setting of the WDK's own driver projects (full optimization, favoring size). Through v1.12.0 they passed no optimization switch, so `cl.exe` compiled both unoptimized. The UMDF headers and Valve's `openvr_driver.h` are passed with `/external:I` and `/external:W0`, which turn warnings off in those headers and the headers they include, while every warning in HIDMaestro's own sources still prints. No `/WX` is set, so a new warning prints and does not stop the build. A full `build_all.cmd` printed 70 compiler warnings at commit c5c0f05 and none at a6fbbe8, development measurements.

The script runs the SDK build once. The SDK project embeds exactly the files its pre-build target stages for the settings in force, each listed with the path it is staged at and the name it is embedded under (v2.0.0). Through v1.12.0 the project globbed `Resources\`, which was evaluated before anything was staged, so a fresh tree needed two builds, and a skip build in a tree that once built everything would have embedded the stale files. Missing native files fail the build with a message naming the script.

The test build script builds the test app, ProfileExtractor, example, and the probe projects used by the battery. It copies a canonical SDK assembly into their outputs and verifies each copy's SHA-256 hash.

The OpenVR smoke probe is x64 because it loads SteamVR's x64 client DLL. The regression script applies the same paths to its freshness checks and launches.

## Build settings (v2.0.0)

Each setting is an environment variable. MSBuild reads environment variables as properties, so a setting both sides read reaches the native scripts and the SDK project alike, and a setting the SDK project reads also works as `-p:` on a `dotnet build` of the SDK. The native scripts read `HM_WDK_ROOT_ARM64`, and only the SDK project reads `HMWdkBin` and `HMInf2catBin`.

| Setting | Effect | Default |
|---|---|---|
| `HMSkipArm64=true` | Builds and embeds the x64 driver, companion and helper only, and leaves out every ARM64 payload: the ARM64 INFs, signtool set, usbip-win2 installer and host controller files. | unset |
| `HMSkipUsbip=true` | Leaves out the USB/IP transport: both installers and the host controller files. Nothing is downloaded, hashed or unpacked for it. | unset |
| `HM_SDK_ROOT` | The Windows SDK: the `um` and `shared` headers, the `um` libraries, `rc.exe`, and the signtool set the SDK embeds. | `WindowsSdkDir` when a Visual Studio or EWDK prompt set it, otherwise `%ProgramFiles(x86)%\Windows Kits\10` |
| `HM_WDK_ROOT` | The WDK: the `km` headers, the UMDF 2.15 headers and stub library, and Inf2Cat. | `WDKContentRoot` when an EWDK prompt set it, otherwise `HM_SDK_ROOT` |
| `HM_WDK_ROOT_ARM64` | The WDK for the ARM64 build. | `HM_WDK_ROOT` |
| `HM_WDK_VERSION` | The kits' version folder. | `Version_Number` when an EWDK prompt set it, otherwise `10.0.26100.0` |
| `HMWdkBin` | The folder whose `x64` and `arm64` folders hold the signtool set. | `HM_SDK_ROOT\bin\<version>\` |
| `HMInf2catBin` | The folder whose `x86` folder holds Inf2Cat. | `HM_WDK_ROOT\bin\<version>\` |

The scripts find Visual Studio through `VSINSTALLDIR` when a Visual Studio or EWDK prompt set it, and otherwise search `C:\Program Files\Microsoft Visual Studio`. Every kit root is checked for the folders the build reads from it, and a missing one stops the build with an error that names the setting. A missing Visual Studio stops it with "Visual Studio C++ build tools are required". The driver steps print where their SDK, WDK, kit version and Visual Studio came from, and the OpenVR step prints its Visual Studio path.

Installed kits need no setting. With the NuGet WDK, `HM_WDK_ROOT` is the `c` folder of `Microsoft.Windows.WDK.x64` and `HM_WDK_ROOT_ARM64` the `c` folder of `Microsoft.Windows.WDK.ARM64`, because each package carries the UMDF stub library for its own architecture only. The Windows SDK then comes from the installed kit, which Visual Studio's C++ workload installs and which Microsoft lists as a requirement of the NuGet WDK ([Install the WDK using NuGet](https://learn.microsoft.com/windows-hardware/drivers/install-the-wdk-using-nuget)). The SDK's own NuGet packages lay out libraries as `c\um\<arch>`, not `Lib\<version>\um\<arch>`, so `HM_SDK_ROOT` cannot point at them. A one-time comparison during development found the NuGet WDK's `km` headers, UMDF 2.15 headers and both stub libraries in 10.0.26100.6584 byte-identical to the installed WDK of the same version. `check_build_layouts.ps1` does not repeat it.

In the EWDK the build runs from the prompt `LaunchBuildEnv.cmd` opens, and the defaults pick up the image's kit, version and Build Tools. The EWDK itself was not run for this release, since downloading it means accepting Microsoft's EWDK license terms. `scripts/check_build_layouts.ps1` builds the native payloads for both architectures from the pinned NuGet WDK packages, then under the variables an EWDK prompt sets, pointed at the installed kit and Visual Studio, then with roots that hold no kit.

The SDK embeds six Inf2Cat files where v1.12.0 embedded eight. `inf2cat.exe.manifest` and `Microsoft.Kits.Logger.dll` are gone: no assembly in the Inf2Cat set references the logger, Inf2Cat.exe's embedded manifest takes precedence over an external one, and runs with and without both files produce the same catalogs. The NuGet WDK carries neither.

## What a build carries

`HMBuildInfo` reports `DriverArchitectures`, `UsbipArchitectures`, `HasOpenVrDriver` and `IsComplete`. Each is read once from the assembly's own resource names, so it describes the bytes actually embedded, whatever the settings were. A controller that needs a payload the build lacks for the machine's architecture throws `HMPayloadMissingException`, derived from `InvalidOperationException`, before any machine-wide step: a composite persona without the USB/IP transport, and any other controller without the driver. `InstallDriver`, `InstallUsbipBackend` and `HMVR.EnsureDriverRegistered` throw it too, and `IsUsbipBackendAvailable` is false in a build without the transport. Official releases stay complete: `pre-tag-validate.cmd` clears `HMSkipArm64` and `HMSkipUsbip` before it builds, battery scenario S78 fails unless the release build reports `IsComplete`, and `check_build_layouts.ps1` builds every layout above before the battery runs.

## NativeAOT, trimming and single-file

The SDK project sets `IsAotCompatible`, which turns on the trim, single-file and AOT analyzers, and `aot-analyzers.globalconfig` raises the `Trimming`, `SingleFile` and `AOT` diagnostic categories to errors in Release. During development, at commit d37e32e, the same analyzers reported 40 warnings on the v1.12.0 source: 38 from the 19 reflection-based `JsonSerializer` calls, one from the `JsonStringEnumConverter`, and one from the `Assembly.Location` read. The release changes four things:

- Profiles and layouts load through `HMJsonContext`, a source-generated `JsonSerializerContext` with the options `HMLayoutJsonOptions.Default` carried: camelCase names read case-insensitively, comments and trailing commas allowed, `HMAxis` through its own converter, every other enum as a snake_case string through a generic `JsonStringEnumConverter<TEnum>`. The generated code assigns every init-only property in one object initializer, so a key the JSON leaves out would arrive as `default(T)`. Reflection kept the record's own initializers, and 68 of the 336 profiles depend on them, as counted during development at commit d37e32e, so the layout converter fills each such key from a freshly constructed record. Battery scenario S76 reads every embedded profile through both paths and requires the same contents.
- All 113 `DllImport` declarations became `LibraryImport`. Five SetupAPI declarations among them that nothing called were then removed, and the code this release adds declares 75 more, 183 in all. Strings marshal as UTF-16, and every `bool` as the 4-byte Win32 `BOOL` except the six `HidD_` results, which are the one-byte `BOOLEAN`. The per-frame calls (`SetEvent`, `WaitForSingleObject`, `WaitForMultipleObjects`) allocate nothing. `CM_Register_Notification` took a managed delegate, which `LibraryImport` does not marshal, so each wait's handler now travels as a `GCHandle` in the registration's context argument to one `[UnmanagedCallersOnly]` dispatcher. S77 counts the events the dispatcher delivers.
- `hmswd.exe` always comes from the embedded resource and is staged and verified, never read from beside the assembly.
- `aot_smoke` publishes one source four ways, NativeAOT and trimmed single-file for each architecture, and S74 and S75 run the two for the machine's architecture.

Measured during development at commit d37e32e, on a 16-core Windows 11 laptop, not on the release build, 30 runs each, process start to catalog loaded: 162.0 ms at p50 (172.8 ms at p95) for a JIT app on v1.12.0, 168.4 ms (174.1 ms) for a JIT app at that commit, 17.0 ms (17.9 ms) for a NativeAOT app, and 345.6 ms (350.4 ms) for a trimmed single-file app. Every Win32 declaration and part of the profile model changed after that commit. At the same commit the first source-generated parse in a JIT process cost about 8 ms more at the median, because the generated metadata is compiled on first use. Trimming drops the framework's precompiled code, which is why the trimmed single-file app starts slowest.

## Outputs

| Directory | Contents |
|---|---|
| build/ | x64 driver DLLs, helper, and stamped INFs |
| build/arm64/ | ARM64 driver DLLs, helper, and stamped INFs |
| build/openvr/hidmaestro/ | SteamVR package with the x64 plugin |
| sdk/HIDMaestro.Core/Resources/ | Staged payloads and the two verified upstream USB/IP installers |
| sdk/HIDMaestro.Core/bin/Release/net10.0-windows10.0.26100.0/ | Universal SDK |
| test/bin/Release/framework/win-architecture/ | Test application |
| tools/HIDMaestroProfileExtractor/bin/Release/framework/win-architecture/ | ProfileExtractor |

The native build shares toolchain discovery through scripts/native_env.cmd. HM_WDK_VERSION selects the SDK/WDK version.

## Versioning

Directory.Build.props controls managed and native VERSIONINFO versions. Builds use Release configuration. Debug builds are rejected.

The INF stamping script decorates the model sections for the target, NTamd64 or NTARM64, updates the date, and stamps the fourth DriverVer component with the build minute. It refuses to write an INF that ends up with neither. Native version resources come from gen_version.ps1.

The first three DriverVer components move only when driver code changes. The build stamps the fourth with the build minute and the date with the build day, so every native build is a new package to Windows. As of v2.0.0 `build_all.cmd` reads the clock once, as `HM_STAMP_TIME` (`yyyy-MM-ddTHH:mm`), and stamps every INF of both architectures with it, where a build whose steps straddled a minute used to carry two stamps. `build.cmd` and `build_companion.cmd` take the time at their start when run alone. A caller can set `HM_STAMP_TIME`, and the stamping script refuses a time later than the clock or earlier than the newest file under the INF's source folder, since a stale time would stamp a new build older than an earlier one. `pre-tag-validate.cmd` clears it before a release build, and battery scenario S78 fails a release build whose four INFs carry more than one stamp. `InstallDriver()` skips its work only when the embedded driver files, INFs included, hash the same as the installed ones, so the first run of a release with a new native build reinstalls the driver once. v2.0.0 stamps DriverVer 2.0.0, because the driver now writes its half of the version section ([Shared Memory Protocol](shared-memory-protocol.md#version-section-v200)).

## Validation and release order

Finish and commit the intended changes, create the local release tag, and then build. The assembly's informational version includes its commit identifier. Package the outputs that were tested.

Stage the release test machine and the Atom fixture before starting their full batteries together. Stream each scenario result. Record each machine's actual result and any unavailable fixture.

The battery has 96 scenarios, S01 to S85 and S87 to S97. S44 checks the bundled USB/IP transport: that it is present, that its hash still matches the pinned SHA-256, and that the deploy path refuses tampered bytes. S58 and S59 cover device identity, derivation without a device and then one controller per family across nine lives. S60 covers the battery reply a pad gives XInput. S61 builds the driver catalogs for both architectures with the embedded Inf2Cat. S62 runs Steam's own firmware updater against the 2026 Steam Controller persona, and skips on a machine without Steam. S63 checks the DualShock 4 reports against SDL and Linux, and S64 the DualShock 3 persona against SDL, Linux, RPCS3 and DsHidMini. Both run stock SDL3 and skip that part without it. S65 checks the Switch 2 Pro composite persona against a capture of a real pad, then through PadForge's SDL3 fork with libusb and through the Steam client. It skips those parts without a build of that fork beside the repository or without Steam. S66 checks that a registry key a virtual shares with real devices goes back to its prior state, S67 what WGI reads from a virtual pad, and S68 that `HMVR.FindDriverNameConflicts` reports a foreign OpenVR driver under HIDMaestro's name. S69 checks the keyboard and mouse descriptors and packers with no device, and S70 every catalog keyboard and mouse through Raw Input, including a consumer killed with input held and the cleanup after it. S71 and S72 run programs side by side as separate processes and check the protected staging. S73 runs the usbip-win2 install in Windows Sandbox, S74 and S75 the NativeAOT and trimmed single-file apps, S76 the JSON parity, S77 the PnP notifications and S78 what a build carries. S79 to S83 cover the GameCube adapter persona: its bytes, its protocol, its WinUSB binding, Dolphin and Slippi, and SDL. S84 fails when a submit path allocates: the worst of its runs for the UMDF2 paths, the median of five runs for a USB/IP device's frame and transfer paths. S85 checks that an event handler that throws stops no other handler and none of the SDK's own handling, and that a handler can dispose its own controller. S87 checks that no `DllImport` is left and that every method the SDK's messages and XML docs name exists. See [Testing and Verification](testing-and-verification.md).

~~~powershell
# Run elevated after staging the matching outputs.
test\regression\swap_regression.ps1

# Select one scenario during diagnosis.
test\regression\swap_regression.ps1 -Filter 'S58*'
~~~

Steam recognition tests must not submit input that a desktop layout could turn into keyboard or mouse actions.

## Packaging

Each release has two ZIPs, one for x64 and one for ARM64. Each holds the SDK, the test application, ProfileExtractor, HIDMaestroProfileCheck (v2.0.0), README, and LICENSE. The SDK DLL is an AnyCPU assembly and is byte-identical in both. The test application and ProfileExtractor are built for the ZIP's architecture.

Preserve probe directory hierarchies when staging a fixture. Verify the SDK hash at each consumer location. Include ProfileExtractor in every release ZIP.

A failed or unavailable test must not be described as passed. Update the website, documentation, and release notes with the actual supported configurations and results.

## USB/IP package preparation

The build downloads the pinned usbip-win2 0.9.8.1 installers, the x64 one from the release and the ARM64 one from the project's signing service, and checks each against its pinned SHA-256. A mismatch fails the build. Both are embedded unmodified, and the license notice embedded beside them names both files and both hashes.

The build also unpacks the host controller's INF, SYS and CAT from those installers with a pinned unpacker, checks each file against UsbipPackage.json, and embeds them per architecture. That is what lets the SDK move a machine from an older transport to 0.9.8.1 through PnP.

At run time the SDK verifies the extracted installer again and runs it with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /COMPONENTS=main,client /TASKS=vcredist /NOICONS` (v2.0.0), and only on a machine with no usbip-win2 driver package and no installer record. See [Driver Install and Signing](driver-install-and-signing.md#usbip-transport) for what each switch does. It never invokes the vendor uninstaller, which removes the shared root-hub filter, and it never runs an installer over an existing install.
