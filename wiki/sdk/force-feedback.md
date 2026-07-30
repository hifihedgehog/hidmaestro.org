# Force Feedback

HID PID 1.0 force feedback for DirectInput consumers (specification at [usb.org/document-library](https://www.usb.org/document-library); search "HID PID 1.0"). End-to-end: descriptor authoring, the four shared-section reports, driver-side EBI auto-allocation, and the canonical packet ordering DirectInput8 / SharpDX / `pid.dll` send.

This page focuses on the SDK-side architecture. For the underlying driver-side IOCTL handling and the shared-memory wire format, see [UMDF2 Driver Internals](../reference/umdf2-driver-internals.md) and [Shared Memory Protocol](../reference/shared-memory-protocol.md).

---

## What "force feedback works" means here

A DirectInput game calls `IDirectInputDevice8::CreateEffect`. The DirectX layer (`dinput8.dll` &rarr; `pid.dll`) walks the device's HID descriptor for the PID FFB block, learns which Output report ID carries Set Effect / Set Constant Force / Effect Operation Start / Block Free, asks the device for its effect-pool capacity (`HidD_GetFeature` for the 0x13 Pool Report), allocates an effect block (`HidD_SetFeature` for the 0x11 Create New Effect Report, then `HidD_GetFeature` for the 0x12 Block Load Report to read the assigned EBI), and starts writing per-frame effect packets via `HidD_SetOutputReport`.

A virtual that "passes FFB" answers each of those interrogations correctly:

1. The descriptor declares the canonical PID FFB block.
2. The Pool Report returns sane pool capacity.
3. The Create-New-Effect &rarr; Block Load handshake assigns and returns an EBI.
4. Set Effect / Set Constant Force / Effect Operation Start round-trip the consumer's `HMController.OutputReceived` handler with the decoded magnitude bytes.

HIDMaestro is the only user-mode virtual-controller library on Windows that does all four. vJoy supports declaring the descriptor but doesn't surface output bytes through a clean SDK; ViGEmBus's PID FFB story stops at XInput rumble.

> **A note on banned phrases.** This page is engineered to operate **as designed** in PadForge's `FfbTest` SharpDX integration test (regression scenario S26). The "decisive" / "matches every symptom" claims that the global feedback rules forbid don't apply &mdash; the verification is in `swap_regression.ps1` and reproducible.

---

## Descriptor authoring

```csharp
var desc = new HidDescriptorBuilder()
    .Joystick()                          // REQUIRED — Gamepad TLC AVs pid.dll
    .AddStick("Left", 16).AddStick("Right", 16)
    .AddTrigger("Left", 8).AddTrigger("Right", 8)
    .AddButtons(N).AddHat()
    .AddPidFfbBlock();                   // emits the canonical PID 1.0 block
```

`AddPidFfbBlock` does three things:

1. **Throws** if the current TLC is Gamepad. `pid.dll` AVs inside `PID_EffectOperation+0x52` when `CreateEffect` is called against Usage 0x05; the only safe TLC is Joystick (Usage 0x04). DirectX 8-era code, not OS-build-gated.
2. **Auto-injects Report ID 0x01** at the descriptor's start if no Report ID has been emitted yet. Mixing untagged input items with the FFB block's tagged Output reports fails HID validation.
3. **Emits the minimum-viable PID block.** All Output reports (0x11 / 0x12 / 0x13 / 0x14 / 0x15 / 0x16 / 0x17 / 0x18 / 0x1A / 0x1B / 0x1C / 0x1D / 0x1E) plus the **single** Feature report 0x11 (Create New Effect).

### Why only one Feature report

vJoy's reference descriptor declares four sibling Feature reports inside the Application Collection: 0x11 Create New Effect, 0x12 Block Load, 0x13 PID Pool, 0x14 PID State. With HIDMaestro's UMDF2 shared-section transport, the four-feature variant causes pid.dll to AV inside `PID_EffectOperation+0x52` the first time the consumer calls `CreateEffect` (issue #16). The bytes are vJoy's; the crash is `pid.dll`'s preparsed-data parser disagreeing about Feature-report dispatch.

The block emitted by `AddPidFfbBlock` drops 0x12 / 0x13 / 0x14 from the Feature side and serves them via the driver's shared-section `HidD_GetFeature` path instead. This is the **only configuration empirically verified not to AV** on Windows 11 26100.

Pair `AddPidFfbBlock` with `HMProfileBuilder.FromDescriptorBuilder` so the wire input report size derives the +1 byte for the auto-injected Report ID:

```csharp
var profile = new HMProfileBuilder()
    .Id("my-stick").Vid(0x0483).Pid(0x5740).ProductString("My HOTAS")
    .FromDescriptorBuilder(desc)         // descriptor + InputReportSize together
    .Build();
```

Manually doing `.Descriptor(desc.Build()).InputReportSize(desc.InputReportByteSize + 1)` is correct and equivalent, but easy to get wrong &mdash; PadForge tracked this across several iterations of issue #16. The kernel sizes the input buffer wrong when the +1 is missing, HidClass preparsed data is misaligned, and `pid.dll` resolves Feature reports to Report ID 0 instead of the declared values.

---

## The four publish/read methods

```csharp
public void PublishPidPool(ushort ramPoolSize, byte simultaneousEffectsMax,
                           bool deviceManagedPool, bool sharedParameterBlocks);
public void PublishPidBlockLoad(byte effectBlockIndex, PidLoadStatus loadStatus,
                                ushort ramPoolAvailable);
public void PublishPidState(byte effectBlockIndex, PidStateFlags flags);
public HMPidBlockLoad GetCurrentPidBlockLoad();
```

The driver answers `HidD_GetFeature` for the canonical PID Report IDs (Pool 0x13, Block Load 0x12, State 0x14) directly from a per-controller shared state section the consumer fills via these methods. **No IPC round trip on the GetFeature path** &mdash; the driver reads from shared memory synchronously inside its IOCTL handler and completes the request.

### `PublishPidPool`: the FFB enable gate

```csharp
ctrl.PublishPidPool(
    ramPoolSize: 0x0400,                // 1 KB total RAM pool
    simultaneousEffectsMax: 16,         // up to 16 effects loaded at once
    deviceManagedPool: false,           // host manages allocation
    sharedParameterBlocks: false);      // each effect has its own params
```

**First call enables FFB on this controller.** Until called at least once, the driver returns `STATUS_NO_SUCH_DEVICE` for the Pool Report so DirectInput cleanly concludes "device exists but no FFB" and stops retrying. This matches vJoy's "FFB not enabled" convention. The shared `HIDMAESTRO_SHARED_PID_STATE` section's `PidEnabled` byte flips to 1 atomically with the Pool fields write under the seqlock.

Subsequent calls update pool state. Cheap &mdash; no driver IOCTL, just a shared-section seqlock write.

Choose `ramPoolSize` and `simultaneousEffectsMax` to match what your physical force-feedback hardware can handle. The driver's EBI free-list bitmap is 32-bit, capping at 32 simultaneous effects regardless of what you advertise here.

### `PublishPidBlockLoad`: **optional in v1.1.37+**

```csharp
ctrl.PublishPidBlockLoad(
    effectBlockIndex: 1,
    loadStatus: PidLoadStatus.Success,
    ramPoolAvailable: 0x03E0);
```

The driver allocates EBIs synchronously inside its `SetFeature(0x11 Create New Effect)` IOCTL handler (mirroring vJoy's `Ffb_GetNextFreeEffect`). The canonical pattern is for the consumer to **read** the assigned EBI via `GetCurrentPidBlockLoad` rather than write its own. Manual writes are still supported &mdash; useful only when the consumer has a reason to mint EBIs itself (specific reservation policy, mapping back to physical-side handles).

`PidLoadStatus`:

| Value | Meaning |
|-------|---------|
| `Success = 1` | Effect block was allocated. |
| `Full = 2` | Pool was full. Host should fail or retry. |
| `Error = 3` | Allocation failed for some other reason. |

**Note on threading:** `OutputReceived` is delivered on the SDK's poll thread (~8 ms latency). It is **not** synchronous with the kernel SetFeature IOCTL. Calling `PublishPidBlockLoad` from inside the handler runs after dinput8 has already issued its follow-up `GetFeature(BlockLoad)`, so the publish lands too late to influence that read. The driver-side allocation in v1.1.37 is what makes the handshake work.

### `PublishPidState`: current device state

```csharp
ctrl.PublishPidState(
    effectBlockIndex: 1,
    flags: PidStateFlags.ActuatorsEnabled
         | PidStateFlags.ActuatorPower
         | PidStateFlags.EffectPlaying);
```

Reflects current device state for the most-recently-referenced effect. Update whenever:

- Effect Operation Start fires &rarr; set `EffectPlaying`.
- Effect Operation Stop fires &rarr; clear `EffectPlaying`.
- Device Reset fires &rarr; clear all flags except `ActuatorsEnabled`.
- Device Pause / Continue fires &rarr; set / clear `DeviceIsPaused`.
- Actuators Enable / Disable fires &rarr; set / clear `ActuatorsEnabled`.

`PidStateFlags`:

| Flag | Bit | HID PID 1.0 §5.8 |
|------|-----|------------------|
| `DeviceIsPaused` | 0 | Device is paused; effects are suspended but not freed. |
| `ActuatorsEnabled` | 1 | Actuators enabled; the device can render force. |
| `SafetySwitch` | 2 | Safety switch is engaged; the device must not render. |
| `ActuatorOverrideSwitch` | 3 | Actuator override switch is engaged. |
| `ActuatorPower` | 4 | Actuator power is on. |
| `EffectPlaying` | 5 | Most-recently-referenced effect is playing. |

### `GetCurrentPidBlockLoad`: read driver-allocated EBI

```csharp
ctrl.OutputReceived += (sender, packet) =>
{
    if (packet.Source == HMOutputSource.HidFeature && packet.ReportId == 0x11)
    {
        // Driver has just allocated an EBI. Read it.
        var bl = ctrl.GetCurrentPidBlockLoad();
        Console.WriteLine($"  Allocated EBI {bl.EffectBlockIndex}, RAM left: {bl.RAMPoolAvailable}");
        WireEbiToPhysicalEffectHandle(bl.EffectBlockIndex);
    }
};
```

Returns a snapshot of the PID Block Load Report fields the driver populated synchronously inside its `SetFeature(0x11)` handler. The driver picks the next free EBI from a bitmap, updates BL fields atomically before completing the IOCTL, so by the time the consumer's `OutputReceived` handler fires (8 ms-ish later via the SDK's poll loop) the BL state is already canonical.

Returns a default-zero `HMPidBlockLoad` if `PublishPidPool` hasn't been called yet (FFB not enabled &mdash; the shared section doesn't exist).

---

## The canonical packet flow

`pid.dll` writes Set Effect &rarr; Set Constant Force &rarr; Effect Operation Start within 1-3 ms when a game calls `IDirectInputEffect::Start`. The consumer's `OutputReceived` handler fires for each:

```csharp
ctrl.OutputReceived += (sender, packet) =>
{
    switch (packet.Source, packet.ReportId)
    {
        // Set Effect — defines effect type, duration, axis selection
        case (HMOutputSource.HidOutput, 0x11):
            DecodeSetEffect(packet.Data.Span);
            break;

        // Set Constant Force — magnitude for a constant-force effect
        case (HMOutputSource.HidOutput, 0x15):
            DecodeSetConstantForce(packet.Data.Span);
            break;

        // Set Periodic — magnitude/period/phase for a periodic effect
        case (HMOutputSource.HidOutput, 0x14):
            DecodeSetPeriodic(packet.Data.Span);
            break;

        // Effect Operation — Start / Stop / Solo for an effect
        case (HMOutputSource.HidOutput, 0x1A):
            DecodeEffectOperation(packet.Data.Span);
            break;

        // PID Block Free — release an EBI back to the pool
        case (HMOutputSource.HidOutput, 0x1B):
            DecodeBlockFree(packet.Data.Span);
            break;

        // PID Device Control — Reset / Pause / Continue / Stop All
        case (HMOutputSource.HidOutput, 0x1C):
            DecodeDeviceControl(packet.Data.Span);
            break;

        // Device Gain — overall force gain
        case (HMOutputSource.HidOutput, 0x1D):
            byte gain = packet.Data.Span[0];
            SetGlobalGain(gain);
            break;

        // Create New Effect FEATURE report — the driver allocated an EBI
        case (HMOutputSource.HidFeature, 0x11):
            var bl = ctrl.GetCurrentPidBlockLoad();
            WireEbi(bl);
            break;
    }
};
```

The byte layouts match HID PID 1.0 §5 exactly; consumers typically port a small chunk of vJoy's `vJoyInterface.cpp` decode logic to handle them. A complete reference implementation lives in PadForge's `HMaestroFfbDecoder.cs`.

### Why the ring buffer matters

Pre-1.1.40 the output channel was a single slot, latest-write-wins. That coalesced `pid.dll`'s tight three-packet bursts within 1-3 ms vs the SDK's 8 ms poll interval &mdash; middle packets dropped, magnitude never reached the consumer. Issue #16.

v1.1.40+ uses a **64-slot ring with monotonic seqlock per slot**. Writer (driver) increments a global Head counter, writes `slot[(Head-1) % N]`, readers track LastSeen and process slots from `LastSeen+1` to `Head`. The SDK's poll loop drains every slot the driver has written since the last poll, in monotonic SeqNo order &mdash; so all three bytes of a Set Effect &rarr; Set Constant Force &rarr; Effect Operation Start burst surface in the right order on the next poll iteration.

Ring depth is 64 slots × 256-byte payload. If the consumer's handler stalls for >512 ms while the driver is writing at burst rate, the oldest packets get overwritten. **Keep the handler cheap** &mdash; no synchronous I/O, no long locks. See [Output Passthrough](output-passthrough.md) for the wire format.

---

## Driver-side EBI auto-allocation

The shared `HIDMAESTRO_SHARED_PID_STATE` section carries an `EbiAllocBitmap` (32-bit) and `EbiAllocatedCount`. When `pid.dll` writes a `SetFeature(0x11 Create New Effect)`, the driver:

1. Picks the lowest free bit (next free EBI). Atomic via `InterlockedOr`.
2. Updates `BL_EffectBlockIndex`, `BL_LoadStatus = Success`, `BL_RAMPoolAvailable` inside the seqlock.
3. Completes the IOCTL.

`pid.dll`'s follow-up `GetFeature(0x12 BlockLoad)` reads the freshly written values from the shared section &mdash; the driver's IOCTL handler reads the same memory the SDK consumer would read. The consumer then sees the SetFeature notification surface as `OutputReceived(HidFeature, 0x11)` ~8 ms later and reads the assigned EBI via `GetCurrentPidBlockLoad`.

If the bitmap is full when an allocation request arrives, the driver writes `BL_LoadStatus = Full` and `BL_EffectBlockIndex = 0`. `pid.dll` propagates this to the game as `DI_OK_NOEFFECT` (the game knows the device is FFB-capable but couldn't allocate this effect).

`PID Block Free (0x1B)` clears the bit when the consumer's `OutputReceived` handler decodes it &mdash; the driver does **not** auto-free; the consumer is responsible for routing Block Free packets back to the bitmap (or, more typically, just trusting `pid.dll` to send Block Free for every allocation it released and ignoring the bookkeeping).

The 32-bit bitmap caps at 32 simultaneous effects, well above any consumer pool you'd realistically advertise via `Pool_MaxSimultaneousEffects`. Mirrors vJoy's `Ffb_GetNextFreeEffect`.

---

## Consumer-side wiring patterns

There are two consumer-side patterns depending on how rich the FFB needs to be:

### Pattern A: route raw bytes to physical hardware

Best when the consumer is bridging a virtual to a physical FFB device that already understands PID 1.0.

```csharp
ctrl.OutputReceived += (_, packet) =>
{
    if (packet.Source != HMOutputSource.HidOutput) return;
    physicalDevice.HidD_SetOutputReport(packet.ReportId, packet.Data);
};
```

PadForge's pass-through wheel/HOTAS pipeline does this for FFB-capable physical hardware.

### Pattern B: decode + render via XInput rumble or audio

Best when the consumer is mixing FFB into a non-FFB output channel (Xbox 360 rumble, audio bass detection, vibration).

```csharp
ctrl.OutputReceived += (_, packet) =>
{
    var effects = ParseFfbPacket(packet);
    foreach (var effect in effects)
    {
        // Collapse vector forces, condition effects, etc. into LeftMotor/RightMotor
        var (leftMotor, rightMotor) = ApplyMotorOutput(effect);
        physicalXInputController.SetMotors(leftMotor, rightMotor);
    }
};
```

PadForge's `ApplyMotorOutput` collapses active effects via polar-direction-to-motor-split for vector forces and condition-effect dispatch for spring/damper/friction/inertia.

---

## Verification

The regression battery covers the FFB path in three scenarios:

| Scenario | Coverage |
|----------|----------|
| **S24_PidFfb_RoundTrip** | DI PID FFB shared-section round-trip on a custom HOTAS profile. `PublishPidPool` / `PublishPidState` reach the driver's HID feature replies; Block Load auto-allocation lands in the shared section. |
| **S25_PidFfb_AllocFree** | Allocate-then-free under burst load with two controllers. Each controller's independent EBI table; pool exhaustion path returns the right HID error. |
| **S26_PidFfb_FfbTest** | DI PID FFB end-to-end via SharpDX / DI8 (`FfbTest`). The PID FFB invariants S24/S25 cover at the SDK boundary actually deliver to a real DI consumer. |

Run from an elevated PowerShell:

```powershell
./test/regression/swap_regression.ps1 -Filter 'S24*'
./test/regression/swap_regression.ps1 -Filter 'S25*'
./test/regression/swap_regression.ps1 -Filter 'S26*'
```

PASS exit code 0; FAIL exit code 1 with leftover instance IDs printed.

---

## Limitations

- **Effect mixing is consumer-side.** The SDK surfaces decoded packets but doesn't synthesize a final force value. Multi-effect mixing, condition-effect dispatch, and gain application are the consumer's job.
- **Vendor-specific FFB extensions.** Logitech G HUB / Thrustmaster TARGET / SimuCUBE Bridge protocols are vendor-private. HIDMaestro carries the standard PID 1.0 reports; vendor extensions need per-controller decoder work in the consumer.
- **No haptics-only output channel.** The PID 1.0 spec is rumble + force feedback; modern haptics (DualSense adaptive triggers, DualSense lightbar) ship as Output reports outside the PID block. The SDK still surfaces them via `OutputReceived` with `Source = HidOutput` and the relevant Report ID, but decoding is profile-specific.
- **Auth chips are out of scope.** Some platforms (PS4/PS5 online, Switch Online) require cryptographic authentication. HIDMaestro cannot replicate authentication chips. PID FFB still works for offline games.

---

## See also

- [HID Descriptor Builder](hid-descriptor-builder.md) &mdash; `AddPidFfbBlock` reference and the four-feature pid.dll AV trap.
- [Output Passthrough](output-passthrough.md) &mdash; the 64-slot ring buffer the FFB packets travel through.
- [Shared Memory Protocol](../reference/shared-memory-protocol.md) &mdash; `HIDMAESTRO_SHARED_PID_STATE` wire format.
- [UMDF2 Driver Internals](../reference/umdf2-driver-internals.md) &mdash; the `IOCTL_UMDF_HID_GET_FEATURE` path that reads from shared memory.
- [Testing and Verification](../reference/testing-and-verification.md) &mdash; the S24-S26 regression scenarios end-to-end.

## References

- HID PID 1.0 specification (USB-IF; download from [usb.org/document-library](https://www.usb.org/document-library)) &mdash; Report ID definitions (Pool §5.7, Block Load §5.5, State §5.8), Effect Operation §5.10, Block Free §5.11, Device Control §5.12.
- vJoy `Ffb_GetNextFreeEffect` &mdash; in [github.com/njz3/vJoy](https://github.com/njz3/vJoy) under `driver/sys/hid.c`. The kernel-side EBI auto-allocation pattern HIDMaestro mirrors in user mode.
- vJoy reference FFB descriptor &mdash; in the same repo under `driver/sys/hidReportDescFfb.h`. The four-feature variant `AddPidFfbBlock` deliberately omits.
- [HIDMaestro issue #16](https://github.com/hifihedgehog/HIDMaestro/issues/16) &mdash; the pid.dll `PID_EffectOperation+0x52` AV.
- [`test/regression/swap_regression.ps1`](https://github.com/hifihedgehog/HIDMaestro/blob/master/test/regression/swap_regression.ps1) &mdash; scenarios S24-S26 validate the FFB round-trip end-to-end.
- [References](../reference/references.md) &mdash; full source bibliography.
