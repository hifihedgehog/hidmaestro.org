# Build and Release

Building HIDMaestro from source. The two-phase build, INF version stamping, the per-tag validation pipeline, and the release ZIP recipe.

For the consumer-side install of a built binary, see [Driver Install and Signing](driver-install-and-signing.md). For testing a build before tagging, see [Testing and Verification](testing-and-verification.md).

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Visual Studio 2022** or later | with **Desktop development with C++** workload | `cl.exe` and `link.exe` for `driver.c`, `companion.c`, `hmswd.c` |
| **Windows SDK / WDK** | 10.0.26100.0 | `hidport.h`, `wdf.h`, UMDF 2.15 libs, `Inf2Cat.exe`, `signtool.exe` |
| **.NET 10 SDK** | latest | `dotnet build` for the C# SDK and test app |
| **PowerShell** | 5.1+ (built-in) | Runs `scripts\stamp_inf.ps1` |
| **Python** | 3.10+ (optional) | Runs `scripts\verify.py` for cross-API validation |

The build is x64-only. There is no x86, ARM64, or "Any CPU" target.

---

## One-shot build

```cmd
cd HIDMaestro
scripts\build_all.cmd
```

`build_all.cmd` runs four phases in order:

```
Phase 1: Native driver
  scripts\build.cmd
  → cl.exe driver.c, companion.c, hmswd.c
  → link.exe → build\HIDMaestro.dll, build\HMXInput.dll, build\hmswd.exe
  → scripts\stamp_inf.ps1 hidmaestro.inf → build\hidmaestro.inf
  → scripts\stamp_inf.ps1 hidmaestro_xusb.inf → build\hidmaestro_xusb.inf

Phase 2: Native companion (separate build script for parallelism)
  scripts\build_companion.cmd
  → cl.exe companion.c → build\HMXInput.dll
  (Note: build.cmd builds the main + hmswd; build_companion.cmd builds only HMXInput)

Phase 3: SDK build #1 — populates Resources/ from build/
  dotnet build sdk\HIDMaestro.Core\HIDMaestro.Core.csproj
  → PackResources MSBuild target copies build/* into sdk/HIDMaestro.Core/Resources/
  → embedded resource glob picks them up
  → output: sdk\HIDMaestro.Core\bin\Release\net10.0-windows10.0.26100.0\HIDMaestro.Core.dll

Phase 4: SDK build #2 — embeds fresh driver bytes
  dotnet build sdk\HIDMaestro.Core\HIDMaestro.Core.csproj
  → PackResources rebuilds Resources/ (idempotent)
  → embedded resource glob has fresh content
  → output: HIDMaestro.Core.dll with current driver bytes embedded
```

After this completes, `dotnet run --project example\SdkDemo` works and the test app at `test\bin\Release\...\HIDMaestroTest.exe` deploys virtuals.

The script is idempotent. Re-run any time you touch `driver/` or `sdk/`. Native source change &rarr; Phase 1+2 rebuild and Phase 3+4 update Resources/.

---

## Why two SDK build phases

MSBuild evaluates the embedded-resource glob **before** the `PackResources` pre-build target runs. On a fresh clone with empty `build/`:

- Phase 1 produces `build\HIDMaestro.dll` etc.
- Phase 3's MSBuild evaluation sees the empty Resources/ and the glob emits zero items.
- `PackResources` runs as a pre-build step, copying `build/*` into Resources/.
- The compile succeeds, but the assembly has **no embedded driver inside**.
- Result: the SDK ships a hollow shell that fails on first `InstallDriver` call.

Phase 4 reruns with Resources/ now populated; the glob picks up the files; the assembly embeds them correctly.

A cleaner fix would be a custom MSBuild target that invokes Phase 1 inline before the resource glob evaluates. Tried; the dependency on `cl.exe` and the WDK environment makes this fragile across MSBuild versions. The two-phase shell script just works, and the failure modes are visible in shell output.

---

## Build script details

### `scripts\build.cmd`

Compiles `driver.c` &rarr; `HIDMaestro.dll` and `hmswd.c` &rarr; `hmswd.exe`. Stamps both INFs.

```cmd
cl.exe /nologo /W4 /GS /Gz /wd4324 ^
    /D _AMD64_ /D _WIN64 /D UNICODE /D _UNICODE ^
    /D UMDF_VERSION_MAJOR=2 /D UMDF_VERSION_MINOR=15 ^
    "/I%UM_INC%" "/I%SHARED_INC%" "/I%KM_INC%" "/I%WDF_INC%" ^
    "/Fo%OUT_DIR%\\" /c "%DRIVER_DIR%\driver.c"

link.exe /nologo /DLL "/OUT:%OUT_DIR%\HIDMaestro.dll" ^
    "/LIBPATH:%UM_LIB%" "/LIBPATH:%WDF_LIB%" ^
    "%OUT_DIR%\driver.obj" ^
    WdfDriverStubUm.lib ntdll.lib OneCoreUAP.lib mincore.lib advapi32.lib
```

`OneCoreUAP.lib` plus `mincore.lib` are the WDK link sets for UMDF2 (replacement for the older `kernel32.lib + advapi32.lib + ...` combinations). UMDF2 drivers can't link against full Win32 because they run in a sandboxed `WUDFHost` instance.

`hmswd.exe` is built right after with `OneCoreUAP.lib + cfgmgr32.lib + ole32.lib + swdevice.lib`.

### `scripts\build_companion.cmd`

Compiles `companion.c` &rarr; `HMXInput.dll`. Same compiler flags as `driver.c`. Separate script so Phase 1 and Phase 2 of `build_all.cmd` can run in parallel if desired (currently sequential for log clarity).

### `scripts\stamp_inf.ps1`

Reads the source INF, replaces the `DriverVer` line with `MM/DD/YYYY,1.x.y.<HHmm>` (HHmm = current build minute), writes to the destination INF.

```powershell
$now = Get-Date
$datePart = $now.ToString("MM/dd/yyyy")
$build = $now.ToString("HHmm")
$verLine = "DriverVer   = $datePart,$baseVersion.$build"
```

`$baseVersion` is read from `Directory.Build.props`'s `<Version>` element. Single source of truth; bump the version there, both INFs follow.

The committed INF source files are never modified by stamp. Only the `build/` copies are stamped, and only the stamped copies get embedded into `HIDMaestro.Core.dll`. The committed INF carries a stable `1.x.y.0` for review.

---

## `Directory.Build.props`: single version source

```xml
<Project>
  <PropertyGroup>
    <Configurations>Release</Configurations>
    <Configuration Condition="'$(Configuration)' == ''">Release</Configuration>
    <Version>1.3.4</Version>
  </PropertyGroup>

  <Target Name="FailOnDebug" BeforeTargets="BeforeBuild" Condition="'$(Configuration)' == 'Debug'">
    <Error Text="Debug builds are disabled repo-wide. Use `dotnet build` (no -c flag) or `-c Release`." />
  </Target>
</Project>
```

`<Version>` is the canonical version. Bump this AND the committed INF source files (the latter is mostly cosmetic but kept consistent for reviewers) when releasing. The build minute appended by `stamp_inf.ps1` makes each package uniquely versioned regardless.

`<Configurations>Release</Configurations>` rejects Debug builds. The `FailOnDebug` MSBuild target hard-fails any `dotnet build -c Debug`. Real incident: the embedded `HMXInput.dll` and INFs came from a stale `Resources/` snapshot when a Debug build's `BeforeBuild` ran against an older `build/` payload while a parallel Release rebuild had moved on. Single-config builds eliminate the failure mode.

---

## Build outputs

After `build_all.cmd`:

```
build/
  HIDMaestro.dll              ← main HID driver
  HIDMaestroCompanion.dll     ← (legacy alias for HMXInput.dll, kept for compat)
  HMXInput.dll                ← XUSB companion
  hmswd.exe                   ← SwDevice helper
  hidmaestro.inf              ← stamped main INF
  hidmaestro_xusb.inf         ← stamped companion INF
  driver.obj / companion.obj / hmswd.obj  ← intermediate objects
  *.exp / *.lib                            ← linker exports

sdk/HIDMaestro.Core/Resources/
  (mirrored copy of build/, plus WDK tooling)

sdk/HIDMaestro.Core/bin/Release/net10.0-windows10.0.26100.0/
  HIDMaestro.Core.dll         ← THE SDK ASSEMBLY (embeds everything above)

test/bin/Release/net10.0-windows10.0.26100.0/win-x64/
  HIDMaestroTest.exe          ← test app

example/SdkDemo/bin/Release/net10.0-windows10.0.26100.0/
  SdkDemo.dll / .exe          ← minimal SDK consumer

tools/HIDMaestroProfileExtractor/bin/Release/net10.0-windows10.0.26100.0/win-x64/publish/
  HIDMaestroProfileExtractor.exe  ← single-file WPF extractor
```

---

## Pre-tag validation

Before tagging a release, run the validation pipeline:

```cmd
scripts\pre-tag-validate.cmd
```

Which runs, in order (`[N/4]` matches the script's own progress labels):

1. **`[1/4]` Build.** `scripts\build_all.cmd` plus the test app, profile extractor, and both Switch Pro probes. Aborts with exit 2 if any build fails.
2. **`[2/4]` Switch Pro protocol checks (issue #33).** `switch_pro_check` replays SDL's exact USB init + subcommand sequence over raw HID (43 asserts), then `switch_pro_sdl3_check` drives the pad end to end through real SDL3 when the sibling `SDL3-build` checkout is present (SKIPs cleanly when absent). A FAIL here aborts with exit 1.
3. **`[3/4]` `test\regression\swap_regression.ps1`.** The 46-scenario live-swap battery. Must report 46/46 PASS. A non-zero battery exit aborts with exit 1.
4. **`[4/4]` Cleanup + verdict.** Confirms no leftover devnodes and prints the safe-to-tag banner.

Total: ~30-40 minutes wall time. The regression battery dominates (devbox 46/46 in ~12 min, Atom Z8350 scale=2 in ~22 min).

The script aborts on first failure with the diagnostic. Don't tag if any step fails.

---

## Release recipe

After successful pre-tag validation:

```cmd
:: 1. Bump Directory.Build.props's <Version> if not already done
:: 2. Bump committed INF DriverVer to match (cosmetic but consistent for reviewers)

:: 3. Commit the version bump
git add Directory.Build.props driver/hidmaestro.inf driver/hidmaestro_xusb.inf
git commit -m "v1.3.4: <one-line summary>"

:: 4. Tag
git tag v1.3.4
git push --tags

:: 5. Rebuild everything against the new tag, then publish the test app
::    and profile extractor
scripts\build_all.cmd
dotnet publish tools\HIDMaestroProfileExtractor\HIDMaestroProfileExtractor.csproj -c Release

:: 6. Assemble the release ZIP by hand (no packaging script exists yet),
::    then create the GitHub release with the ZIP attached
gh release create v1.3.4 HIDMaestro-v1.3.4.zip ^
    --title "v1.3.4" ^
    --notes-file CHANGELOG-v1.3.4.md
```

There is no packaging script in `scripts/`. The ZIP is assembled manually to match the layout every prior release shipped (verified against `v1.3.17`):

```
HIDMaestro-v1.3.4.zip
├── HIDMaestroTest/
│   ├── HIDMaestroTest.exe          ← the test app
│   ├── HIDMaestro.Core.dll         ← the SDK
│   └── (HIDMaestroTest.dll, deps.json, runtimeconfig.json, WinRT deps)
├── HIDMaestroProfileExtractor/
│   ├── HIDMaestroProfileExtractor.exe   ← the standalone WPF extractor
│   └── (HIDMaestro.Core.dll, deps.json, runtimeconfig.json, WinRT deps)
├── HIDMaestro.Core.dll             ← the SDK, also at top level for easy reference
├── README.md                       ← project README
└── LICENSE                         ← MIT
```

**Critical:** `HIDMaestroProfileExtractor.exe` must be in every release ZIP. Documented in README as a shipping component. Has been omitted from 1.3.0 / 1.3.1 / 1.3.2 release ZIPs in the past &mdash; verify before publishing:

```cmd
unzip -l HIDMaestro-v1.3.4.zip | findstr /i extract
```

Should show `HIDMaestroProfileExtractor.exe`.

---

## SDK distribution as NuGet (future)

Currently the SDK is distributed as `HIDMaestro.Core.dll` inside the release ZIP. Consumers reference the DLL via `<HintPath>` (see [Installation](../start/installation.md)).

A NuGet feed is planned but not yet published. The package would carry:

- `HIDMaestro.Core.dll` (with embedded driver payload)
- XML doc comments
- Multi-target framework support (`net10.0-windows10.0.26100.0` only at v1.3.4)

The single-file embedded approach makes packaging clean &mdash; no separate native binary distribution; the .NET assembly is the entire deliverable.

---

## Cross-platform build

Not supported. HIDMaestro is Windows-only by design (UMDF2, mshidumdf, xinputhid, WGI are all Windows-specific). The build requires:

- Visual Studio with the WDK
- Windows-only `cl.exe` / `link.exe`
- Windows-only `Inf2Cat.exe` / `signtool.exe`

Cross-compilation from Linux / macOS is out of scope. CI is the only realistic non-developer build path; even there, the runner must be Windows-Server with the WDK installed.

GitHub-hosted runners are Windows Server (not Win11 client), so the `swap_regression` battery isn't portable to GitHub-hosted CI. Self-hosted runners on Win11 client could run it, but that's not currently set up &mdash; the regression battery stays manual via `pre-tag-validate.cmd`.

---

## Troubleshooting build failures

### `cl.exe` not found

The WDK environment variables aren't sourced. Run from a "Developer Command Prompt for VS 2022" or call `vcvarsall.bat amd64` first. `scripts\build.cmd` auto-detects Visual Studio installations under `C:\Program Files\Microsoft Visual Studio\` and sources `vcvarsall.bat` automatically.

### `hidport.h` not found

WDK 10.0.26100.0 not installed. Install via Visual Studio Installer &rarr; Individual components &rarr; "Windows Driver Kit". The build script expects `C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\km\hidport.h` to exist.

### `Inf2Cat.exe` not found / not embedded

WDK x64 tools missing. Look in `C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\Inf2Cat.exe`. The build copies this into `sdk/HIDMaestro.Core/Resources/` during the SDK build's `PackResources` step.

### `dotnet build` produces empty Resources

Phase 1 didn't run / failed. Check `build/` exists and has the four binaries. Re-run `scripts\build_all.cmd` from the start.

### `Debug builds are disabled` error

You ran `dotnet build -c Debug`. Drop the `-c Debug`. `Directory.Build.props` rejects this configuration repo-wide.

### Stale Resources/ snapshot embedded

Embedding glob ran before `PackResources` finished. Symptom: the embedded driver doesn't match `build/` even after a clean. Fix: run `scripts\build_all.cmd` (the two-phase) instead of a single `dotnet build`.

---

## Source layout summary

| Directory | Contents |
|-----------|----------|
| `driver/` | Native UMDF2 sources (driver.c, companion.c, hmswd.c, INFs) |
| `sdk/HIDMaestro.Core/` | The C# SDK assembly |
| `tools/HIDMaestroProfileExtractor/` | Standalone WPF profile extractor |
| `test/` | `HIDMaestroTest.exe` CLI + `regression/` battery + `probes/` investigation tools |
| `example/SdkDemo/` | Minimal SDK consumer for documentation |
| `profiles/` | 231 profile JSONs across 32 vendor folders |
| `scripts/` | `build_all.cmd`, `verify.py`, `stamp_inf.ps1`, `pre-tag-validate.cmd`, helpers |
| `build/` | Build outputs (gitignored) |
| `docs/` | README assets, investigation logs |

Per-component line counts in the [Architecture Overview](architecture-overview.md).

---

## See also

- [Driver Install and Signing](driver-install-and-signing.md) &mdash; what the embedded payload does at consumer install time.
- [Testing and Verification](testing-and-verification.md) &mdash; the validation pipeline that gates a release.
- [Installation](../start/installation.md) &mdash; consumer-facing instructions for using a built binary.
- [`Directory.Build.props`](https://github.com/hifihedgehog/HIDMaestro/blob/master/Directory.Build.props) &mdash; the version source.
- [`scripts/build_all.cmd`](https://github.com/hifihedgehog/HIDMaestro/blob/master/scripts/build_all.cmd) &mdash; the two-phase build orchestration.
