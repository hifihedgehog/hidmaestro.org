# SwDevice and PnP

The PnP machinery behind every HIDMaestro virtual controller. This page covers the SWD migration story (why HIDMaestro can't use `SetupDiCreateDeviceInfoW` for everything), the slot-1-skip ContainerID fix, the session-unique instance-ID suffix that bypasses Windows' sticky reuse-fast-path, and why `hmswd.exe` exists as a separate native executable.

If you have skimmed the README's "Techniques" section, this is the long-form. The README compresses years of debugging into ~10 paragraphs; this page expands them with the empirical evidence and the alternative paths that didn't work.

For the SDK orchestration that calls into all of this, see [Lifecycle and Teardown](lifecycle-and-teardown.md). For the companion device this enables, see [XUSB Companion](xusb-companion.md).

---

## The two device-creation APIs

Windows offers two paths to create a software-only device node:

| API | Header | Constraint | Used by |
|-----|--------|-----------|---------|
| `SetupDiCreateDeviceInfoW` | `SetupAPI.h` | Cannot specify `pContainerId`; assigned the null-sentinel automatically. | Plain HID profiles (DualSense, etc.) |
| `SwDeviceCreate` | `swdevice.h` (via `cfgmgr32.dll`) | Can specify `pContainerId`. Modern device-creation API (Win10+). | xinputhid Xbox profiles, XUSB companion |

Search Microsoft Learn for the exact symbol name to find the contract docs for either API.

`SetupDiCreateDeviceInfoW` is older and well-documented but doesn't expose a way to set the `ContainerID`. Windows assigns the null-sentinel `{00000000-0000-0000-FFFF-FFFFFFFFFFFF}` to ROOT-enumerated devices created via this API. ContainerID semantics are documented under `DEVPKEY_Device_ContainerId` on Microsoft Learn.

`SwDeviceCreate` lets the creator specify an explicit `pContainerId`. **This is the linchpin of the slot-1-skip fix.** And it's why HIDMaestro has to call the API at all rather than staying on the simpler SetupAPI path.

---

## The slot-1-skip bug

Pre-SWD-migration, HIDMaestro created every devnode via `SetupDiCreateDeviceInfoW` under `ROOT\`. With the null-sentinel ContainerID, XInput exhibited a bug: virtual Xbox controllers were assigned to slot 1, slot 2, slot 3, but **slot 0 was empty**. Multiple consumers (PadForge users, the regression battery) consistently reported:

```
Slot 0: NOT CONNECTED
Slot 1: HM-CTL-0001 (Xbox 360 Wired)
Slot 2: NOT CONNECTED
Slot 3: NOT CONNECTED
```

Or in 4-controller mixed configurations, the lowest user-index assigned was 1, not 0. With 4 Xbox-family virtuals you'd see slots 1, 2, 3 (and one missing &mdash; XInput's 4-slot cap is hit by 1+2+3+4, but if the allocator skips 0, you only get 3 working).

### Ghidra trace

The behavior comes from `xinput1_4.dll`'s slot allocator. Decomp (Win11 26200):

```c
// FUN_18000de2c — tests for slot-1-skip eligibility
ULONG FUN_18000de2c(DEVICE_INFO *dev) {
    if (memcmp(&dev->ContainerId, &NULL_SENTINEL_GUID, 16) == 0) return 1;
    if (StringContains(dev->HardwareIds, "XINPUT_EMBEDDED_DEVICE")) return 1;
    return 0;
}

// FUN_18000c728 at 0x18000C8AE — sets bit 2 on the device struct
result = FUN_18000de2c(dev);
test al, al
jne     L_set_bit_2
jmp     L_normal
L_set_bit_2:
or      dword ptr [rbx], 4    // ← bit 2 set on bit-2 path

// FUN_18000f85c — fallback slot allocator
if (FeatureManagerFlag_0x39EB83D && (dev->Flags & 4)) {
    // bit-2 device + feature flag on → SKIP iter 0
    iter = 1;
}

// FUN_18000f178 — promotes first bit-2 slot to "primary"
// FUN_18000f08c — query-time swap surfaces empty slot 1 to consumers
```

The chain: null-sentinel ContainerID &rarr; bit 2 set on the device struct &rarr; slot allocator skips iter 0 (only when Feature Manager flag `0x39EB83D` is on, which it is on Win11 26200) &rarr; first bit-2 slot becomes "primary" &rarr; query-time swap surfaces an empty slot 1 to consumers.

Setting `XINPUT_EMBEDDED_DEVICE` in HardwareIDs would also trigger this; the null-sentinel ContainerID is one of two sufficient conditions.

### The fix

Use `SwDeviceCreate` with an explicit non-sentinel `pContainerId`. We pass:

```
{48494430-4D41-4553-5452-4F0000000000}    // base
                              ^^^^ ← 16-bit controller index appended
```

Decoded as ASCII: `H I D M A E S T R O \0 \0` + a 16-bit big-endian index. So controller 0 gets `{48494430-4D41-4553-5452-4F0000000000}`, controller 1 gets `{48494430-4D41-4553-5452-4F0000000001}`, etc.

`FUN_18000de2c` returns 0 (not the null sentinel; no `XINPUT_EMBEDDED_DEVICE` in HardwareIDs), bit 2 stays clear, the slot allocator fills 0..3 contiguously. Verified empirically across 5 back-to-back runs.

---

## What moved to SWD vs what stayed

Not every profile needs SWD. The architecture group determines:

| Group | Main HID enumerator | XUSB companion enumerator |
|-------|--------------------|--------------------------|
| **Plain HID** | `ROOT\VID_xxxx&PID_yyyy&IG_00\NNNN` (SetupAPI) | (no companion) |
| **Non-xinputhid Xbox** | `ROOT\VID_045E&PID_*&IG_00\NNNN` (SetupAPI) | `SWD\HIDMAESTRO\<sid>_NNNN` (SwDevice) |
| **xinputhid Xbox** | `SWD\HIDMAESTRO_VID_045E_PID_*&IG_00\<sid>_NNNN` (SwDevice) | (no companion) |

**Plain HID** profiles (DualSense, wheels, HOTAS, etc.) don't go through XInput, so the slot-1-skip bug doesn't apply &mdash; staying on the simpler SetupAPI path is fine.

**Non-xinputhid Xbox** profiles do go through XInput, but only via the XUSB **companion**. The main HID device on the ROOT\ path doesn't carry the XInput device interface; the companion does. So only the companion needs SWD's explicit ContainerID. The main HID stays on SetupAPI.

**xinputhid Xbox** profiles bind `xinputhid.sys` as a kernel filter on the HID child, and `xinputhid` is what publishes the XUSB interface. There's no separate companion; the main HID device must itself be SWD-enumerated with a real ContainerID so its XInput dispatch lands in slot 0.

---

## Why the underscore between VID and PID

Look closely at the xinputhid Xbox enumerator name:

```
SWD\HIDMAESTRO_VID_045E_PID_0B13&IG_00\<sid>_NNNN
              ^^^^                ^
              underscore between VID and PID, NOT &
```

The conventional Windows hardware-ID format is `VID_xxxx&PID_yyyy` with `&`. We use `_PID_` instead.

Reason: any SWD enumerator name matching the substring `VID_*&PID_*&IG_*` triggers a Windows PnP edge case where the registry record exists but the devnode never enumerates as a live PnP object. Empirically observed on Win11 26200; not documented anywhere; presumably a heuristic in PnP that recognizes that pattern as "hardware ID-shaped" and treats it specially.

Replacing `&` with `_` between VID and PID avoids the heuristic. The `&IG_00` suffix is **preserved** because:

- The HID child inherits its parent's enumerator name as the first segment of its instance path.
- HIDAPI / SDL3 / Chromium all blocklist `&IG_` substrings to avoid duplicating XInput-claimed devices &mdash; we want the suffix in the instance path so those skip the device.

So we get the best of both: PnP enumerates the SWD parent (no `&` in `VID_*&PID_*`), and the HID-class libraries skip the inherited `&IG_00` substring on the children.

---

## The session-unique instance-ID suffix

The SWD migration immediately exposed a second Windows PnP behavior on Win11 26200: after `SwDeviceClose` finalizes a devnode with `SWDeviceLifetimeParentPresent`, the kernel retains a sticky per-`(enumerator + instanceId + ContainerId)` record. A subsequent `SwDeviceCreate` with the **identical** tuple takes a "reuse-existing" fast path that creates an empty registry shell &mdash; no Service or Driver bound, no device-interface class registered &mdash; and reports `S_OK` synchronously to the caller.

The sticky state survives across processes and across same-boot uninstall + reinstall of the INF.

### Symptoms before the fix

- First run after a fresh boot: fast (~2 s for 4 mixed), all APIs pass.
- Every **subsequent** run on the same boot: `SwDeviceCreate` returns `S_OK` synchronously while the devnode never materializes.
- `CM_Locate_DevNodeW` returned `CR_NO_SUCH_DEVNODE` the entire time the SDK waited.
- The creation callback timed out at 30 s with `E_FAIL`.
- Phase-1 creation ballooned from ~2 s to **65 s** (15 s callback wait × 2 BT slots + 15 s XInput slot-claim wait × 2 Xbox 360 slots).
- XInput lost visibility for the XUSB-companion path because the empty-shell devnode never bound `HMXInput.dll` and so never registered the XUSB device-interface class.

PadForge users with multiple controllers were hit on every relaunch.

### The two-tier fix

Two iterations.

**v1.x.x.0 (PID prefix)**: Prepend the launching process's PID in hex to every SwD instance-ID suffix, e.g. `SWD\HIDMAESTRO\A7B4_0002`.

```csharp
private static readonly string s_sessionId =
    System.Diagnostics.Process.GetCurrentProcess().Id.ToString("X").ToUpperInvariant();
```

Each launch gets a unique tuple; the kernel runs a fresh full install. Verified for fresh-boot-AND-subsequent-run parity. 5 back-to-back same-boot 4-controller runs all passed.

But: a **same-process** live-swap recreation (e.g. `remove 2; 2 dualsense; remove 2; 2 dualsense`) reused `<PID>_<idx>` and hit the same reuse-existing fast path on the second recreation in a swap cycle. The 2nd Series BT recreation in a cycle was an empty shell; the 2nd Xbox 360 wired ROOT was `[Stopped]`.

**v1.x.x.1 (per-call atomic sequence)**: Add a per-call atomic sequence number. Format `<PID-hex><seq:X4>_<idx:D4>`.

```csharp
private static int s_swdCreateSeq;

private static string NextSwdSuffix(int controllerIndex)
{
    int seq = System.Threading.Interlocked.Increment(ref s_swdCreateSeq);
    return $"{s_sessionId}{seq:X4}_{controllerIndex:D4}";
}
```

Every `SwDeviceCreate` call within this process gets a unique `(enumerator + suffix + ContainerId)` tuple. The kernel never hits the reuse-existing path. `FindExistingCompanion` matches by `ControllerIndex` in Device Parameters (not by suffix), so cleanup and teardown sweep across instances regardless of which session created them.

Verified via the regression battery's S03_Single_LongCycle_8swaps and S08_Multi_SwapOneSlot scenarios &mdash; previously failed, now pass.

---

## Why `hmswd.exe` exists as a separate native binary

`.NET 10`'s P/Invoke to `cfgmgr32!SwDeviceCreate` on Win11 26200 returns `0x8007007E ERROR_MOD_NOT_FOUND` synchronously, while the identical C call succeeds. We tried, in order:

1. **Plain P/Invoke.** Failed with `0x8007007E`.
2. **`CoInitializeEx(COINIT_MULTITHREADED)` first.** No effect.
3. **Preloaded `cfgmgr32.dll` and `swdevice.dll` via `LoadLibrary` before the P/Invoke.** No effect.
4. **`UnmanagedCallersOnly` callback function pointer marshaling.** No effect; same error.
5. **Explicit function-pointer marshaling via `Marshal.GetDelegateForFunctionPointer`.** No effect.
6. **`UnmanagedCallersOnly` with `CallConvCdecl` / `CallConvStdcall` variations.** No effect.
7. **Wrapping the call in `CallerMustBeAdmin` checks just in case.** No effect.

Nothing managed worked. Rather than ship a broken managed migration path, we wrote a small native executable (`driver/hmswd/hmswd.c`, 286 lines) that does the call from C and prints the result to stdout. The SDK's `SwdDeviceFactory` invokes `hmswd.exe` via `Process.Start` and parses the stdout.

```
hmswd.exe create <enumerator> <instance-id-suffix> <container-guid>
                 <hw-ids-csv> <compat-ids-csv> <description>
```

Returns instance-id on success (`OK <full-instance-id>`); writes errors to stderr.

The helper is included in the SDK's embedded resource payload alongside the driver DLLs. Total binary size: ~25 KB. Lifetime per call: <1 second (call, get instance-ID, exit).

The performance overhead of OOP-helper SwDeviceCreate has been verified empirically as **not observable** vs an in-process call &mdash; the P/Invoke marshaling path itself takes long enough that adding `Process.Start` doesn't move the needle. Architectural-cleanup alone doesn't justify chasing the 0x8007007E mystery.

---

## SwDevice removal

`SWDeviceLifetimeParentPresent` (a value of the `SW_DEVICE_LIFETIME` enum &mdash; search Microsoft Learn for the exact name) keeps the device alive across process exit. The only documented removal path:

1. Re-`SwDeviceCreate` with **identical args**. The docs guarantee this returns a fresh handle to the existing device (not a new device). The companion uses `FindExistingCompanion` lookup by `ControllerIndex` to find the right (suffix, ContainerID) tuple to pass.
2. **Downgrade lifetime** from `SWDeviceLifetimeParentPresent` to `SWDeviceLifetimeHandle` via `SwDeviceSetLifetime`.
3. **`SwDeviceClose`** the handle.
4. Block on `CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED` so callers know the kernel has actually propagated removal.

`pnputil /remove-device /force` and `DIF_REMOVE` both silently no-op on `FAILEDINSTALL`-state SWD phantoms, which is why this helper-mediated path is required.

The teardown is implemented in `hmswd.exe`'s `remove` subcommand:

```
hmswd.exe remove <enumerator> <instance-id-suffix> <container-guid>
                 <hw-ids-csv> <compat-ids-csv> <description>
```

Same args as `create`; the helper does the reconnect-then-downgrade-then-close dance.

---

## SwD-first removal ordering (v1.3.1)

Two of the three architecture groups (Xbox 360 Wired and Xbox Series BT) own a SwDevice-enumerated parent. SwDevice lifetimes are anchored to the `HSWDEVICE` handle, **not** the PnP devnode &mdash; children of a SwD parent cannot fully unwind their query-remove cascade until the parent's handle drops its kernel refcount.

Pre-v1.3.1 disposal:

1. `DeviceManager.RemoveDevice` issued `DIF_REMOVE` on every HID child first.
2. Each `DIF_REMOVE` was followed by a 2,000 ms `WaitForDeviceRemoval` that timed out (parent was still holding the lifetime lock).
3. Finally closed the SwDevice handle.
4. Net cost: ~5,700 ms for Xbox 360 Wired, ~11,000 ms for Xbox Series BT, scaling worse with more children.

v1.3.1 inverts the order:

1. For any `SWD\` parent, **close the SwDevice handle FIRST** via `SwdDeviceFactory.Remove`.
2. Block on `CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED` (a value of the `CM_NOTIFY_ACTION` enum on Microsoft Learn) for the parent &mdash; so callers know the kernel has actually propagated removal, not just that the handle closed.
3. Mop up any HID children that survived the cascade. Usually none, because the SwD parent's release fires its children's removal in one cascade.
4. Net cost: ~135 ms for Xbox 360 Wired, ~500 ms for Xbox Series BT.

A second optimization in the same change: when a HIDMAESTRO sweep walks registry entries that exist only as `PHANTOM` (registry residue from prior sessions, no live devnode), skip the `hmswd.exe` `SwDeviceCreate`-reconnect roundtrip entirely. Saves ~50-75 ms per stale entry and prevents creep across same-process recreation cycles.

---

## ContainerID sharing

For non-xinputhid Xbox profiles, the main HID device (ROOT\) and the XUSB companion (SWD\HIDMAESTRO\) **must share** the same per-controller ContainerID. Why:

- `xinput1_4.dll` reads ContainerID to dedupe. If main HID has ContainerID A and companion has ContainerID B, `xinput1_4` sees two separate devices and may double-count slots.
- Settings groups by ContainerID for the "Xbox 360 Wired" entry. Without shared ContainerID, two devices appear in Settings.

The main HID gets ContainerID via `SetupDiSetDeviceProperty(DEVPKEY_Device_ContainerId)`. The XUSB companion gets the same value via `SwDeviceCreate`'s `pContainerId` parameter. Both writes happen in the SDK's `SetupController` orchestration before the devices fully start.

For xinputhid Xbox profiles there's only one device (no companion), but the same per-controller ContainerID `{48494430-4D41-4553-5452-4F00...<idx>}` is still used so the bit-2 path stays closed.

---

## How the suffix mapping works at scale

For 6 controllers running in one process:

```
SWD\HIDMAESTRO\A7B40001_0000   ← controller 0 (Xbox 360 Wired companion), seq=1
SWD\HIDMAESTRO\A7B40002_0001   ← controller 1 (Xbox Series BT main HID), seq=2
SWD\HIDMAESTRO_VID_045E_PID_0B13&IG_00\A7B40002_0001    ← (xinputhid path uses different enumerator)
SWD\HIDMAESTRO\A7B40003_0002   ← controller 2 (DualSense), if it had a companion (it doesn't)
...
```

PID hex is `A7B4`; per-call sequence increments globally per process; controller index varies per call.

`FindExistingCompanion` walks `HKLM\SYSTEM\CurrentControlSet\Enum\SWD\HIDMAESTRO\` and matches devices whose `Device Parameters\ControllerIndex` value matches the controller we're operating on. The suffix isn't load-bearing for matching &mdash; it's there to make the kernel `(enumerator + suffix + ContainerId)` tuple unique.

For across-process matching (e.g. `RemoveAllVirtualControllers` from a fresh process sweeping orphans from a prior crashed session), the `HIDMAESTRO` enumerator name is the only stable identifier &mdash; sweep walks every `SWD\HIDMAESTRO*\*` entry regardless of suffix.

---

## See also

- [Architecture Overview](architecture-overview.md) &mdash; PnP layer's place in the full stack.
- [XUSB Companion](xusb-companion.md) &mdash; the device the SwDevice path is most needed for.
- [Lifecycle and Teardown](lifecycle-and-teardown.md) &mdash; the SDK orchestration that drives `SwDeviceCreate` and the SwD-first removal ordering.
- [Multi-Controller](multi-controller.md) &mdash; why per-controller ContainerIDs scale.
- [Driver Install and Signing](driver-install-and-signing.md) &mdash; the broader install flow that creates these devnodes.

## References

The Win32 PnP API symbols below are documented on [learn.microsoft.com](https://learn.microsoft.com/) &mdash; search by the exact symbol name; the page is one click away.

- `SwDeviceCreate` &mdash; the API and `pContainerId` parameter.
- `SetupDiCreateDeviceInfoW` &mdash; the older device-creation API.
- `DEVPKEY_Device_ContainerId` &mdash; ContainerID semantics, including the null-sentinel default.
- `SW_DEVICE_LIFETIME` &mdash; `SWDeviceLifetimeParentPresent` vs `Handle` lifetime.
- `CM_NOTIFY_ACTION` &mdash; the `DEVICEINSTANCEREMOVED` action used as the kernel-side removal guarantee.
- [References](references.md) &mdash; full source bibliography.
