# Build and release

The ARM64 implementation builds one AnyCPU SDK containing x64 and ARM64 native payloads. It remains under validation. USB/IP 0.9.8.0 failed driver-lifecycle tests, which blocks deployment and release. Published v1.7.3 downloads predate these changes. See [platform support](../start/platform-support.md) for the results.

## Prerequisites

Install the .NET 10 SDK, Visual Studio C++ tools for x64 and ARM64, and Windows SDK/WDK 10.0.26100.0. PowerShell 5.1 or later runs the build scripts. The ARM64 compiler and C runtime libraries are separate Visual Studio components.

## Build

~~~powershell
scripts\build_all.cmd
scripts\build_tests.ps1 -Architecture x64
~~~

The native build compiles the HID driver, XInput companion, and hmswd helper for both architectures. It also builds the x64 OpenVR plugin. The SDK build embeds these files and both signed USB/IP packages.

Resource inputs are explicit. One SDK build is sufficient after the native files exist. Missing native files fail the build.

The test build script builds the test app, ProfileExtractor, example, and the probe projects used by the battery. It copies a canonical SDK assembly into their outputs and verifies each copy's SHA-256 hash.

For an ARM64 fixture:

~~~powershell
scripts\build_tests.ps1 -Architecture arm64
~~~

ARM64 probe outputs use a win-arm64 subdirectory. x64 probes retain the framework-directory layout. The OpenVR smoke probe stays x64 on both operating systems because it loads SteamVR's x64 client DLL. ARM64 fixtures need the x64 .NET 10 runtime for that probe. The regression script applies the same paths to its freshness checks and launches.

Individual applications accept dotnet build -r win-arm64. Native-only builds accept an architecture:

~~~powershell
scripts\build.cmd arm64
scripts\build_companion.cmd arm64
~~~

## Outputs

| Directory | Contents |
|---|---|
| build/ | x64 driver DLLs, helper, and stamped INFs |
| build/arm64/ | ARM64 driver DLLs, helper, and stamped INFs |
| build/openvr/hidmaestro/ | SteamVR package with the x64 plugin |
| sdk/HIDMaestro.Core/Resources/usbip/ | Verified upstream packages for both architectures |
| sdk/HIDMaestro.Core/bin/Release/net10.0-windows10.0.26100.0/ | Universal SDK |
| test/bin/Release/framework/win-architecture/ | Test application |
| tools/HIDMaestroProfileExtractor/bin/Release/framework/win-architecture/ | ProfileExtractor |

The native build shares toolchain discovery through scripts/native_env.cmd. HM_WDK_VERSION selects the SDK/WDK version. Unpacked Microsoft tools can be supplied through HM_ARM64_COMPILER_DIR and HM_ARM64_CRT_DIR. They must contain matching compiler and complete CRT library sets.

## Versioning

Directory.Build.props controls managed and native VERSIONINFO versions. Builds use Release configuration. Debug builds are rejected.

The INF stamping script replaces the architecture token with amd64 or arm64, updates the date, and stamps the fourth DriverVer component with the build minute. Native version resources come from gen_version.ps1.

USB/IP's INF DriverVer values are build stamps, not release numbers. Runtime verification compares pinned binary hashes and loaded paths.

## Validation and release order

Finish and commit the intended changes, create the local release tag, and then build. The assembly's informational version includes its commit identifier. Package the outputs that were tested.

Stage the devbox and Atom fixtures before starting their full batteries together. Stream each scenario result. Record each machine's actual result and any unavailable fixture. ARM64 cross-compilation is not an ARM64 runtime result.

The battery has 60 scenarios. S44 checks the bundled USB/IP transport: that it is present, that its hash still matches the upstream release, and that the deploy path refuses tampered bytes. S58 and S59 cover device identity, derivation without a device and then one controller per family across nine lives. S60 covers the battery reply a pad gives XInput.

~~~powershell
# Run elevated after staging the matching outputs.
test\regression\swap_regression.ps1

# Select one scenario during diagnosis.
test\regression\swap_regression.ps1 -Filter 'S58*'
~~~

Steam recognition tests must not submit input that a desktop layout could turn into keyboard or mouse actions.

## Packaging

Include the universal SDK, the appropriate test application, ProfileExtractor, README, LICENSE, and third-party notices. Application executables are architecture-specific. Their SDK DLL is the same AnyCPU assembly.

Preserve probe directory hierarchies when staging a fixture. Verify the SDK hash at each consumer location. Include ProfileExtractor in every release ZIP.

A failed or unavailable test must not be described as passed. Update the website, documentation, and release notes with the actual supported configurations and results.

## USB/IP package preparation

The build downloads the pinned x64 and ARM64 installers, checks their published hashes, and uses a pinned build-time unpacker to extract their signed INF/SYS/CAT files. Each file is checked against UsbipPackage.json before embedding.

The SDK adds packages through PnP. It never invokes the vendor uninstaller, which removes the shared root-hub filter. Older SDK consumers use an incompatible attach layout, so coordinate their adoption before updating a shared host.
