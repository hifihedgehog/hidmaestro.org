# Build and release

HIDMaestro builds and ships for x64 and ARM64 from one source tree. See [platform support](../start/platform-support.md).

## Prerequisites

Install the .NET 10 SDK, Visual Studio C++ tools for x64 and ARM64, and Windows SDK/WDK 10.0.26100.0. The ARM64 compiler is a separate Visual Studio component. PowerShell 5.1 or later runs the build scripts.

## Build

~~~powershell
scripts\build_all.cmd
~~~

The native build compiles the HID driver, XInput companion, and hmswd helper for x64 and again for ARM64. It also builds the x64 OpenVR plugin. The SDK build embeds both payload sets and both signed USB/IP installers.

The script runs the SDK build twice, and both passes are needed: the first stages the payloads and the second embeds them. Missing native files fail the build with a message naming the script.

The test build script builds the test app, ProfileExtractor, example, and the probe projects used by the battery. It copies a canonical SDK assembly into their outputs and verifies each copy's SHA-256 hash.

The OpenVR smoke probe is x64 because it loads SteamVR's x64 client DLL. The regression script applies the same paths to its freshness checks and launches.

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

The first three DriverVer components move only when driver code changes. The build stamps the fourth with the build minute and the date with the build day, so every native build is a new package to Windows. `InstallDriver()` skips its work only when the embedded driver files, INFs included, hash the same as the installed ones, so the first run of a release with a new native build reinstalls the driver once. v1.10.0 changes driver code, so DriverVer moves to 1.10.0.

## Validation and release order

Finish and commit the intended changes, create the local release tag, and then build. The assembly's informational version includes its commit identifier. Package the outputs that were tested.

Stage the devbox and Atom fixtures before starting their full batteries together. Stream each scenario result. Record each machine's actual result and any unavailable fixture.

The battery has 64 scenarios. S44 checks the bundled USB/IP transport: that it is present, that its hash still matches the pinned SHA-256, and that the deploy path refuses tampered bytes. S58 and S59 cover device identity, derivation without a device and then one controller per family across nine lives. S60 covers the battery reply a pad gives XInput. S61 builds the driver catalogs for both architectures with the embedded Inf2Cat. S62 runs Steam's own firmware updater against the 2026 Steam Controller persona, and skips on a machine without Steam. S63 checks the DualShock 4 reports against SDL and Linux, and S64 the DualShock 3 persona against SDL, Linux, RPCS3 and DsHidMini. Both run stock SDL3 and skip that part without it.

~~~powershell
# Run elevated after staging the matching outputs.
test\regression\swap_regression.ps1

# Select one scenario during diagnosis.
test\regression\swap_regression.ps1 -Filter 'S58*'
~~~

Steam recognition tests must not submit input that a desktop layout could turn into keyboard or mouse actions.

## Packaging

Each release has two ZIPs, one for x64 and one for ARM64. Each holds the SDK, the test application, ProfileExtractor, README, and LICENSE. The SDK DLL is an AnyCPU assembly and is byte-identical in both. The test application and ProfileExtractor are built for the ZIP's architecture.

Preserve probe directory hierarchies when staging a fixture. Verify the SDK hash at each consumer location. Include ProfileExtractor in every release ZIP.

A failed or unavailable test must not be described as passed. Update the website, documentation, and release notes with the actual supported configurations and results.

## USB/IP package preparation

The build downloads the pinned usbip-win2 0.9.8.1 installers, the x64 one from the release and the ARM64 one from the project's signing service, and checks each against its pinned SHA-256. A mismatch fails the build. Both are embedded unmodified, and the license notice embedded beside them names both files and both hashes.

The build also unpacks the host controller's INF, SYS and CAT from those installers with a pinned unpacker, checks each file against UsbipPackage.json, and embeds them per architecture. That is what lets the SDK move a machine from an older transport to 0.9.8.1 through PnP.

At run time the SDK verifies the extracted installer again and runs it silently, and only on a machine with no usbip-win2. It never invokes the vendor uninstaller, which removes the shared root-hub filter, and it never runs an installer over an existing install.
