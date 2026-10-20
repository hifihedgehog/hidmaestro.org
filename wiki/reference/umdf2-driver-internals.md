# UMDF2 Driver Internals

`HIDMaestro.dll` is a UMDF2 lower filter driver under `mshidumdf.sys`. This page documents the driver's responsibilities, the IOCTL dispatch table, the device context, the worker thread, the seqno-gated `READ_REPORT` path, and the empirical reasons each design choice exists. UMDF2 framework reference: search Microsoft Learn for "User-Mode Driver Framework version 2".

Source: [`driver/driver.c`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/driver.c) (2,782 lines), [`driver/driver.h`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/driver.h) (526 lines).

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
│ HIDMaestro.dll (this driver): UMDF2 lower filter    │  User mode
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

    /* HID descriptor: set by user-mode at create time, returned to HID class */
    UCHAR       ReportDescriptor[HIDMAESTRO_MAX_DESCRIPTOR_SIZE];   // 4 KB
    ULONG       ReportDescriptorSize;
    HID_DESCRIPTOR          HidDescriptor;
    HID_DEVICE_ATTRIBUTES   HidDeviceAttributes;
    ULONG       InputReportByteLength;
    UCHAR       FirstInputReportId;        // the report a data-only frame goes out as
    BOOLEAN     InputReportIdConfigured;   // v2.0.0: taken from the SDK's InputReportId

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
    WDFQUEUE    DefaultQueue;     // parallel: HID IOCTLs
    WDFQUEUE    ManualQueue;      // manual: pended READ_REPORT requests

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
    /* ...the owner pipe fields, then (v2.0.0): */
    WCHAR       VersionMappingName[64]; // Global\HIDMaestroVersion<N>
} DEVICE_CONTEXT;
```

The full struct is in [`driver/driver.h`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/driver.h#L74).

---

## EvtDeviceAdd

Called by the framework when PnP binds the driver to a device. Sequence:

1. **Create the WDF device.**
2. **Initialize per-instance paths** from `ControllerIndex`. As of v2.0.0 the driver reads its device instance ID before `WdfDeviceCreate`, takes the identity token from its last segment and reads the index from `HKLM\SOFTWARE\HIDMaestro\Identity\<token>`, which the SDK writes before any PnP work. Since v2.0.0 that is the controller's machine-wide transport index, which can differ from the SDK slot. The driver neither knows nor needs the difference. Builds:
   - `ConfigRegPath = "SOFTWARE\HIDMaestro\Controller<N>"`
   - `SharedMappingName = "Global\HIDMaestroInput<N>"`
   - `OutputMappingName = "Global\HIDMaestroOutput<N>"`
   - `PidStateMappingName = "Global\HIDMaestroPidState<N>"`
   - `InputEventName = "Global\HIDMaestroInputEvent<N>"`
   - `StopEventName = "Global\HIDMaestroStopEvent<N>"`
   - `VersionMappingName = "Global\HIDMaestroVersion<N>"` (v2.0.0)
   - `SerialString = "HM-CTL-<index-zero-padded-to-4-digits>"`
3. **Read configuration** from `HKLM\SOFTWARE\HIDMaestro\Controller<N>`:
   - `ReportDescriptor` (REG_BINARY) &rarr; `ctx->ReportDescriptor`
   - `VendorId` / `ProductId` / `VersionNumber` (REG_DWORD) &rarr; `ctx->HidDeviceAttributes`
   - `LiveFeatureReport` (REG_DWORD, v2.0.0): one plus the ID of a feature report whose answer is the latest one the SDK wrote, as `dualshock-3-full`'s report 0 is.
   - `CachedInputReportIds` (REG_BINARY, v2.0.0, read only under the version contract): the profile's input report IDs.
   As of v2.0.0 `HidAttrPid` is no longer read. A profile's `driverPid` goes into the parent's hardware IDs, where xinputhid's INF matches it.
   - `ProductString` (REG_SZ)
   - `InputReportByteLength` (REG_DWORD) for buffer sizing.
   - `FeatureAnswers` (REG_BINARY, v2.0.0): the controller's compiled feature answer table, read only under the version contract (see [Version announcement](#version-announcement-v200)). Without it the driver serves no feature answers.
   - `InputReportId` (REG_BINARY, v2.0.0, read only under the version contract): the input report a data-only frame fills, in byte 0, its length as a 32-bit little-endian value in bytes 1-4, then the report descriptor the SDK read both from. The driver takes the ID only when that length equals the `InputReportByteLength` it has just read and the descriptor is the one in use, so a value a killed program left never pairs its ID with the length a v1.12.0 program writes for the same index. Without a value that passes, `EvtDeviceAdd` takes the first Report ID item of the descriptor's first Application Collection, as every earlier driver did.
4. **Set HID device attributes** from the values just read.
5. **Create the parallel default queue** with `EvtIoDeviceControl` for HID IOCTLs.
6. **Create the manual queue** for pended `READ_REPORT` requests.
7. **Create the input lock and output lock.**
8. **Open the input event and create the stop event** (`InputDataEvent`, which the SDK creates, and `StopEvent`). As of v2.0.0 the driver creates `StopEvent` and the output event with `D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;LS)`, so a program that is not elevated cannot open them. A `StopEvent` name another program made first is not used, and the worker gets an unnamed stop event. See [Shared Memory Protocol](shared-memory-protocol.md#section-names).
9. **Open the shared input mapping** if it exists, **open the output mapping**, **open the PID state mapping** lazily.
10. **Spawn the worker thread.**

If any of the optional steps fails (e.g. the SDK hasn't created the shared sections yet because we're racing PnP binding against `SetupController`'s registry-then-create-mapping sequence), the driver continues. Subsequent `IOCTL_HID_READ_REPORT` calls retry the open, so PnP order races resolve themselves on the next call.

---

## A devnode with no configuration

As of v2.0.0 the drivers keep no default device. A devnode with no index, neither an identity entry nor a `ControllerIndex`, or with no `Controller<index>` key holding a descriptor, fails its start with STATUS_DEVICE_CONFIGURATION_ERROR. Through v1.12.0 both drivers started such a devnode as an Xbox 360 pad on `Controller0`, from a built-in descriptor.

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

Pre-v1.1.39, every `SetFeature` / `GetFeature` / `SetOutputReport` / `GetInputReport` handler we shipped since v1.1.35 compiled but **never fired**: the case statement constants didn't match the framework's `IoControlCode`, so dispatch fell through to the default and returned `STATUS_NOT_IMPLEMENTED`.

The fix is to include `<hidport.h>` in `driver.h` and let the WDK header own the values. The `#ifndef` guards in `driver.h` are kept as a safety net but should never fire on a current WDK.

---

## `IOCTL_HID_READ_REPORT`: seqno gate + manual queue

The naive design completes every `IOCTL_HID_READ_REPORT` synchronously from the cached input buffer. That worked, but it caused HidClass.sys to hammer `READ_REPORT` in a tight loop because every call returned instantly with the same stale data: **CPU saturation** at scale (issue #3 root cause).

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

    /* No new data: pend in ManualQueue. The worker thread completes us
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

Idle CPU per-controller: ~0.04% (was ~3% per controller pre-fix). The worker thread sleeps on `WaitForMultipleObjects(StopEvent, InputDataEvent, 500ms)`: the 500 ms safety timeout ensures progress if a signal is ever dropped. Every input frame the SDK writes triggers `SetEvent(InputDataEvent)` which wakes the worker immediately.

---

## Worker thread

```c
DWORD WINAPI WorkerThread(LPVOID lpParam)
{
    PDEVICE_CONTEXT ctx = (PDEVICE_CONTEXT)lpParam;
    HANDLE waits[2] = { ctx->StopEvent, ctx->InputDataEvent };

    for (;;) {
        DWORD rc = WaitForMultipleObjects(2, waits, FALSE, 500);

        /* issue #38: the flag is the exit condition, not the signal. */
        if (ctx->TearingDown) return 0;

        if (rc == WAIT_OBJECT_0) {          /* foreign signal: absorb, recycle */
            ResetEvent(ctx->StopEvent);
            if (ctx->TearingDown) return 0;
            break;
        }
        if (rc == WAIT_OBJECT_0 + 1) { ProcessSharedInput(ctx); continue; }
        if (rc == WAIT_TIMEOUT && ++idleTimeouts < 8) continue;
        break;                              /* recycle handles */
    }
    return 0;
}
```

- **TearingDown flag**: checked on every wake, including timeouts. It is the only exit condition. The `StopEvent` signal cannot be trusted in either direction, because a foreign sweep signals without teardown and a same-index sibling's device-start `ResetEvent` can eat our own cleanup's `SetEvent` on the shared named object. Worst-case exit latency is one 500 ms wait, inside cleanup's 2 s join.
- **WAIT_OBJECT_0**: a foreign StopEvent signal. Absorbed with `ResetEvent`, then the handles recycle.
- **WAIT_OBJECT_0 + 1**: InputDataEvent fired; new frame; process and complete pended requests.
- **WAIT_TIMEOUT**: 500 ms safety tick. A single timeout is the normal idle state, and handles recycle only after 8 consecutive ones.

Created in `EvtDeviceAdd` and joined on stop. Cancellation via `SetEvent(StopEvent)` plus the `TearingDown` flag, then `WaitForSingleObject(WorkerThread, 2000)`.

---

## Sony feature reports and why calibration cannot be zeros

The driver answers the Sony arm-handshake feature reads (`0x05`, `0x09`,
`0x20`, `0x02`, `0xA3`) from the controller's `FeatureAnswers` table. As
of v2.0.0 the answers are profile data: six models under
`profiles/models` hold each pad's table, the Sony profiles name theirs with
`deviceModelFrom`, and the driver holds no Sony code and checks no VID. It
serves the table only for a 2.0.0 SDK's controller (see
[Version announcement](#version-announcement-v200)). Through v1.12.0 the
answers were code in `driver.c`, gated on VID `0x054C`.

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

Since v1.10.0 the served payload is the identity calibration for the
pads' own units, with field offsets verified against `hid-playstation.c`:
bias at `buf[1..6]` (zero), plus/minus at `buf[7..18]` (plus and minus
8000), speed at `buf[19..22]` (500 each), accel at `buf[23..34]` (plus and
minus 8192). SDL and `hid-playstation.c` turn that into exactly 16 counts
per degree per second and 8192 per g, the units the SDK's motion fields
carry. The v1.4.4 payload, the neutral calibration from
[WinUHid](https://github.com/cgutman/WinUHid) at plus and minus 10000,
scaled rotation by 0.8 and acceleration by 0.82 in both.

The field order follows the pad. `hid-playstation.c` and DS4Windows parse
a DS4 over USB (report `0x02`) as `pitch+ pitch- yaw+ yaw- roll+ roll-`
but over Bluetooth (report `0x05`) as `pitch+ yaw+ roll+ pitch- yaw-
roll-`. Readers that take absolute values, SDL's PS4 driver and
`hid-playstation.c`, read one payload the same under both orders.
DS4Windows subtracts the minus reference from the plus one as it stands,
so the USB order served over Bluetooth gave it a negative yaw denominator
and an inverted yaw. The driver serves report `0x05` in the Bluetooth
order when the product id is a DualShock 4 (0x05C4, 0x09CC or 0x0BA0) and
in the DualSense order otherwise. Over Bluetooth, reports `0x05`, `0x09`
and `0x20` end with a CRC-32 seeded with `0xA3`. `hid-playstation.c`
checks it, and RPCS3 closes a Bluetooth DualShock 4 whose calibration fails
the check three times.

Two sizing details worth keeping:

- **Report `0x09` is 20 bytes, not 17.** That is what the real DualSense
  descriptor declares and what `hid-playstation.c` requests, and
  `ps_get_report` requires the transferred count to equal the requested
  size exactly. A short reply fails on size before its contents are ever
  examined. The MAC sits at bytes 1..6 and is synthesized per controller
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

### Firmware info (`0x20`) is validated too, not just read (v1.4.6)

Calibration was not the only degenerate blob. Report `0x20`, the DS5
firmware info, was zero-filled apart from one byte, on the reasoning that
the only consumer known at the time read nothing else. A game with native
PlayStation support proved otherwise: a USB capture of F1 22's startup
shows it issuing `0x09`, the report descriptor twice, then `0x20`, and on
a zeroed reply it abandons the device and repeats the whole sequence every
500 ms indefinitely. It dies before calibration is ever requested, which
is why fixing `0x05` changed nothing for it.

`0x20` now serves a real 64-byte blob captured from physical hardware,
verbatim. Which field the game validates is not known, so no byte is
synthesized. Two independent consumers agree on the layout:
`hid-playstation.c` reads `hw_version` at le32 `buf[24]`, `fw_version` at
le32 `buf[28]` and `update_version` at le16 `buf[44]`, while
dualsense-tester reads the build date at 1..11, the time at 12..19,
`fwType` le16 at 20, `hwInfo` le32 at 24, `mainFwVersion` le32 at 28 and
`updateVersion` le16 at 44.

WinUHid ships its own default blob and it is deliberately not used here.
It reports `fwType` 4, which fails dualsense-tester's `fwType ∈ {2,3}`
render gate. The captured blob reports 3 and satisfies both consumers.

The cost of serving hardware's own bytes is that the build date belongs to
the pad they came from, so every virtual DualSense reports it. WinUHid
makes the same trade with a single fixed default for every emulated pad.

### Serving real values in `0x20` forced `0x22` to answer

Worth stating because it is the kind of coupling that turns one fix into
one fix and one regression. dualsense-tester runs a traceability branch
when `hwInfo & 0xFFFF >= 777` and `mainFwVersion >= 65655`. Both are true
of the real blob and both were false of the zeros, so that branch was
previously unreachable. It opens by reading feature `0x22`, and every
report ID outside the Sony gate falls through to `STATUS_NOT_SUPPORTED`.

Shipping `0x20` alone would therefore have fixed the game by breaking the
Factory Info panel that already worked. `0x22` is now served on both
backends at the 64 bytes the descriptor declares. Its payload is zero past
the report ID, and that is the honest value rather than a stub:
`getBtPatchInfo` reads a le32 at offset 31 and its caller drops the row
when the result is falsy, so zero reads as "this pad carries no Bluetooth
patch". The report ID itself must be present, because that function bails
when byte 0 is not `0x22`.

Both lanes assert the 64 bytes against a literal spelled out in each probe
(S43 for the composite backend, S46 for UMDF2), so the two copies cannot
drift apart silently.

### The DualShock 4's pairing read, `0x12` (v1.4.7)

The DS4's equivalent of `0x09`, and the one Sony read whose absence is
fatal rather than cosmetic. Every USB DualShock 4 profile declares it at 16
bytes and the driver did not serve it until v1.4.7, so a declared report
answered `STATUS_NOT_SUPPORTED`.

`hid-playstation.c` requests it in `dualshock4_get_mac_address` on USB, and
the caller returns `ERR_PTR` when it fails, so the device is never created.
The `0xA3` firmware read directly below it only warns and continues. SDL
reads the same report as `k_ePS4FeatureReportIdSerialNumber` and rejects an
all-zero address, so a zero-filled reply would not have satisfied it
either. Both take the MAC from bytes 1..6.

It serves the same stable per-controller locally-administered address the
`0x09` path synthesizes. Bluetooth deliberately does not get it:
`hid-playstation` takes the DS4's BT address from HIDP's `hdev->uniq`, and
a real `dualshock-4-v2-bt` descriptor does not declare `0x12`.

### Why the Edge needs its own firmware line (v1.4.7)

The `0x20` capture came from a base DualSense, and the gate keys on
VendorID with no PID branch, so Edge personas served it verbatim and
claimed the base pad's identity.

Sony's firmware-updater data records the base pad as Type `0004` and the
Edge as Type `0044`. The captured blob carries `swSeries` `0x0004` and
`updateVersion` `0x0630`, matching Sony's "DualSense, Type 0004, version
0x0630" entry exactly. That agreement is what identifies those two offsets
rather than inferring them from field names, and independently confirms the
capture is genuine. PID `0x0DF2` now reports `0x0044` and `0x0217`.

Everything else in the Edge's blob is still the base pad's. No public dump
of an Edge `0x20` exists, and dualshock-tools does not map the Edge's
`hwinfo` at all, skipping Board Model when `is_edge`. Nothing observed
reads those fields on an Edge, since `hid-playstation` derives
`use_vibration_v2` and `is_edge` from the PID and dualsense-tester's Edge
page hardcodes its traceability gate, but that argues the inheritance is
harmless rather than correct.

### The full Sony startup surface

`0x02`, `0x05`, `0x09`, `0x12`, `0x20`, `0x22` and `0xA3`, each served on
both backends. Feature `0x03` (capabilities) is deliberately absent: SDL
reads it only on its third-party detection path, and both its PS4 and PS5
drivers return early for a genuine Sony VID/PID, so a pad carrying Sony IDs
is never asked for it.

---

## Switch Pro protocol

Most profiles are passive: the SDK submits state, the worker completes read requests. The Nintendo Switch Pro Controller (issue #33) is not. Hosts (SDL's `HIDAPI_DriverSwitch`, Steam, BetterJoy) drive a Nintendo init-and-subcommand protocol and stall without a device that answers. As of v2.0.0 that protocol is data in `profiles/nintendo/switch-pro.json`, and the SDK's protocol host (`Internal/ProtocolHost.cs`) runs it. The driver keeps no Switch Pro code. It sends each frame the SDK writes and publishes each output report as written. The SDK's output reader hands the report to the protocol before it raises `OutputReceived`, and a reply goes out ahead of the next report once the driver has delivered the frame before it.

- **USB init.** `switch-pro-usb` carries the pad's 203-byte USB descriptor and its USB protocol: commands `80 01` / `80 02` / `80 03` get their `81 xx` replies, reporting device type Pro and a stable fabricated MAC, and its replies and reports are 64 bytes. `switch-pro` carries the Bluetooth descriptor, which declares no `0x80`/`0x81` family.
- **Subcommands.** Output report `0x01` gets input-report `0x21` replies per the nxbt responder table, including SPI-flash reads served from a fabricated image: factory stick calibration (center `0x800`, range `0x600`) and IMU coefficients (`0x4000` accel, `0x343B` gyro) chosen so SDL's `LoadIMUCalibration` / `LoadStickCalibration` math reduces exactly to its own default scales. Unknown subcommands get a generic ACK rather than nxbt's silent ignore, because SDL retries an unanswered subcommand for ~500 ms where the Switch console does not.
- **Reports on the device clock.** Full-mode `0x30` goes out every 15 ms on the device clock's grid, its timer byte counted per message. Genuine 12-byte `0x3F` simple-mode frames go out when the state changes, before the handshake and after a host selects simple mode, as a real pad sends them. Through v1.12.0 a driver thread slept 15 ms between frames, about 15.6 ms at the default timer resolution, streamed `0x3F` every 15 ms before the handshake, and sent nothing in mode `0x3F`.

The profile's `stateBlock` turns a normal `SubmitState` into the `0x30` body: layout-mapped buttons, 12-bit nibble-packed sticks, and the calibrated IMU channel. `HMGamepadState.AccelG*` / `GyroDps*` are defined in the SDL-standard sensor frame, and the state block's fields own the SDL-to-Switch wire-frame permutation, so a consumer that reads motion from SDL submits it verbatim and the client-side SDL reconstructs the identical vector. A raw submit is that state block. HD rumble comes back decoded to coarse `leftMotor` / `rightMotor` amplitudes on `OutputDecoded` through `protocol.decoders.rumble`, the same lane Sony rumble rides. A profile made outside the catalog with the Switch Pro's VID and PID takes one of the two catalog models through its identity default, by connection. The `test/probes/switch_pro_check` probe replays SDL's exact init sequence over raw HID as the release gate, `switch_pro_sdl3_check` drives the pad through real SDL3 end to end, and `device_oracle_check switch-engine` holds the profile data to the responder the 1.x driver ran.

---

## Switch 2 Pro: no responder needed (v1.5.0)

The Switch 2 Pro Controller (`057E:2069`) is a protocol device like its predecessor, but unlike the Switch Pro it does **not** need a driver-side responder, and that difference is worth understanding before anyone adds one.

A Switch 2 Pro declares three reports. `0x05` is a 63-byte vendor blob that a Nintendo protocol host reads, `0x09` is a structured gamepad view with 21 buttons and four 12-bit axes, and `0x02` is output. The device powers up emitting `0x09` and switches to `0x05` only when a host sends the `subUSBSelectReport` subcommand. So the pad is a complete, usable gamepad over plain HID before any handshake happens, which is exactly what the profile targets: report `0x09`, no protocol code, no `driver.c` changes. The profile marks its `extendedReport` `alwaysArmed` for the same reason. There is no handshake to wait for, and the descriptor's first declared report is the opaque `0x05` blob, so a profile that waited would present a live device that never moves.

The whole format was reconstructed from source rather than captured from hardware. VIIPER's `device/ns2pro` supplies the descriptor item list and the report builders, SDL's `SDL_hidapi_switch2.c` independently confirms the button bits, and switch2-controllers-linux confirms them a third time. The predecessor profile's note claiming a hardware capture was required was simply wrong.

**What SDL does with it, measured rather than assumed.** SDL routes this VID/PID to its own Switch 2 driver, and that driver is out of reach: `HIDAPI_DriverSwitch2_InitUSB` wants libusb or WinUSB on the controller's second interface, and `HIDAPI_DriverSwitch2_InitBluetooth` is an unimplemented stub upstream that returns "Nintendo Switch2 controllers not supported over Bluetooth". A UMDF2 HID profile presents one HID interface and can offer neither, so `InitDevice` fails.

What happens next is the part the withdrawn first cut of v1.5.0 asserted without testing. SDL cleans the driver up, the pad falls through to SDL's Windows backend, and it does arrive at the joystick layer with all 21 buttons and 4 axes carrying live input. It is not promoted to the gamepad layer, though, because SDL synthesizes mappings only for its HIDAPI, RawInput, WGI and XInput devices, and this pad is too new for `SDL_gamepad_db.h`. The profile's `sdlMapping` field closes that: a consumer prepends the runtime GUID and registers it, and SDL then reports a full gamepad including GR, GL and C. Gyro, accelerometer and HD rumble stay unavailable through SDL, since those ride the switch2 driver. `test/probes/switch2_pro_sdl3_check` gates all of it against a real SDL3 with a Switch Pro virtual as the same-window positive control.

**Two encoder features exist because of this pad.** `stick12-pair` packs two 12-bit axes into three shared bytes, and it is one field rather than two because the middle byte carries X's high nibble alongside Y's low nibble. `DPAD_UP` / `DOWN` / `LEFT` / `RIGHT` are button-mask sentinels sourced from `HMHat`, because report `0x09` spells the d-pad as four discrete bits with no hat. Diagonals set both components.

**The axis map is load-bearing.** The canonical trigger axes default to Z and Rz, and Rz is this pad's right stick Y. Without an `axisMap` pointing `leftTrigger` and `rightTrigger` at Z and Ry, usages this descriptor does not declare, a consumer pushing the right stick down would also assert ZR.

---

## Output ring writes

When an output IOCTL arrives (`SET_OUTPUT_REPORT`, `SET_FEATURE`, `WRITE_REPORT`):

1. Take `OutputLock`.
2. `EnsureOutputMapping`: opens the output section if not already; periodic re-open every 500 writes for stale-handle recovery (issue #2). LocalService can't `CreateFileMapping(Global\)`, so it can only `OpenFileMapping` the section the elevated SDK created.
3. Increment `Head` to get the new SeqNo.
4. Write `Slots[(Head - 1) % 64]` with `Source`, `ReportId`, `DataSize`, `Data`.
5. Write `SeqNo` last (memory barrier).
6. Release `OutputLock`.

The 8 ms SDK-side polling interval has 64 × 8 = 512 ms of headroom before the oldest packet would be overwritten. See [Output Passthrough](../sdk/output-passthrough.md).

---

## PID FFB: driver-side EBI auto-allocation

When `IOCTL_UMDF_HID_SET_FEATURE` arrives with Report ID 0x11 (PID Create New Effect), the driver:

1. `EnsurePidStateMapping`: opens the PID state section R/W (the v1.1.39 fix; pre-v1.1.39 it was opened FILE_MAP_READ which AV'd inside the driver-side write).
2. Reads `EbiAllocBitmap` atomically. Picks the lowest free bit.
3. `InterlockedOr(&bitmap, 1u << freeBit)` to claim the EBI.
4. Acquires PID state's seqlock (increment SeqNo; +1 = mid-write, +2 = stable).
5. Writes `BL_EffectBlockIndex = freeBit + 1`, `BL_LoadStatus = Success`, `BL_RAMPoolAvailable`.
6. Releases seqlock (SeqNo += 1 to even).
7. Increments `EbiAllocatedCount` atomically.
8. Returns `STATUS_SUCCESS`.

`pid.dll`'s follow-up `GetFeature(0x12 BlockLoad)` reads from the same shared section, which the driver's IOCTL handler also sources from. The handshake completes within `pid.dll`'s synchronous IOCTL pair without waiting on user-mode. Mirrors vJoy's `Ffb_GetNextFreeEffect`. See [Force Feedback](../sdk/force-feedback.md) for the SDK side.

If the bitmap is full when an allocation request arrives, the driver writes `BL_LoadStatus = Full`, `BL_EffectBlockIndex = 0`, and returns success. `pid.dll` propagates this to the game.

`PID Block Free` (Output 0x1B) writes are captured to the output ring as `HidOutput` so the consumer's `OutputReceived` handler gets a chance to wire the EBI back to its own tracking. The driver does **not** auto-clear the bitmap on Block Free: deliberate; the consumer is responsible for that bookkeeping. Trusting `pid.dll` to send Block Free for every allocation it released and ignoring the driver-side bitmap maintenance is the canonical pattern.

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
        if (seq1 & 1) { seq1 = src->SeqNo; }   // mid-write: re-read once
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

The SDK creates the shared sections with the SDDL `O:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;LS)(A;;GR;;;WD)`. Administrators own them. SYSTEM, BUILTIN\Administrators and LocalService get `GENERIC_ALL`, and Everyone gets `GENERIC_READ`. This is required because:

- The SDK consumer process (admin) writes input frames.
- WUDFHost runs as LocalService (which lacks `SeCreateGlobalPrivilege`, so the driver can NOT create the section) and must `OpenFileMapping` to read and, for the output, PID state, version and acknowledgement sections, to write.
- Everyone's read access is for diagnostic tools that are not elevated.

The section content is one virtual controller's HID state: not security-sensitive. The boundary is the IOCTL surface, which is mediated by the kernel HID stack and not by the shared section permissions.

---

## Version announcement (v2.0.0)

At add, and each time the driver opens the input section, `AnnounceVersion` opens `Global\HIDMaestroVersion<N>`, the 64-byte section the SDK creates beside the input section, and writes its half: its version from the build's generated version header, its capabilities (0x3, the input acknowledgement's delivered and release bits), the oldest SDK protocol it serves, `HIDMAESTRO_DRIVER_PROTOCOL_MIN`, 4, a memory barrier, and last its protocol, `HIDMAESTRO_DRIVER_PROTOCOL`, 5. A reader that sees a nonzero protocol therefore sees the version that goes with it. The driver reads a controller's 2.0.0 values, `FeatureAnswers` and the cached input report IDs, only when the section holds protocol 4 and the identity tag of the devnode's own token. A devnode whose index's section carries another token's tag fails its start with STATUS_DEVICE_CONFIGURATION_ERROR, and a value the driver cannot read fails the start and is named in the section's error word. `HMController.DriverVersion` reads the result. The layout is in [Shared Memory Protocol](shared-memory-protocol.md#version-section-v200).

---

## Self-cleanup at unload

When the device is removed (via `DIF_REMOVE` from the SDK or PnP), `EvtDeviceContextCleanup` runs:

1. `SetEvent(StopEvent)` to wake the worker.
2. `WaitForSingleObject(WorkerThread, 2000)`. Join.
3. `CloseHandle(WorkerThread)`.
4. Unmap and close all three shared sections.
5. Close the named events.

The framework calls `EvtDeviceContextCleanup` on the final reference release. WUDFHost may exit shortly after if no other devices are left in the host (per-instance host model).

As of v2.0.0 both drivers let go of their index earlier, at `EvtDeviceSelfManagedIoFlush`, which the framework calls on a surprise removal and on a removal, never on a stop for a rebalance. The flush releases the sections and their views, both events, the owner pipe, and the companion's pump thread and 8 ms timer. Through v1.12.0 they let go only in the context cleanup, which runs on `IRP_MN_REMOVE_DEVICE`. Windows sends that only once every handle to a surprise-removed device has closed, so a driver host whose device was surprise removed and never removed kept the index's output event and the companion's timer. The release clears each field it closes, so the cleanup after a flush finds nothing left. The HID driver purges its two queues first, since neither is power managed when it runs as a filter, so no I/O callback reads a view the release unmapped. A HID request to a surprise-removed device then fails in the framework with STATUS_INVALID_DEVICE_STATE instead of reaching the output ring.

### Failing the device on request (v2.0.0, protocol 5)

The input worker opens `Global\HIDMaestroRemoveEvent<N>` and `Global\HIDMaestroRemovedEvent<N>` with the input event and waits on the first after its other handles. The SDK signals it when a program refuses a `Dispose`'s removal query, and the worker then calls `WdfDeviceSetFailed(WdfDeviceFailedNoRestart)` and signals the second. Windows then removes the device and its HID children by surprise removal, as it removes an unplugged device, and asks no program that holds a child open. A queried removal asks every holder, and one refusal stops it. `IRP_MN_REMOVE_DEVICE` follows once the last handle closes, and the flush above releases the index before that. DsHidMini calls `WdfDeviceSetFailed` the same way, with `WdfDeviceFailedAttemptRestart` because it wants its device back. Microsoft documents both calls in "Handling an IRP_MN_SURPRISE_REMOVAL Request" and the `WdfDeviceSetFailed` reference. The SDK's side is in [Lifecycle and Teardown](lifecycle-and-teardown.md#a-removal-no-program-can-refuse-v200).

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

`UmdfHostProcessSharing = ProcessSharingDisabled` means each device instance gets its own WUDFHost. Default is `ProcessSharingEnabled` which pools every instance into one shared host: we hit non-linear CPU saturation on that path and the per-instance host model is what makes 6 mixed controllers actually scale. See [`docs/investigations/issue3-dual-xinputhid-saturation-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/issue3-dual-xinputhid-saturation-2026-04).

The INF carries **no `xinputhid` UpperFilter** at the HID level. The SDK writes that string per-instance after device creation, **only for profiles with an XUSB companion**: for non-companion profiles (DualSense, Xbox Series BT, Switch Pro), the HID path IS the only WGI Gamepad source, and blocking it with xinputhid would produce zero Gamepads.

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

Total: 2,954 lines (driver.c) + 620 lines (driver.h) + 129 lines (hm_contract.h, the version contract both drivers read) + 1,165 lines (companion.c) + 266 lines (hmswd.c).

---

## See also

- [Architecture Overview](architecture-overview.md): the driver's position in the full stack.
- [XUSB Companion](xusb-companion.md): the second UMDF2 driver, for non-xinputhid Xbox profiles.
- [Shared Memory Protocol](shared-memory-protocol.md): wire formats for input, output ring, PID state.
- [SwDevice and PnP](swdevice-and-pnp.md): how device nodes get created and torn down.
- [Force Feedback](../sdk/force-feedback.md): SDK-side counterpart to the PID state read/write protocol.
- [Output Passthrough](../sdk/output-passthrough.md): SDK-side counterpart to the output ring.
- [Driver Install and Signing](driver-install-and-signing.md): how the INF gets registered and the DLL gets signed.

## References

- UMDF2 framework primer: search Microsoft Learn for "User-Mode Driver Framework version 2".
- [vhidmini2 sample](https://github.com/microsoft/Windows-driver-samples/tree/main/hid/vhidmini2): the Microsoft-provided reference HIDMaestro's pattern descends from.
- `hidport.h`: the WDK header that defines the canonical `IOCTL_UMDF_HID_*` codes (`HID_CTL_CODE(20)`, `(21)`, `(22)`, `(23)`).
- WDF directives reference: search Microsoft Learn for "Specifying WDF Directives in INF Files" (covers `UmdfHostProcessSharing` and friends).
- HID architecture: search Microsoft Learn for "HID Architecture".
- [`docs/investigations/issue3-dual-xinputhid-saturation-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/issue3-dual-xinputhid-saturation-2026-04): the WUDFHost saturation root cause.
- [References](references.md): full source bibliography.
