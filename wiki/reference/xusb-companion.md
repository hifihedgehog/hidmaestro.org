# XUSB Companion

`HMXInput.dll` is a UMDF2 function driver that registers the XUSB device interface for non-xinputhid Xbox profiles. Created **only** for profiles where `vid == 0x045E` and `driverMode != "xinputhid"` &mdash; i.e. the Xbox 360 Wired family.

The companion is a **separate device node** at `SWD\HIDMAESTRO\<sid>_NNNN`, paired with the main HID device (`ROOT\VID_045E&PID_028E&IG_00\NNNN`) via shared ContainerID. Real Xbox controllers have XUSB and HID on the same PDO; HIDMaestro uses two device nodes because `mshidumdf.sys` suppresses XUSB IOCTLs on devices it hosts.

Source: [`driver/companion.c`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/companion.c) (745 lines), [`driver/hidmaestro_xusb.inf`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/hidmaestro_xusb.inf).

For the main HID driver, see [UMDF2 Driver Internals](umdf2-driver-internals.md). For why this exists at all (and not as a child PDO of the main HID), see [SwDevice and PnP](swdevice-and-pnp.md).

---

## Why a separate device

UMDF2 drivers cannot publish PDOs as children of a bus. The WDF child-list / PDO-init APIs are KMDF-only; UMDF2 linker errors confirm. Real Xbox controllers expose XUSB and HID on a single physical device because the kernel-mode `xusb22.sys` is a bus driver that publishes both interfaces; we can't replicate that in user mode.

The workaround is two peer device nodes that share a ContainerID. From the user's perspective (Settings, Device Manager, `xinput1_4`), they're one logical controller. From the OS's perspective they're two devnodes &mdash; one HIDClass, one System.

The shared ContainerID (`{48494430-4D41-4553-5452-4F00...<idx>}`) is what makes Settings group them into one entry and what makes `xinput1_4!FUN_18000c728` dedupe them into a single XInput slot. See [SwDevice and PnP](swdevice-and-pnp.md).

---

## Setup class: System (not XnaComposite)

`hidmaestro_xusb.inf`:

```
Class       = System
ClassGuid   = {4D36E97D-E325-11CE-BFC1-08002BE10318}
```

**Why System and not XnaComposite?** Windows.Gaming.Input has a `OnPnpDeviceAdded` classifier that walks a hard-coded ClassGuid pass-list ([Ghidra-traced on Win11 26200](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04)). XnaComposite triggers classifier branch 1 and creates a WGI Gamepad entity automatically &mdash; which would be a **second** WGI entity alongside the main HID device's HID-path Gamepad, hanging Windows.Gaming.Input.

System class isn't on the classifier pass-list at all, so WGI doesn't auto-classify the companion. We then admit the companion to WGI's XUSB dispatch path manually via the `xinputhid` UpperFilter tripwire (see below).

`xinput1_4.dll`'s discovery enumerates `GUID_DEVINTERFACE_XUSB {EC87F1E3-...}` directly and does **not** filter by setup class &mdash; so HIDMAESTRO under System class is still XInput-discoverable via its `AddInterface` entry.

---

## Hardware ID matching

```
[Standard.NTamd64]
%DeviceDesc% = XUSB_Install, root\VID_045E&PID_028E&XI_00
%DeviceDesc% = XUSB_Install, root\VID_045E&PID_0291&XI_00
%DeviceDesc% = XUSB_Install, root\VID_045E&PID_0719&XI_00
%DeviceDesc% = XUSB_Install, root\HIDMaestroXUSB
```

Three VID-specific PIDs (Xbox 360 Wired, Xbox 360 Wireless Receiver, etc.) plus a generic `root\HIDMaestroXUSB` fallback. PnP's `DEVPKEY_Device_MatchingDeviceId` carries the right VID:PID string when the SDK writes the hardware ID list at create time. New Xbox 360 PIDs that aren't in the specific list fall through to the generic alias &mdash; still works, but loses the per-PID INF behavior.

The `&XI_00` suffix is a HIDMaestro convention; it's not a Microsoft PnP identifier. The companion's actual instance path uses `SWD\HIDMAESTRO\<sid>_NNNN`, not `root\VID_*&PID_*&XI_00\*` &mdash; the hardware IDs above just give PnP something to match against during INF binding.

---

## The `xinputhid` UpperFilter tripwire

```
[XUSB_HW_AddReg]
HKR,,"UpperFilters",0x00010008,"xinputhid"
```

This is the registry-string tripwire that admits the System-class companion to WGI's XUSB dispatch path. The string `"xinputhid"` is written to the device's `DEVPKEY_Device_UpperFilters`, but `xinputhid.sys` is a HID-class filter and does **not** actually attach to a System-class device.

Why this works:

`Windows.Gaming.Input.dll`'s `ProviderManagerWorker::OnPnpDeviceAdded` (Win11 26200, Ghidra-decompiled in [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04)) admits a device into its provider graph if **either**:

1. The device's ClassGuid is in a hard-coded four-entry pass-list (`HIDClass`, `XnaComposite`, two others), **OR**
2. `IsDeviceOrAncestorFilteredBy(path, L"xinputhid")` returns true. This walks the ancestor chain's `UpperFilters` MULTI_SZ and does a literal `wcsncmp` against `"xinputhid"`.

Path 1 doesn't admit System-class devices. Path 2 does &mdash; a `wcsncmp` doesn't care whether `xinputhid.sys` actually attached, only whether the string appears in the registry. So writing `UpperFilters = "xinputhid"` in the INF AddReg satisfies the wstring compare without loading the kernel filter.

WGI then sees the companion publishing `GUID_DEVINTERFACE_XUSB` and dispatches via `LAB_18005f241` (the XUSB path). `IOCTL_XUSB_SET_STATE` from Chromium's `put_Vibration` lands in the companion's IOCTL handler with FF FF motor bytes &mdash; the empirical confirmation that this works.

The same string is **also** written per-instance by the SDK to the **main HID device** for XUSB-companion profiles. That second write blocks WGI's `HidClient::CreateProvider` from synthesizing a duplicate HID-backed Gamepad for the same logical controller, so WGI shows exactly one Gamepad with live input and working vibration instead of two pads splitting the responsibilities.

---

## What HIDMAESTRO publishes

```c
WdfDeviceCreateDeviceInterface(device, &XUSB_GUID, NULL);
```

**Only** `GUID_DEVINTERFACE_XUSB`. Not `WinExInput` (`{6C53D5FD-...}`) &mdash; Ghidra decomp of `Windows.Gaming.Input.dll` (Win11 26200) found zero references to that GUID; it is **not** WGI's actual `GamepadAdded` source. Pre-v1.x.x INFs registered both; the duplicate-WGI-Gamepad hang documented in [`memory:feedback-one-wgi-device-per-controller.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/CLAUDE.md) was the consequence.

---

## Per-instance device context

```c
typedef struct _COMPANION_CTX {
    ULONG       PacketCount;
    USHORT      VendorId;
    USHORT      ProductId;
    ULONG       ControllerIndex;
    WCHAR       ConfigRegPath[64];      // SOFTWARE\HIDMaestro\Controller<N>
    WCHAR       SharedMappingName[64];  // Global\HIDMaestroInput<N>
    WCHAR       OutputMappingName[64];  // Global\HIDMaestroOutput<N>
    HANDLE      SharedMemHandle;        // OpenFileMapping handle (lazy)
    PVOID       SharedMemPtr;
    HANDLE      OutputMemHandle;
    PVOID       OutputMemPtr;
    ULONG       OutputSeqNoLocal;       // last Head value we wrote
    ULONG       OutputWriteCount;       // re-open every 500 writes
    ULONG       LastGipSeqNo;           // stale-detection
    ULONG       GipStaleCount;
    WDFQUEUE    WaitForInputQueue;      // pended IOCTL_XUSB_WAIT_FOR_INPUT
    WDFTIMER    PumpTimer;              // 8 ms periodic
} COMPANION_CTX;
```

The companion shares the input + output sections with the main HID device (same `ControllerIndex` &rarr; same section names). It reads `GipData[14]` from `HIDMAESTRO_SHARED_INPUT` (the SDK packs that 14-byte slice on every `SubmitState` for Xbox-VID profiles) and writes XInput rumble captures to the same output ring the main driver writes to.

---

## IOCTL dispatch

```c
#define IOCTL_XUSB_GET_INFORMATION    0x80006000
#define IOCTL_XUSB_GET_CAPABILITIES   0x8000E004
#define IOCTL_XUSB_GET_LED_STATE      0x8000E008
#define IOCTL_XUSB_GET_STATE          0x8000E00C
#define IOCTL_XUSB_SET_STATE          0x8000A010
#define IOCTL_XUSB_WAIT_GUIDE         0x8000E014
#define IOCTL_XUSB_GET_BATTERY_INFO   0x8000E018
#define IOCTL_XUSB_GET_INFORMATION_EX 0x8000E3FC
#define IOCTL_XUSB_WAIT_FOR_INPUT     0x8000E3AC
#define IOCTL_XUSB_POWER_INFO         0x80006380
```

These are the canonical XUSB IOCTLs. Microsoft does not publicly document the XUSB IOCTL surface; the values were empirically nailed down by probing live `xinputhid` instances in 2026-04 against the Ghidra decomp of `xinput1_4.dll` and `xusb22.sys` (full archive at [`docs/investigations/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations)). v0.x.x had wrong values for `GET_CAPABILITIES` (`0xE000` instead of `0xE004`) that would have broken the entire experiment if not corrected during the empirical probing.

| IOCTL | Purpose |
|-------|---------|
| `GET_INFORMATION` | Returns minimal "1 controller present" payload for `xinput1_4`'s discovery. |
| `GET_CAPABILITIES` | Returns a synthesized `XINPUT_CAPABILITIES_EX` (gamepad subtype, supports rumble). |
| `GET_LED_STATE` | Always returns "ring quadrant 0" (our virtual has no real LED). |
| `GET_STATE` | Returns `XINPUT_GAMEPAD` packed from the GIP buffer in shared memory. |
| `SET_STATE` | Captures the 5-byte vibration payload to the output ring as `HMOutputSource.XInput`. |
| `WAIT_GUIDE` | Pended; never completes (real Guide button is async). |
| `GET_BATTERY_INFO` | Returns wired-power level (always 0xFF, full charge). |
| `GET_INFORMATION_EX` | Extended info; same semantics as `GET_INFORMATION`. |
| `WAIT_FOR_INPUT` | Pended in `WaitForInputQueue`; pumped by `CompanionPumpTimer`. |
| `POWER_INFO` | Stub. |

---

## `IOCTL_XUSB_GET_STATE`

Reads the 14-byte GIP buffer from shared memory (seqlocked) and unpacks into `XINPUT_GAMEPAD`:

```c
USHORT buttons = 0;

// btnLow byte → wButtons low nibble
UCHAR btnLow = gipBuf[12];
if (btnLow & 0x01) buttons |= XINPUT_GAMEPAD_A;
if (btnLow & 0x02) buttons |= XINPUT_GAMEPAD_B;
if (btnLow & 0x04) buttons |= XINPUT_GAMEPAD_X;
if (btnLow & 0x08) buttons |= XINPUT_GAMEPAD_Y;
if (btnLow & 0x10) buttons |= XINPUT_GAMEPAD_LEFT_SHOULDER;
if (btnLow & 0x20) buttons |= XINPUT_GAMEPAD_RIGHT_SHOULDER;
if (btnLow & 0x40) buttons |= XINPUT_GAMEPAD_LEFT_THUMB;
if (btnLow & 0x80) buttons |= XINPUT_GAMEPAD_RIGHT_THUMB;

// btnHigh byte → Back, Start, hat (bits 2-5), Guide (bit 6)
UCHAR btnHigh = gipBuf[13];
if (btnHigh & 0x01) buttons |= XINPUT_GAMEPAD_BACK;
if (btnHigh & 0x02) buttons |= XINPUT_GAMEPAD_START;

UCHAR hatNybble = (btnHigh >> 2) & 0x0F;
switch (hatNybble) {
    case 1: buttons |= XINPUT_GAMEPAD_DPAD_UP;    break;   // North
    case 2: buttons |= XINPUT_GAMEPAD_DPAD_UP   | XINPUT_GAMEPAD_DPAD_RIGHT; break;
    case 3: buttons |= XINPUT_GAMEPAD_DPAD_RIGHT; break;
    // ... 8-way hat translation
}

if (btnHigh & 0x40) buttons |= 0x0400;   // XINPUT_GAMEPAD_GUIDE (undocumented)

// Sticks: 16-bit unsigned [0..65535] → signed [-32768..32767]
SHORT lx = (SHORT)(gipBuf[0] | (gipBuf[1] << 8)) - 0x8000;
// ... LX/LY/RX/RY same shape
```

This is the v1.3.3 fix for issue #19 (Xbox 360 d-pad stuck on XInput). Pre-v1.3.3 the SDK never wrote the hat bits into `btnHigh` &mdash; XInput consumers hitting `xusb22` directly (SDL3 XInput backend, sample-quality XInput apps) saw no d-pad on Xbox 360 wired. HID-derived consumers (joy.cpl/DI, SDL3-HID, browsers via WGI) were unaffected because `BuildReportInto` correctly populated the descriptor's Hat Switch usage. v1.3.3 packs the hat into bits 2-5 of `btnHigh`; the companion's `IOCTL_XUSB_GET_STATE` handler unpacks back. See `HMController.cs:340-368` for the SDK side.

The Guide button (`HMButton.Guide` &rarr; bit 0x40 of `btnHigh`) is translated to the undocumented `XINPUT_GAMEPAD_GUIDE` (0x0400) bit returned by `XInputGetStateEx`.

---

## `IOCTL_XUSB_WAIT_FOR_INPUT`: the async input pump

WGI's `XusbDevice::QueueInputBuffer` (`Windows.Gaming.Input.dll @ 0x18006af0c`) issues `IOCTL_XUSB_WAIT_FOR_INPUT` async via `InputOutputIoctlAsync` and waits for the 29-byte XUSB state to arrive. Completing it synchronously &mdash; or with an error &mdash; **kills the pump** (verified empirically), and `Gamepad::SendControllerVibration` silently bails at the `flag_0x184` gate because `OnInputResumed` never fires on the WGI Gamepad's `IGameControllerInputSink`.

So the companion has a manual-dispatch queue (`WaitForInputQueue`) and an 8 ms periodic timer (`CompanionPumpTimer`) that drains it:

```c
VOID CompanionPumpTimer(WDFTIMER Timer)
{
    PCOMPANION_CTX ctx = ...;
    WDFREQUEST req;
    while (WdfIoQueueRetrieveNextRequest(ctx->WaitForInputQueue, &req) == STATUS_SUCCESS) {
        UCHAR state[29];
        FormatWaitForInputResponse(ctx, state);
        CopyToRequest(req, state, 29);
    }
}
```

The 29-byte response format was nailed down in the same Ghidra pass:

| Offset | Value | Meaning |
|--------|-------|---------|
| 0..1 | 0x01 0x03 | Version bytes |
| 2 | 0x03 | RESUMED state (set on every completion) |
| 9 | 0x00 | Magic byte that makes `XusbInputParser`'s built-in Gamepad template match. A prior 0x14 value produced an all-zero `GetCurrentReading` despite input arriving. |
| 10 | 0x14 | Non-zero gate byte. |
| (rest) | XUSB-shaped state from GIP buffer | Buttons / triggers / sticks. |

These constants are not documented anywhere &mdash; the values come from decomp + binary-search testing. See [`memory:project-xinputhid-upperfilter-tripwire.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/CLAUDE.md) for the discovery story.

---

## `IOCTL_XUSB_SET_STATE`: rumble capture

```c
case IOCTL_XUSB_SET_STATE: {
    PVOID inBuf; size_t inLen;
    if (NT_SUCCESS(WdfRequestRetrieveInputBuffer(req, 0, &inBuf, &inLen))) {
        // 5-byte XINPUT_VIBRATION-style payload
        PublishOutput(ctx, OUT_SOURCE_XINPUT, 0, (UCHAR*)inBuf, (ULONG)inLen);
    }
    WdfRequestComplete(req, STATUS_SUCCESS);
    break;
}
```

Whatever bytes the host wrote (typically 5: command, size, lo motor, hi motor, reserved) get published to the output ring as `HMOutputSource.XInput`. The SDK reader picks them up on the next 8 ms poll and raises `HMController.OutputReceived` to the consumer. See [Output Passthrough](../sdk/output-passthrough.md).

---

## Output ring writer

The companion mirrors the main driver's output ring writer, with the same `HM_OUTPUT_RING_SLOTS = 64` and `HM_OUTPUT_SLOT_DATA_CAP = 256` byte cap. The two writers (driver and companion) can target different slots concurrently because each slot uses `MemoryBarrier`-fenced SeqNo for torn-write detection.

```c
ULONG headNow = dst->Head;
ULONG newSeq = (headNow > ctx->OutputSeqNoLocal ? headNow : ctx->OutputSeqNoLocal) + 1;
ctx->OutputSeqNoLocal = newSeq;
ULONG slotIdx = (newSeq - 1) % HM_OUTPUT_RING_SLOTS;
slot->Source = source;
slot->ReportId = reportId;
slot->DataSize = (USHORT)dataSize;
for (ULONG i = 0; i < dataSize; i++) slot->Data[i] = data[i];
MemoryBarrier();
slot->SeqNo = newSeq;
MemoryBarrier();
dst->Head = newSeq;
```

`max(Head, OutputSeqNoLocal) + 1` prevents going backwards when both writers race &mdash; whichever increments `Head` last wins; the other's `OutputSeqNoLocal` catches up on the next write.

---

## Stale-handle recovery

Both the input and output mappings have a stale-handle recovery loop. If the SDK tears down and recreates a shared memory section between sessions (RemoveAllVirtualControllers &rarr; Cleanup &rarr; EnsureInputMapping), the companion's cached handle points at the old destroyed section. SeqNo will never advance.

After 500 consecutive stale reads (~2 s at typical XInput polling rate), the companion closes the cached handle and re-opens. Issue #1 / #2 root cause.

```c
if (seq1 == ctx->LastGipSeqNo) {
    if (++ctx->GipStaleCount > 500) {
        UnmapViewOfFile(...); CloseHandle(...);
        ctx->GipStaleCount = 0;
        return FALSE;   // next call lazy-opens the fresh section
    }
}
```

---

## Per-instance WUDFHost

```
[XUSB_Install.NT.Wdf]
UmdfHostProcessSharing      = ProcessSharingDisabled
```

Same rationale as the main HID INF. The async `WAIT_FOR_INPUT` pump + 8 ms periodic timer would otherwise serialize across every HIDMAESTRO instance in a single host. With per-instance hosts, each companion has its own thread pool and the pumps run in parallel.

For 6 controllers (any mix), expect 6-12 `WUDFHost.exe` processes &mdash; one per main HID instance plus one per companion (companions only exist for non-xinputhid Xbox profiles).

---

## See also

- [Architecture Overview](architecture-overview.md) &mdash; the companion's place in the full stack.
- [UMDF2 Driver Internals](umdf2-driver-internals.md) &mdash; the main HID driver this companion is paired with.
- [SwDevice and PnP](swdevice-and-pnp.md) &mdash; how the companion gets its instance ID and ContainerID, and why `SwDeviceCreate` is the only way.
- [Cross-API Coverage](cross-api-coverage.md) &mdash; the WGI dispatch path the UpperFilter tripwire admits.
- [Output Passthrough](../sdk/output-passthrough.md) &mdash; the output ring the rumble bytes travel through.

## References

- [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04) &mdash; full Ghidra decomp of `Windows.Gaming.Input.dll`'s `OnPnpDeviceAdded`, `IsDeviceOrAncestorFilteredBy`, and the `IOCTL_XUSB_WAIT_FOR_INPUT` 29-byte response format that backs every reverse-engineered claim on this page.
- [`docs/investigations/issue3-dual-xinputhid-saturation-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/issue3-dual-xinputhid-saturation-2026-04) &mdash; the per-instance WUDFHost CPU-saturation investigation.
- [HIDMaestro issue #19](https://github.com/hifihedgehog/HIDMaestro/issues/19) &mdash; Xbox 360 d-pad XInput regression and v1.3.3 fix that motivated the current GIP `btnHigh` packing.
- [`driver/companion.c`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/companion.c) &mdash; the companion source itself, all 745 lines.
- [`driver/hidmaestro_xusb.inf`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/hidmaestro_xusb.inf) &mdash; the INF that registers the System-class device with the `xinputhid` UpperFilter tripwire.
- [References](references.md) &mdash; full source bibliography.
