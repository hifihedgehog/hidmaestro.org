# Lifecycle and Teardown

The full create / dispose orchestration. Per-archetype create budget, the three wait gates (`WaitForHidChild`, `WaitForDeviceStarted`, `WaitForXInputSlotClaim`), the SwD-first removal ordering, batch teardown, and the self-heal `RemoveAllVirtualControllers` that runs on `InstallDriver`.

The mechanics here are what make multi-controller create / dispose / live-swap responsive enough for real consumer apps. The README's "Startup and Hot-Plug Timing" table summarizes the latencies; this page is the why.

For the SDK-side API, see [SDK Reference](../sdk/sdk-reference.md). For the underlying PnP machinery, see [SwDevice and PnP](swdevice-and-pnp.md). For the multi-controller scenarios, see [Multi-Controller](multi-controller.md).

---

## Create: `SetupController` orchestration

`HMContext.CreateController(profile)` runs `Internal.DeviceOrchestrator.SetupController(index, profile, infPath)`. The sequence:

```
1. RemoveAllVirtualControllers (one-shot self-heal, first call only)
2. Index allocation (from HMContext._lock)
3. Per-instance registry write
   HKLM\SOFTWARE\HIDMaestro\Controller<N>:
     ReportDescriptor (REG_BINARY)
     VendorId / ProductId / VersionNumber (REG_DWORD)
     ProductString (REG_SZ)
     InputReportByteLength (REG_DWORD)
     [profile-specific extras]
4. Per-instance shared sections + named events
   Global\HIDMaestroInput<N>          (created)
   Global\HIDMaestroOutput<N>         (created)
   Global\HIDMaestroInputEvent<N>     (created)
   Global\HIDMaestroStopEvent<N>      (created)
   PID state section is lazy — only created on first PublishPidPool
5. ContainerID computation
   {48494430-4D41-4553-5452-4F00 + 16-bit index}
6. Device creation:
   plain HID profiles:    SetupDiCreateDeviceInfoW under ROOT\
   xinputhid profiles:    hmswd.exe create SWD\HIDMAESTRO_VID_*_PID_*&IG_00\<sid>_NNNN
   non-xinputhid Xbox:    SetupDiCreateDeviceInfoW (main HID) + hmswd.exe create (XUSB companion)
7. WaitForHidChild       (10 s budget)
8. WaitForDeviceStarted  (5 s budget)
9. WaitForXInputSlotClaim (500 ms budget post-v1.3.2)
10. Per-instance UpperFilter writes (xinputhid-companion-XOR-tripwire profiles only)
11. Friendly-name application (best-effort; FinalizeNames runs the polled re-apply)
```

The driver wakes on PnP binding and reads its configuration from the registry written in step 3. The shared sections from step 4 are opened lazily by the driver (LocalService can't `CreateFileMapping(Global\)`, only `OpenFileMapping` what the SDK already created).

If any step fails after step 3, `TeardownController` is run as a best-effort cleanup. The throw rethrows to the consumer.

---

## Three wait gates

After `SwDeviceCreate` (or `SetupDiCreateDeviceInfoW`) returns success, the device isn't fully usable yet. Three wait gates ensure we only return to the consumer when downstream APIs can read the device.

### Gate 1: `WaitForHidChild` (10 s)

PnP creates the HID child node under the parent we just created. Polls `CM_Locate_DevNodeW` for the expected child instance ID. Typical: <100 ms warm. Slow machines (Atom Z8350): up to 2 s. Cap at 10 s.

If this times out, `SetupController` throws `InvalidOperationException` and best-effort cleanup runs. Cause: usually a corrupt INF or DriverStore inconsistency &mdash; rerun `RemoveAllVirtualControllers` then `InstallDriver` to repair.

### Gate 2: `WaitForDeviceStarted` (5 s)

Polls the HID child's `DEVPKEY_Device_DevNodeStatus` for `DN_STARTED`. The driver isn't fully bound until this status flips. Typical: <50 ms warm. Cap at 5 s.

Without this gate, an immediate `SubmitState` after `CreateController` returns could land before the driver has opened the shared section &mdash; the seqno never increments and no input reaches the consumer.

### Gate 3: `WaitForXInputSlotClaim` (500 ms post-v1.3.2)

For Xbox-family profiles only. Polls `XInputGetState` to confirm the controller has been assigned an XInput slot.

This gate **was 15 s pre-v1.3.2** and was the dominant cost. Distribution is bimodal:

- **Healthy claim**: <100 ms.
- **Stuck case**: never publishes (kernel state issue, prior-session residue).

The 15 s budget burned the full duration on every stuck case. PadForge users observed 13-14 s freezes on a single Xbox Series BT create.

The 500 ms cap (post-v1.3.2) sits ~5x above the slowest observed healthy claim. Stuck cases now degrade to a near-imperceptible pause. Controller stays functional via DI / HIDAPI / Browser / WGI when XInput doesn't pick it up; XInput consumers see the slot appear lazily on their next poll cycle.

For non-Xbox profiles this gate is skipped entirely.

---

## Per-archetype create latency

Warm-start (driver already in DriverStore):

| Profile group | Median | Worst | Notes |
|---------------|--------|-------|-------|
| **Plain HID** | ~200 ms | ~400 ms | One device, no companion, no XInput |
| **Non-xinputhid Xbox** | ~300 ms | ~700 ms | Two devices (main HID + XUSB companion). XInput slot-claim wait ≤500 ms post-v1.3.2 |
| **xinputhid Xbox** | ~250 ms | ~600 ms | One SwD device; xinputhid kernel filter binds. XInput slot-claim wait ≤500 ms post-v1.3.2 |

Multi-controller (sequential):

| Configuration | Total |
|---------------|-------|
| 1 plain HID | ~200 ms |
| 4 mixed (2 BT + 2 wired) | ~2.2-2.8 s |
| 6 mixed | ~3.5 s |

Cold-start (first run on machine, includes cert generation + signing + install): ~18 s for the install + create-1 step. Subsequent creates are warm-start cost.

---

## Per-step install breakdown

Visible in stdout when `HMContext.InstallDriver` runs:

| Step | Cost |
|------|------|
| Extract embedded payload to `%TEMP%` | ~20 ms |
| Remove old packages (idempotent guard) | ~100 ms |
| Sign DLLs and INFs | ~130 ms |
| Generate `.cat` catalogs (largest single step, AV-sensitive) | ~840 ms |
| `pnputil /add-driver` | ~580 ms |
| **Total** | **~1.7 s** |

On corporate workstations with hundreds of devices in the PnP tree, total install can stretch to 5-20 s. HIDMaestro deliberately doesn't run `pnputil /scan-devices` (it's a no-op for our INFs and was the largest variable contributor in profiling).

---

## Self-healing on init

`HMContext.InstallDriver` calls `RemoveAllVirtualControllers` **first thing**, before the actual install logic:

```csharp
public void InstallDriver()
{
    Internal.DeviceOrchestrator.RemoveAllVirtualControllers();   // self-heal

    if (!DriverBuilder.FullDeploy())
        throw new InvalidOperationException(
            "Driver install failed. Run elevated and check pnputil output.");
}
```

Without this, when a prior process crashed or was force-killed (Dispose never ran), its virtual controllers + HIDMAESTRO PnP entries stay live and **remain bound to the old INF**. On the next launch:

- `DriverBuilder.FullDeploy` calls `pnputil /delete-driver /uninstall /force`.
- That fails with "One or more devices are presently installed using the specified INF" and leaves the old INF + stale DLL bytes in DriverStore.
- The subsequent `/add-driver` then sees package-already-present + "Needed repairing" and **restores the stale bytes from `pnputil`'s internal cache** rather than installing the fresh extracted binary.
- Net effect: every launch since the first one serves the stale driver forever, the v1.1.5 self-heal code never actually loads, input keeps hanging, and the only escape is manual `devcon` + TrustedInstaller `takeown` of the FileRepository subdirectory (which users do not have).

Running the sweep here FIRST removes the bound devices via `devcon` (returning "Removed on reboot" is sufficient &mdash; the INF becomes eligible for package deletion immediately), so `FullDeploy`'s `/delete-driver` call actually succeeds and the fresh extracted binary replaces the DriverStore contents.

The same call is exposed publicly as `HMContext.RemoveAllVirtualControllers()` for consumers who want explicit defensive cleanup (e.g. on app exit). In normal operation, individual `HMController.Dispose()` is sufficient &mdash; there is no per-process cleanup obligation on shutdown.

---

## Dispose: `TeardownController` orchestration

`HMController.Dispose()` runs `Internal.DeviceOrchestrator.TeardownController(index, instanceId)`. Sequence:

```
1. Cancel the output reader thread, join (5 s timeout)
2. Dispose the output cancellation token
3. Notify the context (HMContext.OnControllerDisposing)
4. Per-archetype removal:
   plain HID:           DIF_REMOVE on the ROOT\ device
   non-xinputhid Xbox:  hmswd.exe remove (XUSB companion) + DIF_REMOVE (main HID)
   xinputhid Xbox:      hmswd.exe remove (SwD parent) + cascade waits
5. Wait CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED (per device)
6. Close shared memory mappings
7. Free per-controller registry path
8. Release the index back to the context's free pool
```

For SwD-enumerated devices, step 4 uses the SwD-first ordering (see below). For plain HID devices, `DIF_REMOVE` and the per-device removal wait are sufficient.

---

## SwD-first removal ordering (v1.3.1)

Two of the three architecture groups own a SwDevice-enumerated parent: Xbox 360 Wired (XUSB companion is SwD) and Xbox Series BT (main HID is SwD). SwDevice lifetimes are anchored to the `HSWDEVICE` handle, **not** the PnP devnode &mdash; children of a SwD parent cannot fully unwind their query-remove cascade until the parent's handle drops its kernel refcount.

### Pre-v1.3.1: HID-children-first (broken)

```
1. DIF_REMOVE on every HID child first
2. WaitForDeviceRemoval per child (2,000 ms timeout each — always times out
   because the parent is still holding the lifetime lock)
3. Finally close the SwDevice handle

Net cost: ~5,700 ms for Xbox 360 Wired
          ~11,000 ms for Xbox Series BT
```

PadForge users with Xbox Series BT virtuals saw 11+ second "Disposing controller..." pauses. Unacceptable for live profile-switching.

### v1.3.1+: SwD-parent-first (fast)

```
1. Close the SwDevice handle FIRST via hmswd.exe remove
2. Block on CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED for the parent
3. Mop up any HID children that survived the cascade
   (usually zero — the SwD parent's release fires its children's removal in one cascade)

Net cost: ~135 ms for Xbox 360 Wired
          ~500 ms for Xbox Series BT
```

`CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED` is the kernel-side guarantee that the cascade has propagated, not just that the handle closed. Critical for callers that immediately follow with a recreate (live profile switch &mdash; the new controller's `SetupController` would race the old one's cleanup if we returned too early).

A second optimization in the same change: when a HIDMAESTRO sweep walks registry entries that exist only as `PHANTOM` (registry residue from prior sessions, no live devnode), skip the `hmswd.exe` `SwDeviceCreate`-reconnect roundtrip entirely. Saves ~50-75 ms per stale entry and prevents creep across same-process recreation cycles.

---

## Per-archetype dispose latency

| Profile group | Pre-v1.3.1 | Post-v1.3.1 |
|---------------|-----------|------------|
| **Plain HID** | ~80 ms | ~80 ms |
| **Non-xinputhid Xbox** | ~5,700 ms | **~135 ms** |
| **xinputhid Xbox** | ~11,000 ms | **~500 ms** |

The plain HID path was already fast pre-v1.3.1 because there's no SwD parent. The two SwD-bearing groups got the dramatic improvement.

Round-trip (dispose + recreate) latencies:

| Profile pair | Latency |
|--------------|---------|
| **DualSense ↔ DualShock 4** | ~280 ms |
| **DualSense ↔ Xbox 360 Wired** | ~350-850 ms |
| **DualSense ↔ Xbox Series BT** | ~650-1100 ms |
| **Xbox Series BT ↔ Xbox 360 Wired** | ~750-1300 ms |

Down from ~6.4 s and ~11 s respectively pre-v1.3.1. PadForge user-reported: virtually instantaneous create and swap on the post-v1.3.1 path.

---

## Batch teardown: `DisposeControllersInParallel`

```csharp
public void DisposeControllersInParallel(
    IEnumerable<HMController> controllers,
    Action<HMController, long>? perControllerCallback = null);
```

Disposes a set of controllers concurrently with the per-controller HID orphan sweep **suppressed** and run **once at the end** instead of per-controller.

```csharp
ctx.DisposeControllersInParallel(
    new[] { ctrl0, ctrl1, ctrl2, ctrl3 },
    perControllerCallback: (c, ms) => Logger.Info($"  {c.Profile.Id}: {ms} ms"));
```

Internal sequence:

```
1. Set _batchDisposing = true
2. Parallel.ForEach: each controller's Dispose runs concurrently
   (each takes its own per-controller lock; no contention)
3. Set _batchDisposing = false
4. RemoveOrphanHidChildrenBatch — single sweep
```

The per-controller `Dispose` checks `_batchDisposing`; when set, it skips the per-controller orphan sweep that would otherwise run inside each `TeardownController`.

For 4-6 mixed controllers the cleanup typically completes in 1.5-4 s end to end.

`HMContext.Dispose()` itself uses an equivalent path internally &mdash; consumers don't need to call `DisposeControllersInParallel` explicitly unless they want the per-controller wall-clock telemetry.

### Single-element / empty input

Single-element inputs degrade to a plain serial dispose (no parallelism overhead). Empty inputs are no-ops. The implementation:

```csharp
if (arr.Length == 0) return;
if (arr.Length == 1)
{
    var sw = Stopwatch.StartNew();
    try { arr[0].Dispose(); } catch { }
    perControllerCallback?.Invoke(arr[0], sw.ElapsedMilliseconds);
    return;
}
// ... parallel path for ≥2 controllers
```

---

## Live profile switch

Switching a slot's profile mid-session (`HMController.Dispose()` then `HMContext.CreateControllerAt(index, newProfile)`) is **synchronous** by design. Slot-allocation determinism requires the old devnode fully gone before the new one is created &mdash; otherwise the new device would race the old one's removal and might land in a slot the old one hasn't released yet.

Round-trip latencies are the dispose + create numbers above. PadForge's user-perceived "switch slot 1 from DualSense to Xbox 360 Wired" is ~850 ms post-v1.3.x.

---

## Hot-plug API

Each controller is independently disposable. Removing one does not disturb the others:

```csharp
using var ctx = new HMContext();
ctx.LoadDefaultProfiles();
ctx.InstallDriver();

var ctrl0 = ctx.CreateController(ctx.GetProfile("dualsense")!);
var ctrl1 = ctx.CreateController(ctx.GetProfile("xbox-360-wired")!);
var ctrl2 = ctx.CreateController(ctx.GetProfile("switch-pro")!);

ctrl1.Dispose();    // dispose middle one — others stay live, slots renumber
// ctrl0 still works at index 0
// ctrl2 still works at index 2
// indices 1 is free; next CreateController fills it
```

Slot indices don't compact automatically. If you want sparse-to-dense compaction (after disposing index 1, want index 2 to become index 1), you have to dispose index 2 and recreate at index 1. The XInput user-index allocator handles this on its side independently &mdash; an XInput slot-N controller becoming slot-1 means a brief disconnect/reconnect at the XInput level for slot 2 consumers.

PadForge does this compaction explicitly via the "bubble-up cascade" in its Step 5 InputManager &mdash; see PadForge's wiki for the consumer-side implementation. The SDK doesn't enforce a particular scheme.

---

## Force-kill recovery

If the consumer process crashes without disposing controllers, the next process's `HMContext.InstallDriver` calls `RemoveAllVirtualControllers` first thing as a self-heal. Typically:

```csharp
// Process A creates 3 controllers, then crashes
// Process B starts:
using var ctx = new HMContext();   // constructor doesn't sweep yet
ctx.InstallDriver();   // ← RemoveAllVirtualControllers runs here, sweeps process A's orphans
ctrl0 = ctx.CreateController(...);   // fresh state
```

The regression battery's S12_ForceKill_Recovery and S17_ForceKill_MidCascade scenarios validate this end-to-end. See [Testing and Verification](testing-and-verification.md).

### Composite personas are swept by a separate route (v1.4.5)

The sweep walks the ROOT and SWD enumerators removing devices whose hardware IDs carry the `HIDMAESTRO` token. A [composite persona](../sdk/usb-audio-composite.md) carries no such token by design, because the USB Audio Class driver binds against an exact Sony identity, so the enumerator walk cannot reach one. Before v1.4.5 an orphaned persona survived the self-heal: a USB DualSense stayed enumerated with nothing left running to feed it.

`RemoveAllVirtualControllers` now detaches every persona this SDK owns from the emulated host controller, then walks the enumerators as before. Two consequences worth knowing:

- Personas belonging to another live process are detached too. A consumer asking for a clean machine gets one, which is the same contract the enumerator walk has always had for UMDF2 controllers.
- The detach runs before the walk, and before it detaches anything it disposes this process's own emulated devices to join their input pump threads. Those pumps map the shared input sections directly and take no part in the stop-event drain, so a pump still running when the sweep unmaps its section is an access violation on a background thread, not a leak. Consumers calling the public API get this ordering for free.

**Dispose your controllers before sweeping.** The sweep ends by releasing every shared-memory mapping the process holds, and it does not stop a live `HMController`. That controller's output poll loop is stopped only by `Dispose`, so it keeps reading a view the sweep has unmapped and the process dies with `0xC0000005` on a thread unrelated to the call you made. Tracked as [#45](https://github.com/hifihedgehog/HIDMaestro/issues/45), open as of v1.4.5.

For deliberate cleanup (e.g. uninstalling HIDMaestro entirely), use:

```cmd
HIDMaestroTest.exe cleanup
```

Which calls `RemoveAllVirtualControllers` + driver package uninstall. Don't reach for raw `pnputil /remove-device` or `devcon` &mdash; the cleanup command is the right interface.

---

## Anti-pattern: `pnputil /delete-driver /uninstall /force` on the active driver

**Don't.** Leaves devices in Code 14 ("restart required"). Always:

1. `HIDMaestroTest cleanup` (or `HMContext.RemoveAllVirtualControllers()`) FIRST to evict the devices.
2. Plain `pnputil /delete-driver` (no `/uninstall`) if a package delete is even needed.

`InstallDriver` is **idempotent across version bumps** &mdash; manual uninstall before reinstall is almost never the right move.

The cleanup command does the right thing because:

- It walks every HIDMaestro PnP entry by enumerator name (`SWD\HIDMAESTRO*`, `ROOT\VID_*&PID_*&IG_00`).
- It calls `hmswd.exe remove` for SWD entries (the only documented teardown for `SWDeviceLifetimeParentPresent`).
- It calls `DIF_REMOVE` for ROOT entries.
- After the sweep, if a driver-package delete is desired, it runs `pnputil /delete-driver` (no force flags).

---

## See also

- [SDK Reference](../sdk/sdk-reference.md) &mdash; the public API that drives all of this.
- [SwDevice and PnP](swdevice-and-pnp.md) &mdash; the per-controller PnP machinery.
- [Multi-Controller](multi-controller.md) &mdash; multi-controller create / dispose patterns.
- [Driver Install and Signing](driver-install-and-signing.md) &mdash; the InstallDriver step.
- [Testing and Verification](testing-and-verification.md) &mdash; the regression battery that validates this end-to-end.
- [Troubleshooting](../troubleshooting.md) &mdash; lifecycle-related symptoms and fixes.
