# Cross-API Coverage

How a single HIDMaestro virtual device reaches DirectInput, XInput, SDL3 / HIDAPI, browser Gamepad, and Windows.Gaming.Input simultaneously, and the tricks each path requires. Most user-mode virtual-controller projects get one or two of these APIs right; HIDMaestro targets all five.

This page is the per-API breakdown. The general data flow lives in [Architecture Overview](architecture-overview.md); the underlying device-tree shapes live in [Profile System](../profiles/profile-system.md); the descriptor mechanics live in [HID Descriptor Builder](../sdk/hid-descriptor-builder.md).

---

## DirectInput

`dinput8.dll` reads the HID descriptor directly from the kernel's preparsed data and exposes the device as a "joystick" with a fixed axis enumeration order: X, Y, Z, Rx, Ry, Rz, Slider0, Slider1, plus POVs and buttons.

### What we deliver

- **Correct axes for the profile.** Sticks at X/Y, Rx/Ry as the descriptor declares them. **All Xbox profiles** (Xbox 360 Wired, Xbox Series BT, Xbox One BT, Xbox Elite v2 BT) present **combined** triggers in DirectInput &mdash; one Z axis carrying `LT - RT`, matching real `xusb22.sys` behavior. Sony profiles (DualSense, DualShock 4) present separate triggers in DI as Z and Rz, matching their native descriptors.
- **Correct VID/PID.** Read from `HidD_GetAttributes`, set per-profile.
- **Correct product / manufacturer / serial strings.** Per-instance serial (`HM-CTL-<index>`) lets DirectInput disambiguate two virtuals with the same VID:PID/ProductString.
- **HID PID 1.0 force feedback.** `pid.dll` discovers the canonical PID block in the descriptor and the round-trip (Pool, Block Load, Set Effect, Effect Operation Start) works. See [Force Feedback](../sdk/force-feedback.md).

### How

`mshidumdf.sys` is the function driver under HidClass; HIDMaestro.dll is the lower filter. DirectInput pulls preparsed data from the kernel HID stack just like a real device. No DI-specific shenanigans &mdash; just a correct descriptor and `IOCTL_UMDF_HID_GET_FEATURE` wired to the PID state shared section.

### The Vx/Vy velocity-usage trick (every Xbox profile)

Real Xbox controllers (360, Series, One, Elite) all expose a **combined** trigger axis (Z) in DirectInput &mdash; that's `xusb22.sys`'s legacy DI shape. Browsers and WGI need separate trigger values. Previous user-mode virtual solutions had to choose: correct DI (5 axes, combined Z) or correct browser (6 axes, separate triggers).

HIDMaestro uses HID **velocity usages** (Vx and Vy, Usage Page 0x01, Usages 0x40 and 0x41 per HID Usage Tables 1.5 §4 &mdash; [usb.org/document-library](https://www.usb.org/document-library)) to carry separate trigger values in the same HID report. DirectInput does **not** map velocity usages to any axis slot &mdash; it sees 5 axes (X, Y, Rx, Ry, combined Z), matching real `xusb22.sys` for every Xbox controller. Microsoft GameInput / WGI enumerates Vx/Vy as additional axes and reads separate trigger data via the GameInput registry mapping (see WGI section below).

Result: 5 axes and combined Z trigger in DirectInput (matching real `xusb22.sys` for the entire Xbox family), separate triggers in the browser (matching real XInput), all from one HID descriptor.

The velocity usages are emitted by appending raw bytes via `HidDescriptorBuilder.AddRaw` &mdash; the fluent `AddTrigger` doesn't emit Vx/Vy because their byte-alignment validation is different. The catalog Xbox profiles do this manually; custom profiles needing the trick follow the same pattern.

---

## XInput

`xinput1_4.dll` discovers Xbox controllers through the **XUSB device interface GUID** `{EC87F1E3-...}`, **not** by HID class. Walks `SetupDiGetClassDevsW(GUID_DEVINTERFACE_XUSB)` and returns up to 4 slots.

### What we deliver

- **Single-slot allocation contiguously from 0** for Xbox-family profiles.
- **Separate triggers** (LT, RT independent).
- **Correct button mapping** including Guide via `XInputGetStateEx` (the undocumented 0x0400 bit).
- **D-pad** (fixed in v1.3.3 &mdash; pre-v1.3.3 the SDK never wrote hat bits into the GIP buffer; consumers hitting `xusb22` directly missed the d-pad).
- **Rumble passthrough** via `IOCTL_XUSB_SET_STATE` &rarr; `OutputReceived(HMOutputSource.XInput)`.

### How: two paths

**Path 1: xinputhid Xbox profiles** (Xbox Series BT family). The HID child binds Microsoft's `xinputhid.sys` as an upper filter. `xinputhid` natively publishes the XUSB device interface and translates `IOCTL_XUSB_*` to its own internal HID-out / HID-in path. HIDMaestro just provides the descriptor and bytes.

**Path 2: non-xinputhid Xbox profiles** (Xbox 360 Wired family). The HIDMaestro **XUSB companion** at `SWD\HIDMAESTRO\<sid>_NNNN` registers the XUSB device interface itself. The companion handles every `IOCTL_XUSB_*` directly, reading the 14-byte GIP buffer the SDK packs in shared memory and translating to `XINPUT_GAMEPAD` wire format. See [XUSB Companion](xusb-companion.md).

### The slot-1-skip fix

Pre-SWD-migration, virtual Xbox controllers were assigned to slots 1, 2, 3 and slot 0 was empty. Cause: the null-sentinel ContainerID `{00000000-...-FFFF-FFFFFFFFFFFF}` triggered a code path in `xinput1_4!FUN_18000de2c` that set bit 2 on the device struct and made the fallback slot allocator skip iter 0.

Fix: assign explicit per-controller ContainerID via `SwDeviceCreate`. Slots fill 0..3 contiguously. See [SwDevice and PnP](swdevice-and-pnp.md).

### Switch Pro DirectInput and the real Bluetooth descriptor (issues #35/#36/#37)

The real Pro Controller's HID descriptor declares a report 0x30 layout that does not match the Nintendo full-mode bytes the controller actually streams, and real hardware hides this by streaming nothing until a host completes the 0x80 handshake. The virtual Pro streams immediately (so SDL's report-ID sniff locks full mode from the first read), which exposed the mismatch to descriptor-driven parsers: joy.cpl showed strobing buttons, wandering axes, and a spinning hat.

Since v1.3.19 the pre-handshake stream is packed in the layout the descriptor declares (buttons at bytes 1-2, four 16-bit axes, hat nibble), so DirectInput consumers read a working pad, which is strictly better than real hardware's dead pre-handshake pad. The first Switch-protocol write (any 0x80 USB command or 0x01 subcommand) flips the stream permanently to the Nintendo layout. Note that Chromium-based browsers with an active gamepad service speak the Nintendo protocol and initialize the pad within milliseconds of arrival, exactly as they do to real hardware, after which DirectInput sees the same post-handshake stream real hardware produces.

Since v1.3.20 (issue #36) the responder's SPI analog-stick parameter block serves a ZERO stick dead zone (a real Pro reports ~150 counts, ~10% of the calibration range). Chromium's Nintendo driver reads the dead zone from that block and radially snaps both axes to center inside it, so the virtual pad now delivers the full linear range from center in every browser Gamepad API consumer. SDL and Steam's SDL lineage never read the parameter block (factory and user calibration only) and are unaffected. `switch_pro_check` asserts the zero on the wire so a future parameter-block refresh from hardware captures cannot silently reintroduce the dead band.

Since v1.3.21 (issue #37) the virtual Pro ships the real BLUETOOTH descriptor, extracted byte-exact from a live Pro Controller's SDP cache. Report 0x3F is the only report DirectInput can parse (16 buttons, null-state hat, X/Y/Rx/Ry at 16 bits). The full-mode reports 0x21/0x30/0x31-0x33 are vendor blobs. Pre-handshake the driver streams genuine 12-byte 0x3F simple-mode frames, so joy.cpl reads a live pad through a report a real Pro actually declares rather than v1.3.19's synthetic layout. The first 0x01 subcommand flips the stream to the 49-byte Bluetooth full-mode 0x30, which DirectInput ignores entirely. The DInput view freezes at neutral exactly as a real Bluetooth Pro does once Steam or a browser owns it, so the v1.3.19 Chromium caveat is gone: post-handshake bytes can no longer reach descriptor-driven parsers at all. The 0x80 USB-init family is absent from the descriptor (writes fail at HidClass, as on real hardware), so SDL initializes over its Bluetooth path. The profile presents a Bluetooth bus and HID version 0 to match the live pad's enumeration.

### The 4-slot cap

`xinput1_4.dll` hard-caps at 4 slots. This **only constrains Xbox-family profiles** (xbox-360-wired, xbox-series-xs-bt, etc.); non-Xbox profiles (DualSense, Switch Pro, wheels, sticks) don't claim XInput slots and can run beyond 4 simultaneously through DInput / HIDAPI / WGI / RawInput / Browser.

For up-to-date multi-slot testing, use Nefarius's [MultiPadTester](https://github.com/nefarius/MultiPadTester) &mdash; the historical 4-slot WGI cap was fixed upstream per `nefarius/MultiPadTester#15`.

### XInput slot-claim wait

`SetupController` runs three wait budgets after device create. The third &mdash; `WaitForXInputSlotClaim` &mdash; was 15 s pre-v1.3.2. The slot-claim wait was the **dominant cost**: distribution is bimodal (xinputhid publishes the slot in <100 ms when healthy, never publishes when xinputhid's allocator is in a stuck state), so the prior 15 s budget burned the full duration on every stuck case. PadForge users observed 13-14 s freezes on a single Xbox Series BT create.

The 500 ms cap (post-v1.3.2) sits ~5x above the slowest observed healthy claim and degrades the stuck case to a near-imperceptible pause. Controller stays functional via DI / HIDAPI / Browser / WGI when XInput doesn't pick it up; XInput consumers see the slot appear lazily on their next poll cycle.

---

## SDL3 / HIDAPI

SDL3 detects gamepads through three backends with fallback: XInput, HIDAPI (libusb-mode HID enumeration), and a RawInput fallback. SDL3's controller mapping database (`gamecontrollerdb.txt`) keys by GUID derived from VID/PID/version.

### What we deliver

- **Correct identity** via `HidD_GetProductString` / `HidD_GetManufacturerString` / `HidD_GetSerialNumberString`.
- **Bluetooth bus type** for BT-mode profiles (via the BTHLEDEVICE spoof).
- **Per-instance disambiguation.** Two virtual DualSense with the same VID:PID/ProductString get unique serials (`HM-CTL-0001`, `HM-CTL-0002`) so `hid_enumerate` doesn't bucket them as one device.

### The &amp;IG_ enumerator trick

By using `VID_*&PID_*&IG_00` as the device enumerator, the HID child's device path contains `&IG_`. This has three simultaneous effects:

- **[Chromium RawInput](https://source.chromium.org/chromium/chromium/src/+/main:device/gamepad/raw_input_data_fetcher_win.cc)** skips it (prevents duplicate gamepad entries).
- **[HIDAPI](https://github.com/libusb/hidapi/blob/master/windows/hid.c)** skips it (by design for XInput-handled devices).
- **[SDL3](https://github.com/libsdl-org/SDL/tree/main/src/joystick/windows)** still detects it &mdash; it falls through to the RawInput backend and maps by VID/PID.

One string in a device path controls three different detection paths across three different libraries.

### The BTHLEDEVICE spoof

HIDAPI detects Bluetooth controllers by checking for `BTHLEDEVICE` in the device's CompatibleIDs (see HIDAPI's Windows backend at [`windows/hid.c`](https://github.com/libusb/hidapi/blob/master/windows/hid.c) &mdash; the `hid_get_device_info` bus-type detection). HIDMaestro sets this property from user mode during device creation, **without Bluetooth hardware** and **without a kernel bus driver**.

SDL3 then uses its Bluetooth-specific controller parsing path, which handles the descriptor correctly. Without this spoof, SDL3's default parser produces zeros for certain virtual device configurations.

For BT-mode profiles only (`connection: "bluetooth"` in the JSON). USB profiles get USB CompatibleIDs.

### Custom SDL3 fork

PadForge's SDL3 fork (branch `feat/hidmaestro-filter`) adds a substring filter list at `SDL_OpenJoystick` so SDL doesn't open HIDMaestro virtuals **as input devices** when PadForge owns those virtuals. This is a **PadForge-side concern** &mdash; PadForge needs to enumerate physical controllers (via SDL) without re-enumerating its own HIDMaestro virtuals as input.

If you write a different consumer that doesn't need this filter (an emulator that just reads its own HIDMaestro output as gamepads is a corner case), you can use stock SDL3.

---

## Browser Gamepad

Chromium's `navigator.getGamepads()` exposes connected gamepads to web pages. Modern Win10/11 Chromium uses **Windows.Gaming.Input** (WGI) on the input read path and dispatches `Gamepad.Vibration` through WGI on the rumble write path.

### What we deliver

- **STANDARD_GAMEPAD layout** for Xbox-family profiles (`mapping = "standard"`, axes 0..3 are sticks, axes 4 and 5 are triggers, buttons 0..16 are the standard gamepad layout).
- **Separate triggers** in the buttons array (4 / 5 indexes for LT / RT).
- **`put_Vibration` round-trip** on Win10/11 through Chromium's WGI vibration path. The motor magnitudes reach `HMController.OutputReceived`.

### Single browser entry per controller

Real controllers expose one entry in Chromium's gamepad list. HIDMaestro's `&IG_` enumerator skips the duplicate-device condition (Chromium's RawInput backend skips `&IG_` paths, leaving only the WGI path).

### Browser vibration paths

Three different routings depending on architecture group:

| Profile group | Chromium's `put_Vibration` path |
|---------------|-------------------------------|
| **Plain HID** (DualSense, Logitech wheels) | WGI dispatches a HID Output report to the HID device. Surfaces as `HMOutputSource.HidOutput`. |
| **Non-xinputhid Xbox** (Xbox 360 Wired) | WGI dispatches `IOCTL_XUSB_SET_STATE` to the XUSB companion via the xinputhid UpperFilter tripwire. Surfaces as `HMOutputSource.XInput`. |
| **xinputhid Xbox** (Xbox Series BT) | WGI dispatches via the HID path; `xinputhid.sys` translates internally. Surfaces as `HMOutputSource.HidOutput`. |

In all three cases the consumer's `OutputReceived` handler fires; only the wire format differs.

### Chromium's controller order quirk

Chromium uses **alphabetical / lexical GUID ordering** for the gamepad list. Any match to physical creation order is coincidental. If your consumer cares about controller ordering at the browser layer, sort or remap on the consumer side &mdash; the SDK creates virtuals in deterministic order, but Chromium reorders.

Chromium also caches gamepad slots within a session. Adding/removing controllers during a Chromium session leaves stale duplicate slots with identical inputs. **Restart Chromium to clear.** Not a HIDMaestro bug.

### Edge / Firefox

Edge uses Chromium's pipeline so behaves identically. Firefox's Gamepad implementation is also Chromium-derived for the WGI path on Win11.

---

## Windows.Gaming.Input (WGI)

The WinRT API surface that powers `Gamepad.Vibration`, `RawGameController`, `IGameController`, etc. Used by Chromium for browser Gamepad and by UWP / WinUI games. **Most fragile of the five surfaces** &mdash; the most empirical investigation went into making this work.

### What we deliver

- **One Gamepad entity per controller.** Not two splitting input/vibration.
- **Live input** via the HID path or the XUSB path depending on profile group.
- **Working `put_Vibration`** via the same path.

### The classifier pass-list

Decomp of `Windows.Gaming.Input.dll` (Win11 26200) shows that `ProviderManagerWorker::OnPnpDeviceAdded` admits a device into its provider graph if **either**:

1. The device's ClassGuid is in a hard-coded four-entry pass-list:
   - HIDClass `{745A17A0-...}`
   - XnaComposite `{D61CA365-...}`
   - Two others (one is a setup class for legacy XBox, one is GameInput-related)
2. `IsDeviceOrAncestorFilteredBy(path, L"xinputhid")` returns true.

Both branches are reverse-engineered from the Win11 26200 binary; the full Ghidra output and ProcMon traces are archived at [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04).

Path 1 admits plain HID profiles (HIDClass) automatically. Path 2 is what admits the System-class XUSB companion via the registry-string tripwire &mdash; see [XUSB Companion](xusb-companion.md).

`System` class is **not** on the pass-list. So plain System-class devices are skipped by WGI unless they also have `"xinputhid"` in their UpperFilters.

### Why we don't use XnaComposite for the companion

Initially obvious choice: XnaComposite is on the pass-list. Why pick System?

XnaComposite triggers classifier branch 1 and creates a WGI Gamepad entity automatically &mdash; which would be a **second** WGI entity alongside the main HID device's HID-path Gamepad. Two WGI Gamepads splitting input and vibration on one logical controller hangs the entire `Windows.Gaming.Input` subsystem. Recovery: `Restart-Service -Force GameInputSvc`.

The System class isn't classified at all, then admitted via the UpperFilter tripwire and dispatched via the XUSB path. Exactly one Gamepad entity per logical controller. See [`memory:feedback-one-wgi-device-per-controller.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/CLAUDE.md).

### The GameInput registry override

Windows ships a built-in GameInput mapping database for known VID/PIDs at `HKLM\SYSTEM\CurrentControlSet\Control\GameInput\Devices\<key>`. It tells WGI how to map HID axes/buttons to the Gamepad interface (which axis is leftStickX, which is the trigger, etc.).

For Xbox profiles using the Vx/Vy velocity-usage trick, the default mapping points trigger axes at the combined Z axis (axis 4). HIDMaestro writes custom GameInput mappings that point trigger axes at Vx/Vy (axes 5 and 6). WGI's Gamepad object then reads actual separate trigger values from the Vx/Vy fields.

Mapping format is undocumented; HIDMaestro emits the byte sequences empirically determined to work for Xbox 360 / Xbox Series profiles. See `DeviceOrchestrator.GameInputMapping*` methods.

### `IsDeviceOrAncestorFilteredBy`: the literal wstring compare

The check is a `wcsncmp` against `"xinputhid"`. Doesn't load `xinputhid.sys`. Doesn't check whether the filter actually attached. Just asks "does any ancestor's UpperFilters MULTI_SZ contain this string". Writing the string in the INF AddReg is sufficient.

This was discovered by Ghidra-decompiling `Windows.Gaming.Input.dll` and seeing the literal `wcsncmp` instruction. See [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04) for the multi-week investigation.

### `IOCTL_XUSB_WAIT_FOR_INPUT`: the async input pump

WGI's `XusbDevice::QueueInputBuffer` issues `IOCTL_XUSB_WAIT_FOR_INPUT` async. **Completing it synchronously kills the WGI input pump** &mdash; verified empirically. The XUSB companion has a manual-dispatch queue and an 8 ms periodic timer that drains pended requests with the right 29-byte response format. See [XUSB Companion](xusb-companion.md).

### XUSB `IOCTL_XUSB_WAIT_FOR_INPUT` 29-byte response format

| Offset | Value | Meaning |
|--------|-------|---------|
| 0..1 | `0x01 0x03` | Version bytes |
| 2 | `0x03` | RESUMED state |
| 9 | `0x00` | Magic byte that makes `XusbInputParser`'s built-in Gamepad template match (a prior `0x14` value here produced an all-zero `GetCurrentReading` despite input arriving) |
| 10 | `0x14` | Non-zero gate byte |
| 11..28 | XUSB state | Buttons / triggers / sticks |

These constants come from Ghidra + binary-search testing. The `state[9]=0x00` magic byte is the most counterintuitive &mdash; in the Microsoft tooling that generated these state frames, that field would presumably mean something specific, but in our context the only thing that matters is that the `XusbInputParser` template matches it.

---

## RawInput

Chromium and other browsers may fall back to RawInput (`Win32 Raw Input API`) for device enumeration when the WGI path doesn't fire. RawInput sees every HID device on the system.

### What we deliver

- **Skipped by default** for Xbox profiles via the `&IG_` substring blocklist Chromium maintains.
- **Visible** for non-XInput profiles.

### The phantom-axis trap

Chromium's RawInput parser surfaces any trailing Const Input item as a phantom axis with a literal value (`AXIS 9 = 1227133568`). Issue #6.

`HidDescriptorBuilder.AddButtons(N)` rounds button counts up to a byte boundary instead of emitting a Const padding item. `AddTrigger(name, bits)` rejects non-byte-aligned bit counts that would force a Const pad. Fluent descriptor authoring eliminates this trap by construction; raw descriptor authoring (via `AddRaw`) needs to handle it manually.

---

## Microsoft GameInput (newer API)

The official product name is **Microsoft GameInput** (note the spacing &mdash; no dot, `GameInput` is one word). The DLL on Windows is `GameInput.dll`. Distinct from the older `Windows.Gaming.Input` WinRT surface (WGI), but on current Windows builds both run through the same kernel-side dispatch. Reads device-to-Gamepad mapping from `HKLM\SYSTEM\CurrentControlSet\Control\GameInput\Devices\`.

We don't currently target Microsoft GameInput differently from WGI. Investigation in 2026-04 confirmed:

- No user-mode provider model exists.
- Haptics still route through the same kernel drivers as WGI.
- Chromium doesn't use Microsoft GameInput on Win11.

See [Glossary](../start/glossary.md) for the term and `docs/investigations/wgi-silent-sink-2026-04/` for the rationale. **Not a lever for HIDMaestro work.**

---

## Per-archetype API summary

| API | Plain HID | Non-xinputhid Xbox | xinputhid Xbox |
|-----|-----------|--------------------|---------------|
| **DirectInput** | descriptor-correct axes, buttons | 5 axes (combined Z; Vx/Vy invisible) + 10 btns | 5 axes (combined Z; Vx/Vy invisible) + 16 btns (xinputhid synth) |
| **XInput** | not visible | 1 slot, separate triggers, Guide | 1 slot, separate triggers, Guide |
| **SDL3 / HIDAPI** | HIDAPI direct (USB or BT bus type) | XInput backend (&amp;IG_ filter) | XInput backend (&amp;IG_ filter) |
| **Browser Gamepad** | Detected, separate triggers (where descriptor allows) | STANDARD_GAMEPAD via WGI&rarr;XUSB | STANDARD_GAMEPAD via WGI&rarr;HID |
| **WGI** | 1 Gamepad via HID classifier | 1 Gamepad via XUSB tripwire | 1 Gamepad via HID classifier (xinputhid filtered) |

---

## Verification

`scripts/verify.py` checks all five paths in one pass:

```cmd
python scripts\verify.py --controllers 4
```

Per-controller:

- XInput slot status (`XInputGetState`)
- DirectInput axes/buttons (`winmm.joyGetDevCapsW`)
- HIDAPI enumeration (`hid.enumerate`)
- Browser Gamepad state (headless Chrome &rarr; `navigator.getGamepads()`)
- WGI Gamepad state (`winrt.windows.gaming.input.RawGameController`)
- HID enumeration order (filtered by `HM-CTL-` serial)

PASS if every API agrees on slot count, identity, and basic state. Exit 0 / 1.

See [Testing and Verification](testing-and-verification.md) for the regression battery integration.

---

## See also

- [Architecture Overview](architecture-overview.md) &mdash; the full data flow these per-API mechanics fit into.
- [XUSB Companion](xusb-companion.md) &mdash; the XInput / WGI dispatch path for non-xinputhid Xbox profiles.
- [UMDF2 Driver Internals](umdf2-driver-internals.md) &mdash; the driver IOCTLs the kernel HID stack marshals from these APIs.
- [HID Descriptor Builder](../sdk/hid-descriptor-builder.md) &mdash; the velocity-usage trick + button/trigger byte alignment.
- [Profile System](../profiles/profile-system.md) &mdash; the three architecture groups that determine which path applies.

## References

- HID Usage Tables 1.5 &mdash; Vx/Vy usage codes (Generic Desktop §4). Download from [usb.org/document-library](https://www.usb.org/document-library).
- [W3C Gamepad API](https://www.w3.org/TR/gamepad/) &mdash; STANDARD_GAMEPAD mapping bucket.
- [Chromium gamepad backend](https://source.chromium.org/chromium/chromium/src/+/main:device/gamepad/) &mdash; `&IG_` skip semantics in RawInput.
- [HIDAPI](https://github.com/libusb/hidapi) &mdash; the Windows backend at `windows/hid.c` has bus type detection (`BTHLEDEVICE` CompatibleIDs check).
- [SDL3](https://github.com/libsdl-org/SDL) &mdash; XInput / RawInput / HIDAPI fallback hierarchy under `src/joystick/windows/`.
- XInput documentation &mdash; search Microsoft Learn for "XInput Game Controller APIs". 4-slot cap, `XInputGetState` semantics.
- [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04) &mdash; Ghidra decomp of WGI's `OnPnpDeviceAdded` classifier and `IsDeviceOrAncestorFilteredBy`.
- [References](references.md) &mdash; full source bibliography for every claim in this wiki.
