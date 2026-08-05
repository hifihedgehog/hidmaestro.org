# UMDF2 Driver Internals

`HIDMaestro.dll` is a UMDF2 lower filter driver under `mshidumdf.sys`. This page documents the driver's responsibilities, the IOCTL dispatch table, the device context, the worker thread, the seqno-gated `READ_REPORT` path, and the empirical reasons each design choice exists. UMDF2 framework reference: search Microsoft Learn for "User-Mode Driver Framework version 2".

Source: [`driver/driver.c`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/driver.c) (1,574 lines), [`driver/driver.h`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/driver.h) (414 lines).

For the XUSB companion driver, see [XUSB Companion](xusb-companion.md). For the SDK side that talks to this driver, see [SDK Reference](../sdk/sdk-reference.md) and [Shared Memory Protocol](shared-memory-protocol.md).

---

## Driver position in the HID stack

```
┌─────────────────────────────────────────────────────┐
│ Consumer (DInput / XInput / WGI / SDL3 / Browser)   │
└─────────────────────────────────────────────────────┘
                        ↓ HID class IOCTLs
┌─────────────────────────────────────────────────────┐
│ HidClass.sys                                         │  Kernel
│  Owns IOCTL_HID_READ_REPORT pump, preparsed data,    │
│  HID class device interface registration.            │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ xinputhid.sys (xinputhid Xbox profiles only)         │  Kernel filter
│  16-button HID synthesis, native XInput delivery.    │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ mshidumdf.sys (HID minidriver function driver)       │  Kernel
│  Marshals HID IOCTLs into UMDF2 IRPs.                │
└─────────────────────────────────────────────────────┘
                        ↓ IOCTL_UMDF_HID_*
┌─────────────────────────────────────────────────────┐
│ WUDFRd.sys (UMDF reflector)                          │  Kernel
│  Bridges to the user-mode WUDFHost instance.         │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ HIDMaestro.dll (this driver) — UMDF2 lower filter    │  User mode
│  EvtIoDeviceControl handles GET_DEVICE_DESCRIPTOR,   │
│  GET_REPORT_DESCRIPTOR, READ_REPORT, GET_FEATURE,    │
│  SET_OUTPUT_REPORT, GET_STRING.                      │
└─────────────────────────────────────────────────────┘
```

**`mshidumdf.sys` is the function driver; HIDMaestro.dll is the lower filter.** This is the standard UMDF2 HID minidriver pattern from Microsoft's [`vhidmini2` sample](https://github.com/microsoft/Windows-driver-samples/tree/main/hid/vhidmini2). The HID class stack sees a real HID device because mshidumdf services the class queries; HIDMaestro just handles the IOCTLs that mshidumdf marshals down via `IOCTL_UMDF_HID_*` codes.

The driver compiles as a DLL (UMDF2 differs from KMDF in this), uses `EvtIoDeviceControl` (not `InternalDeviceControl`), and includes `<windows.h>` (not `<ntddk.h>`).

---

## Device context

`DEVICE_CONTEXT` is the per-device WDF context allocated by the framework on `EvtDeviceAdd`. The big picture:

```c
typedef struct _DEVICE_CONTEXT {
    WDFDEVICE   Device;

    /* HID descriptor — set by user-mode at create time, returned to HID class */
    UCHAR       ReportDescriptor[HIDMAESTRO_MAX_DESCRIPTOR_SIZE];   // 4 KB
    ULONG       ReportDescriptorSize;
    HID_DESCRIPTOR          HidDescriptor;
    HID_DEVICE_ATTRIBUTES   HidDeviceAttributes;
    ULONG       InputReportByteLength;
    UCHAR       FirstInputReportId;

    /* Latest input report cache (for READ_REPORT) */
    UCHAR       InputReport[HIDMAESTRO_MAX_REPORT_SIZE];   // 1 KB
    ULONG       InputReportSize;
    BOOLEAN     InputReportReady;
    ULONG       LastDeliveredInputSeqNo;   // seqno gate

    /* Strings */
    WCHAR       ProductString[128];
    ULONG       ProductStringBytes;
    WCHAR       SerialString[64];          // "HM-CTL-NNNN" for SDL3 disambiguation
    ULONG       SerialStringBytes;

    /* Queues */
    WDFQUEUE    DefaultQueue;     // parallel — HID IOCTLs
    WDFQUEUE    ManualQueue;      // manual — pended READ_REPORT requests

    /* Locks */
    WDFWAITLOCK InputLock;
    WDFWAITLOCK OutputLock;

    /* Shared memory: input */
    HANDLE      SharedMemHandle;
    PVOID       SharedMemPtr;          // HIDMAESTRO_SHARED_INPUT view
    ULONG       SharedMemSeqNo;
    HANDLE      InputDataEvent;        // OpenEvent on Global\HIDMaestroInputEvent<N>
    HANDLE      StopEvent;             // Global\HIDMaestroStopEvent<N>
    HANDLE      WorkerThread;
    WCHAR       InputEventName[64];
    WCHAR       StopEventName[64];

    /* Shared memory: output ring */
    HANDLE      OutputMemHandle;
    PVOID       OutputMemPtr;
    ULONG       OutputSeqNoLocal;      // last value we wrote (always increment)
    ULONG       OutputWriteCount;      // re-open every 500 writes (#2)

    /* Shared memory: PID FFB state */
    HANDLE      PidStateMemHandle;
    PVOID       PidStateMemPtr;
    WCHAR       PidStateMappingName[64];

    /* Per-instance identity */
    ULONG       ControllerIndex;
    WCHAR       ConfigRegPath[64];     // SOFTWARE\HIDMaestro\Controller<N>
    WCHAR       SharedMappingName[64]; // Global\HIDMaestroInput<N>
    WCHAR       OutputMappingName[64]; // Global\HIDMaestroOutput<N>
} DEVICE_CONTEXT;
```

The full struct is in [`driver/driver.h`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/driver.h#L74).

---

## EvtDeviceAdd

Called by the framework when PnP binds the driver to a device. Sequence:

1. **Create the WDF device.**
2. **Initialize per-instance paths** from `ControllerIndex` (read from the device HW key written by the SDK's `SetupController`). Builds:
   - `ConfigRegPath = "SOFTWARE\HIDMaestro\Controller<N>"`
   - `SharedMappingName = "Global\HIDMaestroInput<N>"`
   - `OutputMappingName = "Global\HIDMaestroOutput<N>"`
   - `PidStateMappingName = "Global\HIDMaestroPidState<N>"`
   - `InputEventName = "Global\HIDMaestroInputEvent<N>"`
   - `StopEventName = "Global\HIDMaestroStopEvent<N>"`
   - `SerialString = "HM-CTL-<index-zero-padded-to-4-digits>"`
3. **Read configuration** from `HKLM\SOFTWARE\HIDMaestro\Controller<N>`:
   - `ReportDescriptor` (REG_BINARY) &rarr; `ctx->ReportDescriptor`
   - `VendorId` / `ProductId` / `VersionNumber` (REG_DWORD) &rarr; `ctx->HidDeviceAttributes`
   - `HidAttrPid` (REG_DWORD, optional) &rarr; overrides `ProductID` in HID attributes only (companion still reads `ProductId` for XUSB identity). PID 0x0001 is used for xinputhid profiles to prevent GameInput / HIDAPI from claiming the device, so SDL3 falls through to its XInput backend with the correct identity.
   - `ProductString` (REG_SZ)
   - `InputReportByteLength` (REG_DWORD) for buffer sizing.
4. **Set HID device attributes** from the values just read.
5. **Create the parallel default queue** with `EvtIoDeviceControl` for HID IOCTLs.
6. **Create the manual queue** for pended `READ_REPORT` requests.
7. **Create the input lock and output lock.**
8. **Create the named events** (`InputDataEvent`, `StopEvent`).
9. **Open the shared input mapping** if it exists, **open the output mapping**, **open the PID state mapping** lazily.
10. **Spawn the worker thread.**

If any of the optional steps fails (e.g. the SDK hasn't created the shared sections yet because we're racing PnP binding against `SetupController`'s registry-then-create-mapping sequence), the driver continues. Subsequent `IOCTL_HID_READ_REPORT` calls retry the open, so PnP order races resolve themselves on the next call.

---

## Default HID descriptor (used when no registry override)

If `HKLM\SOFTWARE\HIDMaestro\Controller<N>\ReportDescriptor` is missing or empty, the driver falls back to a built-in Xbox 360-shaped descriptor: 6 axes (16-bit), 10 buttons, 1 hat, plus a Vendor-Defined Feature report (Report ID 2) for legacy data-channel use. ~120 bytes.

The fallback exists to make `EvtDeviceAdd` succeed even when the SDK is mid-`SetupController` and hasn't written the registry yet. The driver re-reads the registry on every PnP wake; once the SDK has written the real descriptor, subsequent `IOCTL_HID_GET_REPORT_DESCRIPTOR` returns the right bytes.

In normal operation the fallback is never delivered to a consumer because the SDK orchestrates the registry write before binding the driver. It's a safety net for the corner case of a PnP race or a corrupt registry.

---

## EvtIoDeviceControl: the dispatch table

Every HID class request marshals through here as one of the `IOCTL_UMDF_HID_*` codes from `<hidport.h>`:

| IOCTL | Handler |
|-------|---------|
| `IOCTL_HID_GET_DEVICE_DESCRIPTOR` | Return `ctx->HidDescriptor` (HID descriptor stub pointing at the report descriptor's length). |
| `IOCTL_HID_GET_DEVICE_ATTRIBUTES` | Return `ctx->HidDeviceAttributes` (VID, PID, VersionNumber). |
| `IOCTL_HID_GET_REPORT_DESCRIPTOR` | Copy `ctx->ReportDescriptor` to the output buffer. |
| `IOCTL_HID_READ_REPORT` | Seqno-gated cache hit OR pend in `ManualQueue`. See below. |
| `IOCTL_HID_WRITE_REPORT` | Capture as `HidOutput` source &rarr; output ring. |
| `IOCTL_UMDF_HID_GET_FEATURE` | Serve PID Pool / Block Load / State from PID state shared section. |
| `IOCTL_UMDF_HID_SET_FEATURE` | Capture as `HidFeature` source &rarr; output ring. Auto-allocate EBI on PID Create New Effect (Report ID 0x11). |
| `IOCTL_UMDF_HID_GET_INPUT_REPORT` | Synchronous read from the input cache (rare path; mostly used by HIDAPI). |
| `IOCTL_UMDF_HID_SET_OUTPUT_REPORT` | Capture as `HidOutput` source &rarr; output ring. |
| `IOCTL_HID_GET_STRING` | Return product / manufacturer / serial string per `HID_STRING_ID_*`. |
| (anything else) | Pass through with `STATUS_NOT_IMPLEMENTED`. |

### IOCTL constants: the v1.1.39 fix

Pre-1.1.39, the driver header defined fabricated `IOCTL_UMDF_HID_*` values:

```c
// WRONG values, pre-1.1.39
#define IOCTL_UMDF_HID_SET_FEATURE        0x00210003
#define IOCTL_UMDF_HID_GET_FEATURE        0x00210007
#define IOCTL_UMDF_HID_SET_OUTPUT_REPORT  0x0021000B
#define IOCTL_UMDF_HID_GET_INPUT_REPORT   0x0021000F
```

These don't match what mshidumdf delivers. WDK `<hidport.h>` provides the real values:

```c
// CORRECT, v1.1.39+
#define IOCTL_UMDF_HID_SET_FEATURE        HID_CTL_CODE(20)  // 0x000B0053
#define IOCTL_UMDF_HID_GET_FEATURE        HID_CTL_CODE(21)  // 0x000B0057
#define IOCTL_UMDF_HID_SET_OUTPUT_REPORT  HID_CTL_CODE(22)  // 0x000B005B
#define IOCTL_UMDF_HID_GET_INPUT_REPORT   HID_CTL_CODE(23)  // 0x000B005F
```

Pre-v1.1.39, every `SetFeature` / `GetFeature` / `SetOutputReport` / `GetInputReport` handler we shipped since v1.1.35 compiled but **never fired** &mdash; the case statement constants didn't match the framework's `IoControlCode`, so dispatch fell through to the default and returned `STATUS_NOT_IMPLEMENTED`.

The fix is to include `<hidport.h>` in `driver.h` and let the WDK header own the values. The `#ifndef` guards in `driver.h` are kept as a safety net but should never fire on a current WDK.

---

## `IOCTL_HID_READ_REPORT`: seqno gate + manual queue

The naive design completes every `IOCTL_HID_READ_REPORT` synchronously from the cached input buffer. That worked, but it caused HidClass.sys to hammer `READ_REPORT` in a tight loop because every call returned instantly with the same stale data &mdash; **CPU saturation** at scale (issue #3 root cause).

The fix is a **seqno gate**:

```c
NTSTATUS HandleReadReport(WDFREQUEST Request, PDEVICE_CONTEXT ctx)
{
    /* New data since last delivery? Complete synchronously. */
    if (ctx->SharedMemSeqNo > ctx->LastDeliveredInputSeqNo) {
        CompleteRequestWithCachedReport(Request, ctx);
        ctx->LastDeliveredInputSeqNo = ctx->SharedMemSeqNo;
        return STATUS_SUCCESS;
    }

    /* No new data — pend in ManualQueue. The worker thread completes us
       on the next ProcessSharedInput tick. */
    return WdfRequestForwardToIoQueue(Request, ctx->ManualQueue);
}
```

`ProcessSharedInput` (called by the worker thread on each `InputDataEvent` signal):

```c
VOID ProcessSharedInput(PDEVICE_CONTEXT ctx)
{
    ReadInputFrameSeqlocked(ctx);    // updates ctx->InputReport, ctx->SharedMemSeqNo

    /* Drain ManualQueue: every pended READ_REPORT gets the new bytes. */
    WDFREQUEST req;
    while (WdfIoQueueRetrieveNextRequest(ctx->ManualQueue, &req) == STATUS_SUCCESS) {
        CompleteRequestWithCachedReport(req, ctx);
    }
    ctx->LastDeliveredInputSeqNo = ctx->SharedMemSeqNo;
}
```

Idle CPU per-controller: ~0.04% (was ~3% per controller pre-fix). The worker thread sleeps on `WaitForMultipleObjects(StopEvent, InputDataEvent, 50ms)` &mdash; the 50 ms safety timeout ensures progress if a signal is ever dropped. Every input frame the SDK writes triggers `SetEvent(InputDataEvent)` which wakes the worker immediately.

---

## Worker thread

```c
DWORD WINAPI WorkerThread(LPVOID lpParam)
{
    PDEVICE_CONTEXT ctx = (PDEVICE_CONTEXT)lpParam;
    HANDLE waits[2] = { ctx->StopEvent, ctx->InputDataEvent };

    while (TRUE) {
        DWORD r = WaitForMultipleObjects(2, waits, FALSE, 50);
        if (r == WAIT_OBJECT_0) break;             // StopEvent
        if (r == WAIT_OBJECT_0 + 1 || r == WAIT_TIMEOUT) {
            ProcessSharedInput(ctx);
        }
    }
    return 0;
}
```

- **WAIT_OBJECT_0** &mdash; StopEvent fired; exit.
- **WAIT_OBJECT_0 + 1** &mdash; InputDataEvent fired; new frame; process and complete pended requests.
- **WAIT_TIMEOUT** &mdash; 50 ms safety tick; process opportunistically.

Created in `EvtDeviceAdd` and joined on stop. Cancellation via `SetEvent(StopEvent)` then `WaitForSingleObject(WorkerThread, 5000)`.

---

## Sony feature reports and why calibration cannot be zeros

`driver.c` answers the Sony arm-handshake feature reads (`0x05`, `0x09`,
`0x20`, `0x02`, `0xA3`), gated on VID `0x054C` so the IDs cannot collide
with an unrelated profile's own feature reports. Report `0x02` is also the
Feature Report ID the default Xbox 360 descriptor declares, which is
exactly the collision that gate prevents.

Those payloads were zero-filled until v1.4.4 (issue #43), and for the
calibration reports that was a defect rather than a shortcut. **Calibration
is a divisor, not decoration.** Every parser builds a sensitivity from the
plus/minus pairs, so a zero blob yields a zero denominator:

- SDL's `HIDAPI_DriverPS5_LoadCalibrationData` computes
  `(plus + minus) * RES / (pitchPlus - pitchMinus)`, which is `0.0f / 0`,
  so the sensitivity becomes NaN. SDL still enumerates the pad, because
  NaN gyro does not stop buttons or sticks. That is why SDL-based
  consumers looked unaffected while native-PlayStation titles rejected the
  device.
- Linux's `hid-playstation.c` checks `sens_denom == 0` at four sites, warns
  `"Invalid gyro calibration data for axis (%d), disabling calibration"`,
  and substitutes `S16_MAX`. The canonical driver defends against exactly
  what this driver used to emit.

The served payload is the neutral calibration from
[WinUHid](https://github.com/cgutman/WinUHid), a working virtual PS4/PS5
for Windows, with field offsets verified against `hid-playstation.c`: bias
at `buf[1..6]`, plus/minus at `buf[7..18]`, speed at `buf[19..22]`, accel
at `buf[23..34]`. Gyro and accel denominators come out at 20000 and
`speed_2x` at 1000.

It is deliberately order-agnostic. `hid-playstation.c` parses a DS4 over
USB as `pitch+ pitch- yaw+ yaw- roll+ roll-` but over Bluetooth as
`pitch+ yaw+ roll+ pitch- yaw- roll-`. Because every plus is +10000 and
every minus is -10000, one payload reads correctly under both orderings,
so the 37-versus-41-byte split needs no ordering branch.

Two sizing details worth keeping:

- **Report `0x09` is 20 bytes, not 17.** That is what the real DualSense
  descriptor declares and what `hid-playstation.c` requests, and
  `ps_get_report` requires the transferred count to equal the requested
  size exactly. A short reply fails on size before its contents are ever
  examined. The MAC sits at bytes 1..6 and is synthesised per controller
  in the locally-administered range, so it cannot collide with a real
  pad's globally-assigned address.
- **CRC is a Bluetooth-only gate.** `ps_get_report` verifies the trailing
  CRC32 only when `hdev->bus == BUS_BLUETOOTH`, so USB paths, including
  every composite persona, never reach it.

`UsbipEmulatedDevice` reproduces this table for composite personas, and the
two payload copies are asserted byte-identical. A consumer reading
calibration from a composite must see exactly what the plain profile
serves. `sony_feature_gate_check` (battery scenario S46) drives the real
UMDF2 path and computes the denominators the way SDL and Linux do.

---

## Switch Pro protocol responder

Most profiles are passive: the SDK submits state, the worker completes read requests. The Nintendo Switch Pro Controller (issue #33) is not. Hosts (SDL's `HIDAPI_DriverSwitch`, Steam, BetterJoy) drive a Nintendo init-and-subcommand protocol and stall without a device that answers, so the generic report-builder cannot express it. `driver.c` carries a hardcoded responder keyed on `VID 0x057E && PID 0x2009` (`ctx->SwitchProtocol`), with protocol in code and layout in JSON, the same split as the Sony vendor-blob work.

Three pieces:

- **USB init.** Commands `80 01` / `80 02` / `80 03` get their `81 xx` replies, reporting device type Pro and a stable fabricated MAC.
- **Subcommands.** Output report `0x01` gets input-report `0x21` replies per the nxbt responder table, including SPI-flash reads served from a fabricated image: factory stick calibration (center `0x800`, range `0x600`) and IMU coefficients (`0x4000` accel, `0x343B` gyro) chosen so SDL's `LoadIMUCalibration` / `LoadStickCalibration` math reduces exactly to its own default scales. Unknown subcommands get a generic ACK rather than nxbt's silent ignore, because SDL retries an unanswered subcommand for ~500 ms where the Switch console does not.
- **0x30 streaming.** A dedicated `SwitchStreamProc` thread serves input report `0x30` at the wire's ~60 Hz cadence (15 ms), reading the latest consumer-submitted body via `SwitchFillLatestState` and stamping live timer and battery bytes over it. Subcommand replies preempt the stream via `SwitchQueueReply`.

`SwitchStreamProc` and the worker thread both touch `ctx->SharedMemPtr`. The worker's stale-handle recycle skips the shared-view unmap for `SwitchProtocol` devices (the view is unmapped only at cleanup, after both threads join) so it can never unmap the mapping out from under the streaming thread mid-read.

SDK side, `SwitchProPacker` converts a normal `SubmitState` into the 48-byte `0x30` body: layout-mapped buttons, 12-bit nibble-packed sticks, and the calibrated IMU channel. `HMGamepadState.AccelG*` / `GyroDps*` are defined in the SDL-standard sensor frame. The packer owns the SDL-to-Switch wire-frame permutation, so a consumer that reads motion from SDL submits it verbatim and the client-side SDL reconstructs the identical vector. HD rumble comes back decoded to coarse `leftMotor` / `rightMotor` amplitudes on `OutputDecoded`, the same lane Sony rumble rides. The `test/probes/switch_pro_check` probe replays SDL's exact init sequence over raw HID as the release gate, and `switch_pro_sdl3_check` drives the pad through real SDL3 end to end.

---

## Output ring writes

When an output IOCTL arrives (`SET_OUTPUT_REPORT`, `SET_FEATURE`, `WRITE_REPORT`):

1. Take `OutputLock`.
2. `EnsureOutputMapping` &mdash; opens the output section if not already; periodic re-open every 500 writes for stale-handle recovery (issue #2). LocalService can't `CreateFileMapping(Global\)`, so it can only `OpenFileMapping` the section the elevated SDK created.
3. Increment `Head` to get the new SeqNo.
4. Write `Slots[(Head - 1) % 64]` with `Source`, `ReportId`, `DataSize`, `Data`.
5. Write `SeqNo` last (memory barrier).
6. Release `OutputLock`.

The 8 ms SDK-side polling interval has 64 × 8 = 512 ms of headroom before the oldest packet would be overwritten. See [Output Passthrough](../sdk/output-passthrough.md).

---

## PID FFB: driver-side EBI auto-allocation

When `IOCTL_UMDF_HID_SET_FEATURE` arrives with Report ID 0x11 (PID Create New Effect), the driver:

1. `EnsurePidStateMapping` &mdash; opens the PID state section R/W (the v1.1.39 fix; pre-v1.1.39 it was opened FILE_MAP_READ which AV'd inside the driver-side write).
2. Reads `EbiAllocBitmap` atomically. Picks the lowest free bit.
3. `InterlockedOr(&bitmap, 1u << freeBit)` to claim the EBI.
4. Acquires PID state's seqlock (increment SeqNo; +1 = mid-write, +2 = stable).
5. Writes `BL_EffectBlockIndex = freeBit + 1`, `BL_LoadStatus = Success`, `BL_RAMPoolAvailable`.
6. Releases seqlock (SeqNo += 1 to even).
7. Increments `EbiAllocatedCount` atomically.
8. Returns `STATUS_SUCCESS`.

`pid.dll`'s follow-up `GetFeature(0x12 BlockLoad)` reads from the same shared section, which the driver's IOCTL handler also sources from. The handshake completes within `pid.dll`'s synchronous IOCTL pair without waiting on user-mode. Mirrors vJoy's `Ffb_GetNextFreeEffect`. See [Force Feedback](../sdk/force-feedback.md) for the SDK side.

If the bitmap is full when an allocation request arrives, the driver writes `BL_LoadStatus = Full`, `BL_EffectBlockIndex = 0`, and returns success. `pid.dll` propagates this to the game.

`PID Block Free` (Output 0x1B) writes are captured to the output ring as `HidOutput` so the consumer's `OutputReceived` handler gets a chance to wire the EBI back to its own tracking. The driver does **not** auto-clear the bitmap on Block Free &mdash; deliberate; the consumer is responsible for that bookkeeping. Trusting `pid.dll` to send Block Free for every allocation it released and ignoring the driver-side bitmap maintenance is the canonical pattern.

---

## `IOCTL_UMDF_HID_GET_FEATURE`: PID state read

When the consumer pulls a Feature report ID 0x12 / 0x13 / 0x14, the driver reads the PID state section seqlocked:

```c
static BOOLEAN ReadPidState(PDEVICE_CONTEXT ctx, HIDMAESTRO_SHARED_PID_STATE *out)
{
    if (ctx->PidStateMemPtr == NULL && !EnsurePidStateMapping(ctx))
        return FALSE;

    volatile HIDMAESTRO_SHARED_PID_STATE *src = ctx->PidStateMemPtr;
    ULONG seq1, seq2;
    int retries = 4;
    do {
        seq1 = src->SeqNo;
        if (seq1 & 1) { seq1 = src->SeqNo; }   // mid-write — re-read once
        MemoryBarrier();
        out->PidEnabled            = src->PidEnabled;
        out->BL_EffectBlockIndex   = src->BL_EffectBlockIndex;
        // ... copy all fields
        MemoryBarrier();
        seq2 = src->SeqNo;
        if (seq1 == seq2 && !(seq1 & 1)) break;
    } while (--retries > 0);
    return seq1 == seq2 && !(seq1 & 1);
}
```

Standard seqlock read. If the publisher (the SDK consumer's `PublishPid*` call) is mid-write, `seq1 & 1`; the snapshot is unstable. Re-read up to 4 times.

If `PidEnabled == 0` (consumer hasn't called `PublishPidPool` yet), the driver returns `STATUS_NO_SUCH_DEVICE` for the Pool Report (matches vJoy's "FFB not enabled" convention so DInput cleanly concludes "device exists but no FFB" without retrying) and `STATUS_NOT_SUPPORTED` for Block Load / State.

---

## DACL on the shared sections

The SDK creates the shared sections with the SDDL `D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;WD)` &mdash; SYSTEM, BUILTIN\Administrators, and Everyone get `GENERIC_ALL`. This is required because:

- The SDK consumer process (admin) writes input frames.
- WUDFHost runs as LocalService (which lacks `SeCreateGlobalPrivilege`, so the driver can NOT create the section) and must `OpenFileMapping` to read.
- Unelevated WGI / GameInput consumers also need to read shared sections in some indirect paths.

`Everyone GENERIC_ALL` looks loose, but the section content is one virtual controller's HID state &mdash; not security-sensitive. The boundary is the IOCTL surface, which is mediated by the kernel HID stack and not by the shared section permissions.

---

## Self-cleanup at unload

When the device is removed (via `DIF_REMOVE` from the SDK or PnP), `EvtDeviceContextCleanup` runs:

1. `SetEvent(StopEvent)` to wake the worker.
2. `WaitForSingleObject(WorkerThread, 5000)`. Join.
3. `CloseHandle(WorkerThread)`.
4. Unmap and close all three shared sections.
5. Close the named events.

The framework calls `EvtDeviceContextCleanup` on the final reference release. WUDFHost may exit shortly after if no other devices are left in the host (per-instance host model).

---

## INF: `hidmaestro.inf`

Class `HIDClass`, ClassGuid `{745a17a0-...}`. PnP install matches `root\HIDMaestro`. The SDK creates devices via `SetupDiCreateDeviceInfoW` (plain HID profiles) or `SwDeviceCreate` (xinputhid profiles); both paths produce devnodes that match this INF.

Key sections:

```
[HIDMaestro_Install.NT.HW]
HKR,,"LowerFilters",0x00010008,"WUDFRd"
HKR,,Security,,"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;WD)"

[HIDMaestro_Install.NT.Services]
AddService = mshidumdf,0x000001fa,mshidumdf_Service
AddService = WUDFRd,0x000001f8,WUDFRD_Service

[HIDMaestro_Install.NT.Wdf]
UmdfService                 = HIDMaestro, HIDMaestro_UmdfService
UmdfKernelModeClientPolicy  = AllowKernelModeClients
UmdfFileObjectPolicy        = AllowNullAndUnknownFileObjects
UmdfMethodNeitherAction     = Copy
UmdfFsContextUsePolicy      = CanUseFsContext2
UmdfHostProcessSharing      = ProcessSharingDisabled    ← critical
```

`UmdfHostProcessSharing = ProcessSharingDisabled` means each device instance gets its own WUDFHost. Default is `ProcessSharingEnabled` which pools every instance into one shared host &mdash; we hit non-linear CPU saturation on that path and the per-instance host model is what makes 6 mixed controllers actually scale. See [`docs/investigations/issue3-dual-xinputhid-saturation-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/issue3-dual-xinputhid-saturation-2026-04).

The INF carries **no `xinputhid` UpperFilter** at the HID level. The SDK writes that string per-instance after device creation, **only for profiles with an XUSB companion** &mdash; for non-companion profiles (DualSense, Xbox Series BT, Switch Pro), the HID path IS the only WGI Gamepad source, and blocking it with xinputhid would produce zero Gamepads.

---

## Self-contained, no MSVCRT

The driver doesn't link against MSVCRT. `swprintf` / `wsprintf` aren't available. The `AppendUlongDecimal` helper at the top of `driver.c` is hand-rolled string building. Linking MSVCRT into a UMDF2 driver is technically possible but introduces a dependency on a redistributable that LocalService might not have access to. Self-contained is simpler.

---

## Source layout summary

| Function | Lines (approx) | Purpose |
|----------|----------------|---------|
| `DriverEntry` | 30 | Framework entry, register `EvtDeviceAdd` |
| `EvtDeviceAdd` | 250 | Parse registry, create queues/locks/events, spawn worker |
| `InitInstancePaths` | 80 | Build per-instance section/registry path strings |
| `LoadConfigurationFromRegistry` | 100 | Read descriptor, VID/PID, version, strings |
| `EvtIoDeviceControl` | 200 | IOCTL dispatch table |
| `HandleReadReport` | 80 | Seqno gate, sync complete or pend in ManualQueue |
| `HandleGetFeature` | 200 | PID FFB state queries from shared section |
| `HandleSetFeature` | 150 | EBI auto-alloc on Report ID 0x11; output ring publish |
| `HandleSetOutputReport` | 80 | Output ring publish |
| `WorkerThread` + `ProcessSharedInput` | 80 | Event-driven shared-mem read, manual queue drain |
| `EnsureOutputMapping` / `EnsurePidStateMapping` / etc. | 100 | Lazy mapping helpers |

Total: 1,574 lines (driver.c) + 414 lines (driver.h) + 745 lines (companion.c) + 286 lines (hmswd.c).

---

## See also

- [Architecture Overview](architecture-overview.md) &mdash; the driver's position in the full stack.
- [XUSB Companion](xusb-companion.md) &mdash; the second UMDF2 driver, for non-xinputhid Xbox profiles.
- [Shared Memory Protocol](shared-memory-protocol.md) &mdash; wire formats for input, output ring, PID state.
- [SwDevice and PnP](swdevice-and-pnp.md) &mdash; how device nodes get created and torn down.
- [Force Feedback](../sdk/force-feedback.md) &mdash; SDK-side counterpart to the PID state read/write protocol.
- [Output Passthrough](../sdk/output-passthrough.md) &mdash; SDK-side counterpart to the output ring.
- [Driver Install and Signing](driver-install-and-signing.md) &mdash; how the INF gets registered and the DLL gets signed.

## References

- UMDF2 framework primer &mdash; search Microsoft Learn for "User-Mode Driver Framework version 2".
- [vhidmini2 sample](https://github.com/microsoft/Windows-driver-samples/tree/main/hid/vhidmini2) &mdash; the Microsoft-provided reference HIDMaestro's pattern descends from.
- `hidport.h` &mdash; the WDK header that defines the canonical `IOCTL_UMDF_HID_*` codes (`HID_CTL_CODE(20)`, `(21)`, `(22)`, `(23)`).
- WDF directives reference &mdash; search Microsoft Learn for "Specifying WDF Directives in INF Files" (covers `UmdfHostProcessSharing` and friends).
- HID architecture &mdash; search Microsoft Learn for "HID Architecture".
- [`docs/investigations/issue3-dual-xinputhid-saturation-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/issue3-dual-xinputhid-saturation-2026-04) &mdash; the WUDFHost saturation root cause.
- [References](references.md) &mdash; full source bibliography.
