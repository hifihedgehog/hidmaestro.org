# Build and release

This describes the shipped x64 build. An ARM64 build and a USB/IP transport upgrade past the pinned 0.9.7.7 are in development on a branch; the upgrade currently fails driver-lifecycle validation, which is what blocks it. Published v1.8.1 downloads are x64-only. See [platform support](../start/platform-support.md).

## Prerequisites

Install the .NET 10 SDK, Visual Studio C++ tools for x64, and Windows SDK/WDK 10.0.26100.0. PowerShell 5.1 or later runs the build scripts.

## Build

~~~powershell
scripts\build_all.cmd
~~~

The native build compiles the HID driver, XInput companion, and hmswd helper for x64. It also builds the x64 OpenVR plugin. The SDK build embeds these files and the signed USB/IP package.

Resource inputs are explicit. One SDK build is sufficient after the native files exist. Missing native files fail the build.

The test build script builds the test app, ProfileExtractor, example, and the probe projects used by the battery. It copies a canonical SDK assembly into their outputs and verifies each copy's SHA-256 hash.

The OpenVR smoke probe is x64 because it loads SteamVR's x64 client DLL. The regression script applies the same paths to its freshness checks and launches.

## Outputs

| Directory | Contents |
|---|---|
| build/ | x64 driver DLLs, helper, and stamped INFs |
| build/openvr/hidmaestro/ | SteamVR package with the x64 plugin |
| sdk/HIDMaestro.Core/Resources/ | The verified upstream USB/IP package |
| sdk/HIDMaestro.Core/bin/Release/net10.0-windows10.0.26100.0/ | Universal SDK |
| test/bin/Release/framework/win-architecture/ | Test application |
| tools/HIDMaestroProfileExtractor/bin/Release/framework/win-architecture/ | ProfileExtractor |

The native build shares toolchain discovery through scripts/native_env.cmd. HM_WDK_VERSION selects the SDK/WDK version.

## Versioning

Directory.Build.props controls managed and native VERSIONINFO versions. Builds use Release configuration. Debug builds are rejected.

The INF stamping script replaces the architecture token with amd64, updates the date, and stamps the fourth DriverVer component with the build minute. Native version resources come from gen_version.ps1.

USB/IP's INF DriverVer values are build stamps, not release numbers. Runtime verification compares pinned binary hashes and loaded paths.

## Validation and release order

Finish and commit the intended changes, create the local release tag, and then build. The assembly's informational version includes its commit identifier. Package the outputs that were tested.

Stage the devbox and Atom fixtures before starting their full batteries together. Stream each scenario result. Record each machine's actual result and any unavailable fixture.

The battery has 60 scenarios. S44 checks the bundled USB/IP transport: that it is present, that its hash still matches the upstream release, and that the deploy path refuses tampered bytes. S58 and S59 cover device identity, derivation without a device and then one controller per family across nine lives. S60 covers the battery reply a pad gives XInput.

~~~powershell
# Run elevated after staging the matching outputs.
test\regression\swap_regression.ps1

# Select one scenario during diagnosis.
test\regression\swap_regression.ps1 -Filter 'S58*'
~~~

Steam recognition tests must not submit input that a desktop layout could turn into keyboard or mouse actions.

## Packaging

Include the SDK, the test application, ProfileExtractor, README, LICENSE, and third-party notices. The SDK DLL is an AnyCPU assembly.

Preserve probe directory hierarchies when staging a fixture. Verify the SDK hash at each consumer location. Include ProfileExtractor in every release ZIP.

A failed or unavailable test must not be described as passed. Update the website, documentation, and release notes with the actual supported configurations and results.

## USB/IP package preparation

The build downloads the pinned x64 installer, checks its published hash, and uses a pinned build-time unpacker to extract the signed INF/SYS/CAT files. Each file is checked against UsbipPackage.json before embedding.

The SDK adds packages through PnP. It never invokes the vendor uninstaller, which removes the shared root-hub filter. Older SDK consumers use an incompatible attach layout, so coordinate their adoption before updating a shared host.
