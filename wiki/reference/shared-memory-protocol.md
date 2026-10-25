# Shared Memory Protocol

The wire format of the five pagefile-backed shared memory sections HIDMaestro uses for cross-process communication between the SDK (consumer process) and the driver (`HIDMaestro.dll` in WUDFHost) plus the XUSB companion (`HMXInput.dll` in another WUDFHost). All five are RAM-only: no disk I/O.

This page is the byte-level reference. For the SDK-facing API that wraps these sections, see [SDK Reference](../sdk/sdk-reference.md). For the driver-side seqlock readers, see [UMDF2 Driver Internals](umdf2-driver-internals.md).

---

## Section names

For transport index `<N>`, `HMController.TransportIndex`. A program running alone gets its slot numbers, 0, 1, 2, ..., as every release before v2.0.0 did, with two exceptions: a keyed create whose identity a dead program's device still carries lands on that device's index, and an index whose names another program took first is skipped. While a program built on v1.12.0 runs, every create starts at index 64. When several programs that embed HIDMaestro run, a controller can get another free index, so native writers read the names from `HMController.SectionNames` or compute them from `TransportIndex`, never from the slot. See [Programs Side by Side](../sdk/programs-side-by-side.md).

| Section | Name | Size | Purpose |
|---------|------|------|---------|
| Input | `Global\HIDMaestroInput<N>` | 362 bytes | Consumer &rarr; driver: HID input frames + GIP buffer |
| Output | `Global\HIDMaestroOutput<N>` | ~16.5 KB | Driver / companion &rarr; consumer: rumble / haptics / FFB capture |
| PID State | `Global\HIDMaestroPidState<N>` | 40 bytes, of which the driver's struct uses 36 | Consumer &rarr; driver: HID PID 1.0 state mirror. The driver writes its effect-block allocation back |
| Input acknowledgement (v1.12.0) | `Global\HIDMaestroInputAck<N>` | 688 bytes | Driver &rarr; consumer: the last delivered frame's sequence number. Consumer &rarr; driver: release frames for keyboards and mice |
| Version (v2.0.0) | `Global\HIDMaestroVersion<N>` | 64 bytes | Both directions: the SDK's and the driver's versions and protocols, and the controller's identity tag. See [Version section](#version-section-v200) |

Plus named events for wake-up, and the owner pipe:

| Event | Name | Purpose |
|-------|------|---------|
| Input data | `Global\HIDMaestroInputEvent<N>` | Auto-reset; signaled by the SDK after every input frame. Driver worker thread waits on this. |
| Companion input | `Global\HIDMaestroCompanionInputEvent<N>` | Auto-reset. Signaled with the input event, for frames that carry GIP data, so the XUSB companion completes a parked read at frame arrival. |
| Input acknowledgement | `Global\HIDMaestroInputAckEvent<N>` | Auto-reset. Signaled by the driver when it acknowledges a delivered frame (v1.12.0). |
| Remove | `Global\HIDMaestroRemoveEvent<N>` | Created by the SDK with the input section. A `Dispose` of a ROOT device signals it when a program refuses its removal query, and the driver fails its device so Windows removes it by surprise removal (v2.0.0, driver protocol 5). |
| Removed | `Global\HIDMaestroRemovedEvent<N>` | Created by the SDK with the input section. Signaled by the driver once it has failed its device. The SDK waits up to 2 s for it (v2.0.0, driver protocol 5). |
| Output | `Global\HIDMaestroOutputEvent<N>` | Signaled per published output packet. The driver and the XUSB companion create or open it, and the SDK creates it for a USB/IP persona. |
| Stop | `Global\HIDMaestroStopEvent<N>` | Manual-reset. Created and signaled by the driver to stop its worker thread on device unload. |
| Owner pipe | `\\.\pipe\HIDMaestroOwner<N>` | Held by the SDK for the controller's life. The driver sends the release frames when it closes (v1.12.0). |

`HMController.SectionNames` lists the names the SDK creates or opens for one controller, from `Global\HIDMaestroInput<N>` to the owner pipe. The stop event is the driver's own.

The SDK creates the sections and its events with `SDDL = O:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;LS)(A;;GR;;;WD)`. Administrators own them. SYSTEM, BUILTIN\Administrators and LocalService get `GENERIC_ALL`, and Everyone gets `GENERIC_READ`. The owner pipe carries `O:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;LS)`. The owner is set to Administrators so it does not depend on the machine's default-owner policy, under which an elevated program's objects can be owned by the user.

The driver creates the stop and output events, and the XUSB companion the output event, with `D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;LS)`, so a program that is not elevated can neither signal a controller's stop event nor take its output doorbell. The companion's stop event is unnamed. Any program can create a `Global\` event first, so the driver uses an existing one only when it has a DACL and SYSTEM, Administrators or LocalService owns it. An existing NULL-DACL output event that a driver before v2.0.0 made is taken over and given the descriptor above. Otherwise the stop event is unnamed, which still stops the worker at teardown, and the output event is not used while the name stays unusable. The driver tries again each time it maps the input section, on each idle timeout and every 256 frames, and the SDK's reader falls back to its poll meanwhile.

Before it takes a transport index, the SDK opens each of the index's named sections and events. An index where one exists as another kind of object, refuses to be opened, or has an owner other than SYSTEM or Administrators, or an owner that cannot be read, is skipped. So is an index whose v1.12.0 owner pipe is held. LocalService passes as an owner only for the stop and output events, which the driver host creates as LocalService.

The permissive DACL is required because:
- The SDK consumer (admin) writes input frames.
- WUDFHost runs as LocalService and **lacks** `SeCreateGlobalPrivilege`. The driver can `OpenFileMapping` but cannot `CreateFileMapping` in the `Global\` namespace: only the elevated SDK can.
- Everyone's read access is for diagnostic tools that are not elevated.

The boundary is the IOCTL surface, which is mediated by the kernel HID stack and not by the shared-section permissions.

---

## Input section: `HIDMAESTRO_SHARED_INPUT`

```c
#pragma pack(push, 1)
typedef struct _HIDMAESTRO_SHARED_INPUT {
    volatile ULONG  SeqNo;           //  4 bytes: incremented each write
    ULONG           DataSize;        //  4 bytes: HID input report data size (excluding Report ID)
    UCHAR           Data[256];       // 256 bytes: HID input report data (native descriptor format)
    UCHAR           GipData[14];     //  14 bytes: GIP-format data for XUSB GET_STATE
} HIDMAESTRO_SHARED_INPUT, *PHIDMAESTRO_SHARED_INPUT;
#pragma pack(pop)
// Total: 362 bytes
```

Single-producer (the SDK consumer's `SubmitState` call), multi-reader (the main driver's worker thread, the XUSB companion's `IOCTL_XUSB_GET_STATE` handler).

### Why 256 bytes for `Data`?

Covers every HID input report size in the profile database without truncation. DualSense BT report 0x31 is **78 bytes**; Switch Pro standard input reports can run to ~64; gyro / accelerometer passthrough on these pads writes motion values **late** in the report, so the prior 64-byte pipe (pre-2026-04-23) clipped exactly the motion fields consumers (Dolphin, Cemu, yuzu/Citron, RetroArch) needed.

256 matches the mirror in `SHARED_OUTPUT`'s slot data cap and gives headroom for custom profile descriptors.

### Why 14 bytes for `GipData`?

The XUSB companion reads ONLY this slice on `IOCTL_XUSB_GET_STATE`. The SDK packs LX/LY/RX/RY/LT/RT/buttons into the 14 bytes for profiles with an XUSB companion regardless of the descriptor declared in `Data`: so the same controller can serve DirectInput (descriptor-formatted bytes in `Data`) and XInput (GIP-formatted bytes in `GipData`) from one shared write.

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

For every other profile, the GIP buffer is left zeroed (no XUSB companion is bound, so the bytes are unused). The SDK's `_packsGipBuffer` flag short-circuits the packing entirely: ~60-80 instructions saved per frame on DualSense / Switch Pro / generic gamepad paths.

### Seqlock write protocol (writer)

```csharp
// SDK side, in WriteInputFrame
Volatile.Write(ref view->SeqNo, seq + 1);  // odd = mid-write
Volatile.WriteBarrier();                   // the payload's stores after the odd number
// ... write DataSize, Data, GipData, ExtendedReportSize and ExtendedReportData
Volatile.Write(ref view->SeqNo, seq + 2);  // even = stable, a release store after the payload
SetEvent(inputEventHandle);                // wake the driver's worker
```

Until 2.1.0 the SDK wrote the payload between two full memory fences. The write barrier and the release store keep the order a reader needs: the odd number before the payload, and the payload before the even number. On x64 neither is a fence instruction, and on ARM64 they are `dmb ish` and `stlr`.

### Seqlock read protocol (reader)

```c
// Driver / companion side
volatile SHARED_INPUT *src = ...;
ULONG seq1, seq2;
int retries = 4;
do {
    seq1 = src->SeqNo;
    if (seq1 & 1) { seq1 = src->SeqNo; }   // mid-write: re-read once
    MemoryBarrier();
    /* copy fields */
    MemoryBarrier();
    seq2 = src->SeqNo;
    if (seq1 == seq2 && !(seq1 & 1)) break;
} while (--retries > 0);
```

If `seq1 != seq2` after 4 retries, the read is unstable and is treated as "no new data": will retry on the next event signal.

The SDK's writer is single-threaded (the consumer's input thread) so reader contention is rare. Two readers (driver worker and companion `IOCTL_XUSB_GET_STATE` handler) can read concurrently; both use the seqlock and don't interfere.

### Cadence

The SDK doesn't pump frames itself: the consumer drives cadence. Typical rates:

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
    volatile ULONG  SeqNo;           //  4 bytes: per-slot SeqNo, equal to Head value at write time
    UCHAR           Source;          //  1 byte: HIDMAESTRO_OUTPUT_SOURCE_*
    UCHAR           ReportId;        //  1 byte: HID Report ID (0 if no Report IDs)
    USHORT          DataSize;        //  2 bytes: bytes valid in Data[]
    UCHAR           Data[256];       // 256 bytes: payload
} HIDMAESTRO_OUTPUT_SLOT;
// Per-slot total: 264 bytes

typedef struct _HIDMAESTRO_SHARED_OUTPUT {
    volatile ULONG          Head;            //  4 bytes: monotonic total writes
    ULONG                   _Reserved;       //  4 bytes: reserved for future layout version
    HIDMAESTRO_OUTPUT_SLOT  Slots[64];       // 64 × 264 = 16896 bytes
} HIDMAESTRO_SHARED_OUTPUT;
#pragma pack(pop)
// Total: 16904 bytes
```

Single-producer (the driver or companion, whichever IOCTL fires) → single-consumer (the SDK's per-controller `HMOutputReader` thread).

### Source values

```c
#define HIDMAESTRO_OUTPUT_SOURCE_HID_OUTPUT       0   // HidOutput
#define HIDMAESTRO_OUTPUT_SOURCE_HID_FEATURE      1   // HidFeature
#define HIDMAESTRO_OUTPUT_SOURCE_XINPUT           2   // XInput
#define HIDMAESTRO_OUTPUT_SOURCE_HID_FEATURE_READ 3   // HidFeatureRead (v1.3.5)
```

Source 3 signals a feature *read*, not a write. The host issued `IOCTL_HID_GET_FEATURE` for that report id, and the Sony BT `extendedReport.armOn` watcher uses it to flip vendor-blob emission on.

For `Source = HidOutput` / `HidFeature`, `ReportId` is the HID Report ID byte (0 if descriptor uses none). For `Source = XInput`, `ReportId` is reserved (0); `Data` is the 5-byte XINPUT_VIBRATION-style payload from the IOCTL_XUSB_SET_STATE input buffer.

The driver does **not** classify rumble vs haptic vs adaptive trigger: that distinction is semantic and lives in the consumer. See [Output Passthrough](../sdk/output-passthrough.md).

### Ring-buffer write protocol

```c
// Writer (driver or companion)
ULONG newSeq = (ULONG)InterlockedIncrement((volatile LONG *)&dst->Head);
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

Two writers (the main driver and the XUSB companion for an Xbox 360 Wired controller) publish into the same ring from separate processes. `InterlockedIncrement` on the shared `Head` reserves a unique sequence for each, and the fenced `slot->SeqNo` store is the publish gate the reader validates. A reserved but unwritten slot is retried on the reader's next wake. The earlier `max(Head, local) + 1` form could mint the same sequence from both producers and silently overwrite a slot, which the audit of #34 replaced.

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
        // The slot we expected has been overwritten: reader fell behind by ≥64
        // Skip ahead; this is the "drop" path
        lastSeen = currentHead;
        break;
    }
    // ... read Source, ReportId, DataSize, Data
    uint slotSeqAfter = slot->SeqNo;
    if (slotSeqAfter != slotSeqBefore) continue;   // torn: retry

    OutputReceived?.Invoke(controller, packet);
    lastSeen = nextSeq;
}
```

If `slotSeqBefore != nextSeq`, the reader has fallen behind by at least 64 writes: the slot we were going to read has been overwritten. The reader skips ahead to current Head and resumes; the consumer would see a SeqNo gap if it tracks them.

### Reader-stall threshold

64 slots give the reader 512 ms of handler-stall headroom before the oldest packet would be overwritten (the reader itself is event-driven since issue #34, so drain latency is dispatch cost, not poll cadence). If the consumer's `OutputReceived` handler stalls past that threshold while the producer is bursting, the oldest packets get overwritten.

Pre-1.1.40 the channel was single-slot, latest-write-wins. `pid.dll` writes Set Effect → Set Constant Force → Effect Operation Start within 1-3 ms; the middle (magnitude) packet got coalesced. Issue #16. The 64-slot ring is the fix.

### Periodic mapping refresh

The driver and companion both close and re-open the output mapping every 500 writes (~2 s at typical XInput polling rate) for stale-handle recovery. If the SDK tears down and recreates the section between sessions, the cached handle points at the old destroyed kernel object: writes go nowhere. Periodic re-open picks up the fresh section.

---

## PID FFB state section: `HIDMAESTRO_SHARED_PID_STATE`

```c
#pragma pack(push, 1)
typedef struct _HIDMAESTRO_SHARED_PID_STATE {
    volatile ULONG  SeqNo;                   //  4 bytes: seqlock
    UCHAR           PidEnabled;              //  1 byte: 0 until first PublishPidPool
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
    volatile ULONG  EbiAllocBitmap;          //  4 bytes: bit N = EBI N+1 allocated
    volatile ULONG  EbiAllocatedCount;       //  4 bytes: count

    /* Report ID overrides from the profile's descriptor, 0 = canonical (v1.3.7) */
    UCHAR PoolReportId, StateReportId, BlockLoadReportId;
    UCHAR CreateNewEffectReportId, BlockFreeReportId, DeviceControlReportId;
    UCHAR _pad2[2];
} HIDMAESTRO_SHARED_PID_STATE;
#pragma pack(pop)
// Total: 36 bytes. The SDK creates the section at 40 bytes.
```

Both producer and consumer in this case: the SDK consumer writes Pool / State, the driver writes Block Load and EBI bitmap. **Different field groups**, partitioned to avoid contention.

### `PidEnabled`: the FFB gate

Zero-initialized when the SDK creates the section. First call to `HMController.PublishPidPool` flips it to 1 atomic with the Pool fields write under the same seqlock cycle. Driver checks `PidEnabled` before reading any other field. When 0:

- `IOCTL_UMDF_HID_GET_FEATURE` for **Pool** returns `STATUS_NO_SUCH_DEVICE` (matches vJoy's "FFB not enabled" convention so DInput cleanly concludes "device exists but no FFB").
- `IOCTL_UMDF_HID_GET_FEATURE` for **Block Load** / **State** returns `STATUS_NOT_SUPPORTED`.

This means a non-FFB consumer (PadForge with a non-FFB device, SdkDemo) can ignore the PID FFB API entirely and the driver will correctly tell DInput "no FFB" without surfacing as a half-broken FFB device.

### Wire layout matches HID PID 1.0 reports

The `BL_*`, `Pool_*`, `State_*` field groups are wire-format compatible with the HID PID 1.0 report layouts they correspond to. The driver can `memcpy` directly into the IOCTL output buffer with minimal packing: no field-by-field rebuilding.

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

`PID Block Free` (Output 0x1B) writes are captured to the output ring as `HidOutput` so the consumer's handler can clear the bit if it wants to track. The driver does **not** auto-clear: deliberate; the consumer is responsible for that bookkeeping.

---

## Version section (v2.0.0)

`Global\HIDMaestroVersion<N>`, 64 bytes, `HIDMAESTRO_VERSION_INFO` in `driver/driver.h`. The SDK creates it beside the input section before the devnode exists and writes its half, the identity tag included. It also writes the controller's index under `HKLM\SOFTWARE\HIDMaestro\Identity\<token>` before any PnP work. No existing layout changed.

| Offset | Field | Written by |
|---|---|---|
| 0 | Layout version, 1 | SDK |
| 4 | Oldest driver protocol the SDK runs on, 4 | SDK |
| 8 | Protocol the SDK speaks, 4 | SDK |
| 12 | SDK version: major, minor, patch, 0, four 16-bit fields | SDK |
| 20 | Driver protocol, 4, and 0 until written | driver |
| 24 | Driver version: major, minor, patch, 0, four 16-bit fields | driver |
| 32 | Driver capabilities: 0x3, the input acknowledgement's delivered bit (0x1) and release bit (0x2) | driver |
| 36 | Oldest SDK protocol the driver serves, 4 | driver |
| 40, 44 | The XUSB companion's protocol and the oldest SDK protocol it serves | companion |
| 48 | Identity tag: the 64-bit FNV-1a hash of the controller's identity token in UTF-16LE, no terminator (`HM_0000` gives 0x1FD048916B8D461F) | SDK |
| 56 | The value the driver could not read before it failed the start | driver |
| 60 | The same for the companion | companion |

The driver reads its device instance ID before `WdfDeviceCreate`, takes the identity token from its last segment and reads the index from the identity key. It reads the controller's 2.0.0 values, `FeatureAnswers` and the cached input report IDs, only when the section exists, its range holds protocol 4 and its tag equals the tag of the devnode's own token. Every other devnode, a 1.x program's or one a killed program's key still names, is read as a 1.x controller: the values every version writes and nothing of 2.0.0, so it gets no feature answers. A devnode whose index's section carries another token's tag fails its start with STATUS_DEVICE_CONFIGURATION_ERROR. The driver writes its version, capabilities and oldest served protocol first and its protocol last, with a barrier between, at add and each time it opens the input section.

Protocol 1 is the layout set through v1.11.0: the input and output sections, the events and the PID state. Protocol 2 adds the input acknowledgement and the owner pipe (v1.12.0). Protocol 3 added this section in a build that never shipped, and protocol 4 is the 2.0.0 contract. The 2.0.0 HID driver serves protocols 4 to 5 and the XUSB companion 4: driver protocol 5 adds the remove and removed events above, which the SDK uses only when the driver's half says 5, and the contract the SDK checks at create stays protocol 4. A create reads the section once its device has started. A driver whose range does not hold 4 fails the create, which removes its devnode and throws `HMDriverVersionException` with `Problem` `ProtocolNotServed`, and a set error word throws it with `ValueNotRead`. `HMController.DriverVersion` reads the driver's half. It is null until the driver has started the device, on a driver older than v2.0.0, which never writes it, and on a USB/IP persona, which has no driver.

---

## Section creation lifecycle

The SDK consumer creates the sections and its events in `SetupController` before binding the driver, under the transport index its lease claimed:

```csharp
// In DeviceOrchestrator.SetupController
SharedMemoryIO.EnsureInputMapping(transportIndex);    // Input, InputAck, Version, their events, the owner pipe
SharedMemoryIO.EnsureOutputMapping(transportIndex);   // creates Global\HIDMaestroOutput<N>
// PID state section is lazy: only created on first HMController.PublishPidPool call
```

The owner pipe's first instance is created with `FILE_FLAG_FIRST_PIPE_INSTANCE`. If a program built on v1.12.0 took the same index in the meantime, the create stops with `HMResourceInUseException` rather than share its sections.

The driver and companion both `OpenFileMapping` (not `Create`): LocalService doesn't have permission to create.

Beside the sections, the SDK writes each index's configuration under `HKLM\SOFTWARE\HIDMaestro\Controller<N>`. As of v2.0.0 that configuration gains `InputReportId` (REG_BINARY): the input report a data-only frame fills, its length as a 32-bit little-endian value, then the descriptor. The driver ignores a value whose length is not the `InputReportByteLength` beside it or whose descriptor is not the one in use, and then scans the descriptor as before. A 2.0.0 controller's configuration also holds `FeatureAnswers`, its compiled feature answer table. The driver reads both only under the version contract (see [Version section](#version-section-v200)), so a native writer that wants feature answers writes the section and the identity entry as the SDK does. The configuration no longer holds `DeviceInstanceId`, which no driver read, and a create writes `VendorId` and `ProductId` first. See [UMDF2 Driver Internals](umdf2-driver-internals.md).

The SDK closes (`CloseHandle`) all sections in `HMController.Dispose` after the device removal IOCTL completes. The kernel reclaims the `Global\` namespace entry once the last handle drops. If the SDK process crashes without closing, the kernel reclaims when the process exits.

The driver's stale-handle recovery loop (close + re-open every 500 reads / writes) handles the cross-session case where the SDK creates a fresh section after a previous one was closed.

---

## Concrete example: input frame

For a DualSense controller (transport index 3) submitting a state with the left stick X slightly right of center and the right trigger pressed (`HMGamepadStateHelpers.StandardAxes(profile, leftStickX: 0.75f, rightTrigger: 0.7f)`) plus `Buttons = HMButton.A | HMButton.LeftBumper`:

```
Global\HIDMaestroInput3 view (after SDK write):

Offset  Bytes                          Field
─────── ─────────────────────────────── ──────────────────────
0       42 00 00 00                    SeqNo = 0x42 (66: even, stable)
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
72      00 ...                         Data[64..255] (zero-padded)
264     00 00 00 00 00 00 00 00 ...    GipData[0..13] (zeroed without a companion)
```

The driver's worker thread wakes on `Global\HIDMaestroInputEvent3`, reads the seqlock-stable view, copies `Data[0..63]` into its IOCTL_HID_READ_REPORT cache, and either completes a pended request or returns to wait.

DirectInput, SDL3 / HIDAPI, browser RawInput-fallback, and WGI all see the new bytes within ~2 ms.

---

## See also

- [Architecture Overview](architecture-overview.md): the place of these sections in the full data flow.
- [UMDF2 Driver Internals](umdf2-driver-internals.md): the driver-side reader and worker-thread mechanics.
- [XUSB Companion](xusb-companion.md): the second reader of the input section and second writer of the output ring.
- [Output Passthrough](../sdk/output-passthrough.md): the consumer-side API on top of the output ring.
- [Force Feedback](../sdk/force-feedback.md): the consumer-side API on top of the PID state section.
- [SDK Reference](../sdk/sdk-reference.md): the public API surface that hides all of this.
