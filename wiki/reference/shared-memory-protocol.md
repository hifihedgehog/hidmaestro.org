# Shared Memory Protocol

The wire format of the three pagefile-backed shared memory sections HIDMaestro uses for cross-process communication between the SDK (consumer process) and the driver (`HIDMaestro.dll` in WUDFHost) plus the XUSB companion (`HMXInput.dll` in another WUDFHost). All three are RAM-only &mdash; no disk I/O.

This page is the byte-level reference. For the SDK-facing API that wraps these sections, see [SDK Reference](../sdk/sdk-reference.md). For the driver-side seqlock readers, see [UMDF2 Driver Internals](umdf2-driver-internals.md).

---

## Section names

For controller index `<N>` (0, 1, 2, ...):

| Section | Name | Size | Purpose |
|---------|------|------|---------|
| Input | `Global\HIDMaestroInput<N>` | 278 bytes | Consumer &rarr; driver: HID input frames + GIP buffer |
| Output | `Global\HIDMaestroOutput<N>` | ~16.5 KB | Driver / companion &rarr; consumer: rumble / haptics / FFB capture |
| PID State | `Global\HIDMaestroPidState<N>` | ~32 bytes | Consumer &rarr; driver: HID PID 1.0 state mirror |

Plus two named events for wake-up:

| Event | Name | Purpose |
|-------|------|---------|
| Input data | `Global\HIDMaestroInputEvent<N>` | Auto-reset; signaled by the SDK after every input frame. Driver worker thread waits on this. |
| Stop | `Global\HIDMaestroStopEvent<N>` | Manual-reset; signaled by the driver to stop its worker thread on device unload. |

The SDK creates all three sections and both events with `SDDL = D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;WD)` &mdash; SYSTEM, BUILTIN\Administrators, and Everyone get `GENERIC_ALL`.

The permissive DACL is required because:
- The SDK consumer (admin) writes input frames.
- WUDFHost runs as LocalService and **lacks** `SeCreateGlobalPrivilege`. The driver can `OpenFileMapping` but cannot `CreateFileMapping` in the `Global\` namespace &mdash; only the elevated SDK can.
- Unelevated WGI / GameInput consumers may need to read indirectly via shared section paths.

The boundary is the IOCTL surface, which is mediated by the kernel HID stack and not by the shared-section permissions.

---

## Input section: `HIDMAESTRO_SHARED_INPUT`

```c
#pragma pack(push, 1)
typedef struct _HIDMAESTRO_SHARED_INPUT {
    volatile ULONG  SeqNo;           //  4 bytes — incremented each write
    ULONG           DataSize;        //  4 bytes — HID input report data size (excluding Report ID)
    UCHAR           Data[256];       // 256 bytes — HID input report data (native descriptor format)
    UCHAR           GipData[14];     //  14 bytes — GIP-format data for XUSB GET_STATE
} HIDMAESTRO_SHARED_INPUT, *PHIDMAESTRO_SHARED_INPUT;
#pragma pack(pop)
// Total: 278 bytes
```

Single-producer (the SDK consumer's `SubmitState` call), multi-reader (the main driver's worker thread, the XUSB companion's `IOCTL_XUSB_GET_STATE` handler).

### Why 256 bytes for `Data`?

Covers every HID input report size in the profile database without truncation. DualSense BT report 0x31 is **78 bytes**; Switch Pro standard input reports can run to ~64; gyro / accelerometer passthrough on these pads writes motion values **late** in the report, so the prior 64-byte pipe (pre-2026-04-23) clipped exactly the motion fields consumers (Dolphin, Cemu, yuzu/Citron, RetroArch) needed.

256 matches the mirror in `SHARED_OUTPUT`'s slot data cap and gives headroom for custom profile descriptors.

### Why 14 bytes for `GipData`?

The XUSB companion reads ONLY this slice on `IOCTL_XUSB_GET_STATE`. The SDK packs LX/LY/RX/RY/LT/RT/buttons into the 14 bytes for Xbox-VID profiles regardless of the descriptor declared in `Data` &mdash; so the same controller can serve DirectInput (descriptor-formatted bytes in `Data`) and XInput (GIP-formatted bytes in `GipData`) from one shared write.

Layout:

| Offset | Bits | Field |
|--------|------|-------|
| 0..1 | 16 | LX (unsigned, 0..65535) |
| 2..3 | 16 | LY (unsigned, 0..65535) |
| 4..5 | 16 | RX |
| 6..7 | 16 | RY |
| 8..9 | 10 | LT (low bits) |
| 10..11 | 10 | RT (low bits) |
| 12 | 8 | btnLow (A=0x01 B=0x02 X=0x04 Y=0x08 LB=0x10 RB=0x20 LS=0x40 RS=0x80) |
| 13 | 8 | btnHigh (Back=0x01 Start=0x02 hat<<2 [bits 2-5] Guide=0x40) |

For non-Xbox-VID profiles, the GIP buffer is left zeroed (no XUSB companion is bound; the bytes are unused). The SDK's `_packsGipBuffer` flag short-circuits the packing entirely &mdash; ~60-80 instructions saved per frame on DualSense / Switch Pro / generic gamepad paths.

### Seqlock write protocol (writer)

```csharp
// SDK side, in WriteInputFrame
// Increment SeqNo to odd → readers know "writer is mid-update"
view->SeqNo += 1;        // odd = mid-write
MemoryBarrier();
// ... write DataSize, Data, GipData
MemoryBarrier();
view->SeqNo += 1;        // even = stable
SetEvent(inputEventHandle);   // wake driver worker
```

### Seqlock read protocol (reader)

```c
// Driver / companion side
volatile SHARED_INPUT *src = ...;
ULONG seq1, seq2;
int retries = 4;
do {
    seq1 = src->SeqNo;
    if (seq1 & 1) { seq1 = src->SeqNo; }   // mid-write — re-read once
    MemoryBarrier();
    /* copy fields */
    MemoryBarrier();
    seq2 = src->SeqNo;
    if (seq1 == seq2 && !(seq1 & 1)) break;
} while (--retries > 0);
```

If `seq1 != seq2` after 4 retries, the read is unstable and is treated as "no new data" &mdash; will retry on the next event signal.

The SDK's writer is single-threaded (the consumer's input thread) so reader contention is rare. Two readers (driver worker and companion `IOCTL_XUSB_GET_STATE` handler) can read concurrently; both use the seqlock and don't interfere.

### Cadence

The SDK doesn't pump frames itself &mdash; the consumer drives cadence. Typical rates:

- **PadForge**: 1000 Hz (consumer's polling-loop rate).
- **SdkDemo**: 125 Hz (just enough to drive the example).
- **A profile-switch utility**: 0 Hz between switches.

The driver's worker thread wakes on `SetEvent` so its CPU cost scales with submission rate, not with a fixed polling interval. Idle CPU per controller: ~0.04% (down from ~3% pre-event-driven, when the driver had a 1ms WdfTimer busy-poll).

---

## Output section: `HIDMAESTRO_SHARED_OUTPUT`

```c
#define HIDMAESTRO_OUTPUT_RING_SLOTS     64u
#define HIDMAESTRO_OUTPUT_SLOT_DATA_CAP  256u

#pragma pack(push, 1)
typedef struct _HIDMAESTRO_OUTPUT_SLOT {
    volatile ULONG  SeqNo;           //  4 bytes — per-slot SeqNo, equal to Head value at write time
    UCHAR           Source;          //  1 byte  — HIDMAESTRO_OUTPUT_SOURCE_*
    UCHAR           ReportId;        //  1 byte  — HID Report ID (0 if no Report IDs)
    USHORT          DataSize;        //  2 bytes — bytes valid in Data[]
    UCHAR           Data[256];       // 256 bytes — payload
} HIDMAESTRO_OUTPUT_SLOT;
// Per-slot total: 264 bytes

typedef struct _HIDMAESTRO_SHARED_OUTPUT {
    volatile ULONG          Head;            //  4 bytes — monotonic total writes
    ULONG                   _Reserved;       //  4 bytes — reserved for future layout version
    HIDMAESTRO_OUTPUT_SLOT  Slots[64];       // 64 × 264 = 16896 bytes
} HIDMAESTRO_SHARED_OUTPUT;
#pragma pack(pop)
// Total: 16904 bytes
```

Single-producer (the driver or companion, whichever IOCTL fires) → single-consumer (the SDK's per-controller `HMOutputReader` thread).

### Source values

```c
#define HIDMAESTRO_OUTPUT_SOURCE_HID_OUTPUT   0   // HidOutput
#define HIDMAESTRO_OUTPUT_SOURCE_HID_FEATURE  1   // HidFeature
#define HIDMAESTRO_OUTPUT_SOURCE_XINPUT       2   // XInput
```

For `Source = HidOutput` / `HidFeature`, `ReportId` is the HID Report ID byte (0 if descriptor uses none). For `Source = XInput`, `ReportId` is reserved (0); `Data` is the 5-byte XINPUT_VIBRATION-style payload from the IOCTL_XUSB_SET_STATE input buffer.

The driver does **not** classify rumble vs haptic vs adaptive trigger &mdash; that distinction is semantic and lives in the consumer. See [Output Passthrough](../sdk/output-passthrough.md).

### Ring-buffer write protocol

```c
// Writer (driver or companion)
ULONG headNow = dst->Head;
ULONG newSeq = max(headNow, ctx->OutputSeqNoLocal) + 1;   // never go backwards
ctx->OutputSeqNoLocal = newSeq;
ULONG slotIdx = (newSeq - 1) % 64;

slot->Source = source;
slot->ReportId = reportId;
slot->DataSize = (USHORT)dataSize;
memcpy(slot->Data, data, dataSize);
MemoryBarrier();
slot->SeqNo = newSeq;
MemoryBarrier();
dst->Head = newSeq;
```

Two writers (the main driver and the XUSB companion for an Xbox 360 Wired controller) can both write to the same output ring concurrently because each takes a per-device lock (`OutputLock`) before claiming a slot. `max(Head, OutputSeqNoLocal) + 1` ensures the writer's local seqno never goes backward relative to the global Head, preserving monotonic ordering across both writers.

### Ring-buffer read protocol

```csharp
// Consumer (SDK reader thread)
uint lastSeen = ...;     // initialized to current Head on first poll
uint currentHead = view->Head;

while (lastSeen < currentHead)
{
    uint nextSeq = lastSeen + 1;
    int slotIdx = (int)((nextSeq - 1) % 64);
    var slot = view->Slots[slotIdx];

    // Torn-write detection: read SeqNo before and after the field read
    uint slotSeqBefore = slot->SeqNo;
    if (slotSeqBefore != nextSeq) {
        // The slot we expected has been overwritten — reader fell behind by ≥64
        // Skip ahead; this is the "drop" path
        lastSeen = currentHead;
        break;
    }
    // ... read Source, ReportId, DataSize, Data
    uint slotSeqAfter = slot->SeqNo;
    if (slotSeqAfter != slotSeqBefore) continue;   // torn — retry

    OutputReceived?.Invoke(controller, packet);
    lastSeen = nextSeq;
}
```

If `slotSeqBefore != nextSeq`, the reader has fallen behind by at least 64 writes &mdash; the slot we were going to read has been overwritten. The reader skips ahead to current Head and resumes; the consumer would see a SeqNo gap if it tracks them.

### Reader-stall threshold

64 slots give the reader 512 ms of handler-stall headroom before the oldest packet would be overwritten (the reader itself is event-driven since issue #34, so drain latency is dispatch cost, not poll cadence). If the consumer's `OutputReceived` handler stalls past that threshold while the producer is bursting, the oldest packets get overwritten.

Pre-1.1.40 the channel was single-slot, latest-write-wins. `pid.dll` writes Set Effect → Set Constant Force → Effect Operation Start within 1-3 ms; the middle (magnitude) packet got coalesced. Issue #16. The 64-slot ring is the fix.

### Periodic mapping refresh

The driver and companion both close and re-open the output mapping every 500 writes (~2 s at typical XInput polling rate) for stale-handle recovery. If the SDK tears down and recreates the section between sessions, the cached handle points at the old destroyed kernel object &mdash; writes go nowhere. Periodic re-open picks up the fresh section.

---

## PID FFB state section: `HIDMAESTRO_SHARED_PID_STATE`

```c
#pragma pack(push, 1)
typedef struct _HIDMAESTRO_SHARED_PID_STATE {
    volatile ULONG  SeqNo;                   //  4 bytes — seqlock
    UCHAR           PidEnabled;              //  1 byte — 0 until first PublishPidPool
    UCHAR           _pad0[3];

    /* Block Load Report (0x12) */
    UCHAR           BL_EffectBlockIndex;     //  1 byte
    UCHAR           BL_LoadStatus;           //  1 byte (1=Success, 2=Full, 3=Error)
    USHORT          BL_RAMPoolAvailable;     //  2 bytes

    /* Pool Report (0x13) */
    USHORT          Pool_RAMPoolSize;        //  2 bytes
    UCHAR           Pool_MaxSimultaneousEffects;  // 1 byte
    UCHAR           Pool_MemoryManagement;   //  1 byte (bit0=DeviceManagedPool, bit1=SharedParamBlocks)

    /* PID State Report (0x14) */
    UCHAR           State_EffectBlockIndex;  //  1 byte
    UCHAR           State_Flags;             //  1 byte
    UCHAR           _pad1[2];

    /* Driver-side EBI free-list */
    volatile ULONG  EbiAllocBitmap;          //  4 bytes — bit N = EBI N+1 allocated
    volatile ULONG  EbiAllocatedCount;       //  4 bytes — count
} HIDMAESTRO_SHARED_PID_STATE;
#pragma pack(pop)
// Total: 28 bytes
```

Both producer and consumer in this case &mdash; the SDK consumer writes Pool / State, the driver writes Block Load and EBI bitmap. **Different field groups**, partitioned to avoid contention.

### `PidEnabled`: the FFB gate

Zero-initialized when the SDK creates the section. First call to `HMController.PublishPidPool` flips it to 1 atomic with the Pool fields write under the same seqlock cycle. Driver checks `PidEnabled` before reading any other field. When 0:

- `IOCTL_UMDF_HID_GET_FEATURE` for **Pool** returns `STATUS_NO_SUCH_DEVICE` (matches vJoy's "FFB not enabled" convention so DInput cleanly concludes "device exists but no FFB").
- `IOCTL_UMDF_HID_GET_FEATURE` for **Block Load** / **State** returns `STATUS_NOT_SUPPORTED`.

This means a non-FFB consumer (PadForge with a non-FFB device, SdkDemo) can ignore the PID FFB API entirely and the driver will correctly tell DInput "no FFB" without surfacing as a half-broken FFB device.

### Wire layout matches HID PID 1.0 reports

The `BL_*`, `Pool_*`, `State_*` field groups are wire-format compatible with the HID PID 1.0 report layouts they correspond to. The driver can `memcpy` directly into the IOCTL output buffer with minimal packing &mdash; no field-by-field rebuilding.

### EBI auto-allocation (v1.1.37+)

`EbiAllocBitmap` is a 32-bit field (32 simultaneous effects max). The driver atomically allocates on `SetFeature(0x11 Create New Effect)`:

```c
// Driver side, inside SetFeature handler
ULONG bitmap = atomic_load(&pidState->EbiAllocBitmap);
ULONG freeBit = __builtin_ctz(~bitmap);    // lowest free bit
if (freeBit >= 32) return /* full */;
atomic_or(&pidState->EbiAllocBitmap, 1u << freeBit);
atomic_inc(&pidState->EbiAllocatedCount);

// Update BL_* fields under seqlock
pidState->SeqNo += 1;    // odd
MemoryBarrier();
pidState->BL_EffectBlockIndex = (UCHAR)(freeBit + 1);
pidState->BL_LoadStatus = 1;   // Success
pidState->BL_RAMPoolAvailable = ramAvailable;
MemoryBarrier();
pidState->SeqNo += 1;    // even
```

Mirrors vJoy's `Ffb_GetNextFreeEffect`. `pid.dll`'s follow-up `GetFeature(0x12 Block Load)` reads from the same shared section; the handshake completes within `pid.dll`'s synchronous IOCTL pair.

The bitmap is **outside** the seqlock'd block intentionally so EBI alloc/free never has to synchronize with `PublishPid*` writers. `BL_*` fields ARE inside the seqlock and the driver writes them atomically with SeqNo increment after a successful allocation.

The consumer reads the assigned EBI via `HMController.GetCurrentPidBlockLoad()`. See [Force Feedback](../sdk/force-feedback.md) for the consumer-side pattern.

`PID Block Free` (Output 0x1B) writes are captured to the output ring as `HidOutput` so the consumer's handler can clear the bit if it wants to track. The driver does **not** auto-clear &mdash; deliberate; the consumer is responsible for that bookkeeping.

---

## Section creation lifecycle

The SDK consumer creates all three sections + both events in `SetupController` before binding the driver:

```csharp
// In DeviceOrchestrator.SetupController
SharedMemoryIO.EnsureInputMapping(controllerIndex);    // creates Global\HIDMaestroInput<N> + Event
SharedMemoryIO.EnsureOutputMapping(controllerIndex);   // creates Global\HIDMaestroOutput<N>
// PID state section is lazy — only created on first HMController.PublishPidPool call
```

The driver and companion both `OpenFileMapping` (not `Create`) &mdash; LocalService doesn't have permission to create.

The SDK closes (`CloseHandle`) all sections in `HMController.Dispose` after the device removal IOCTL completes. The kernel reclaims the `Global\` namespace entry once the last handle drops. If the SDK process crashes without closing, the kernel reclaims when the process exits.

The driver's stale-handle recovery loop (close + re-open every 500 reads / writes) handles the cross-session case where the SDK creates a fresh section after a previous one was closed.

---

## Concrete example: input frame

For a DualSense controller (controller index 3) submitting a state with the left stick X slightly right of center and the right trigger pressed (`HMGamepadStateHelpers.StandardAxes(profile, leftStickX: 0.75f, rightTrigger: 0.7f)`) plus `Buttons = HMButton.A | HMButton.LeftBumper`:

```
Global\HIDMaestroInput3 view (after SDK write):

Offset  Bytes                          Field
─────── ─────────────────────────────── ──────────────────────
0       42 00 00 00                    SeqNo = 0x42 (66 — even, stable)
4       40 00 00 00                    DataSize = 64 bytes
8       01 ff bf 00 80 00 80 ...       Data[0..63] (DualSense report 0x01 layout):
                                         [0]   = Report ID (1)
                                         [1]   = LX = 0xBF (192, ≈75%)
                                         [2]   = LY = 0x80 (centered)
                                         [3]   = RX = 0x80
                                         [4]   = RY = 0x80
                                         [5]   = LT = 0x00
                                         [6]   = RT = 0xB3 (≈70%)
                                         [9]   = buttons low byte = 0x11 (A + LB)
                                         [10..]  = remaining DualSense state
264     00 ...                         Data[64..255] (zero-padded)
264     00 80 00 80 00 80 00 80 ...    GipData[0..13] (zeroed for non-Xbox-VID)
```

The driver's worker thread wakes on `Global\HIDMaestroInputEvent3`, reads the seqlock-stable view, copies `Data[0..63]` into its IOCTL_HID_READ_REPORT cache, and either completes a pended request or returns to wait.

DirectInput, SDL3 / HIDAPI, browser RawInput-fallback, and WGI all see the new bytes within ~2 ms.

---

## See also

- [Architecture Overview](architecture-overview.md) &mdash; the place of these sections in the full data flow.
- [UMDF2 Driver Internals](umdf2-driver-internals.md) &mdash; the driver-side reader and worker-thread mechanics.
- [XUSB Companion](xusb-companion.md) &mdash; the second reader of the input section and second writer of the output ring.
- [Output Passthrough](../sdk/output-passthrough.md) &mdash; the consumer-side API on top of the output ring.
- [Force Feedback](../sdk/force-feedback.md) &mdash; the consumer-side API on top of the PID state section.
- [SDK Reference](../sdk/sdk-reference.md) &mdash; the public API surface that hides all of this.
