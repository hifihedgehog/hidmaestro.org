# Troubleshooting

Symptom &rarr; cause &rarr; fix table for everything that's gone wrong in HIDMaestro deployments. Organized by phase: install, create, runtime input, output / FFB, multi-controller, teardown, and Windows-side state.

If you're not sure where to start, run the test app's cleanup command and try again:

```cmd
HIDMaestroTest.exe cleanup
```

That sweeps every HIDMaestro PnP entry, removes the driver packages, and deletes the certificate. After cleanup, a fresh `InstallDriver` rebuilds from scratch.

---

## Install phase

### `UnauthorizedAccessException` from `InstallDriver`

**Cause**: process not elevated. `InstallDriver` requires admin (`SeLoadDriverPrivilege`).

**Fix**: launch the consumer with admin privileges. PadForge auto-elevates via UAC; bare SDK consumers must self-elevate or be started from an elevated shell.

### `InvalidOperationException` "Driver install failed"

**Cause**: one of the install steps (cert install, signing, Inf2Cat, pnputil) returned non-zero.

**Fix**: check the consumer's stdout for the specific step that failed. Common causes:

- **Antivirus holding files.** Real-time scanning of `%TEMP%\HIDMaestro\<hash>\` causes `signtool` or `Inf2Cat` to fail with sharing violations. Whitelist `%TEMP%\HIDMaestro\` in your AV.
- **Network failure during timestamp step.** `signtool /tr http://timestamp.digicert.com` requires HTTP egress. Air-gapped or proxied environments may need a different timestamp URL via `HIDMAESTRO_TIMESTAMP_URL`.
- **Corrupt embedded payload.** Reinstall the SDK (download a fresh release ZIP).

### `pnputil` returns "Needed repairing"

**Cause**: stale orphan device pinning the old INF "in use", so `pnputil`'s integrity check incorrectly classifies a fresh install as a repair candidate. Restores stale binary from `pnputil`'s internal cache instead of installing the fresh extracted bytes.

**Fix**: this is what the self-heal sweep at the start of `InstallDriver` is supposed to prevent. If it persists:

```cmd
HIDMaestroTest.exe cleanup
:: then re-run your consumer; InstallDriver will run fresh
```

If cleanup itself fails (rare; usually means `hmswd.exe` is denied), reboot then retry. The orphan devnode releases on reboot.

### Driver installed but virtuals don't appear in `joy.cpl`

**Cause**: the self-signed cert isn't in `Cert:\LocalMachine\TrustedPublisher`. Windows refused to bind the unsigned-from-its-perspective driver.

**Fix**: check `Cert:\LocalMachine\TrustedPublisher` for "HIDMaestro Self-Signed":

```powershell
Get-ChildItem Cert:\LocalMachine\TrustedPublisher | Where-Object Subject -like '*HIDMaestro*'
```

If missing, run `HIDMaestroTest.exe cleanup` then call `InstallDriver` again &mdash; the install will regenerate the cert and place it in all three stores.

### Subsequent install replaces with stale binary

**Cause**: DriverStore corruption. The FileRepository subdirectory has the wrong bytes and `pnputil` keeps restoring it on every install.

**Fix** (manual, last resort):

```cmd
:: Find the FileRepository subdirectory
dir C:\Windows\System32\DriverStore\FileRepository\hidmaestro*

:: Take ownership as TrustedInstaller (you can't just delete; ACL refuses)
takeown /f "C:\Windows\System32\DriverStore\FileRepository\<dir>" /r /d y
icacls "C:\Windows\System32\DriverStore\FileRepository\<dir>" /grant administrators:F /t

:: Now delete
rmdir /s /q "C:\Windows\System32\DriverStore\FileRepository\<dir>"

:: Then run InstallDriver again — fresh extraction
```

Almost never needed in normal operation. The self-heal sweep prevents this from happening; if you hit it, capture state and file an issue.

### `0x80004005` from Inf2Cat

**Cause**: missing `Microsoft.UniversalStore.HardwareWorkflow.*` dependency DLLs.

**Fix**: the embedded payload is missing files. Reinstall the SDK package &mdash; this means the SDK assembly itself is corrupt, not a runtime issue.

---

## Create phase

### `InvalidOperationException` "device-node creation failed"

**Cause**: the PnP wait gate timed out. Usually the HID child never reached `DN_STARTED`.

**Fix**: enable diagnostic logging:

```cmd
set HIDMAESTRO_DIAG=1
:: re-run your consumer; %TEMP%\HIDMaestro\teardown_diag.log captures every step
```

Common causes:

- **xinputhid binding hung.** Xbox Series BT profiles need `xinputhid.sys` to bind on the HID child. If the kernel xinputhid allocator is in a stuck state from prior session residue, the bind never completes. Reboot fixes it (clears xinputhid kernel state). v1.3.2's 500ms `WaitForXInputSlotClaim` cap means the consumer no longer freezes for 15s on this case &mdash; the controller still creates, just may not have an XInput slot until xinputhid recovers on its own (typically next reboot).
- **Stale ContainerID.** The reuse-existing fast path (see [SwDevice and PnP](reference/swdevice-and-pnp.md)) leaves an empty registry shell. v1.x.x.1's per-call atomic sequence number prevents this. If you hit it on a current build, capture `teardown_diag.log` and the registry state.

### Single Xbox Series BT create takes 13-14 seconds

**Cause**: pre-v1.3.2 with `WaitForXInputSlotClaim = 15s` and xinputhid in a stuck state. The 15s wait burned even when the slot would never publish.

**Fix**: upgrade to v1.3.2+. Cap is now 500 ms.

### XInput slot 1 is empty (slot-1-skip)

**Cause**: pre-SWD-migration; null-sentinel ContainerID triggered `xinput1_4!FUN_18000de2c`'s bit-2 path.

**Fix**: upgrade to a build with the SWD migration (current). Verify your build:

```cmd
HIDMaestroTest.exe info xbox-360-wired
:: should show "driverMode: null" and the SWD-enumerated companion path
```

If you're on the latest build and still see slot-1-skip, the per-controller ContainerID may have been reset to null-sentinel by a hardware ID list change. File an issue with `Get-PnpDevice ... | Format-List *` output.

### Subsequent run after a fresh boot is fast (~2 s); same-boot relaunch is slow (65 s) and XInput loses visibility

**Cause**: pre-v1.x.x.0 with the sticky `(enumerator + suffix + ContainerId)` reuse-fast-path leaving subsequent-run companion devnodes as empty registry shells.

**Fix**: upgrade to a build with the per-process PID prefix on SwD instance-IDs (current). Verify by checking the companion's instance ID:

```cmd
Get-PnpDevice -InstanceId 'SWD\HIDMAESTRO\*'
:: Instance ID should look like "<HEXPID><HEX4>_<DEC4>", e.g. "A7B40001_0002"
:: NOT just "0001_0002" or "0_0002"
```

### `hmswd.exe` returns `E_FAIL`

**Cause**: `SwDeviceCreate` failed. Typically a callback timeout (the kernel didn't acknowledge the create within 30 seconds).

**Fix**:

- Check `%TEMP%\HIDMaestro\hmswd_self.log` for the per-call hresult breakdown.
- Reboot if the failure is "the device is busy" (a prior orphan is somehow still holding the slot).
- Verify the current driver is signed and registered (`pnputil /enum-drivers | findstr hidmaestro`).

---

## Runtime input phase

### `SubmitState` succeeds but no input reaches consumers

**Cause options**:

- The driver hasn't bound yet. `CreateController`'s wait gates should prevent this; if you bypass them with `CreateControllerAt` and submit immediately, may race the bind.
- The shared section isn't accessible to the driver. WUDFHost (LocalService) needs the section's DACL to permit `OpenFileMapping`. SDK creates with `D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;WD)`; if you saw a permission failure, the SDK's section creation step failed.

**Fix**: check that:

```cmd
HIDMaestroTest.exe emulate xbox-360-wired
:: in another terminal, while HIDMaestroTest is still running:
joy.cpl
:: Do you see "Controller (XBOX 360 For Windows)"? Move sticks in the test app's interactive prompt; do they reflect in joy.cpl?
```

If `joy.cpl` shows the controller but axes don't move on input: the input section isn't being read. Check `HIDMAESTRO_DIAG` log for "InputDataEvent fired" entries.

If `joy.cpl` doesn't show the controller at all: the driver didn't bind. Check `Get-PnpDevice -Status OK | Where FriendlyName -like '*HIDMaestro*'`.

### Some buttons / axes work but others don't

**Cause**: descriptor mismatch. The catalog profile's `inputReportSize` doesn't match what the descriptor actually wire-encodes, OR the consumer is using `SubmitRawReport` with bytes that don't match the descriptor.

**Fix**: verify the descriptor's parsed layout vs. submitted state:

```csharp
var profile = ctx.GetProfile("xbox-360-wired");
Console.WriteLine($"Buttons declared: {profile.ButtonCount}");
Console.WriteLine($"Axes declared:    {profile.AxisCount}");
Console.WriteLine($"InputReportSize:  {profile.InputReportSize}");
```

If those don't match what you expect, the profile is wrong &mdash; either re-extract via `HMDeviceExtractor.Extract` or use `HMProfileBuilder` to define the right shape.

### Xbox 360 d-pad doesn't work in XInput consumers

**Cause** (pre-v1.3.3): the SDK never wrote hat bits into the GIP buffer. XInput consumers hitting `xusb22` directly (SDL3 XInput backend, sample-quality XInput apps) saw no d-pad on Xbox 360 wired.

**Fix**: upgrade to v1.3.3+. Issue #19 fix packs hat into bits 2-5 of GIP `btnHigh`; the companion's `IOCTL_XUSB_GET_STATE` handler unpacks back. Verified by `swap_regression.ps1` scenario S27_Xbox360_Dpad_XInput.

### Hat directions wrong on a HOTAS

**Cause** (pre-v1.3.4): `AddHat()` declared `LogicalMax = positions` (one too many). Pre-v1.3.4 8-position hat had LogicalMax=8 but encoder wrote 0..7; LogicalMax should be 7. Surfaced for consumers that inspect the descriptor's LogicalMax (rare).

**Fix**: upgrade to v1.3.4+. Encoder behavior unchanged; descriptor LogicalMax now correct.

For higher-resolution hats (16+ positions) you also need to use `HatDegrees` / `HatHundredths` / `HatRaw` instead of the 8-way `Hat` enum. See [HID Descriptor Builder](sdk/hid-descriptor-builder.md) and [Custom Profiles](profiles/custom-profiles.md).

### Real BT Xbox controller stops working after I run HIDMaestro

**NEVER assume the user device is the cause.** Real BT Xbox controllers and HidHide are always false positives during HIDMaestro debugging. When in doubt, blame HIDMaestro first.

**Specific case**: if you ran a probe that killed `WUDFHost.exe` directly, the real BT Xbox controller goes into Code 43. **Don't kill WUDFHost.** Let the system manage host lifetime. Recovery: replug the BT controller (or `Disable-PnpDevice -InstanceId 'BTHENUM\Dev_*' && Enable-PnpDevice ...`).

---

## Output / FFB phase

### `OutputReceived` never fires

**Cause**: handler subscribed too late, output section not opened, or no host is actually sending output.

**Fix**:

```csharp
ctrl.OutputReceived += (sender, packet) => Logger.Info($"output: {packet.Source} rid={packet.ReportId} bytes={packet.Data.Length}");

// After subscribing, verify by triggering an output:
//   - For Xbox 360 Wired: XInputSetState from a tester
//   - For DualSense: a game's HID output report (e.g. lightbar set via DualSense Tester app)
//   - For PID FFB: a game's CreateEffect call
```

If you see input reaching the consumer (`SubmitState` is being polled by something) but `OutputReceived` never fires after a known output trigger:

- Check the SDK's output reader thread is running. Set a breakpoint in `HMOutputReader_<index>`.
- Check the output section is open. `Marshal.ReadInt32(_outputView, 0)` should return Head value, not 0.

### PID FFB: `CreateEffect` succeeds but `Start` does nothing

**Cause options**:

- `PublishPidPool` was never called. FFB is gated; without it the driver returns `STATUS_NO_SUCH_DEVICE` for Pool, and `pid.dll` decides "device exists but no FFB" without trying.
- The descriptor declared four Feature reports (the vJoy reference layout). `pid.dll` AVs inside `PID_EffectOperation+0x52`. See [Force Feedback](sdk/force-feedback.md) and [HID Descriptor Builder](sdk/hid-descriptor-builder.md).
- The TLC is Gamepad. `AddPidFfbBlock` throws on Gamepad TLC; if you bypassed via `AddRaw`, `pid.dll` AVs.

**Fix**:

```csharp
// Required for FFB to enable
ctrl.PublishPidPool(0x0400, 16, deviceManagedPool: false, sharedParameterBlocks: false);

// Verify by reading back
var bl = ctrl.GetCurrentPidBlockLoad();
Console.WriteLine($"PID FFB enabled (load status: {bl.LoadStatus})");
```

### PID FFB middle packet lost (`pid.dll` writes Set Effect / Set Constant / Operation Start; consumer only sees Set Effect and Operation Start)

**Cause** (pre-v1.1.40): single-slot output channel coalesced bursts within 1-3 ms vs the SDK's 8 ms poll. Issue #16.

**Fix**: upgrade to v1.1.40+. 64-slot ring buffer drains every slot per poll.

### Browser vibration doesn't reach my consumer

**Cause options**:

- For Xbox 360 Wired: the xinputhid UpperFilter tripwire isn't on the XUSB companion. Check `HKLM\SYSTEM\CurrentControlSet\Enum\SWD\HIDMAESTRO\<sid>_<idx>\UpperFilters` &mdash; should contain `xinputhid`. INF carries this; if missing, the install was corrupt.
- For Xbox Series BT: xinputhid handles vibration internally as a HID Output report. Surfaces as `HMOutputSource.HidOutput` not `HMOutputSource.XInput`.
- For plain HID: WGI dispatches a HID Output report directly. Subscribe to `HidOutput` source, not just `XInput`.

**Fix**: subscribe to all three sources:

```csharp
ctrl.OutputReceived += (sender, packet) =>
{
    if (packet.Source == HMOutputSource.HidOutput || packet.Source == HMOutputSource.XInput)
        HandleVibration(packet);
};
```

See [Cross-API Coverage](reference/cross-api-coverage.md) for the per-architecture-group dispatch path.

---

## Multi-controller phase

### Friendly names are all "Game Controller" instead of profile names

**Cause**: the Windows PnP race where the first controller's friendly name gets overwritten by the second controller's driver-bind activity.

**Fix**: call `HMContext.FinalizeNames()` once after creating ALL controllers. See [Multi-Controller](reference/multi-controller.md).

### Controllers in browser appear in wrong order

**Cause**: Chromium uses alphabetical / lexical GUID ordering for the gamepad list. Match to creation order is coincidental.

**Fix**: this is a Chromium quirk, not a HIDMaestro bug. If your consumer cares about browser ordering, sort or remap on the consumer side.

### Browser still shows old/duplicate controllers after I removed them

**Cause**: Chromium caches gamepad slots within a session. Adding/removing controllers during a Chromium session leaves stale duplicate slots with identical inputs.

**Fix**: restart Chromium to clear. Not a HIDMaestro bug.

### CPU saturation with 4+ controllers

**Cause**: a regression has dropped `UmdfHostProcessSharing = ProcessSharingDisabled` from one of the INFs. All UMDF2 instances are pooling into one shared `WUDFHost.exe`; contention scales non-linearly.

**Fix**: verify the INF has the line:

```cmd
findstr /i "ProcessSharingDisabled" driver\hidmaestro.inf driver\hidmaestro_xusb.inf
```

Both INFs should show the line. If missing, fix the INF and rebuild. Verify per-instance hosts at runtime:

```powershell
Get-Process WUDFHost | Measure-Object -Property Count
# Expected: N main HID instances + M XUSB companion instances (matches your controller count)
# Regression: 1-2 hosts regardless of controller count
```

---

## Teardown phase

### Dispose takes 5+ seconds

**Cause** (pre-v1.3.1): HID-children-first removal ordering. Each child's `WaitForDeviceRemoval` timed out at 2 s waiting for the SwD parent to release its lifetime lock.

**Fix**: upgrade to v1.3.1+. SwD-first removal ordering closes the parent first; children cascade.

### Dispose hangs on Xbox Series BT (~11 seconds pre-v1.3.1)

Same root cause; SwD-first ordering fix shortens to ~500 ms.

### Process force-kill leaves orphan devnodes

**Cause**: normal. The consumer process didn't run `Dispose`.

**Fix**: the next `InstallDriver` call will sweep them via `RemoveAllVirtualControllers` self-heal. Or call `HIDMaestroTest.exe cleanup` manually to wipe state.

### Phantom devnodes accumulate over time

**Cause**: registry residue from `SWDeviceLifetimeParentPresent` cleanup. Windows retains entries even after `SwDeviceClose`; they're cosmetic.

**Fix**: `PHANTOM` entries don't occupy XInput slots, don't show in active-controller lists, and don't affect anything user-visible. The regression battery's PASS criterion ignores PHANTOMs.

If they bother you cosmetically, `HIDMaestroTest.exe cleanup` clears them.

---

## Process / privilege

### "The process hosting the driver for this device has been terminated." (Windows error 1291)

**Cause** (pre-v1.1.39): the driver-side write to the PID state shared section AV'd because the section was opened `FILE_MAP_READ` instead of `FILE_MAP_READ | FILE_MAP_WRITE`. The AV terminated WUDFHost; surfaced as Win32 1291.

**Fix**: upgrade to v1.1.39+. Section is now opened R/W.

### NEVER kill `WUDFHost.exe` to "fix" things

This breaks real BT Xbox controllers (Code 43). HIDMaestro shares WUDFHost with Microsoft-shipped UMDF2 drivers; killing one host kills its currently-bound devices.

**Fix**: let the system manage host lifetime. If you need to force-recover from a HIDMaestro state, use `HIDMaestroTest.exe cleanup` &mdash; that goes through proper PnP removal, not host termination.

---

## Reference: when in doubt, full reset

```cmd
HIDMaestroTest.exe cleanup
:: ...wait 5 seconds for kernel cascade...
:: re-run your consumer
```

If cleanup itself fails:

```cmd
:: Reboot
:: Then:
HIDMaestroTest.exe cleanup
:: re-run your consumer
```

Reboot is the strongest reset for kernel-state issues (xinputhid stuck, DriverStore corruption, host pool sharing). Don't reach for it first &mdash; cleanup handles 99% of cases &mdash; but it's the documented escape hatch for the 1%.

---

## Diagnostic logs

| Variable | Effect |
|----------|--------|
| `HIDMAESTRO_DIAG=1` | Writes `%TEMP%\HIDMaestro\teardown_diag.log` with per-call timing for every TeardownController and SwdDeviceFactory.Remove |
| `HIDMAESTRO_TIMEOUT_SCALE=2` | Doubles every PnP wait budget. Use on slow hardware (Atom Z8350) |
| `HIDMAESTRO_QUIET=1` | Suppresses redundant ProcessExit RemoveAllVirtualControllers call. Used by the regression harness |
| `HIDMAESTRO_TIMESTAMP_URL` | Override the RFC 3161 timestamp server for signtool. Default `http://timestamp.digicert.com` |

Logs to inspect:

| Path | Contents |
|------|---------|
| `%TEMP%\HIDMaestro\teardown_diag.log` | Per-call SDK orchestration trace (with `HIDMAESTRO_DIAG=1`) |
| `%TEMP%\HIDMaestro\hmswd_self.log` | Every `SwDeviceCreate` / `SwDeviceClose` call's hresult |
| `%TEMP%\HIDMaestro\<hash>\install.log` | Inf2Cat / signtool / pnputil output during install |

---

## Reporting an issue

Include:

1. **HIDMaestro version** (`HIDMaestroTest.exe info` shows it).
2. **Windows version** (`winver` or Settings &rarr; About).
3. **The full consumer stdout** during the failing operation.
4. **`%TEMP%\HIDMaestro\teardown_diag.log`** if the issue is create/dispose-related.
5. **`Get-PnpDevice -InstanceId 'SWD\HIDMAESTRO\*' | Format-List *`** if devnodes are involved.
6. **`Get-PnpDevice -InstanceId 'ROOT\VID_*&PID_*&IG_00\*' | Format-List *`** for ROOT-enumerated profiles.

[Open an issue](https://github.com/hifihedgehog/HIDMaestro/issues/new) with the above. Profile-specific issues use the [profile contribution template](https://github.com/hifihedgehog/HIDMaestro/issues/new?template=profile-contribution.yml) (different form).

---

## See also

- [Driver Install and Signing](reference/driver-install-and-signing.md) &mdash; the install pipeline that produces install-phase failure modes.
- [Lifecycle and Teardown](reference/lifecycle-and-teardown.md) &mdash; the create / dispose orchestration with per-archetype latencies.
- [Multi-Controller](reference/multi-controller.md) &mdash; the multi-controller regression scenarios and what they catch.
- [Cross-API Coverage](reference/cross-api-coverage.md) &mdash; per-API browser vibration / WGI / XInput dispatch paths.
- [Testing and Verification](reference/testing-and-verification.md) &mdash; how to reproduce a regression locally with `swap_regression.ps1`.
- [Glossary](start/glossary.md) &mdash; term definitions for the unfamiliar.
