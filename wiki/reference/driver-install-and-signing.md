# Driver Install and Signing

How `HMContext.InstallDriver` turns the embedded payload inside `HIDMaestro.Core.dll` into installed, signed, and registered Windows drivers. Self-bootstrapping &mdash; no EV certificate, no `bcdedit /set testsigning`, no reboot, no manual signing step.

This is the single biggest reason HIDMaestro exists. Every other "no kernel driver" approach on Windows still requires either an EV cert ($300+/yr) or test-signing mode (boot flag that defaces the desktop with "Test Mode"). HIDMaestro avoids both via UMDF2 + a per-machine self-signed certificate trusted by the target machine. The trust path is the standard Windows driver-signing chain (cert in `Cert:\LocalMachine\Root` + cert in `TrustedPublisher` &rarr; `pnputil /add-driver` accepts the INF without WHQL).

For the broader install context (when a consumer would call this), see [Installation](../start/installation.md). For the source mechanics, see [Build and Release](build-and-release.md).

---

## What InstallDriver does

```csharp
public void InstallDriver()
{
    Internal.DeviceOrchestrator.RemoveAllVirtualControllers();   // self-heal sweep
    if (!DriverBuilder.FullDeploy())
        throw new InvalidOperationException(
            "Driver install failed. Run elevated and check pnputil output.");
}
```

`FullDeploy` runs through these steps. **Idempotent** &mdash; if the embedded payload's hash matches what's installed, returns immediately.

```
1. Compute payload hash (SHA-256 of every embedded resource)
2. IsDriverInstalled? → check DriverStore for matching hash → if yes, return
3. EnsureExtracted: extract embedded resources to %TEMP%\HIDMaestro\<hash>\
4. Generate self-signed certificate if not in Cert:\LocalMachine\Root
5. Install certificate to Cert:\LocalMachine\Root and \TrustedPublisher
6. Generate .cat catalogs via Inf2Cat for both INFs
7. Sign HIDMaestro.dll, HMXInput.dll, hmswd.exe, both .cat files
8. pnputil /add-driver hidmaestro.inf /install
9. pnputil /add-driver hidmaestro_xusb.inf /install
10. Delete %TEMP%\HIDMaestro\<hash>\ (leave nothing behind)
```

Total: ~1.7 s on a clean machine, ~50 ms on a machine with the same hash already installed.

**Requires admin** (`UnauthorizedAccessException` if not elevated).

---

## The embedded payload

`HIDMaestro.Core.dll` embeds these resources via `<EmbeddedResource>` in the csproj's `PackResources` MSBuild target:

| Resource | Purpose | Source |
|----------|---------|--------|
| `HIDMaestro.dll` | UMDF2 lower filter (main HID driver) | Built by `scripts\build.cmd` |
| `HMXInput.dll` | UMDF2 function driver (XUSB companion) | Built by `scripts\build_companion.cmd` |
| `hmswd.exe` | SwDevice helper executable | Built by `scripts\build.cmd` |
| `hidmaestro.inf` | Main HID INF, version-stamped | Stamped by `scripts\stamp_inf.ps1` |
| `hidmaestro_xusb.inf` | Companion INF, version-stamped | Stamped by `scripts\stamp_inf.ps1` |
| `Inf2Cat.exe` | Catalog generator | Microsoft WDK `bin\<sdk>\x64\Inf2Cat.exe` |
| `signtool.exe` | Authenticode signing tool | Microsoft Windows SDK |
| `Microsoft.UniversalStore.HardwareWorkflow.*.dll` (5 files) | Inf2Cat dependencies | WDK |
| `mssign32.dll` | Signing dependency | WDK |
| `wintrust.dll` + `wintrust.dll.ini` | Signing trust dependency | WDK |
| `appxpackaging.dll` | Inf2Cat catalog dependency | WDK |
| `appxsip.dll` | Same | WDK |
| `opcservices.dll` | Same | WDK |
| `WindowsProtectedFiles.xml` | Inf2Cat config | WDK |
| Various `.manifest` files | DLL activation contexts | WDK |

Total embedded payload size: ~13 MB. The SDK DLL itself is ~25 MB.

These are extracted to `%TEMP%\HIDMaestro\<hash>\` on first install. The hash directory means multiple SDK versions can coexist (same machine has v1.3.3 cached, v1.3.4 installs to a different directory and replaces what's in DriverStore).

After successful install the temp directory is **deleted**. Nothing is left in the consuming app's directory.

---

## The self-signed certificate

Generated once per machine via .NET's [`CertificateRequest`](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.x509certificates.certificaterequest) (search Microsoft Learn for the exact symbol if the URL has moved):

```csharp
var ecdsa = ECDsa.Create(ECCurve.NamedCurves.nistP256);
var req = new CertificateRequest(
    "CN=HIDMaestro Self-Signed",
    ecdsa,
    HashAlgorithmName.SHA256);

req.CertificateExtensions.Add(new X509KeyUsageExtension(
    X509KeyUsageFlags.DigitalSignature, critical: false));

req.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(
    new OidCollection {
        new Oid("1.3.6.1.5.5.7.3.3")    // Code Signing
    }, critical: false));

var cert = req.CreateSelfSigned(
    DateTimeOffset.UtcNow.AddDays(-1),
    DateTimeOffset.UtcNow.AddYears(10));
```

Properties:

- **Subject**: `CN=HIDMaestro Self-Signed`
- **Algorithm**: ECDSA P-256 + SHA-256
- **EKU**: Code Signing (1.3.6.1.5.5.7.3.3)
- **Validity**: 10 years from generation
- **Storage**: `Cert:\LocalMachine\My` (private key) + `Cert:\LocalMachine\Root` + `Cert:\LocalMachine\TrustedPublisher` (public cert)

Why those three stores:

| Store | Purpose |
|-------|---------|
| `LocalMachine\My` | Private key for signing. Read by `signtool.exe` during install. |
| `LocalMachine\Root` | Trusted root authority. Without this, the chain validation for the signed driver fails. |
| `LocalMachine\TrustedPublisher` | Auto-acceptance of signatures from this publisher during driver install. Without this, `pnputil /add-driver` would prompt "Windows can't verify the publisher". |

The cert is **per-machine**. Survives reboots. Multiple HIDMaestro consumers on the same machine share it &mdash; whichever one runs first generates and installs; subsequent consumers find it already there.

---

## Why no EV cert / WHQL / test-signing

Windows requires a code-signing certificate **and** trust path validation for any driver install. Three common paths:

1. **EV Certificate + WHQL submission.** $300+/year for the cert; multi-week WHQL review; required for every kernel-mode driver.
2. **Standard Certificate + cross-signed by Microsoft.** Cross-signing was retired in 2020 for new drivers.
3. **Test-signing mode.** `bcdedit /set testsigning` boots Windows in a state that accepts unsigned drivers. Defaces the desktop with "Test Mode" watermark. Not consumer-acceptable.

UMDF2 + per-machine self-signed cert in `Root` + `TrustedPublisher` is the **fourth path**, and it's specific to UMDF2:

- UMDF2 drivers run in user mode (`WUDFHost.exe`), not kernel.
- The kernel signature requirement applies to the function driver (`mshidumdf.sys`, signed by Microsoft) and the reflector (`WUDFRd.sys`, signed by Microsoft) &mdash; **not** to our UMDF2 DLL.
- Our UMDF2 DLL still needs a signature for `pnputil /add-driver` to accept the INF. The trust path is: cert in `Root` (validates the chain) + cert in `TrustedPublisher` (accepts the publisher) = sufficient.

The trust path is **per-machine**. Distributing HIDMaestro to a fresh machine generates a fresh cert on that machine. The cert never travels with the SDK.

---

## Catalog generation via Inf2Cat

```cmd
Inf2Cat.exe /driver:%TEMP%\HIDMaestro\<hash> /os:10_X64,Server10_X64 /uselocaltime
```

`Inf2Cat` walks the INF, hashes every file the INF references, and produces a `.cat` (catalog) file. The `.cat` is what's actually signed; `pnputil` validates the INF + binaries against the catalog signature on install.

Inf2Cat is the **single largest cost in the install** at ~840 ms total for both catalogs. Antivirus is the variable factor &mdash; clean machines without aggressive AV finish in 200-400 ms; corporate workstations with real-time scanning extend to 1-2 s.

We ship Inf2Cat embedded because it's not a redistributable component &mdash; it's part of the WDK. Embedding it lets HIDMaestro install without requiring the consumer's machine to have the WDK.

The five `Microsoft.UniversalStore.HardwareWorkflow.*.dll` files are Inf2Cat's dependencies (recently moved to a separate library by Microsoft). All five must be present alongside Inf2Cat; missing any one produces a cryptic `0x80004005` error.

---

## Authenticode signing via signtool

```cmd
signtool.exe sign /sha1 <thumbprint> /fd sha256 /td sha256 ^
    /tr http://timestamp.digicert.com ^
    HIDMaestro.dll HMXInput.dll hmswd.exe hidmaestro.cat hidmaestro_xusb.cat
```

| Flag | Purpose |
|------|---------|
| `/sha1 <thumbprint>` | Find the cert in `Cert:\LocalMachine\My` by SHA-1 thumbprint |
| `/fd sha256` | File digest algorithm: SHA-256 |
| `/td sha256` | Timestamp digest algorithm: SHA-256 |
| `/tr http://timestamp.digicert.com` | RFC 3161 timestamp server |

The timestamp matters: a signed driver without a timestamp expires when the cert expires. With a timestamp, the signature remains valid past cert expiry as long as the timestamp itself is from a trusted RFC 3161 server. We use DigiCert's free timestamp endpoint by default; configurable via `HIDMAESTRO_TIMESTAMP_URL` env var.

Network access during install: yes &mdash; the timestamp request is the only network-required step. Air-gapped install fails the timestamp step but succeeds with cert chain validation; the resulting driver works for the cert's validity window (10 years).

---

## pnputil /add-driver

```cmd
pnputil /add-driver hidmaestro.inf /install
pnputil /add-driver hidmaestro_xusb.inf /install
```

`/install` flag: install the driver to the DriverStore AND tag it as "boot critical" so PnP binds it on next devnode arrival. Without `/install`, the driver is staged but not actually loadable.

If the driver package matches a previously-installed package (same hash), `pnputil` no-ops and reports "Driver package added successfully" with the existing OEM number.

If the package partially matches (same INF name, different binaries), `pnputil` errors with "Driver package failed integrity verification" or "Driver package needs repair" and silently restores the previously cached version. **This is the bug the self-heal sweep prevents** &mdash; orphan virtuals from a prior crashed session keep the old INF "in use", so the integrity check incorrectly classifies a fresh install as a repair candidate. See [Lifecycle and Teardown](lifecycle-and-teardown.md).

`pnputil` requires admin. Returns exit code 0 on success, non-zero on failure (codes vary). HIDMaestro reads the exit code and surfaces failure to the consumer via `InvalidOperationException`.

---

## INF version stamping

The committed INFs (`driver/hidmaestro.inf`, `driver/hidmaestro_xusb.inf`) carry a stable `1.x.y.0` `DriverVer` for review. The build process **stamps** them with a fresh version including the build minute:

```powershell
# scripts\stamp_inf.ps1
$now = Get-Date
$build = $now.ToString("HHmm")     # e.g. 1142
# DriverVer = MM/DD/YYYY,1.x.y.<build>
```

Result: every package has a unique version. `pnputil` will never see "same version, skip install" against a prior DriverStore directory &mdash; which was the failure mode that hid every driver bugfix during the v1.x development cycle behind a stale already-installed binary.

The stamp is applied during `scripts\build.cmd` and `scripts\build_companion.cmd`; the stamped INFs are what get embedded into `HIDMaestro.Core.dll`. The committed INF source files are never modified by the build.

---

## Manifest hashing

`HMContext.IsDriverInstalled` doesn't query `pnputil` &mdash; that's slow (~300 ms per call) and unreliable across DriverStore states. Instead it computes a SHA-256 of the embedded payload and compares against a marker file in the DriverStore directory:

```csharp
public static bool IsDriverInstalled()
{
    string expectedHash = EmbeddedManifest.Sha256Hex;
    string markerPath = $@"C:\Windows\System32\DriverStore\HIDMaestro_{expectedHash}.marker";
    return File.Exists(markerPath);
}
```

Marker is written after a successful `FullDeploy`. If the SDK version is bumped, the embedded payload changes, the hash changes, and `IsDriverInstalled` returns false on the next consumer launch &mdash; triggering a fresh install.

The marker file is namespaced to HIDMaestro and doesn't conflict with any Microsoft-shipped DriverStore content. If the user manually deletes the DriverStore subdirectory but leaves the marker, subsequent install will re-extract the package from the embedded payload.

---

## Driver uninstall

```csharp
HMContext.RemoveAllVirtualControllers();   // evict every live + ghost devnode
DriverBuilder.Uninstall();                 // pnputil /delete-driver
```

`Uninstall` runs:

```cmd
pnputil /delete-driver hidmaestro.inf
pnputil /delete-driver hidmaestro_xusb.inf
```

Deletes both packages from the DriverStore. Idempotent &mdash; no-op if the package is already gone.

The certificate is **not** removed by `Uninstall`. The cert is per-machine and may be in use by other HIDMaestro versions or by future installs. `HMOemNameOverride.RecoverOrphans` is also not run by Uninstall &mdash; that's a separate concern handled at consumer startup.

To fully wipe HIDMaestro state from a machine:

```cmd
HIDMaestroTest.exe cleanup
```

The cleanup command in the test app does:

1. `HMContext.RemoveAllVirtualControllers()` &mdash; evict all virtuals.
2. `DriverBuilder.Uninstall()` &mdash; remove driver packages.
3. Delete `Cert:\LocalMachine\Root\HIDMaestro Self-Signed`.
4. Delete `Cert:\LocalMachine\TrustedPublisher\HIDMaestro Self-Signed`.
5. Delete `Cert:\LocalMachine\My\HIDMaestro Self-Signed`.
6. Delete `%TEMP%\HIDMaestro\` (extracted payload).
7. Delete `HKLM\SOFTWARE\HIDMaestro\` (per-controller config keys).
8. Delete `HKLM\SOFTWARE\HIDMaestroOemOverrides\` (pending overrides).

After cleanup, the machine is in the same state as before HIDMaestro was ever installed. New consumers will go through cold-start install path again.

---

## Why **never** `pnputil /delete-driver /uninstall /force` on the active driver

Empirically: leaves devices in **Code 14** ("restart required"). The flag combination forces removal even if devices are bound, but the kernel doesn't actually clean up &mdash; the devnodes stay live with `STATUS_RESTART_REQUIRED`. User experience: HIDMaestro virtuals show as broken in Device Manager and don't recover until reboot.

The right pattern:

1. **`HIDMaestroTest cleanup` first.** Evicts every devnode cleanly (`DIF_REMOVE` + SwD-first ordering). After this, no device is bound to the INF.
2. **Plain `pnputil /delete-driver` second** (no `/uninstall`, no `/force`). The package is removable now because nothing's using it.

`InstallDriver` is **idempotent across version bumps**. Manual uninstall before reinstall is almost never the right move &mdash; just call `InstallDriver` again and let the hash-check + DriverStore replacement do the right thing.

---

## Cold-start flow at a glance

A fresh consumer install on a machine with no HIDMaestro state. The per-step `InstallDriver` numbers below come from the README's measured breakdown on a clean dev machine; **catalog generation, signing, and `pnputil /add-driver` numbers are totals across both INFs**, not per-INF, because the steps batch the work internally.

```
Process A:                                           Time
─────────────────────────────────────────────       ────
1.  using var ctx = new HMContext();                ~10 ms
       Background prewarm tasks fire-and-forget
2.  ctx.LoadDefaultProfiles();                      ~100 ms
       Parse 231 embedded JSONs
3.  ctx.InstallDriver();                            ~1.7 s on a clean machine
       3a. RemoveAllVirtualControllers (no-op)        ~50 ms
       3b. Compute hash, IsDriverInstalled? no       <50 ms
       3c. Extract embedded payload to %TEMP%         ~20 ms
       3d. Remove any prior package (idempotent)     ~100 ms
       3e. Generate self-signed cert (first-ever)    ~500 ms (one-time per machine)
       3f. Install cert to Root + TrustedPublisher    ~50 ms (one-time per machine)
       3g. Sign DLLs + INFs (signtool, batched)      ~130 ms
       3h. Generate .cat catalogs (Inf2Cat, batched) ~840 ms (largest single step, AV-sensitive)
       3i. pnputil /add-driver, both INFs            ~580 ms total
       3j. Delete %TEMP% extraction                   <50 ms
       3k. Write marker file                          <1 ms
4.  ctx.CreateController(profile);                  ~200-700 ms
       SetupController for one Xbox 360 Wired
─────────────────────────────────────────────       ────
                                            Total: ~2.5-3 s on a clean dev machine
                                                   ~5-20 s on a corporate workstation
                                                       (PnP tree depth scales pnputil)
```

The README's "~18 s cold start" figure cited in [Lifecycle and Teardown](lifecycle-and-teardown.md) is the typical case **including** machine-state contributors that aren't strictly part of the install pipeline: first-ever .NET runtime cold-load, first-ever embedded-JSON parse on a slow disk, the cert-gen + cert-install one-time costs, and `pnputil`'s scan time on machines with hundreds of PnP devices in the tree. Subsequent runs skip 3c-3i entirely (`IsDriverInstalled` returns true at 3b). Subsequent total: ~50 ms for `InstallDriver`, ~200 ms for `CreateController`.

---

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `UnauthorizedAccessException` from `InstallDriver` | Process not elevated | Re-launch the consumer with admin privileges |
| `InvalidOperationException` "Driver install failed" | Inf2Cat or signtool failed | Check `%TEMP%\HIDMaestro\<hash>\install.log`; common causes: AV holding files, network failure during timestamp step |
| `pnputil /add-driver` returns "Needed repairing" | Stale orphan device pinning the old INF | The self-heal sweep at start of `InstallDriver` should have prevented this; if it persists, run `HIDMaestroTest cleanup` then retry |
| Driver installed but virtuals don't appear in `joy.cpl` | Cert not in `TrustedPublisher` | Check `Cert:\LocalMachine\TrustedPublisher` for "HIDMaestro Self-Signed"; reinstall if missing |
| Subsequent install replaces with stale binary from `pnputil` cache | DriverStore corruption | Manual fix: `takeown` the FileRepository subdir as TrustedInstaller and delete; then reinstall |
| `0x80004005` from Inf2Cat | Missing `Microsoft.UniversalStore.HardwareWorkflow.*` deps | Embedded payload corrupted; reinstall the SDK package |

See [Troubleshooting](../troubleshooting.md) for a fuller table.

---

## See also

- [Installation](../start/installation.md) &mdash; consumer-facing install steps.
- [Lifecycle and Teardown](lifecycle-and-teardown.md) &mdash; the `RemoveAllVirtualControllers` self-heal that prevents the stale-binary trap.
- [Build and Release](build-and-release.md) &mdash; how the embedded payload gets built and stamped.
- [Troubleshooting](../troubleshooting.md) &mdash; install-specific symptoms and fixes.
- [`sdk/HIDMaestro.Core/Internal/DriverBuilder.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/Internal/DriverBuilder.cs) &mdash; the full implementation (~509 lines).
