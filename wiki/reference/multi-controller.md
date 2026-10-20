# Multi-Controller

Up to N virtual controllers running simultaneously. Verified working with 6 mixed (2× Xbox Series BT + 2× Xbox 360 Wired + 2× DualSense) on a Ryzen 9955HX3D dev box and on an Intel Atom Z8350 fixture. The SDK supports unlimited; downstream APIs cap variously.

This page covers the mechanics that make multi-controller work: slots and transport indices, the friendly-name re-application race, per-instance WUDFHost, ordering across APIs, and what each downstream consumer caps at.

For per-controller PnP machinery, see [SwDevice and PnP](swdevice-and-pnp.md). For the underlying driver design, see [UMDF2 Driver Internals](umdf2-driver-internals.md).

---

## SDK-side: slots and transport indices

`CreateController` takes the lowest free slot in its context, first-fit with no upper bound. Slots are dense in normal operation: 0, 1, 2, 3 for four sequential creates, and after the controller in slot 1 is disposed, the next create lands in slot 1. For deterministic slots, use `CreateControllerAt(index, profile)`, which keeps its contract of one controller per slot per context.

As of v2.0.0 a controller also holds a machine-wide transport index, `HMController.TransportIndex`. It is the slot number when no other program uses that index, and otherwise the lowest free one, so a program running alone gets the numbers every earlier release gave it, except that a keyed create whose identity a dead program's device still carries lands on that device's index, and an index whose names another program took first is skipped. While a program built on v1.12.0 runs, every create starts at index 64, slot 0 on 64 and slot 1 on 65, and a keyless controller's paths and container id, and every controller's HID serial and MAC bytes, move with the index. See [Programs Side by Side](../sdk/programs-side-by-side.md#transport-index). Through v1.12.0 the slot was the only index, and two programs that each created a first controller both got index 0 and wrote each other's sections and keys. Two contexts in one process collided the same way.

The transport index drives:

- The shared memory section names (`Global\HIDMaestroInput<N>`, etc.), listed by `HMController.SectionNames`.
- The per-instance registry path (`HKLM\SOFTWARE\HIDMaestro\Controller<N>`).
- The `ControllerIndex` the driver reads from its device key, and the serial number string (`HM-CTL-<N>` zero-padded to 4 digits).
- The default identity of a controller created without an identity key, and with it the ContainerID GUID's last 16 bits (`{48494430-...-4F00<idx:X4>}`).

The devnode instance names and the ContainerID derive from the identity key when the caller passes one, and from the transport index otherwise, so a controller created with a key comes back at the same paths across processes. A keyless controller can land on another transport index, and so another identity, when another program holds its slot's index. See [SwDevice and PnP](swdevice-and-pnp.md#stable-device-identity) and [Programs Side by Side](../sdk/programs-side-by-side.md#transport-index).

---

## Friendly name re-application

There's a Windows PnP race where the **first** controller's friendly name gets overwritten by the **second** controller's driver-bind activity. Symptom: 4 controllers all show "Game Controller" instead of their per-profile names like "Controller (XBOX 360 For Windows)" / "DualSense Wireless Controller".

### Fix: `HMContext.FinalizeNames`

Call **once after creating ALL controllers**:

```csharp
using var ctrl0 = ctx.CreateController(profile1);
using var ctrl1 = ctx.CreateController(profile2);
using var ctrl2 = ctx.CreateController(profile3);
using var ctrl3 = ctx.CreateController(profile4);
ctx.FinalizeNames();   // re-apply friendly names after PnP settles
```

The method polls each HID child for `DN_STARTED` (driver fully bound) before re-applying. On fast machines exits in <100 ms; on slow machines adapts up to 5 s rather than failing from an insufficient fixed sleep.

The proven pre-SDK test app (~v0.x) called this as "Phase 1.5: Finalizing device names". The functionality moved into the SDK; consumers should call it as their final create step.

---

## Per-instance WUDFHost

Both INFs (`hidmaestro.inf` and `hidmaestro_xusb.inf`) carry:

```
[..._Install.NT.Wdf]
UmdfHostProcessSharing = ProcessSharingDisabled
```

Each device instance gets its own `WUDFHost.exe` process (~8 MB RSS, ~10 threads). With 6 controllers running, expect 6-12 `WUDFHost.exe` processes: one per main HID instance plus one per XUSB companion (companions only exist for non-xinputhid Xbox profiles).

### Why per-instance hosts

Default (`ProcessSharingEnabled`) funnels every UMDF2 instance into one shared WUDFHost. At 6 controllers, the shared host accumulates 9+ minutes of CPU time vs ~2 seconds per per-instance host. Empirically traced in 2026-04 ([`docs/investigations/issue3-dual-xinputhid-saturation-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/issue3-dual-xinputhid-saturation-2026-04)).

Root cause: contention between writer threads (HIDMaestro virtual instances) and concurrent `XInputGetState` reader threads when 2+ virtuals coexist with a real xinputhid device in the same host. Per-instance hosts run their I/O paths in parallel, idle CPU stays near zero, and peak throughput scales with controller count.

### Detecting regression

If a future change accidentally drops the `ProcessSharingDisabled` line, the symptom is exponential CPU saturation under multi-controller load. Detection:

```powershell
Get-Process WUDFHost | Measure-Object -Property Count
# Expected: N main HID instances + M XUSB companion instances
# Regression: 1-2 hosts regardless of controller count
```

---

## XInput's 4-slot cap

`xinput1_4.dll` hard-caps at 4 slots regardless of how many Xbox-family virtuals exist. With 6 Xbox-family controllers, only 4 are visible through `XInputGetState`. Slots 0..3 fill in creation order.

**Non-Xbox profiles don't claim XInput slots.** A 6-controller config of (4× Xbox Series BT + 2× DualSense) sees 4 XInput slots (the 4 Xbox controllers) plus 2 controllers visible through DI / HIDAPI / WGI / Browser. Non-Xbox profiles can run beyond 4 simultaneously through every other API.

If your consumer needs more than 4 XInput-visible controllers, that's a Microsoft-side limit; no user-mode workaround.

---

## Browser cap

Chromium's gamepad API caps at 4 connected gamepads on Win10/11. With 6 mixed controllers, browser sees 4 in a deterministic order (alphabetical by GUID, not by creation order: see [Cross-API Coverage](cross-api-coverage.md)).

Restart Chromium to clear stale slot caching when adding/removing controllers during a session.

---

## SDL3 / DirectInput / HIDAPI: no cap

These APIs see every controller HIDMaestro creates. 6 mixed = 6 visible. PadForge's bench tests have run 8+ controllers simultaneously through DI/HIDAPI without issue.

The SDK side scales linearly: each additional controller adds one shared memory section (~17 KB), one WUDFHost process (~8 MB), and proportional cost to `SetupController` / `Dispose` / `FinalizeNames`. As of v2.0.0 a create also takes its ownership claims and a census of the owner records and present devices, and a dispose releases them.

---

## Several programs

Controllers from several programs that embed HIDMaestro share the XInput, Browser and ordering behavior above, since Windows sees devices, not programs. Each program's controllers keep their own transport indices, identities and sections, and a program's cleanup removes only what exited programs left. The XInput cap of 4 slots above counts every Xbox-family controller on the machine, whichever program created it. See [Programs Side by Side](../sdk/programs-side-by-side.md).

---

## Ordering across consumers

Game enumeration anchors to **creation order** across most APIs:

| API | Order |
|-----|-------|
| **XInput** | Sequential user-index 0, 1, 2, 3 in creation order. Slot allocator skips dead slots. |
| **DirectInput** | `IDirectInput8::EnumDevices` returns in Windows-internal order (typically creation order). |
| **HIDAPI** | `hid_enumerate` returns in PnP enumeration order (creation order). |
| **Browser Gamepad (Chromium)** | **Alphabetical / lexical GUID ordering.** Match to creation order is coincidental. |
| **WGI** | Creation order via `Gamepad::Gamepads`. |
| **joy.cpl** | Creation order. |
| **SDL3** | Creation order via `SDL_GetJoysticks`. |

For UI flows where the user expects "Controller 1 = first one I created", every API except Chromium gets it right. Chromium reorders: the consumer needs to sort or remap if browser ordering matters.

### Don't parallelize `CreateController`

A consumer might be tempted to parallelize multi-controller creation:

```csharp
// DON'T DO THIS
await Task.WhenAll(profiles.Select(p => Task.Run(() => ctx.CreateController(p))));
```

The creation order **anchors** every downstream API. Parallel creates produce non-deterministic order across XInput, WGI, joy.cpl, browser, RawInput, SDL3 simultaneously: the user-visible game enumeration becomes a coin flip per launch.

**Always create sequentially.** Multi-controller perf comes from making each step faster (the v1.3.x latency improvements), not from parallelism. Verified at the SDK level: `CreateController` takes the context lock for index allocation but otherwise serializes through `SetupController`'s registry-then-PnP-create path.

---

## `DisposeControllersInParallel`

Disposal can run from parallel threads because the user-visible ordering is already broken when controllers are gone. Since v2.0.0 the removals themselves run one at a time, because each devnode removal holds the machine-wide PnP lock:

```csharp
ctx.DisposeControllersInParallel(
    new[] { ctrl0, ctrl1, ctrl2 },
    perControllerCallback: (c, ms) => Logger.Info($"  {c.Profile.Id} disposed in {ms} ms"));
```

The per-controller HID orphan sweep is suppressed during the batch and run **once at the end** instead of per-controller. A batch of several controllers takes about the sum of their removals, where before v2.0.0 it took about the longest one, so what the batch path saves is the repeated orphan sweep.

Before v2.0.0, with the removals overlapping, 4-6 mixed controllers took 1.5-4 s end to end. No figure for v2.0.0 exists. See [Lifecycle and Teardown](lifecycle-and-teardown.md) and [Registrations and removals](../sdk/programs-side-by-side.md#registrations-and-removals).

---

## Per-controller serial number for SDL3 disambiguation

Two virtual DualSense with the same VID:PID:ProductString get bucketed by `hid_enumerate` into a single device unless they have different serial numbers. HIDMaestro generates a per-instance serial:

```c
// Driver-side, in InitInstancePaths
WCHAR serial[64];
RtlCopyMemory(serial, L"HM-CTL-", sizeof(L"HM-CTL-") - sizeof(WCHAR));
AppendUlongDecimal(serial, ControllerIndex, /* zero-pad to 4 */);
// e.g. serial = "HM-CTL-0001"
```

Returned by `IOCTL_HID_GET_STRING / HID_STRING_ID_ISERIALNUMBER`. SDL3 / HIDAPI use this string as a per-device disambiguator; identical VID:PID/ProductString controllers get distinct GUIDs derived from the serial.

The exact format (`HM-CTL-<index>`) isn't part of any contract: consumers are expected to treat the string as opaque. Don't parse the index out and use it for ordering; use creation order instead.

---

## Verified configurations

The regression battery (`regression_battery.ps1`) exercises multi-controller configurations:

| Scenario | Configuration | What it tests |
|----------|---------------|---------------|
| **S07_Multi_CreateAll_Idle** | 4 mixed, idle, quit | Baseline multi-slot teardown via clean process exit |
| **S08_Multi_SwapOneSlot** | 4 wired, swap slot 1 | Single-slot swap doesn't leak across siblings |
| **S09_Multi_SwapAllSlots** | 4 wired, swap each slot to a different family | Concurrent live-swap of every slot |
| **S10_Multi_RemoveOne** | 3 mixed, `remove 1` | `HMController.Dispose` without replacement leaves no residue |
| **S11_Multi_MultipleXinputhid** | 3 different xinputhid profiles + swap | xinputhid INF-match handling under multiple concurrent xinputhid binds |
| **S15_Multi_SixControllers** | 6 mixed (beyond XInput's 4) + swap slot 5 | Slot-allocator skip + ContainerID encoding for high indices. The HM "6-controller baseline" use case. |
| **S19_Multi_RapidMultiSlotSwap** | 4 controllers, swap each slot's profile back-to-back, no settle | Closest stdin proxy for PadForge's `ApplyAscendingIndexPreemption` async-dispose path |
| **S20_Multi_HeterogeneousCascade** | 4 controllers, every family in one batch, then quit | `DisposeControllersInParallel` correctness with all four families simultaneously |
| **S23_Multi_CustomInMix** | 5 mixed: 360 + Series BT + DualSense + Switch Pro + Custom + swap custom slot | Real PadForge-shape consumer config |
| **S71_Coexistence** | Programs that embed HIDMaestro as separate processes, with peers built on v1.12.0 and v1.11.0 | Transport indices, identity claims, sweeps and deploys across programs, with an XInput slot, WGI and Raw Input entries left alone |

See [Testing and Verification](testing-and-verification.md) for the harness mechanics.

---

## Performance at scale

Measured before v2.0.0. The registration gate v2.0.0 adds before each devnode registration has not been timed on a live create.

| Configuration | Cold start (1st run) | Warm start (subsequent) | Idle CPU |
|---------------|---------------------|------------------------|----------|
| **1 plain HID** | ~18 s (cert + sign + install + create) | ~200 ms | ~0.04% |
| **1 Xbox 360 Wired** | ~18 s | ~200-700 ms (slot-claim wait dominates worst case) | ~0.04% |
| **1 Xbox Series BT** | ~18 s | ~150-600 ms | ~0.04% |
| **4 mixed (2 BT + 2 wired)** | ~20 s | ~2.2-2.8 s | ~0.16% (4× ~0.04%) |
| **6 mixed (sequential creates)** | ~22 s | ~3.5 s | ~0.24% |

Cold-start cost is dominated by certificate generation, signing, and `pnputil /add-driver`. After the first run the driver is in the DriverStore and subsequent creates skip the install entirely.

Idle CPU is the **per-controller WUDFHost** measurement. Each per-instance host has its own thread pool sleeping on the input event; it spends most of the time in kernel `WaitForMultipleObjects`. Linear scaling means 6 controllers consume ~0.24% of one CPU core at idle, well within the noise floor.

---

## Atom Z8350 fixture (slow-hardware validation)

The regression battery also runs on an Intel Atom Z8350 (4 cores @ 1.44 GHz, 4 GB RAM, Win10 IoT LTSC 19044). Slow-hardware target for validating the event-driven harness without time-based settles.

It runs the full battery at `HIDMAESTRO_TIMEOUT_SCALE=2`. Its last full run, the 57-scenario v1.7.3 battery, passed 57/57, as on Ryzen-class hardware. The slow-hardware result is the reason the harness is pure ACK-driven instead of fixed-sleep timed: a fixed sleep that's "enough" on a fast machine isn't enough on Atom. ACK-driven waits scale with the machine.

See [Testing and Verification](testing-and-verification.md).

---

## See also

- [Architecture Overview](architecture-overview.md): per-controller WUDFHost in the full stack diagram.
- [SwDevice and PnP](swdevice-and-pnp.md): per-controller indices, ContainerIDs, instance suffixes.
- [Lifecycle and Teardown](lifecycle-and-teardown.md): create / dispose mechanics that scale.
- [Cross-API Coverage](cross-api-coverage.md): per-API ordering and slot caps.
- [Testing and Verification](testing-and-verification.md): the multi-controller regression scenarios.
