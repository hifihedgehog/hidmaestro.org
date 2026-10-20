# Lifecycle and Teardown

The full create / dispose orchestration. Per-archetype create budget, the three wait gates (`WaitForHidChild`, `WaitForDeviceStarted`, `WaitForXInputSlotClaim`), the SwD-first removal ordering, the PnP lock and removal test (v2.0.0), batch teardown, and the sweep `InstallDriver` runs first, which since v2.0.0 removes only what programs that have exited left behind.

The mechanics here are what make multi-controller create / dispose / live-swap responsive enough for real consumer apps. The README's "Startup and Hot-Plug Timing" table summarizes the latencies; this page is the why.

For the SDK-side API, see [SDK Reference](../sdk/sdk-reference.md). For the underlying PnP machinery, see [SwDevice and PnP](swdevice-and-pnp.md). For the multi-controller scenarios, see [Multi-Controller](multi-controller.md).

---

## Create: `SetupController` orchestration

`HMContext.CreateController(profile, identityKey)` takes a slot in its context, then a machine-wide lease, then runs `Internal.DeviceOrchestrator.SetupController(transportIndex, profile, identity)`. The sequence:

```
1. Device model compiled and payload checked, before anything machine-wide
   (ports, protocol and WinUSB blocks, and the driver or USB/IP payload this build carries)
2. Once-per-session sweep (first create only): devices and ledger holds
   of programs that have exited. A running program's devices are never touched.
   Also starts the once-per-process phantom cleanup on a background thread
3. Lease (v2.0.0), holding the phantom cleanup off until the last record write:
   census of owner records and present devices,
   identity claim for a keyed create (waits up to 120 s while no live record
   lists the key and another program's sweep holds it),
   transport index claim (from 64 while a v1.12.0 program runs),
   owner-record entry for the controller
   identity: token, ContainerID, ParentIdPrefix, serial, all from the identity key,
   or from the transport index when the caller passed none
   {48494430-4D41-4553-5452-4F00 + 16-bit index} for the index identity
4. Per-instance owner pipe, shared sections and events, N = transport index
   (HMController.SectionNames lists them), in this order:
   \\.\pipe\HIDMaestroOwner<N> first: a v1.12.0 program that took the index
     meanwhile holds it, and the create is refused before any section is written
   Global\HIDMaestroInput<N>, CompanionInputEvent<N>, InputAck<N>,
   InputAckEvent<N>, Version<N>, then InputEvent<N>, then Output<N>
   PID state section is lazy: only created on first PublishPidPool
   Global\HIDMaestroStopEvent<N> and OutputEvent<N> are the driver's, created
     in EvtDeviceAdd (a USB/IP persona's OutputEvent<N> is the SDK's)
5. Per-instance registry write
   HKLM\SOFTWARE\HIDMaestro\Controller<N>:
     ReportDescriptor (REG_BINARY)
     VendorId / ProductId / VersionNumber (REG_DWORD)
     ProductString (REG_SZ)
     InputReportByteLength (REG_DWORD)
     InputReportId (REG_BINARY, v2.0.0): report ID, 32-bit length, descriptor
     FeatureAnswers (REG_BINARY, v2.0.0): the compiled feature answer table
   HKLM\SOFTWARE\HIDMaestro\Identity\<token> (v2.0.0): the controller's index,
     which the driver reads before its first start
     [profile-specific extras]
     VendorId and ProductId are written first. DeviceInstanceId, which no
     driver read, is no longer written (v2.0.0)
6. Driver-store check (UMDF2 creates): a missing driver package deploys under
   the deploy lock, HIDMaestro.Admin\Deploy
7. Registration gate (v2.0.0), per devnode: rivals for the ParentIdPrefix and a
   prior life of the id removed, each removal under the PnP lock and its removal
   test, up to 30 s for Windows' pending installs (CMP_WaitNoPendingInstallEvents),
   then HIDMaestro.Admin\Pnp taken and one more look, up to three rounds
8. Device registration under the PnP lock, instance name = the identity token:
   plain HID profiles:    SetupDiCreateDeviceInfoW ROOT\HIDClass\<token>, ParentIdPrefix written before DIF_REGISTERDEVICE
   xinputhid profiles:    hmswd.exe create SWD\HIDMAESTRO_VID_*_PID_*&IG_00\<token>, ParentIdPrefix reconciled, then the restart
   non-xinputhid Xbox:    SetupDiCreateDeviceInfoW (main HID) + hmswd.exe create SWD\HIDMAESTRO\<token> (XUSB companion)
   the lock is let go after each registration, and the driver goes onto the new
   devnode alone with DiInstallDevice (v2.0.0)
9. WaitForHidChild       (10 s budget)
10. WaitForDeviceStarted  (5 s budget)
11. WaitForXInputSlotClaim (500 ms budget post-v1.3.2)
12. Per-instance UpperFilter writes (xinputhid-companion-XOR-tripwire profiles only)
13. Friendly-name application (best-effort, FinalizeNames runs the polled re-apply)
```

The driver wakes on PnP binding and reads its configuration from the registry written in step 5. The shared sections from step 4 are opened lazily by the driver (LocalService can't `CreateFileMapping(Global\)`, only `OpenFileMapping` what the SDK already created).

If any step fails after the lease, `TeardownController` is run as a best-effort cleanup, then the lease is released, so the transport index and identity go back to the machine only once the devices are gone, and the exception reaches the consumer. A create refused with `HMResourceInUseException`, because a v1.12.0 program took its index or a running program's device holds its ParentIdPrefix, has made no device yet. It releases only what it made, its sections, ledger holds and configuration key, and leaves the index's devices to the program that owns them. Since v2.0.0 a create also throws `InvalidOperationException` when its device's prior life is still there after its removal, when a gamepad or XUSB companion is not made, and when another program holds the PnP lock for ten minutes. See [Creates that now fail](../sdk/programs-side-by-side.md#creates-that-now-fail).

---

## Three wait gates

After `SwDeviceCreate` (or `SetupDiCreateDeviceInfoW`) returns success, the device isn't fully usable yet. Three wait gates ensure we only return to the consumer when downstream APIs can read the device.

### Gate 1: `WaitForHidChild` (10 s)

PnP creates the HID child node under the parent we just created. Polls `CM_Locate_DevNodeW` for the expected child instance ID. Typical: <100 ms warm. Slow machines (Atom Z8350): up to 2 s. Cap at 10 s.

If this times out, `SetupController` throws `InvalidOperationException` and best-effort cleanup runs. Cause: usually a corrupt INF or DriverStore inconsistency: run `HIDMaestroTest cleanup` (or `RemoveAllVirtualControllers(HMCleanupScope.Everything, false)`), then `InstallDriver`, to repair.

### Gate 2: `WaitForDeviceStarted` (5 s)

Polls the HID child's `DEVPKEY_Device_DevNodeStatus` for `DN_STARTED`. The driver isn't fully bound until this status flips. Typical: <50 ms warm. Cap at 5 s.

Without this gate, an immediate `SubmitState` after `CreateController` returns could land before the driver has opened the shared section: the seqno never increments and no input reaches the consumer.

Both gates end within one 25 ms poll when the driver sets its error word, or when the devnode reports a failed start (problem 10, 31, 37, 39 or 43) while Windows has no device installation pending, and the create fails naming the device and the code. As of v2.0.0 a failed start is held while an installation is pending: a full cleanup removes the driver package, Windows flags each record that named it for reinstall, and a software parent revived from that record reports problem 18 and then 10 until the install Windows queued restarts it. A gate whose time runs out fails the create on any problem the devnode shows, 28 for a queued install that failed and 18 for one Windows put off included. The XUSB companion gets three waits for its interface, with a restart after each one that ends without it.

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

Warm-start (driver already in DriverStore), measured before v2.0.0. The registration gate v2.0.0 adds before each devnode registration has not been timed on a live create:

| Profile group | Median | Worst | Notes |
|---------------|--------|-------|-------|
| **Plain HID** | ~200 ms | ~400 ms | One device, no companion, no XInput |
| **Non-xinputhid Xbox** | ~300 ms | ~700 ms | Two devices (main HID + XUSB companion). XInput slot-claim wait ≤500 ms post-v1.3.2 |
| **xinputhid Xbox** | ~250 ms | ~600 ms | One SwD device; xinputhid kernel filter binds. XInput slot-claim wait ≤500 ms post-v1.3.2 |

Multi-controller (sequential), measured before v2.0.0:

| Configuration | Total |
|---------------|-------|
| 1 plain HID | ~200 ms |
| 4 mixed (2 BT + 2 wired) | ~2.2-2.8 s |
| 6 mixed | ~3.5 s |

Cold-start (first run on machine, includes cert generation + signing + install): ~18 s for the install + create-1 step, measured before v2.0.0. Subsequent creates are warm-start cost.

---

## Per-step install breakdown

Visible in stdout when `HMContext.InstallDriver` runs. The figures were measured before v2.0.0:

| Step | Cost |
|------|------|
| Stage the embedded payload under `%ProgramFiles%\HIDMaestro\Staging` and verify each file's SHA-256 | not measured for v2.0.0 |
| Remove old packages (idempotent guard) | ~100 ms |
| Sign DLLs and INFs | ~130 ms |
| Generate `.cat` catalogs (largest single step, AV-sensitive) | ~840 ms |
| `pnputil /add-driver` | ~580 ms |
| **Total** | **~1.7 s** |

On corporate workstations with hundreds of devices in the PnP tree, total install can stretch to 5-20 s. HIDMaestro deliberately doesn't run `pnputil /scan-devices` (it's a no-op for our INFs and was the largest variable contributor in profiling).

---

## Self-healing on init

`HMContext.InstallDriver` sweeps **first thing**, before the deploy:

```csharp
public void InstallDriver()
{
    ThrowIfDisposed();
    HMBuildInfo.ThrowIfMissing(HMPayload.Driver);
    Internal.OwnerSweep.ReclaimDeadOwners();       // what exited programs left
    LastDriverInstall = Internal.DriverDeploy.Run();
}
```

Since v2.0.0 the sweep removes only the devices of programs that have exited, and the deploy installs the 2.0.0 driver over any older one, beside it when another program's devices hold it, and never downgrades a newer one. The first `InstallDriver` of a process also starts the once-per-process phantom cleanup on a background thread, unless a create or `RemoveAllVirtualControllers()` started it first. See [Programs Side by Side](../sdk/programs-side-by-side.md).

Without the sweep, when a prior process crashed or was force-killed (Dispose never ran), its virtual controllers + HIDMAESTRO PnP entries stay live and **remain bound to the old INF**. On the next launch:

- `DriverBuilder.FullDeploy` calls `pnputil /delete-driver /uninstall /force`.
- That fails with "One or more devices are presently installed using the specified INF" and leaves the old INF + stale DLL bytes in DriverStore.
- The subsequent `/add-driver` then sees package-already-present + "Needed repairing" and **restores the stale bytes from `pnputil`'s internal cache** rather than installing the fresh extracted binary.
- Net effect: every launch since the first one serves the stale driver forever, the v1.1.5 self-heal code never actually loads, input keeps hanging, and the only escape is manual `devcon` + TrustedInstaller `takeown` of the FileRepository subdirectory (which users do not have).

Running the sweep here FIRST removes the bound devices via `devcon` (returning "Removed on reboot" is sufficient: the INF becomes eligible for package deletion immediately), so the deploy's `/delete-driver` call actually succeeds and the fresh staged binary replaces the DriverStore contents.

The same removal is exposed publicly as `HMContext.RemoveAllVirtualControllers()` for consumers who want explicit defensive cleanup. It never touches a running program's controllers, the caller's own included. In normal operation, individual `HMController.Dispose()` is sufficient, and a program that exits normally without disposing has its devices removed as it exits.

---

## Dispose: `TeardownController` orchestration

`HMController.Dispose()` runs `Internal.DeviceOrchestrator.TeardownController(index, instanceId)`. Sequence:

```
1. Cancel the output reader thread, join (5 s timeout)
2. Dispose the output cancellation token
3. Notify the context (HMContext.OnControllerDisposing)
   A ROOT device whose driver serves protocol 5 (v2.0.0): capture its HID
   children, signal Global\HIDMaestroRemoveEvent<N>, and wait up to 2 s for
   the driver to fail its device, which Windows then removes by surprise
   removal
4. Per-archetype removal:
   plain HID:           DIF_REMOVE on the ROOT\ device
   non-xinputhid Xbox:  hmswd.exe remove (XUSB companion) + DIF_REMOVE (main HID)
   xinputhid Xbox:      hmswd.exe remove (SwD parent) + cascade waits
5. Removal test per device (v2.0.0): out of the tree, the record gone for an
   uninstall, then CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED within 2 s more.
   A HID child removed with its parent counts on the parent's notification.
   Each removal holds HIDMaestro.Admin\Pnp from its call through its test
6. Close shared memory mappings
7. Free per-controller registry path
8. Release the index back to the context's free pool
```

For SwD-enumerated devices, step 4 uses the SwD-first ordering (see below). For plain HID devices, `DIF_REMOVE` and the per-device removal test are sufficient.

Since v2.0.0 each removal holds the machine-wide PnP lock from its call through its removal test, so removals run one at a time, in a program and across programs, and no program of this release registers a device while another removes one. The test ends `Removed`, `GoneWithoutRemoved` (logged, never refused) or `NotGone` (the next registration of that id is refused). A parent removed with `SetupDiRemoveDevice` or `SwDeviceClose` gets its caller's budget, and every removal whose call finishes its work before it returns gets 2 s. See [Registrations and removals](../sdk/programs-side-by-side.md#registrations-and-removals).

### A removal no program can refuse (v2.0.0)

A queried removal asks every program that has the device open, and one refusal stops it. Steam holds the PlayStation pads' HID children open, and through v1.12.0 its refusal (`PNP_VetoOutstandingOpen`) stopped a `Dispose` halfway: the class installer had already deleted the HID child's driver and service, Windows marked the record as needing a reboot, and every later HID child on that path failed its start with problem code 19.

Since v2.0.0 a `Dispose` of a ROOT device first makes that query itself, as Safely Remove Hardware does (`CM_Query_And_Remove_SubTreeW`), before any record is touched. Every program that watches the device lets go: Windows' input stack for a keyboard or mouse, and a vendor's service that opens its own devices, such as Logitech's lighting service. A refusal changes nothing. Only when a program refuses does the `Dispose` ask the driver to fail the device, through the remove events of driver protocol 5 ([UMDF2 Driver Internals](umdf2-driver-internals.md#failing-the-device-on-request-v200-protocol-5)). Windows then removes the device and its HID children by surprise removal, which asks no one, and the removals that follow find the children gone. A program that keeps reading the child sees its read fail, as after an unplug. Against one that never reads, Windows waits about 5 s before it refuses the query, the `Dispose` returns in about 7.5 s with no record left, and Windows finishes the removal when that program closes its handle. A watcher lets go later after a surprise removal than after a query, and a create of the same identity in that moment would get the old devnode back, which is why the query comes first. A driver older than protocol 5 does not answer, and the removal is queried as before. Software devices under `SWD\`, the xinputhid parents, keep the queried removal, and a USB/IP persona is not asked.

A create at an identity whose previous device a program still holds open gets that devnode back, marked for removal and never started (`DN_WILL_BE_REMOVED`). The create stops waiting on that flag and fails within about 2 s, saying that a program still holds the device, and a create after the program lets go starts normally.

A ROOT create also reads the HID child records under its identity's prefix. When one is out of the tree, names HIDMaestro and has no driver, as the refusal above left records through v1.12.0, the parent takes the next prefix of the identity, `1&hash&1` to `1&hash&3`, the counter Windows raises when it mints one, and its HID child starts on a path with no such record. The rival guard and the ParentIdPrefix written to the parent use the prefix taken, and sweeps count every identity's alternates as HIDMaestro's.

---

## SwD-first removal ordering (v1.3.1)

Two of the three architecture groups own a SwDevice-enumerated parent: Xbox 360 Wired (XUSB companion is SwD) and Xbox Series BT (main HID is SwD). SwDevice lifetimes are anchored to the `HSWDEVICE` handle, **not** the PnP devnode: children of a SwD parent cannot fully unwind their query-remove cascade until the parent's handle drops its kernel refcount.

### Pre-v1.3.1: HID-children-first (broken)

```
1. DIF_REMOVE on every HID child first
2. WaitForDeviceRemoval per child (2,000 ms timeout each: always times out
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
   (usually zero: the SwD parent's release fires its children's removal in one cascade)

Net cost, measured at v1.3.1:
          ~135 ms for Xbox 360 Wired
          ~500 ms for Xbox Series BT
```

`CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED` says the cascade has propagated, where a returned close says only that the handle closed. Critical for callers that immediately follow with a recreate (live profile switch: the new controller's `SetupController` would race the old one's cleanup if we returned too early). Through v1.12.0 the wait also ended as soon as a locate no longer found the devnode, without the notification. Since v2.0.0 the removal test waits for it, up to 2 s past the devnode's leaving, and logs a removal whose notification never comes.

A second optimization in the same change: when a HIDMAESTRO sweep walks registry entries that exist only as `PHANTOM` (registry residue from prior sessions, no live devnode), skip the `hmswd.exe` `SwDeviceCreate`-reconnect roundtrip entirely. Saves ~50-75 ms per stale entry and prevents creep across same-process recreation cycles.

---

## Per-archetype dispose latency

Measured at v1.3.1, before v2.0.0. The 2.0.0 release notes compare 2.0.0's create and dispose times with 1.12.0's.

| Profile group | Pre-v1.3.1 | Post-v1.3.1 |
|---------------|-----------|------------|
| **Plain HID** | ~80 ms | ~80 ms |
| **Non-xinputhid Xbox** | ~5,700 ms | **~135 ms** |
| **xinputhid Xbox** | ~11,000 ms | **~500 ms** |

The plain HID path was already fast pre-v1.3.1 because there's no SwD parent. The two SwD-bearing groups got the dramatic improvement.

Round-trip (dispose + recreate) latencies, measured before v2.0.0:

| Profile pair | Latency |
|--------------|---------|
| **DualSense ↔ DualShock 4** | ~280 ms |
| **DualSense ↔ Xbox 360 Wired** | ~350-850 ms |
| **DualSense ↔ Xbox Series BT** | ~650-1100 ms |
| **Xbox Series BT ↔ Xbox 360 Wired** | ~750-1300 ms |

Down from ~6.4 s and ~11 s respectively pre-v1.3.1. PadForge users reported create and swap as instantaneous on the v1.3.1 path, before v2.0.0.

---

## Batch teardown: `DisposeControllersInParallel`

```csharp
public void DisposeControllersInParallel(
    IEnumerable<HMController> controllers,
    Action<HMController, long>? perControllerCallback = null);
```

Disposes a set of controllers from parallel threads, with the per-controller HID orphan sweep **suppressed** and run **once at the end** instead of per-controller. Since v2.0.0 every devnode removal holds the machine-wide PnP lock, so the removals themselves run one after another, and the batch takes about the sum of the controllers' removals, where it took about the longest one. The time the callback reports for each controller includes the time its removals waited behind the others'.

```csharp
ctx.DisposeControllersInParallel(
    new[] { ctrl0, ctrl1, ctrl2, ctrl3 },
    perControllerCallback: (c, ms) => Logger.Info($"  {c.Profile.Id}: {ms} ms"));
```

Internal sequence:

```
1. Set _batchDisposing = true
2. Parallel.ForEach: each controller's Dispose runs on its own thread,
   and their removals take HIDMaestro.Admin\Pnp one at a time
3. Set _batchDisposing = false
4. RemoveOrphanHidChildrenBatch: single sweep
```

The per-controller `Dispose` checks `_batchDisposing`; when set, it skips the per-controller orphan sweep that would otherwise run inside each `TeardownController`.

A `perControllerCallback` that throws stops nothing (v2.0.0). Every controller is disposed, the orphan sweep runs, and the exceptions come out afterward in one `AggregateException`, with one controller as with many. Through v1.12.0 a set of two or more left the controllers not yet started undisposed once a callback threw, and with one controller the exception came out bare.

Before v2.0.0, with the removals overlapping, 4-6 mixed controllers took 1.5-4 s end to end. No figure for v2.0.0 exists.

`HMContext.Dispose()` itself uses an equivalent path internally: consumers don't need to call `DisposeControllersInParallel` explicitly unless they want the per-controller wall-clock telemetry.

### Single-element / empty input

Single-element inputs degrade to a plain serial dispose on the calling thread. Empty inputs are no-ops. The implementation:

```csharp
if (arr.Length == 0) return;
if (arr.Length == 1)
{
    var sw = Stopwatch.StartNew();
    try { arr[0].Dispose(); } catch { }
    // Wrapped as the set path wraps it.
    try { perControllerCallback?.Invoke(arr[0], sw.ElapsedMilliseconds); }
    catch (Exception ex) { throw new AggregateException(ex); }
    return;
}
// ... two or more: each Dispose on its own thread, removals one at a time
```

---

## Live profile switch

Switching a slot's profile mid-session (`HMController.Dispose()` then `HMContext.CreateControllerAt(index, newProfile)`) is **synchronous** by design. Slot-allocation determinism requires the old devnode fully gone before the new one is created: otherwise the new device would race the old one's removal and might land in a slot the old one hasn't released yet.

Round-trip latencies are the dispose + create numbers above. PadForge's user-perceived "switch slot 1 from DualSense to Xbox 360 Wired" was ~850 ms, measured before v2.0.0.

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

ctrl1.Dispose();    // dispose middle one: others stay live, slots renumber
// ctrl0 still works at index 0
// ctrl2 still works at index 2
// indices 1 is free; next CreateController fills it
```

Slot indices don't compact automatically. If you want sparse-to-dense compaction (after disposing index 1, want index 2 to become index 1), you have to dispose index 2 and recreate at index 1. The XInput user-index allocator handles this on its side independently: an XInput slot-N controller becoming slot-1 means a brief disconnect/reconnect at the XInput level for slot 2 consumers.

PadForge does this compaction explicitly via the "bubble-up cascade" in its Step 5 InputManager: see PadForge's wiki for the consumer-side implementation. The SDK doesn't enforce a particular scheme.

---

## Force-kill recovery

If the consumer process crashes without disposing controllers, the next sweep of any program on the machine removes them: the sweep at the start of `InstallDriver`, the one a program runs on its first create, or `RemoveAllVirtualControllers()`. The crashed program's ownership claim died with it, so its owner record proves it is gone. The sweep holds each dead group's index and identity claims until its devices, and the orphaned HID children it removes after them, are out of the device tree, so a restarted program cannot create over a device on its way out. A group whose claims another program holds is skipped, and a group the sweep cannot confirm gone keeps its configuration and its dead record for the next sweep. Typically:

```csharp
// Process A creates 3 controllers, then crashes
// Process B starts:
using var ctx = new HMContext();   // constructor doesn't sweep yet
ctx.InstallDriver();   // ← the sweep runs here and removes process A's devices
ctrl0 = ctx.CreateController(...);   // fresh state
```

A program that exits normally without disposing has its devices removed by the SDK's own exit handler, which waits at most 10 seconds for the phantom cleanup and a create in flight, then removes them to the end, as `Dispose` does. When that wait runs out, a device does not leave, or another program holds the PnP lock past what is left of the 10 seconds, the devices stay until the next sweep, as a crashed program's do. A keyless program restarted after a crash gets its old transport index, and so its old identity, back only when no other program holds that index, and while a program built on v1.12.0 runs, only when the index is 64 or more.

The regression battery's S12_ForceKill_Recovery and S17_ForceKill_MidCascade scenarios validate this end-to-end. See [Testing and Verification](testing-and-verification.md).

### Composite personas are swept by a separate route (v1.4.5)

The sweep walks the ROOT and SWD enumerators removing devices whose hardware IDs carry the `HIDMAESTRO` token. A [composite persona](../sdk/usb-audio-composite.md) carries no such token by design, because the USB Audio Class driver binds against an exact Sony identity, so the enumerator walk cannot reach one. Before v1.4.5 an orphaned persona survived the self-heal: a USB DualSense stayed enumerated with nothing left running to feed it.

`RemoveAllVirtualControllers` detaches personas from the emulated host controller first, then walks the enumerators. Two consequences worth knowing:

- As of v2.0.0 it detaches only the personas of programs that have exited, matched by the server port each program's owner record names, and any import on the SDK's port ranges whose server no longer listens, which covers a v1.12.0 program that has exited. `RemoveAllVirtualControllers(HMCleanupScope.Everything, preserveInstall)` detaches every one, another live program's included.
- The detach runs before the walk, and before it detaches anything it disposes this process's own emulated devices to join their input pump threads. Those pumps map the shared input sections directly and take no part in the stop-event drain, so a pump still running when the sweep unmaps its section is an access violation on a background thread, not a leak. Consumers calling the public API get this ordering for free.

**Sweeping with a live controller is safe as of v1.4.6.** Until then it was not: the sweep released every shared-memory mapping the process held without stopping a live `HMController`, whose output poll loop is canceled only by `Dispose`. The loop kept reading a view that had just been unmapped and the process died with `0xC0000005` on a thread unrelated to the call that was made ([#45](https://github.com/hifihedgehog/HIDMaestro/issues/45)).

Poll threads now register with the shared-memory layer, and every unmap path cancels and joins them first, so this is handled inside the SDK rather than being a rule callers have to remember. Disposing controllers before a sweep is still the tidier shape, and on older versions it is the only safe one.

For deliberate cleanup (e.g. uninstalling HIDMaestro entirely), use:

```cmd
HIDMaestroTest.exe cleanup
```

Which calls `RemoveAllVirtualControllers(HMCleanupScope.Everything, preserveInstall: false)`: every HIDMaestro device and import on the machine, then the driver packages. Don't reach for raw `pnputil /remove-device` or `devcon`: the cleanup command is the right interface.

---

## Anti-pattern: `pnputil /delete-driver /uninstall /force` on the active driver

**Don't.** Leaves devices in Code 14 ("restart required"). Always:

1. `HIDMaestroTest cleanup` (or `HMContext.RemoveAllVirtualControllers(HMCleanupScope.Everything, false)`) FIRST to evict the devices.
2. Plain `pnputil /delete-driver` (no `/uninstall`) if a package delete is even needed.

`InstallDriver` is **idempotent across version bumps**: manual uninstall before reinstall is almost never the right move.

The cleanup command does the right thing because:

- It walks every HIDMaestro PnP entry by enumerator name (`SWD\HIDMAESTRO*`, `ROOT\VID_*&PID_*&IG_00`).
- It calls `hmswd.exe remove` for SWD entries (the only documented teardown for `SWDeviceLifetimeParentPresent`).
- It calls `DIF_REMOVE` for ROOT entries.
- After the sweep, if a driver-package delete is desired, it runs `pnputil /delete-driver` (no force flags).

---

## See also

- [SDK Reference](../sdk/sdk-reference.md): the public API that drives all of this.
- [SwDevice and PnP](swdevice-and-pnp.md): the per-controller PnP machinery.
- [Multi-Controller](multi-controller.md): multi-controller create / dispose patterns.
- [Driver Install and Signing](driver-install-and-signing.md): the InstallDriver step.
- [Testing and Verification](testing-and-verification.md): the regression battery that validates this end-to-end.
- [Troubleshooting](../troubleshooting.md): lifecycle-related symptoms and fixes.
