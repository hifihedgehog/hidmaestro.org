# Output Passthrough

How rumble, haptics, force feedback, adaptive trigger config, LED color, and any other host-to-device data reaches the consumer. The driver captures the bytes; the SDK surfaces them via `HMController.OutputReceived` events; the consumer decodes per the active profile.

The SDK does **not** classify packets as "rumble" vs "haptic" vs "FFB" &mdash; that distinction is semantic and lives in the consumer. All three end up in the same payload at different byte offsets per profile.

This page covers the wire format, the ring buffer mechanics, and consumer decoding patterns. For the driver-side IOCTL handling, see [UMDF2 Driver Internals](../reference/umdf2-driver-internals.md) and [XUSB Companion](../reference/xusb-companion.md). For the canonical PID FFB packet flow, see [Force Feedback](force-feedback.md).

---

## The output channel

```csharp
public event Action<HMController, HMOutputPacket>? OutputReceived;

public readonly struct HMOutputPacket
{
    public readonly HMOutputSource Source;
    public readonly byte ReportId;
    public readonly ReadOnlyMemory<byte> Data;
    public readonly uint SeqNo;
}

public enum HMOutputSource : byte
{
    HidOutput  = 0,    // HidD_SetOutputReport / dinput8 PID effects / HIDAPI write
    HidFeature = 1,    // HidD_SetFeature
    XInput     = 2,    // XInputSetState (XUSB-wire 5-byte vibration)
}
```

Subscribe at any time after `HMContext.CreateController` returns. Unsubscribe before disposing the controller, or just rely on dispose to break the event-source link. Multiple subscribers work; each gets a copy of the invocation.

### `OutputDecoded` (v1.3.5+)

For profiles whose JSON declares an `extendedOutputReport` block (Sony BT family in v1.3.5; future profiles via JSON only), the SDK additionally raises a parsed-field event whenever an inbound output report matches the declared report ID:

```csharp
public event EventHandler<HMOutputDecodedEventArgs>? OutputDecoded;

public sealed class HMOutputDecodedEventArgs : EventArgs
{
    public byte ReportId { get; init; }
    public IReadOnlyDictionary<string, object> Fields { get; init; } = null!;
    public ReadOnlyMemory<byte> RawBytes { get; init; }
    public bool CrcValid { get; init; } = true;
}
```

`Fields` is keyed by the profile JSON's `semantic` names. Field-type → runtime-type mapping:

| JSON `type` | `Fields[semantic]` runtime type |
|---|---|
| `uint8`, `uint8-rolling` | `byte` |
| `uint8-axis` | `float` (mapped from byte via the declared center) |
| `uint8-trigger` | `float` (mapped from byte / 255) |
| `rgb24` | `byte[3]` (R, G, B) |
| `bytes-passthrough` | `byte[]` (length per the declared range) |
| `button-mask` | `List<string>` of pressed-button names |

Both `OutputReceived` (raw) and `OutputDecoded` (parsed) fire on every matching report — choose whichever the consumer needs. Pure raw consumers can ignore `OutputDecoded`; consumers wanting named field access can ignore `OutputReceived`. `CrcValid` reports the result of any `crc32-le` field declared in the spec; consumers decide whether to act on a mismatch.

```csharp
controller.OutputDecoded += (sender, e) =>
{
    if (e.Fields.TryGetValue("leftMotor", out var lm)
        && e.Fields.TryGetValue("rightMotor", out var rm))
    {
        Console.WriteLine($"[rumble] L={lm} R={rm}");
    }
    if (e.Fields.TryGetValue("lightbar", out var rgb) && rgb is byte[] c)
    {
        Console.WriteLine($"[lightbar] #{c[0]:X2}{c[1]:X2}{c[2]:X2}");
    }
};
```

---

## Sources

`HMOutputSource` tells the consumer **which API the host used** to send the packet. The bytes have different wire formats per source even on the same controller.

### `HidOutput` (0)

Host wrote via `HidD_SetOutputReport` / `IOCTL_HID_WRITE_REPORT`. Bytes are the raw HID output report payload. `ReportId` carries the HID Report ID byte (0 if the descriptor uses no Report IDs); `Data` is everything **after** the Report ID.

Use case: every HID-aware FFB / rumble path.

- **DirectInput PID FFB**: every Output report 0x11 / 0x14 / 0x15 / 0x16 / 0x17 / 0x18 / 0x1A / 0x1B / 0x1C / 0x1D / 0x1E lands here. See [Force Feedback](force-feedback.md).
- **DualSense rumble + adaptive triggers + lightbar**: a single 47-byte (USB) or 78-byte (BT) Output report 0x02 carries motor magnitudes, trigger profiles, LED color, mute LED state.
- **Switch Pro vendor protocol**: 0x10 / 0x80 prefix bytes, vendor commands.

### `HidFeature` (1)

Host wrote via `HidD_SetFeature`. Used by some controllers (DualSense, DualShock 4) for configuration writes; used by `pid.dll` for PID FFB Create New Effect (Report ID 0x11).

For a HIDMaestro virtual with `AddPidFfbBlock`-built descriptor, every `OutputReceived(HidFeature, 0x11)` is a Create New Effect notification &mdash; the driver has just allocated an EBI in shared memory. Read it via `HMController.GetCurrentPidBlockLoad`.

### `XInput` (2)

Host called `XInputSetState`. Bytes are the XUSB-wire-format vibration packet, typically 5 bytes:

| Offset | Field |
|--------|-------|
| 0 | Command (`0x00`) |
| 1 | Size byte |
| 2 | Low-frequency motor (left, 0..255) |
| 3 | High-frequency motor (right, 0..255) |
| 4 | Reserved |

Only fires for profiles with the XUSB companion (non-xinputhid Xbox profiles like Xbox 360 Wired). xinputhid profiles route XInput rumble through the kernel filter, which translates it back into a HID Output report; those surface as `HidOutput`.

Browser `put_Vibration` from Chromium dispatches `IOCTL_XUSB_SET_STATE` to the XUSB companion via the xinputhid UpperFilter tripwire (see [Cross-API Coverage](../reference/cross-api-coverage.md)). The companion captures the bytes and writes them into the output ring as `HMOutputSource.XInput`.

---

## The 64-slot ring buffer (v1.1.40+)

The output channel is a 64-slot ring on a per-controller pagefile-backed shared section. Wire format is `HIDMAESTRO_SHARED_OUTPUT`:

```c
#define HIDMAESTRO_OUTPUT_RING_SLOTS     64u
#define HIDMAESTRO_OUTPUT_SLOT_DATA_CAP  256u

typedef struct {
    volatile ULONG  SeqNo;
    UCHAR           Source;
    UCHAR           ReportId;
    USHORT          DataSize;
    UCHAR           Data[HIDMAESTRO_OUTPUT_SLOT_DATA_CAP];
} HIDMAESTRO_OUTPUT_SLOT;

typedef struct {
    volatile ULONG          Head;
    ULONG                   _Reserved;
    HIDMAESTRO_OUTPUT_SLOT  Slots[64];
} HIDMAESTRO_SHARED_OUTPUT;
```

Total size: ~16.5 KB per controller. Pagefile-backed; never touches disk.

### Writer (driver) protocol

Single producer. Inside the relevant IOCTL handler (`IOCTL_UMDF_HID_SET_OUTPUT_REPORT`, `IOCTL_UMDF_HID_SET_FEATURE`, or `IOCTL_XUSB_SET_STATE` on the companion):

1. Take `OutputLock` (per-device lock that serializes IOCTL handler races).
2. Increment `Head` to get the new SeqNo (the value that will identify the slot).
3. Compute slot index `(Head - 1) % 64`.
4. Write Source / ReportId / DataSize / Data into that slot.
5. Write SeqNo last (memory-barrier; readers detect torn writes by re-reading SeqNo).
6. Release `OutputLock`.

`SeqNo = 0` is reserved for "never written"; first write is `SeqNo = 1`.

### Reader (SDK) protocol

Single consumer (the per-controller `HMOutputReader_<index>` background thread):

```csharp
// Initialize lastSeen to current Head so pre-existing ring contents
// (stale or legitimate) never fire a spurious OutputReceived.
uint lastSeen = (uint)Marshal.ReadInt32(_outputView, 0);

while (!ct.IsCancellationRequested)
{
    // Drain every slot the driver wrote since last poll, in monotonic SeqNo order.
    while (SharedMemoryIO.TryReadOutputFrame(_outputView, ref lastSeen,
            out byte source, out byte reportId, out int dataSize, buf))
    {
        var data = new ReadOnlyMemory<byte>(buf, 0, dataSize);
        var pkt = new HMOutputPacket((HMOutputSource)source, reportId, data, lastSeen);
        OutputReceived?.Invoke(this, pkt);
    }
    WaitHandle.WaitAny(new[] { ct.WaitHandle, doorbell }, 500);  // event-driven (issue #34)
}
```

Each `TryReadOutputFrame` call reads `Head`, computes slots from `lastSeen + 1` to `Head`, and returns one slot at a time. The reader uses per-slot SeqNo for torn-write detection: if SeqNo before-read ≠ SeqNo after-read, the slot was being rewritten &mdash; skip it.

### Why the ring depth is 64

`pid.dll` writes Set Effect &rarr; Set Constant Force &rarr; Effect Operation Start within 1-3 ms. Pre-1.1.40 the channel was a single slot &mdash; the magnitude packet (Set Constant Force, in the middle) got coalesced and dropped. With 64 slots the reader has 512 ms of headroom (handler-stall bound) before the oldest slot would be overwritten, which is plenty for any realistic FFB burst pattern.

The 256-byte payload covers DualSense BT report 0x31 (78 bytes) and any current PID FFB Output (largest is Set Effect at 22 bytes). Profile descriptors with larger output reports than 256 bytes would need the section widened.

### Reader-stall threshold

If the consumer's handler stalls for >512 ms while the driver is writing at burst rate, the oldest packets get overwritten. The consumer would see a `SeqNo` jump (e.g. from 17 to 80) that signals a drop. **Keep handlers cheap** &mdash; no synchronous I/O, no long locks, no UI marshaling on the SDK poll thread (use `Dispatcher.BeginInvoke` to fire-and-forget the marshal).

---

## Cadence

The SDK reader is event-driven (issue #34): the driver signals `Global\HIDMaestroOutputEvent<N>` after each published packet, so the reader wakes at dispatch cost instead of poll quantization. Against a pre-#34 driver that never created the event, the reader falls back to the historical ~125 Hz (8 ms) poll. Multiple invocations of `OutputReceived` per wake are normal &mdash; the loop drains every new slot before waiting again, so three-packet PID FFB bursts arrive together.

Dispose latency: cancel-token-driven. The output thread waits on the cancel handle alongside the doorbell, so cancellation returns within ~1 ms.

---

## Consumer decode patterns

### Pattern: parsed-field subscription (v1.3.5+)

For profiles with `extendedOutputReport`, the simplest path is to subscribe to `OutputDecoded` and read named values directly. No byte-offset knowledge in the consumer:

```csharp
ctrl.OutputDecoded += (_, e) =>
{
    if (e.Fields.TryGetValue("rightMotor", out var rm))   ApplyHighFreqMotor((byte)rm);
    if (e.Fields.TryGetValue("leftMotor",  out var lm))   ApplyLowFreqMotor((byte)lm);
    if (e.Fields.TryGetValue("lightbar",   out var rgb)
        && rgb is byte[] c)                                ApplyLightbar(c[0], c[1], c[2]);
    if (e.Fields.TryGetValue("rightTriggerEffect", out var rte)
        && rte is byte[] rteBytes)                         ApplyAdaptiveTriggerR(rteBytes);
};
```

Pair with `HMOutputEncoder.Encode` to drive a real device from synthesized state without reimplementing byte layouts:

```csharp
var fields = new Dictionary<string, object>
{
    { "btTag",       (byte)0x02 },
    { "validFlag0",  (byte)0xFF },
    { "validFlag1",  (byte)0xF7 },
    { "rightMotor",  (byte)200 },
    { "leftMotor",   (byte)64 },
    { "lightbar",    new byte[] { 0xFF, 0x00, 0x80 } },
};
byte[] wireBytes = HMOutputEncoder.Encode(profile, fields);
// Hand wireBytes to a raw-HID write into the real device.
```

### Pattern: dispatch by (Source, ReportId)

```csharp
ctrl.OutputReceived += (_, packet) =>
{
    var bytes = packet.Data.Span;
    var key = (packet.Source, packet.ReportId);

    switch (key)
    {
        case (HMOutputSource.XInput, 0):
            // 5-byte XINPUT_VIBRATION-style payload, motor bytes at [2] and [3]
            byte left = bytes[2], right = bytes[3];
            HandleXInputRumble(left, right);
            break;

        case (HMOutputSource.HidOutput, 0x02):
            // DualSense Report 0x02 — full motor + adaptive trigger + LED bytes
            HandleDualSenseOutput(bytes);
            break;

        case (HMOutputSource.HidOutput, 0x11):
        case (HMOutputSource.HidOutput, 0x14):
        case (HMOutputSource.HidOutput, 0x15):
        case (HMOutputSource.HidOutput, 0x1A):
        case (HMOutputSource.HidOutput, 0x1B):
        case (HMOutputSource.HidOutput, 0x1C):
        case (HMOutputSource.HidOutput, 0x1D):
            // PID FFB output reports — see Force Feedback page
            HandlePidFfbOutput(packet.ReportId, bytes);
            break;

        case (HMOutputSource.HidFeature, 0x11):
            // PID FFB Create New Effect — driver allocated an EBI
            var bl = ctrl.GetCurrentPidBlockLoad();
            WireEbi(bl);
            break;
    }
};
```

### Pattern: ring-buffer-aware drop detection

```csharp
uint lastSeenSeqNo = 0;

ctrl.OutputReceived += (_, packet) =>
{
    if (lastSeenSeqNo > 0 && packet.SeqNo > lastSeenSeqNo + 1)
    {
        // Driver wrote (packet.SeqNo - lastSeenSeqNo - 1) packets we missed.
        // Probably handler stalled. Log and continue.
        long dropped = packet.SeqNo - lastSeenSeqNo - 1;
        Telemetry.RumbleDropsTotal.Add(dropped);
    }
    lastSeenSeqNo = packet.SeqNo;
    DispatchPacket(packet);
};
```

### Pattern: marshal off the poll thread

```csharp
ctrl.OutputReceived += (sender, packet) =>
{
    // Don't decode on the poll thread — push to a queue, decode on UI thread
    _decoderQueue.Enqueue(packet);
    _decoderSignal.Set();
};
```

PadForge uses this pattern for FFB-to-audio conversion (the audio mix happens on the audio thread, not the SDK poll thread).

### Pattern: copy the data

`packet.Data` is a `ReadOnlyMemory<byte>` over the SDK's reusable buffer. **It's only valid for the duration of the handler call.** If you need the bytes past the handler return:

```csharp
ctrl.OutputReceived += (_, packet) =>
{
    byte[] copy = packet.Data.ToArray();    // explicit copy
    Task.Run(() => ProcessAsync(copy));     // safe to use later
};
```

The buffer is reused on the next slot read. Don't store the `ReadOnlyMemory` reference past the handler.

---

## Per-source mechanics

### XInput rumble (XUSB companion path)

For non-xinputhid Xbox profiles (Xbox 360 Wired), the XUSB companion (`HMXInput.dll`) handles `IOCTL_XUSB_SET_STATE`. Inside its handler it reads the IRP's input buffer (5 bytes, XINPUT_VIBRATION-style), takes the per-controller `OutputLock` against the main HID device's shared section, writes a slot with `Source = XInput`, `ReportId = 0`, `Data = 5 bytes`. The companion signals the same output event after publishing, so the SDK reader picks it up at dispatch cost (8 ms poll against pre-#34 drivers).

For xinputhid profiles (Xbox Series BT), `xinputhid.sys` handles `IOCTL_XUSB_SET_STATE` itself and converts to a HID Output report against the HID child &mdash; so rumble surfaces as `HMOutputSource.HidOutput` with whatever Report ID `xinputhid` writes (typically 0).

### Browser vibration

Chromium's `Gamepad.Vibration::put_Vibration` dispatches through WGI. The path depends on the architecture group:

- **Xbox 360 Wired**: WGI dispatches `IOCTL_XUSB_SET_STATE` to the XUSB companion via the xinputhid UpperFilter tripwire. Surfaces as `HMOutputSource.XInput`.
- **Xbox Series BT**: WGI dispatches via the HID path (`xinputhid.sys` is the kernel filter). Surfaces as `HMOutputSource.HidOutput`.
- **Plain HID profiles** (DualSense, etc.): WGI dispatches a HID Output report via the standard HID path. Surfaces as `HMOutputSource.HidOutput`.

In all three cases the consumer's `OutputReceived` handler fires; only the wire format differs.

### DirectInput PID FFB

See [Force Feedback](force-feedback.md) for the full mechanism. Briefly: every Output report `pid.dll` writes (Set Effect 0x11, Set Constant Force 0x15, Effect Operation 0x1A, etc.) surfaces as `HMOutputSource.HidOutput`. Create New Effect (Feature 0x11) surfaces as `HMOutputSource.HidFeature`.

### Vendor-specific output

Vendor-specific output reports (Logitech rotation calibration, DualSense lightbar color, Thrustmaster TARGET binding writes) surface as `HMOutputSource.HidOutput` with the Report ID the vendor declared. Decoding is profile-specific; HIDMaestro doesn't ship pre-built decoders for vendor protocols.

---

## What HIDMaestro does **not** do

- **Auto-routing to physical hardware.** The driver accepts the bytes and the SDK surfaces them. Forwarding to a physical FFB device, mixing into XInput rumble, or rendering as audio is the consumer's job. PadForge is the reference example of a consumer that does all three.
- **Effect mixing or condition synthesis.** The SDK delivers raw decoded packets. Multi-effect mixing, gain application, and condition-effect dispatch (Spring / Damper / Friction / Inertia) are consumer-side.
- **XInput rumble synthesis from PID FFB.** A DirectInput-only game writing PID FFB to an Xbox 360 Wired profile won't get XInput rumble unless the consumer maps the FFB output back to motor magnitudes and writes them via a separate path.

---

## See also

- [Force Feedback](force-feedback.md) &mdash; HID PID 1.0 architecture, the canonical packet flow, EBI auto-allocation.
- [Shared Memory Protocol](../reference/shared-memory-protocol.md) &mdash; `HIDMAESTRO_SHARED_OUTPUT` wire format and seqlock invariants.
- [XUSB Companion](../reference/xusb-companion.md) &mdash; how `IOCTL_XUSB_SET_STATE` becomes an `HMOutputSource.XInput` packet.
- [UMDF2 Driver Internals](../reference/umdf2-driver-internals.md) &mdash; how `IOCTL_UMDF_HID_SET_OUTPUT_REPORT` becomes an `HMOutputSource.HidOutput` packet.
- [Cross-API Coverage](../reference/cross-api-coverage.md) &mdash; per-API browser vibration / WGI dispatch path.
