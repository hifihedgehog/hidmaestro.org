# Profile System

Every device HIDMaestro can emulate is a JSON file in `profiles/<vendor>/<slug>.json`. 337 ship in the embedded catalog across 73 vendors, counting the distinct `vendor` values with Logitech (Saitek), Generic/Arduino, PXN/Lite Star and Sony Interactive Entertainment under their parent brands and Generic left out (Microsoft, Sony, Nintendo, Logitech, Thrustmaster, Fanatec, MOZA, SimuCUBE, VKB, VIRPIL, WinWing, Honeycomb, Hori, 8BitDo, Razer, Steelseries, Valve, Corsair, Keychron, Cherry, and 53 more). 51 are keyboards and 52 are mice. Runtime-built profiles authored via `HMProfileBuilder` use the identical schema and run through identical machinery.

This page documents the JSON schema field-by-field, the three runtime architecture groups a profile can fall into, and how the SDK resolves a profile into a deployable virtual device at `CreateController` time.

---

## On-disk layout

```
profiles/
  schema.json                       # JSON Schema document for all profiles
  scraped_descriptors.json          # 22 raw descriptors recovered from real devices
  linux-kernel-fixed-descriptors.json  # patched descriptors from the Linux kernel
  microsoft/
    xbox-360-wired.json
    xbox-series-xs-bt.json
    xbox-elite-v2.json
    ...23 Microsoft profiles
  sony/
    dualsense.json
    dualsense-edge.json
    dualshock-4-v1.json
    dualshock-3.json
    ...16 Sony profiles
  nintendo/
    switch-pro.json
    switch2-pro.json
    joycon-l.json
    joycon-r.json
    gamecube-adapter.json
    n64-nso.json
    snes-nso.json
    ...12 Nintendo profiles
  thrustmaster/
    t300rs.json
    t-flight-hotas-4.json
    t16000m.json
    ...20 Thrustmaster profiles
  ...28 more vendor folders
```

Vendor folder names are slugs of the manufacturer (`thrustmaster`, `8bitdo`, `vkbsim`). File names are slugs of the model (`xbox-360-wired`, `t-flight-hotas-x`, `dualsense-edge-bt`).

The full vendor list at v1.8.1: 8bitdo, amazon, asetek, cammus, ch-products, fanatec, flydigi, google, heusinkveld, honeycomb, hori, logitech, microsoft, misc, moza, nacon, nintendo, pxn, razer, sega, simagic, simucube, snk, sony, steelseries, taito, thrustmaster, turtle-beach, valve, virpil, vkbsim, winwing.

The `misc/` vendor catches everything else: arcade controllers, niche racing pedals, devices the contributor couldn't slot into a clean vendor namespace.

---

## Schema

```json
{
  "id": "xbox-360-wired",
  "name": "Xbox 360 Controller (Wired)",
  "vendor": "Microsoft",
  "vid": "0x045E",
  "pid": "0x028E",
  "productString": "Controller (XBOX 360 For Windows)",
  "manufacturerString": "©Microsoft Corporation",
  "type": "gamepad",
  "connection": "usb",
  "descriptor": "05010905a101a10009300931150026ffff350046ffff950275108102c0...",
  "nativeDescriptor": "05010905a101...",
  "inputReportSize": 18,
  "deviceDescription": "Controller (XBOX 360 For Windows)",
  "triggerMode": "combined",
  "driverMode": null,
  "buttonMap": null,
  "axisMap": null,
  "triggerButtons": null,
  "notes": null
}
```

### Required fields

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Unique slug, e.g. `"xbox-360-wired"`. Used by `HMContext.GetProfile`, case-insensitively. The filename need not match: most vendor folders prefix the id with the vendor slug, so `profiles/logitech/g29.json` carries `"id": "logitech-g29"`. |
| `name` | string | Human-readable display name shown in UIs. |
| `vendor` | string | Manufacturer name. Doesn't need to be a slug. |
| `vid` | string | USB Vendor ID as a 4-digit hex string with `0x` prefix. |
| `pid` | string | USB Product ID, same format. |
| `productString` | string | The string returned by `IOCTL_HID_GET_STRING (HID_STRING_ID_IPRODUCT)`. **This is what `joy.cpl` and games see.** Match the real device exactly. SDL3's controller database keys off this. See [when revisions disagree](#when-hardware-revisions-disagree). |
| `type` | string | Device category. One of: `gamepad`, `wheel`, `joystick`, `flightstick`, `hotas`, `arcadestick`, `pedals`, `keyboard`, `mouse`, `other`. A `keyboard` or `mouse` profile takes `SubmitKeyboard`, `SubmitMouse` and `SubmitConsumer` (see [Keyboards and Mice](../sdk/keyboards-and-mice.md)). |
| `connection` | string | Connection type the profile represents. One of: `usb`, `bluetooth`, `wireless-adapter`. |

### Optional fields

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `manufacturerString` | string \| null | null | The string returned for manufacturer query. Defaults to `vendor` if null. |
| `descriptor` | string \| null | null | HID report descriptor as a continuous hex string. Null = profile is a placeholder, not deployable. Spaces and dashes are ignored. A string with any other character that is not a hex digit, or an odd number of digits, refuses the file at load, and a profile built in code at create with `HMProfileException` (v2.0.0). |
| `inputReportSize` | int \| null | derived | Length on the wire of the input report a data-only frame fills, in bytes, the report ID's byte included. The driver sends that report at this length. When null, the report's own length in the descriptor. |
| `dataReportId` | string \| null | null | v2.0.0. The input report a data-only frame fills, as a hex byte such as `"0x01"`, for a device where the SDK's own choice is wrong. Must name an input report the descriptor declares, and is refused beside an always-armed `extendedReport`. See [The report a data frame fills](#the-report-a-data-frame-fills-v200). |
| `nativeDescriptor` | string \| null | null | The original physical device's descriptor before any HIDMaestro-side modifications. Kept as a record; not used at runtime. |
| `deviceDescription` | string \| null | `productString` | The Device Manager display name (`FriendlyName` PnP property). Some catalog profiles (Logitech F310) carry a curated `deviceDescription` distinct from `productString`. |
| `triggerMode` | string \| null | null | Profile-level annotation describing the descriptor's trigger encoding: `combined` (descriptor declares one Z axis carrying `LT - RT`), `separate` (descriptor declares independent Z + Rz), or null for non-gamepad. **Note:** every Xbox profile surfaces in DirectInput as 5 axes with combined Z regardless of this annotation: the velocity-usage trick + xinputhid synthesis collapse separate-trigger descriptors into the canonical `xusb22.sys` 5-axis shape. WGI / browser see separate triggers via Vx/Vy + GameInput registry mapping. |
| `driverMode` | string \| null | null | `"xinputhid"` binds Microsoft's xinputhid filter for GIP-over-HID profiles like Xbox Series BT, One BT and Elite v2 BT. As of v2.0.0 it is the alias of the `xinput` block's `"via": "xinputhid"`, and `"xusb22"` an alias for the same path. A profile carries its `xinput` block, its `driverMode`, or neither. |
| `xinput` | object \| null | null | v2.0.0. How the device reaches XInput, the presentation group of the device model. `via` is `"xusbCompanion"`, an XUSB companion devnode beside the HID device as xusb22 presents a wired Xbox 360 pad, or `"xinputhid"`. `subType`, `flags`, `battery`, `information` and `capabilities` set what the companion answers. An empty block means no XInput. See [XUSB Companion](../reference/xusb-companion.md#answers-from-the-profile-v200). |
| `bluetoothTransport` | string \| null | `"classic"` | v2.0.0. For a Bluetooth profile, the hardware and compatible IDs of a real device of that transport: `"classic"` gives `BTHENUM\{00001124-...}` IDs, `"le"` gives `BTHLEDevice\{00001812-...}` IDs. See [Cross-API Coverage](../reference/cross-api-coverage.md#bluetooth-identity-v200). |
| `bluetoothVendorIdSource` | string \| null | `"usb"` | v2.0.0. Who assigned the VID in the Bluetooth IDs: the USB-IF (`"usb"`, source 2) or the Bluetooth SIG (`"bluetooth"`, source 1, as the Luna's `_Dev_VID&010171` carries). |
| `driverPid` | string \| null | null | PID override for hardware-ID matching only. The driver's INF-bind process matches against this PID; applications still see the real `pid` field via `HidD_GetAttributes`. Used for xinputhid-bound profiles where the real PID would be claimed by GameInput / HIDAPI: a sentinel like `0x0001` here makes those backends skip the device so SDL3 falls through to its XInput backend with the correct identity. |
| `buttonMap` | int[] \| null | identity | Optional remapping table. Index = `HMButton` bit position; value = descriptor button index. Sony profiles use this to swap A/B/X/Y &harr; Cross/Circle/Square/Triangle. `-1` means "abstract bit not in this descriptor" (the bit is dropped, never identity-mapped). Values at or past the declared button count address the contiguous 1-bit vendor run continuing the button array, where the DualSense Edge's paddles and Fn buttons live on real hardware (v1.5.1, issue #48). |
| `axisMap` | object \| null | heuristic | Axis semantic override. Keys are hex HID usage codes (`"0x32"` for Z); values are semantic names (`"leftStickX"`, `"rightTrigger"`). Sony profiles override `Z/Rz &rarr; rightStick`. |
| `sdlMapping` | string \| null | null | v1.5.0+. SDL gamepad mapping body, everything after the GUID and name, trailing comma included. Set it for pads SDL reaches through DirectInput and has no database entry for, which SDL would otherwise expose as roleless joysticks. See [SDK Reference](../sdk/sdk-reference.md) for the consumer side. |
| `triggerButtons` | int[] \| null | null | Two-element array `[LT_button_index, RT_button_index]`. When triggers are nonzero, the corresponding buttons engage automatically (DS4/DualSense L2/R2 digital buttons). |
| `extendedReport` | object \| null | null | v1.3.5+. Vendor-blob input layout. When present, `HMController.SubmitState` packs reports per the field list rather than via the descriptor-driven encoder. Used for profiles where the descriptor declares a single opaque vendor-defined field (Sony BT 0x31, future profiles with similar shape). See section below. |
| `extendedOutputReport` | object \| null | null | v1.3.5+. Vendor-blob output layout. When present, the SDK decodes incoming output reports of the declared report ID and surfaces parsed-field events via `HMController.OutputDecoded`. Pairs with `HMOutputEncoder.Encode` for the inverse direction. |
| `deviceModelFrom` | string \| null | null | v2.0.0. The device model the profile takes for the groups its own keys leave empty: a catalog profile's id, a model this release holds, or a model in the loaded directory's `models` folder. See [Device models](#device-models-v200). |
| `deviceModel` | string \| null | null | v2.0.0. `"none"` takes no model, by name or by identity. No other value is accepted. |
| `featureStubs`, `valueSources` | object \| null | null | The answers the device gives to GET_REPORT(Feature), with the value sources their patches read. On UMDF2, v2.0.0 compiles them into the controller's `FeatureAnswers` value. See [Composite USB Personas](../sdk/usb-audio-composite.md#profile-schema). |
| `protocol` | object \| null | null | v2.0.0. A USB/IP device's registers, commands, replies and clock. See [`protocol`](#protocol). |
| `stateBlock`, `inputReports`, `liveFeatureReports` | object \| null | null | v2.0.0. A device that builds its reports from its own state. See [Report programs](#report-programs-and-stream-v200). |
| `stream` | object \| null | null | v2.0.0. The idle repeat: the last frame sent again at the device's period while the consumer is quiet. See [`stream`](#stream). |
| `axisCenters` | object \| null | null | v2.0.0. The wire value a descriptor-path axis carries at the SDK's 0.5, keyed by HID usage name, such as `{"X": 127}`. See [Report field parameters](#report-field-parameters-v200). |
| `extendedReport.ports`, `extendedOutputReport.ports` | object \| null | null | v2.0.0. A report that carries several controllers, one block per port. See [Devices with ports and protocols](#devices-with-ports-and-protocols-v200). |
| `backend` | string \| null | null | `"usbip"` runs the profile on the USB/IP transport instead of the UMDF2 driver, with `usbConfiguration` describing the whole USB device. See [Composite USB Personas](../sdk/usb-audio-composite.md#profile-schema). |
| `notes` | string \| null | null | Implementation notes, descriptor provenance, quirks. Free-form. |

The full JSON Schema lives in `profiles/schema.json`.

### When hardware revisions disagree

"Match the real device exactly" stops being a complete instruction when a manufacturer changes a string mid-life and leaves nothing on the wire to tell the revisions apart. A DualSense sold in 2020 reports `Wireless Controller`. One sold today reports `DualSense Wireless Controller`. Both report `bcdDevice` 0x0100 and the same 054C:0CE6, so no field a profile could branch on distinguishes them, and a profile serves one string or the other.

HIDMaestro's rule for that case is that the current revision wins, since a consumer keyed to a retired string is already broken against real hardware a user can buy. As of v1.4.5 `dualsense` and `dualsense-composite` serve `DualSense Wireless Controller`. The launch string remains available on `dualsense-bt`, whose `dualsense-bt-full` sibling carries the current one, so both are reachable from the catalog and a consumer that needs the older identity can ask for it by profile id.

Write the reasoning into `notes` when you make this call in a profile of your own. The next person to compare the profile against a descriptor dump will find the mismatch and needs to know it was a decision.

### The report a data frame fills (v2.0.0)

A data-only frame, from `SubmitRawReport` or from `SubmitState` through the descriptor-driven encoder, goes out from the UMDF2 driver as one input report at one length. The SDK picks that report from its own parse of the descriptor: the first input report with game pad fields, or for a keyboard or mouse the descriptor's first input report. `inputReportSize`, when set, is that report's whole length on the wire, its ID byte included. The SDK writes the report ID and length into the controller's configuration, and the driver uses them only when they match the descriptor and length in use.

When the SDK's choice is not the report the real device sends, `dataReportId` names the right one. A create refuses a `dataReportId` that names no input report of the descriptor, and one beside an `extendedReport` with `alwaysArmed`, whose report the data frames fill instead, before anything machine-wide. `HMProfileBuilder.FromProfile` copies it. `microsoft-designer-keyboard` sets `"0x01"`. Its descriptor declares a vendor report 0x27 as its first input report, and the real keyboard sends its keys as report 0x01 of 12 bytes: "Press A" is `01 00 04 00 00 00 00 00 00 00 00 00` in Android CTS's `microsoft_designer_keyboard_keyeventtests.json`, beside the register file the profile's descriptor comes from.

Through v1.12.0 the driver took the first Report ID item of the descriptor's first Application Collection, whatever kind of report it named, and the SDK measured that report with a walk that kept no Push and Pop stack. Sixteen catalog profiles now send a different data report on a UMDF2 controller:

| Profile | v1.12.0 | v2.0.0 |
|---|---|---|
| `logitech-wingman-formula-gp` | 0x00, 3 bytes | 0x00, 5 bytes |
| `gamecube-adapter-hid` | 0x11 (an output report), 1 byte | 0x21, 38 bytes |
| `joypad-gc-adapter` | 0x11 (an output report), 1 byte | 0x21, 37 bytes |
| `microsoft-designer-keyboard` | 0x22 (a feature report), 1 byte | 0x01, 12 bytes, by its `dataReportId` |
| `genesis-nso`, `n64-nso`, `snes-nso`, `joycon-l` | 0x21, 49 bytes | 0x3F, 12 bytes |
| `joycon-charging-grip` | 0x21, 49 bytes | 0x3F, 12 bytes |
| `switch2-pro-controller` | 0x05, 64 bytes | 0x09, 64 bytes |
| `joypad-steam-input` | 0x02, 64 bytes | 0x01, 64 bytes |
| `ps3-remote` | 0x00, 17 bytes, the driver's default | 0x00, 12 bytes |
| `circuitpython-gamepad` | 0x05, 6 bytes | 0x05, 7 bytes |
| `pxn-vd6` | 0x01, 62 bytes | 0x01, 63 bytes |
| `thrustmaster-t16000m` | 0x00, 10 bytes | 0x00, 9 bytes |
| `vader-4-pro` | 0x00, 32 bytes | 0x00, 9 bytes |

The last four carried `inputReportSize` values that disagreed with their own descriptors. `circuitpython-gamepad` and `pxn-vd6` counted the data bytes without the ID, one byte short of the declared report, which HID class rejects. `thrustmaster-t16000m` and `vader-4-pro` sent a report longer than any their descriptors declare. `switch2-pro-controller` sends every frame whole on its extended lane, so its change does not reach the wire. Two rows still do not match the device. `gamecube-adapter-hid`'s descriptor gives each of its ten Application collections Usage 0, as the real adapter's does, so Windows' HID parser refuses it (HIDP_GETCOLDESC_TOP_COLLECTION_USAGE, which S37 checks) and the device fails with Code 10 either way. `joycon-charging-grip` carries the Bluetooth Joy-Con descriptor, and a wired grip never sends 0x3F. `switch-pro` keeps 0x21 at 362 bytes, and every other UMDF2 profile keeps its report and length. A driver older than v2.0.0 ignores the SDK's choice, so these profiles keep their old reports on a 1.x driver, which a running 1.x program's `InstallDriver` puts back.

Four catalog descriptors held main items of tag 0, which HID 1.11 does not define, and now hold their sources' bytes:

- `ps3-remote`: hid-sony.c `ps3remote_rdesc`, which the profile names as its source, with two items given a data byte (below). The catalog copy had 90 bytes, with bytes doubled.
- `saitek-x52`: the 119 bytes of Launchpad bug 492056 comment 14. One byte was missing and three were changed.
- `thrustmaster-t80`: byte 79 is 09, so Rx and Ry follow as in the T-Flight HOTAS 4 and T300RS descriptors the profile says it shares. No dump of a T80's own bytes is published.
- `joypad-steam-input`: joypad-os `sinput_descriptors.h`. The copy had lost the three report ID values its macros stand for.

Windows' own HID parser refused three catalog descriptors. HID class runs it at the device's start, so each of these devices failed its start with problem code 10:

- `ps3-remote`: hid-sony.c writes its Usage Minimum and one Input item with no data byte, which Windows refuses. HID 1.11 gives such an item the value 0, so the profile writes both with a data byte of 0: 69 bytes and the same 12-byte report.
- `tinyusb-generic-gamepad`: its reports were not whole bytes. It now serves TinyUSB's `TUD_HID_REPORT_DESC_GAMEPAD` with its report ID 2: a 12-byte input report of six 8-bit axes, an 8-bit hat and 32 buttons, and no output or feature report.
- `nacon-bigben-ps4`: Linux's fixed descriptor, whose Feature item has no usage. It now serves the descriptor the pad serves (hid-bigbenff.c): a 27-byte input report with X, Y, Z and Rz and with L2 and R2 as buttons 7 and 8, beside 8-byte vendor output and feature reports. 146B:0902 is BigBen's wired game pad for the PS3, so the profile is now "BigBen Game Pad for PS3", with "Bigben Interactive" and "Bigben Game Pad" as its USB strings. Its id is unchanged.

`gamecube-adapter` and `gamecube-adapter-hid` stay refused, as the real adapter's descriptor is: each of their ten Application collections carries Usage 0, which hidparse refuses as a top-level collection without a usage (STATUS_COULD_NOT_INTERPRET, HIDP_GETCOLDESC_TOP_COLLECTION_USAGE). `joypad-gc-adapter` parses.

Every descriptor walker in the SDK keeps HID 1.11's global item stack, Push and Pop. Battery scenario S37 checks the input, output and feature lengths the SDK reads for all 243 catalog report descriptors against hid-tools', and runs every one through the machine's own hidparse.sys, as HID class does at a device's start.

---

## Vendor-blob fields (`extendedReport` / `extendedOutputReport`)

Some controllers' descriptors declare their input as a single opaque vendor-defined field: Sony BT (DualSense, DualSense Edge, DS4 BT) is the canonical example, but Switch Pro and various wheels follow the same pattern. The descriptor doesn't say which bytes carry sticks vs buttons vs gyro vs CRC; the wire format is firmware convention.

Pre-v1.3.5 the SDK couldn't pack these: it would fall back to whatever simpler input report the descriptor declared first (Sony BT: Report 1, 9 bytes), which Steam Input misclassified and parsers like `dualsense-tester` couldn't read. v1.3.5 makes the byte layout data: profile JSON describes every field's type, position, and bit range; the SDK walks the field list as a generic codec.

```jsonc
"extendedReport": {
  "reportId": "0x31",     // hex string; emitted as the report ID byte
  "size": 78,             // total bytes including report ID at byte 0
  "fields": [
    { "byte":  1, "type": "uint8-rolling", "semantic": "btSeqTag", "initial": 0 },
    { "byte":  2, "type": "uint8-axis",    "semantic": "leftStickX",  "center": 128 },
    { "byte":  3, "type": "uint8-axis",    "semantic": "leftStickY",  "center": 128 },
    { "byte":  6, "type": "uint8-trigger", "semantic": "leftTrigger" },
    { "byte":  9, "bits": "0-3", "type": "hat-octant", "semantic": "hat", "neutralValue": 8 },
    { "byte":  9, "bits": "4-7", "type": "button-mask", "buttons": ["X","A","B","Y"] },
    { "byte": 10, "type": "button-mask",
      "buttons": ["LeftBumper","RightBumper","_","_","Back","Start","LeftStick","RightStick"] },
    { "bytes": "74-77", "type": "crc32-le",
      "scope": { "prefix": [161, 49], "from": 1, "to": 73 } }
  ]
}
```

### Field types

| Type | Direction | Semantics |
|---|---|---|
| `uint8` | both | Plain byte. Encode writes `initial`, or the touch report's packet counter for `touchpadPacketCounter`. Decode returns the byte |
| `uint8-rolling` | both | Per-controller counter that advances by `stride` each report (input). Plain byte (output) |
| `uint8-axis` | both | Stick axis. Encode takes the SDK's 0..1 stick (0.5 centered) to `min`..`max`, or `center - 127`..`center + 127` when `center` is not 128. Decode returns a signed float about `center` |
| `uint8-trigger` | both | Trigger, 0..1 to `min`..`max`. Decode returns 0..1 |
| `uint8-pressure` | input | A button's pressure, 0 to 255, from the `Pressure*` fields |
| `uint8-battery` | input | `BatteryLevel` in the declared bit range, `fullValue` while full |
| `uint8-level-map` | input | The battery byte from an 11-entry `levels` table, with `fullValue` ahead of `chargingValue` (v2.0.0) |
| `int16-le` | both | A motion word: the raw `Gyro*` and `Accel*` shorts, or with `scale` the calibrated `AccelG*` and `GyroDps*` values. `center` writes offset binary |
| `int16-axis` | input | Signed 16-bit stick axis, `min`..`max` |
| `int16-pad`, `int16-pad-or-stick` | input | A Valve trackpad coordinate from the touch fingers. `int16-pad-or-stick` sends the stick while the finger is up, as the 2015 Steam Controller does |
| `uint16-le`, `uint32-le` | input | `sensorTimestamp`: the consumer's stamp, divided by `divisor` in the 16-bit form, or with `clock: "accumulate"` elapsed time over `divisor` |
| `uint16-trigger` | input | 16-bit trigger, `min`..`max`. `max` is required |
| `uint16-pressure` | input | Pad pressure from `TouchpadFinger0Pressure` or `TouchpadFinger1Pressure`, `min` at 0 and `max` at 1. A touching finger left at 0 sends `max`, as every touch did before v2.0.2. `max` is required |
| `uint10-be` | input | A 10-bit big-endian motion value about `center`, rescaled by `resolution` over `sourceResolution` |
| `uint32-rolling` | input | 32-bit packet counter that advances every report |
| `touchpad-finger` | input | Sony's 4-byte touch finger: lifted bit, tracking ID, 12-bit X and Y |
| `bitfield` | input | Status flags named in `buttons`: `batteryCharging`, `batteryFull`, `micMuted`, `headphonesConnected`, `cableConnected` |
| `hat-octant` | both | 4-bit hat in the declared bit range. `HMHat.None` is `neutralValue` (typically 8), 1..8 are 0..7 |
| `button-mask` | both | Named-button bitmask. `buttons` is an ordered list of `HMButton` names or `"#n"` for bit n (LSB first within the declared bit range). `"_"` is a placeholder slot |
| `stick12-pair` | input | Two 12-bit stick axes packed in three bytes, a Switch 2 stick |
| `rgb24` | output | 3 contiguous bytes packed as R, G, B |
| `packed-uint` | output | Bit groups gathered across frames of a stride and reduced to one value (v2.0.0) |
| `crc32-le` | both | CRC-32/ISO-HDLC (poly 0xEDB88320) over `scope.prefix` + report bytes `[scope.from..scope.to]`, stored LE in the declared 4-byte range |
| `bytes-passthrough` | both | Opaque byte slice. `parsed[semantic]` is `byte[]` of the declared range length |
| `bytes-zero` | encode | Explicit zero-fill (default for unmapped bytes) |

An unknown type, or an input semantic the type cannot read, refuses a profile file at load and a profile built in code at create, with the profile and the field's JSON path.

### Report field parameters (v2.0.0)

As of v2.0.0 a field's wire form is set by parameters, never by a type named for a device. A parameter on a type that ignores it is refused.

| Key | On | Meaning |
|---|---|---|
| `min`, `max` | every type that carries a normalized value | The wire values at the SDK's 0 and 1. The type's full range by default. `min` equal to `max` is refused |
| `invert` | every axis and trigger type | The wire grows the other way |
| `center` | `int16-le` | The wire value of a zero reading, 0 to 65535. 32768 writes offset binary, as the PS Move's motion words are. The word clamps to 0 to 65535 |
| `scale`, `negate`, `repeat` | `int16-le` of a calibrated source, `accelGX` to `gyroDpsZ` | Counts per g or per degree a second, as a number or an exact ratio such as `[13371, 936]`, and `[count, stride]` for a report that carries several samples |
| `dpad: "resolved"` | `button-mask`, `hat-octant` | The d-pad from `HatDegrees`, `HatHundredths`, `HatRaw` or `Hat`, the first one set |
| `"#n"` in `buttons` | `button-mask` | `HMButton` bit n |
| `levels`, `chargingValue`, `fullValue` | `uint8-level-map` | The battery byte as an 11-entry table, `fullValue` ahead of `chargingValue` |
| `clock: "accumulate"`, `divisor`, `holdWhile` | `uint16-le`, `uint32-le` of `sensorTimestamp` | Elapsed time in the 1/3 microsecond ticks of `SensorTimestamp`, from the controller's clock until the first nonzero consumer stamp and from the consumer's stamps after. A repeat of the last state adds nothing, and a stamp that runs backward adds one idle interval. `holdWhile` names a protocol register under which the clock holds still, as `steam-controller-2`'s does while the host has its IMU off |
| `parts` | `packed-uint` | Bit groups over frames of a stride, reduced by `max`, scaled and clamped to a byte, as the Switch Pro's and Switch 2 Pro's rumble is |
| `triggerThreshold: { max, at }` | `button-mask` with `LT_DIGITAL` or `RT_DIGITAL` | Since v2.0.2, each trigger bit is set while the trigger's value on `max` counts is at least `at`. Without it a bit sets at the first count of an 8-bit trigger. `steam-deck-composite` and `steam-controller-2` set 29490 of 32767, the 90 percent default of their firmware, and `steam-controller-composite` 255 of 255, where its trigger switch closes |

`ps-move` writes its motion with them:

```jsonc
{ "byte": 13, "type": "int16-le", "semantic": "accelGX",
  "scale": [8723, 2], "center": 32654, "repeat": [2, 6] },
{ "byte": 12, "type": "uint8-level-map", "semantic": "batteryLevel",
  "levels": [238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238],
  "chargingValue": 238, "fullValue": 239 }
```

A profile can also set `axisCenters` at the top level, outside any report block. It gives a descriptor-path axis, named by its HID usage, the wire value it carries at the SDK's 0.5. `amazon-luna-usb` sets `{"X": 127, "Y": 127, "Z": 127, "Rz": 127}` and `amazon-luna-ble` 32767 on the same axes, because SDL's Luna driver reads 0x7F and 0x7FFF as zero.

### Keys 2.0.0 requires

Where a profile written for 1.x left a key out and got a behavior from code, 2.0.0 requires the key, so no such profile changes its bytes unseen:

- A `uint16-trigger` or `uint16-pressure` input field needs `max`. 1.x wrote a full pull or press as 32767: add `"max": 32767` for that, or `"max": 65535` for the full width.
- An `int16-axis`, `int16-pad` or `int16-pad-or-stick` field of a Y semantic needs `invert`. 1.x negated every int16 Y: add `"invert": true` for that, or `"invert": false` for a wire that grows downward.
- The `ds3-battery` type is gone. Write it as `uint8-level-map` with `levels` `[1, 2, 2, 2, 3, 3, 4, 4, 4, 5, 5]`, `chargingValue` 238 and `fullValue` 239.
- An output field refuses `min`, `max` and `dpad`, `invert` on any type but `uint8-axis`, and `center` on `int16-le`, since its decoder ignores them.

A profile file that breaks one is refused at load and listed in `HMContext.ProfileLoadIssues`, with the JSON path and the value that keeps 1.x's bytes. A profile built or changed in code is refused at create with `HMProfileException`, before anything machine-wide:

```
JsonPath  $.extendedReport.fields[3]
Reason    extendedReport.fields[3] ('uint16-trigger').max is required. v1 wrote a full pull or press as 32767: add "max": 32767 for that, or "max": 65535 for the full width.
```

Battery scenario S91 checks these refusals beside its golden reports.

### Values on the wire (v2.0.0)

Every normalized value the SDK writes, on the descriptor path, the XUSB slice, the codec, both Switch packers and the output encoder, is `min + RoundHalfEven(v' x (max - min))` in double, where `v'` is the clamped input, or 1 minus it for an inverted field. Ties go to the even value. Through v1.12.0 the SDK truncated or multiplied in float, which sent a value a consumer normalized from a raw count back one count low on 32,895 of the 65,536 values of a 0..65535 axis and on 252 of 256 XInput trigger bytes. Now every raw value comes back as it went in, except on a 16-bit centered stick, where a consumer that normalizes in float gets 64 or 65 values just above the center back one count low.

- A NaN writes the field's resting value, 0.5 for a stick or a centered axis and 0 for a trigger, on every path.
- A stick the consumer leaves unwritten rests at its center. Axes the profile's layout names as sticks rest at 0.5, and every other axis as before, 0.5 when signed and 0 when not.
- An axis with an `axisCenters` entry takes two slopes, computed at create, and rounds its distance from the center once, so 0.5 and a consumer's 32768 / 65535 both land on the center.

Battery scenario S90 sends every raw value of every catalog conversion through the SDK's own code and requires it back.

### Catalog profiles whose bytes changed (v2.0.0)

- `ps-move` presents the 178-byte descriptor a real Move serves over USB: a Game Pad with three top-level collections, so Windows creates three HID children, and its HID child's usage hardware ID is `UP:0001_U:0005`. Its input report is the Move's own. Cross is `HMButton.A`, Circle `B`, Square `X`, Triangle `Y`, Select `Back`, Start `Start`, PS `Guide` and Move `Misc1`, and the T trigger is the left trigger. Motion goes in `AccelGX/GY/GZ` and `GyroDpsX/Y/Z`. Its battery byte is 0xEE, or 0xEF with `BatteryFull`, and its manufacturer string is "Sony Computer Entertainment".
- `xbox-360-flight-stick` presents the 127-byte joystick descriptor its notes cite: 8-bit Z and Rz ahead of its 16-bit axes, a 12-byte report. Its HID child's usage hardware ID is `UP:0001_U:0004`.
- The nine Xbox 360 profiles whose manufacturer string was mangled read "©Microsoft Corporation". Nothing on the wire changes.

Battery scenario S96 checks these against their sources. A program that stored the HID child path of `ps-move` or `xbox-360-flight-stick` sees a new device once. See [Moving from 1.x](../start/migration.md#bytes-on-the-wire).

`semantic` is the dictionary key consumers see in `OutputDecoded.Fields` and pass to `HMOutputEncoder.Encode`. Pick names per your domain.

### Field positioning syntax

- `"byte": N`: single byte at offset N (0-indexed; byte 0 is the report ID)
- `"bytes": "N-M"`: inclusive range [N..M] (used by `crc32-le`, `rgb24`, `bytes-passthrough`)
- `"bits": "L-H"`: sub-byte bit range [L..H] within the byte/byte-range

### CRC32 scope

```jsonc
"scope": {
  "prefix": [161, 49],   // two bytes for Sony BT input: [0xA1, 0x31]
  "from": 1,             // first byte covered (after report ID)
  "to":   73             // last byte covered (before CRC field)
}
```

Sony's wire-format prefixes:
- Input report CRC: `[0xA1, reportId]`
- Output report CRC: `[0xA2, reportId]`
- Feature report CRC: `[0x53, reportId]` (per dualsense-tester reference impl)

### Arming: `armOn` and `alwaysArmed`

A vendor blob is not always what the controller emits first. Sony BT pads power up on the short legacy report and only switch to `0x31` / `0x11` once a host reads feature `0x05`, `0x09` or `0x20`, which is the same handshake real firmware uses. `armOn` lists those triggers, and until one fires the SDK takes the descriptor-driven path so joy.cpl and RawInput still see structured axes.

```jsonc
"armOn": [
  { "type": "featureRead", "reportId": "0x05" },
  { "type": "featureRead", "reportId": "0x09" }
]
```

Trigger types are `featureRead`, `featureWrite` and `outputWrite`.

Some controllers have no handshake to wait for. A Switch 2 Pro streams its structured report `0x09` from power-on and leaves it only when a host asks for the vendor blob instead, so waiting would be wrong in both directions: nothing would ever arm, and the descriptor's first declared report is the opaque `0x05` blob with no buttons or axes in it. Those profiles set `alwaysArmed` and emit the vendor report from the first frame.

```jsonc
"extendedReport": { "reportId": "0x09", "size": 64, "alwaysArmed": true, "fields": [ ... ] }
```

A profile with neither `armOn` nor `alwaysArmed` never runs the codec on the input direction, which is the correct default for every USB Sony profile and every plain-HID gamepad. The output direction ignores both fields.

---

### When to use `extendedReport` vs leave it unset

Set `extendedReport` only when the descriptor's first declared input is an opaque vendor blob and the wire format requires firmware-convention byte placement. For controllers whose descriptors fully describe the input report (Xbox 360 wired, DualSense USB, Switch Pro, every plain-HID gamepad), the descriptor-driven encoder packs correctly without an `extendedReport` block: leave it null/unset.

`extendedOutputReport` is independent: even when the input descriptor is fully self-describing, declaring an `extendedOutputReport` lets consumers use `HMOutputEncoder.Encode(profile, fields)` to produce wire-format bytes for driving real devices without inline byte-packing. v1.3.5 ships output blocks for DS5 USB (Report 0x02), DS5 Edge USB, DS4 v1/v2 USB (Report 0x05), in addition to BT output blocks for the DS5 family (Report 0x31) and DS4 BT (Report 0x11).

When `extendedReport` is set, the descriptor should declare the matching report ID first so the kernel HID stack delivers the right ID to consumers. The Sony BT profiles in v1.3.5 reorder their descriptors to put Report 0x31 (DS5 family) or Report 0x11 (DS4 family) INPUT before Report 1.

---

## Devices with ports and protocols (v2.0.0)

Some devices carry several controllers in one report, and some answer commands a host must send before they report at all. A profile describes both as data, and the SDK holds only mechanisms any profile can use. The Wii U GameCube adapter is built this way, and nothing in the SDK names it. See [Wii U GameCube Adapter](../sdk/gamecube-adapter.md) for the device and `profiles/nintendo/gamecube-adapter.json` for the whole profile.

### `extendedReport.ports`

A report that carries several controllers, one block per port: a multi-port adapter, a multitap, a receiver with several pads.

| Key | Meaning |
|---|---|
| `count`, `offset`, `stride` | How many blocks, where port 1's starts, and how far apart they are. Byte 0 is the report ID, so an input report with an ID, and every output report, start their blocks at byte 1 or later |
| `status` | The block's status byte: its `byte` offset, the `connections` a port can hold with the value each sets (the first is the empty port, the second the default, at least two, each with a value of its own), and device-wide `flags` every status byte carries while on |
| `data` | The block's data bytes, such as `"1-8"`. An empty port's are zero |
| `snapshots` | Copies of a block the device keeps, taken `on: "connect"` from the first report in which the port holds something |
| `fields` | The block's fields in the `extendedReport` field vocabulary, offsets relative to the block |

```jsonc
"extendedReport": {
  "reportId": "0x21", "size": 37, "alwaysArmed": true, "fields": [],
  "ports": {
    "count": 4, "offset": 1, "stride": 9,
    "status": {
      "byte": 0,
      "connections": [
        { "name": "empty", "value": "0x00" },
        { "name": "wired", "value": "0x10" },
        { "name": "wireless", "value": "0x22" },
        { "name": "wirelessNotCommunicating", "value": "0x20" }
      ],
      "flags": [ { "name": "rumblePower", "value": "0x04", "default": true } ]
    },
    "data": "1-8",
    "snapshots": [ { "name": "origin", "on": "connect" } ],
    "fields": [
      { "byte": 1, "type": "button-mask", "buttons": ["A","B","X","Y","DPAD_LEFT","DPAD_RIGHT","DPAD_DOWN","DPAD_UP"] },
      { "byte": 2, "type": "button-mask", "buttons": ["Start","RightBumper","RightTriggerClick","LeftTriggerClick"] },
      { "byte": 3, "type": "uint8-axis", "semantic": "leftStickX" },
      { "byte": 4, "type": "uint8-axis", "semantic": "leftStickY", "invert": true },
      { "byte": 7, "type": "uint8-trigger", "semantic": "leftTrigger" }
      // ...the C-stick at bytes 5 and 6 and the right trigger at byte 8
    ]
  }
}
```

`extendedOutputReport.ports` describes an output report's blocks the same way. Its fields are whole numbers, `uint8`, `uint8-axis`, `uint8-trigger`, `uint16-le` and `int16-le`, and each is reported under its `semantic`: `HMPort.GetOutput("rumble")`, and `port1.rumble` in `OutputDecoded`. Its port count must match the input report's.

### `protocol`

How a USB/IP device behaves beyond its descriptors. As of v2.0.0 `protocol` sits at the profile's top level. `usbConfiguration.protocol` is refused at load with its path. The full grammar is mechanism 3 of [the data-driven design note](https://github.com/hifihedgehog/HIDMaestro/blob/master/docs/design/data-driven-devices.md).

| Key | Meaning |
|---|---|
| `state` | Registers of 1 to 32 bits with `initial` values, restored at attach and at a port reset unless `keepOnPortReset`. At most 64 |
| `counters` | Counts of reports, frames, reads or clock periods, each written into replies and reports |
| `memory` | Images a reply reads from and a rule writes into, filled, with constant segments and value segments such as the serial |
| `input` | The interrupt IN `endpoint`, the condition under which a poll gets a report (`while`, such as `["polling", "!stalled"]`), and its `clock`. For a device that sends the SDK's report, the clock is the device's own controller poll in `sourcePollMs`, with `sourcePollRules` that change it while exactly the listed ports hold something. For a device that builds its reports, it is a period, an origin and a missed-tick rule |
| `commands` | The interrupt OUT `endpoint`, whose packets are each a command. `setReport` makes a SET_REPORT(Output) one command too, its whole data stage, report ID first. `setReportStripsId`, with `setReport` only, drops a leading byte that matches wValue's report ID, when that ID is not 0, from a data stage longer than one byte, as tinyusb does. A reply prefix and status, then `rules`, tried in order: the first that matches applies, and a command no rule matches is ignored. A rule matches a command's bytes, with `..` for any byte, and its length, then sets, stores, ORs or clears registers, writes memory, decodes or raises an output report, and queues a `reply` built from the registers before the rule ran: constant bytes, echoed command bytes, a register, a counter, memory, a bitmap, a layout's bytes, a value or a `snapshot`'s bytes for every port. Each part can take a `while`, and is zeros when it does not hold |
| `replies` | The channel replies go out on (the input endpoint, or a bulk IN endpoint), `pending`, how many can wait (1 when absent), and `overflow`, which one a reply past them drops |
| `decoders` | Output reports decoded into named values that `OutputDecoded` carries |
| `halt` | The registers under which the device answers nothing, at least one, and the `status` transfers fail with until a port reset: `EPROTO`, the default, or `EPIPE` |
| `setProtocol` | `"ack"`, or `"stall"`, the default |
| `getStatus` | `"descriptor"`: the self-powered bit the configuration declares |
| `getReport` | The GET_REPORT answer. `"input"`, the default, answers the input report as it stands for its own ID, another declared input report with its ID and zeros, and stalls an ID the descriptor does not declare. `"reportId"` answers the requested report ID alone and stalls report ID 0 or a one-byte request, for every report type, as tinyusb does for a firmware that supplies no report. `"deviceReport"`, for a device that builds its reports, answers the layout that would go out now |
| `log` | How many commands the device keeps, raw, for a consumer to read |

```jsonc
"protocol": {
  "state": [ { "name": "polling" }, { "name": "stalled" }, { "name": "halted" } ],
  "input": {
    "endpoint": "0x81",
    "while": ["polling", "!stalled"],
    "clock": { "sourcePollMs": 1.19971, "sourcePollRules": [ { "portsConnected": [1, 2], "periodMs": 0.9995 } ] }
  },
  "commands": {
    "endpoint": "0x02",
    "setReport": true,
    "setReportStripsId": true,
    "rules": [
      { "match": "11", "minLength": 5 },
      { "match": "11", "set": { "stalled": true } },
      { "match": "12", "reply": [ { "hex": "22" }, { "snapshot": "origin", "bytes": "3-8", "while": ["polling"] } ] },
      { "match": "13", "set": { "polling": true, "stalled": false } },
      { "match": "14", "reply": [ { "hex": "24" }, { "state": "polling" } ], "set": { "polling": false } },
      { "match": "15", "set": { "halted": true, "polling": false } }
      // ...0x16 and 0x17 set stalled too
    ]
  },
  "replies": { "pending": 1, "overflow": "dropNewest" },
  "halt": { "while": ["halted"], "status": "EPROTO" },
  "setProtocol": "ack",
  "getStatus": "descriptor",
  "getReport": "reportId"
}
```

The device runs the protocol on a modeled host poll. A host polls an interrupt endpoint every period while a transfer is queued, on a grid that starts at attach and again at a port reset, and fills a transfer one packet per poll. The period is the one Windows gives the endpoint descriptor's bInterval: 8 ms for bInterval 0 to 15, 16 ms for 16 to 35 and 32 ms beyond at low speed, bInterval ms rounded down to a power of two, at most 32, at full speed, and 2^(bInterval-1) microframes, at most 32, at high speed. `usbConfiguration.busSpeed` takes `"low"`, `"full"` or `"high"`, the default. A low-speed device is held to an 8-byte control endpoint, interrupt endpoints of at most 8 bytes, and no bulk or isochronous endpoints. `HMController.DeviceProtocol.HostPollInterval` models a faster host and takes only a period Windows schedules at the device's speed. It throws `InvalidOperationException` on a device that builds its reports, which sends them on its own clock, and on one whose protocol names no input endpoint. A command, its reply, a report and a GET_REPORT answer allocate nothing, which battery scenario S95 checks over 100,000 of each. A device with a `sourcePollMs` has a new report for a host poll only once it has read its controllers since its last report, as real hardware does.

### `usbConfiguration.winUsb` and `sharedSerial`

`winUsb.interfaceGuid` is the `DeviceInterfaceGUIDs` value a WinUSB binding registers, which libusb needs to open a WinUSB device. `HMController.BindWinUsb()` builds the driver package from it and the device's descriptors. The device must have one interface and `bDeviceClass` 0. See [Dolphin, Slippi and SDL](../sdk/gamecube-adapter.md#dolphin-slippi-and-sdl) for where the binding goes and what it leaves on an instance a real adapter can take.

`sharedSerial: true` serves the profile's `serialString` unchanged for every identity key, for a device whose every unit carries the same serial. Other USB/IP personas fold the identity into their serial.

### Validation

A profile file's device model is checked when it loads, and a mistake refuses the file into `HMContext.ProfileLoadIssues` with its JSON path. `CreateController` compiles the whole model again before it takes anything machine-wide, so a profile built or changed in code is refused with `HMProfileException` naming the profile, the JSON path that holds it and the limit it breaks. Both refuse:

- ports that do not fit their report, or that start on the report ID byte
- a status block with fewer than two connections, or two connections that share a value
- input report fields beside ports, and output report fields that overlap the port blocks
- a field outside a block's data bytes, or wider than its block or report by its type's own width
- an unknown field type, an input semantic that names no SDK value, or a button name the SDK cannot express
- a report ID that does not parse, or an `armOn` type other than `featureWrite`, `outputWrite` and `featureRead`
- an output port count that differs from the input's, or more than 32 ports under a protocol
- an input report over the 80-byte extended lane, or an output block or field past the output ring's 256 data bytes
- output ports or fields past one OUT packet on a protocol whose SET_REPORT loses its report ID
- a command rule whose match or minimum length is longer than the OUT endpoint's packet
- a register a rule names that `state` does not declare, `replies.pending` outside 1 to 1024, `setReportStripsId` without `setReport`, or a `getReport` other than `"input"`, `"reportId"` and `"deviceReport"`
- `usbConfiguration.protocol`, which moved to `protocol` at the top level
- an endpoint the configuration descriptor lacks or of the wrong type, and a reply on a device with no input endpoint
- a low-speed device over its packet limits, an endpoint whose transfer type differs between alternate settings, an interrupt or bulk endpoint whose descriptors differ between them, or an isochronous endpoint declared in more than one
- a WinUSB GUID that does not parse

The descriptor checks run at that point only for a profile with `protocol` or `winUsb`, whose descriptors the device model compiles. Every other USB/IP persona meets them when its device is built, after its transport index is taken. Every catalog profile compiles, which battery scenario S79 checks.

---

## Report programs and `stream` (v2.0.0)

A device that builds its reports at send time splits into data. Four catalog profiles work this way: `switch-pro`, `switch-pro-usb`, `dualshock-3-full` and `switch2-pro-controller-composite`.

- `stateBlock`: a field list in the codec's vocabulary that `SubmitState` encodes. A raw submit on such a device is the state block itself, verbatim and of its size, and any other length throws `ArgumentException`. `HMProfile.BuildsItsOwnReports` says which profiles work this way.
- `inputReports`: layouts, each with a report ID, a size, a `while` condition on the protocol's registers, a `send` rule and a program over the state block. A program is built from `copy`, `bits`, `const`, `xor`, `swap16`, `field`, `lookup`, `hat8`, `pack12`, `counter` and `when` blocks.
- `liveFeatureReports`: the same programs, for a feature report whose answer is the current state.

The build turns every catalog program and decoder into straight-line C#, and the SDK binds it once at create. A program from outside the catalog runs on an interpreter compiled from the same validated form, with no rebuild. A catalog program the build cannot validate fails the build with `KG0001`, its file and its JSON path. Battery scenario S94 runs every program three ways: generated, interpreted and through a naive evaluator written from the design note.

### `stream`

`stream` gives a device's idle repeat: the consumer's last frame sent again one period after the last frame went out, as the real device reports at rest.

| Key | Meaning |
|---|---|
| `periodMs` | The period, fractions allowed, such as 1.25 for a DualSense over Bluetooth |
| `periodRegister` | A period a host sets, from a protocol register, with `periodMs` while the register holds 0 |
| `while` | When the device streams, on the protocol's registers. Absent streams from creation |
| `timestamps` | `"hold"`, the default, repeats the consumer's last sensor timestamp. `"advance"` moves it on by the time since the frame it repeats |

`extendedReport.idleFrameIntervalMs` still loads as a stream of that period. 21 catalog profiles repeat at rest: the DualSense family at 1 ms (Edge), 1.25 ms (Bluetooth) and 4 ms (USB), the DualShock 4 USB family and `steam-deck` at 4 ms, `openffboard` at 101 ms and five Thrustmaster wheels at 250 ms, none of which repeated anything before 2.0.0, and `steam-controller-2`, `steam-deck-composite` and `steam-controller-composite`, which already did. A consumer that counts frames sees the repeats.

Since v2.0.2 those three Valve profiles set `extendedReport.send` to `"clock"`: every report goes out on the device clock, one each `idleFrameIntervalMs` (4 ms on the Deck and the 2026 controller, 9 ms on the 2015 controller), carrying the consumer's latest frame, and a submit only stores it. `"submit"`, the default, sends each frame as the consumer submits it and repeats the last one while the consumer is quiet.

---

## Device models (v2.0.0)

A profile's device model is the behavior it gives beyond its reports, in three groups, each resolved at load on its own:

| Group | Keys |
|---|---|
| Answers | `featureStubs`, `valueSources` |
| Protocol | `protocol`, `stateBlock`, `inputReports`, `liveFeatureReports` |
| Presentation | `xinput`, `driverMode` as its alias, `driverPid` |

Within a group the first of these that applies wins, and no two merge:

1. The profile's own keys in the group.
2. `deviceModelFrom`, naming a catalog profile, a model this release holds or a model loaded from the profile's directory.
3. A name nothing loaded holds, or a model that does not fit the profile's descriptor: the identity default, and `HMProfile.DeviceModelProblem` says why.
4. No keys and no name: the identity default whose entry matches the profile, or nothing.
5. `"deviceModel": "none"`: no model.

The identity defaults are data, `profiles/models/identity-defaults.json`, written from the vendor and product checks 1.x kept in code: the Switch Pro over USB and over Bluetooth (057E:2009, the models `switch-pro-usb` and `switch-pro`), a `sixaxisCompatible` profile (`dualshock-3-full`), Sony's VID 054C by product and connection, each Sony entry naming one of the six Sony models (`sony-dualsense`, `sony-dualsense-bt`, `sony-dualsense-edge`, `sony-dualsense-edge-bt`, `sony-dualshock4`, `sony-dualshock4-bt`), and VID 045E with "xbox" in the id, name or product string, which gives `xbox-360-wired`'s presentation, an XUSB companion. The 16 Sony catalog profiles name theirs with `deviceModelFrom`, the ten Xbox 360 profiles carry their `xinput` block and the twelve xinputhid profiles their `driverMode`, and no catalog profile takes a group from an identity default, which battery scenario S92 checks. The defaults exist so a profile from `HMProfileBuilder`, `HMDeviceExtractor` or your own JSON keeps the behavior its identity got from 1.x.

`HMProfile.HasDeviceModel`, `DeviceModelSource` (per group: `own`, `named:<id>`, `identity:<entry>` or `none`) and `DeviceModelProblem` report the result. `HMDeviceExtractor.Extract` writes the `deviceModelFrom` its identity gives, and `HMDeviceExtractor.ResolveDeviceModel` returns a copy with that name for a profile that has none.

A file from a directory gets every check at load. The embedded catalog's files had their model groups checked at build, where a program that does not compile fails the build with `KG0001`, and S92 loads the same files with every check, so the catalog's own load reads their groups without checking them again.

A directory loaded with `LoadProfilesFromDirectory` can carry a `models` folder at its top: named models and an `identity-defaults.json` in the catalog's formats, which load with no rebuild. Its models resolve by name for its profiles and later loads, and its identity defaults are tried before the catalog's, for profiles outside the catalog, as `identity:<file>#<entry>`. A `keyedHexFile` value source is refused on UMDF2, where the driver answers without calling the SDK.

On UMDF2 the SDK compiles a profile's answers into the controller's `FeatureAnswers` value, and the driver answers from it only for a 2.0.0 SDK's controller. A 1.x program's controller on the 2.0.0 driver gets no feature answers.

---

## Three runtime architecture groups

The profile fields determine which of three architecture groups the runtime instance lands in. USB/IP profiles (`"backend": "usbip"`), the composite personas and the GameCube adapter, are none of the three: see [Composite USB Personas](../sdk/usb-audio-composite.md). Disposal speed, device-tree shape, and downstream API mechanics all vary by group. See [Lifecycle and Teardown](../reference/lifecycle-and-teardown.md) for the per-group teardown latency table. The create and dispose times in the headings below were measured before v2.0.0.

### 1. Plain HID (~200 ms create, ~80 ms dispose)

Profiles on HIDMaestro's UMDF2 driver with no XInput presentation. The parent is `ROOT\HIDClass\<token>`. As of v2.0.0 that includes the nine Microsoft profiles that are no XInput device, the SideWinder Force Feedback 2 and eight keyboards and mice, which carry no `IG_` and no XUSB compatible IDs, so SDL now lists them.

Includes DualSense, DualShock 4, all Logitech wheels, Thrustmaster HOTAS, flight sticks, pedals, arcade sticks, every keyboard and mouse, and most of the 337-profile catalog (307 profiles).

```
ROOT\HIDClass\<token>               ← UMDF2 driver (mshidumdf host)
  └─ HID\VID_054C&PID_0CE6\...       ← raw HID PDO, no upper filter
```

Lightest stack. One `DIF_REMOVE` on the ROOT parent tears down the entire tree. No XUSB companion device, no Microsoft upper filter.

### 2. Non-xinputhid Xbox (~200-700 ms create, ~135 ms dispose)

Profiles whose `xinput` block names `"via": "xusbCompanion"`, the Xbox 360 family. XInput is delivered via a separate SWD-enumerated XUSB companion device running `HMXInput.dll`. WGI dispatch also runs through that companion, admitted by the xinputhid UpperFilter tripwire.

Includes Xbox 360 Wired (`xbox-360-wired`), Xbox 360 Type 2, Xbox 360 Wireless, Xbox 360 dance pad, Xbox 360 Arcade Stick, Xbox 360 Wheel V1/V2, Xbox 360 Guitar V1/V2 and the Xbox 360 flight stick: a 10-profile group. Xbox Adaptive is not in it. It sets `driverMode: xinputhid` and belongs to the group below.

```
ROOT\VID_045E&PID_028E&IG_00\NNNN    ← UMDF2 driver (main HID device)
  │                                    UpperFilters += "xinputhid" per-instance
  │                                    (SDK-written; blocks WGI from synthesizing
  │                                    a duplicate HID-backed Gamepad)
  └─ HID\VID_045E&PID_028E&IG_00\... ← HID child (raw PDO, input.inf)
SWD\HIDMAESTRO\<sid>_NNNN            ← XUSB companion (HMXInput.dll)
  │                                    SwDeviceCreate, System class, explicit
  │                                    per-controller ContainerID (shared with main HID).
  │                                    UpperFilters = "xinputhid" from INF
  │                                    (admits the companion to WGI's XUSB
  │                                    dispatch; xinputhid.sys does not actually
  │                                    attach: wrong device class).
  └─ XUSB interface → XInput slot + WGI Gamepad
```

Medium stack, fast on both sides post-v1.3.2. Two device trees to tear down. The XUSB companion runs its own WUDFHost instance hosting `HMXInput.dll`, which needs its own PnP release cycle.

### 3. xinputhid Xbox (~150-600 ms create, ~500 ms dispose)

Profiles with `driverMode: "xinputhid"`. These match `xinputhid.inf [GIP_Hid]` by hardware ID (`HID\VID_045E&PID_0B13&IG_00`), which binds Microsoft's `xinputhid.sys` as an upper filter on the HID child. xinputhid provides XInput delivery and 16-button HID descriptor synthesis natively: no XUSB companion needed, single Device Manager entry.

Includes the whole Xbox One / Series / Elite family, wired and Bluetooth: `xbox-series-xs`, `xbox-series-xs-bt`, `xbox-one-s`, `xbox-one-s-bt`, `xbox-one-s-bt-full`, `xbox-one-original`, `xbox-one-rev1`, `xbox-elite-v1`, `xbox-elite-v2`, `xbox-elite-v2-bt`, `xbox-elite-v2-bt-v2` and `xbox-adaptive`. Twelve profiles using Microsoft's GIP-over-HID protocol.

```
SWD\HIDMAESTRO_VID_045E_PID_0B13&IG_00\<sid>_NNNN
  │                                  ← UMDF2 driver via SwDeviceCreate
  │                                    (mshidumdf host). Explicit non-sentinel
  │                                    ContainerID closes the slot-1-skip
  │                                    bit-2 path in xinput1_4!FUN_18000de2c.
  │                                    Underscore between VID and PID avoids
  │                                    the `VID_*&PID_*&IG_*` PnP edge case;
  │                                    `&IG_00` retained for HIDAPI/SDL3/Chromium.
  └─ HID\HIDMAESTRO_VID_045E_PID_0B13&IG_00\...
        │                            ← HID child (xinputhid.inf, xinputhid
        │                              upper filter)
        ├─ xinputhid.sys              ← Microsoft inbox kernel filter
        ├─ XInput delivery (internal)
        └─ 16-button HID synthesis
```

Both sides fast post-v1.3.2. xinputhid is a Microsoft inbox kernel filter driver; we don't ship it. The SwD-first removal ordering in v1.3.1 closes the SwD parent first, and the children cascade automatically.

> The 16-button synthesis is a **known trade-off**. Win11's xinputhid replaces the source descriptor's button declaration with a 15+ button Xbox One layout. This is incompatible with profiles that need the Xbox 360's 10-button fidelity through DirectInput (`btnfix.c` exists in the repo as an experimental approach but is incomplete: the trade-off stands as of v1.3.4). For Xbox 360 Wired the catalog profile uses driverMode=null + XUSB companion to keep 10 buttons through DI; for Xbox Series BT it accepts 16 buttons because the source descriptor already has 12 and the +4 are dead bits.

---

## How `CreateController` resolves a profile

1. **Index allocation.** Linear scan from 0; first free index wins. Locked.
2. **Architecture group selection.** Branch on the presentation, the `xinput` block or the one the profile takes from a model:
   - no XInput &rarr; plain HID
   - `"via": "xusbCompanion"` &rarr; non-xinputhid Xbox (XUSB companion)
   - `"via": "xinputhid"`, or `driverMode: "xinputhid"` &rarr; xinputhid Xbox
3. **Container ID assignment.** Per-controller GUID `{48494430-4D41-4553-5452-4F00...<idx>}` (ASCII "HIDMAESTRO" + 16-bit index). Shared by the main HID and any companion so xinput1_4 and Settings dedupe them. See [SwDevice and PnP](../reference/swdevice-and-pnp.md).
4. **Per-instance registry write.** Writes `ControllerIndex`, `Vid`, `Pid`, `ProductString`, `ManufacturerString`, `DeviceDescription`, `ReportDescriptor` (REG_BINARY), the compiled feature and XUSB answers, etc. to `HKLM\SOFTWARE\HIDMaestro\Controller<index>` and the device's HW key. The driver reads these at `EvtDeviceAdd`.
5. **Device creation.** Plain HID via `SetupDiCreateDeviceInfoW`; SWD profiles via `SwDeviceCreate` (called through `hmswd.exe` to bypass a .NET P/Invoke incompat).
6. **PnP wait.** Polls the HID child for `DN_STARTED`. Up to 10 s on slow machines; typically <100 ms.
7. **XInput slot-claim wait** for Xbox profiles. Capped at 500 ms post-v1.3.2 to avoid 13-14 s freezes when xinputhid's allocator is in a stuck state.
8. **UpperFilter writes** for non-xinputhid Xbox profiles. INF carries it on the companion; SDK writes per-instance on the main HID device.
9. **Friendly-name application.** Best-effort; finalize via `HMContext.FinalizeNames` after all controllers are created.

The full per-archetype sequence lives in `DeviceOrchestrator.cs`'s `SetupController` (~390 lines). See [Lifecycle and Teardown](../reference/lifecycle-and-teardown.md) for the disposal counterpart.

---

## Loading the catalog

```csharp
// Embedded catalog (337 profiles)
ctx.LoadDefaultProfiles();

// Custom directory of JSON profiles
ctx.LoadProfilesFromDirectory(@"C:\my-profiles");

// Mix both. An id already loaded refuses the later file.
ctx.LoadDefaultProfiles();
ctx.LoadProfilesFromDirectory(@"C:\my-extra-profiles");

// What a load refused, and why
foreach (var issue in ctx.ProfileLoadIssues)
    Console.WriteLine(issue);   // file at $.json.path: reason

// Lookup
HMProfile? p = ctx.GetProfile("xbox-360-wired");

// Enumerate
foreach (var profile in ctx.AllProfiles)
    Console.WriteLine($"{profile.Id}: {profile.Name}");
```

Profiles are loaded into the context's catalog. As of v2.0.0 they load strictly. A file that does not parse, a key the schema lacks, a key written twice, a value a check refuses, a removed spelling (`steamFirmwareStamp`, the `ds3-battery` type, `usbConfiguration.protocol`) and an id already loaded each refuse the file. None of them throws from the load. Each becomes an `HMProfileLoadIssue` in `HMContext.ProfileLoadIssues`, with `File`, `ProfileId`, `JsonPath` (as the file writes it, such as `$.protocol.rules[3].reply[1].length`), `Reason` and `Kind`: `Refused`, `NotAProfile` for a file with no `id`, or `ModelProblem` for a profile that loaded with a model problem. Files load in ordinal path order, and a repeated id refuses the later file and names the earlier one, so an edited copy of a catalog profile needs an id of its own. Schema files (`schema.json`) and the directory's top-level `models` folder are not read as profiles.

### Checking a profile before you ship it

`HIDMaestroProfileCheck`, in the release ZIP beside the profile extractor, loads the catalog and then a profile file or directory as the SDK does. It prints each issue of the named files as `<file> at <JSON path>: <reason>`, and each loaded profile with its `DeviceModelSource`:

```
HIDMaestroProfileCheck [--cost [--launches N] [--runs N] [--reports N] [--register name=value ...]] <file or directory> ...
```

It exits 0 when every named file loads clean, 1 when one has an issue or a measurement fails, and 2 on a usage error. `--cost` runs each of the file's report programs and decoders on the interpreter, as a profile from outside the catalog runs them: 30 hidden launches at high priority by default, each the median of 10 runs of 100,000 reports, printing p50 and p95 with the runtime, tiering, CPU and instruction set, and each program's compile and the whole model's. Registers start at the protocol's initial values, so a block a host's command turns on runs only with `--register` setting it, as `featureEnabled=0x04` turns on the Switch 2 Pro's motion in report 0x05.

A consumer that wants to ship a **subset** of the catalog (e.g. only racing wheels) loads just that subset:

```csharp
ctx.LoadProfilesFromDirectory(@"C:\my-app\racing-wheels-only");
// Don't call LoadDefaultProfiles
```

Consumers that want to **modify** a built-in profile clone via `HMProfileBuilder.FromProfile`:

```csharp
var modded = new HMProfileBuilder()
    .FromProfile(ctx.GetProfile("dualsense")!)
    .Pid(0x9999)
    .ProductString("Modded DualSense")
    .Build();

using var ctrl = ctx.CreateController(modded);   // not loaded into ctx.AllProfiles
```

The modded profile isn't registered in the catalog: it's used directly for one `CreateController` call. See [Custom Profiles](custom-profiles.md) for the full clone / build / spoof patterns.

---

## A verbatim profile dissected: Xbox 360 Wired

```json
{
  "id": "xbox-360-wired",
  "name": "Xbox 360 Controller (Wired)",
  "vendor": "Microsoft",
  "vid": "0x045E",
  "pid": "0x028E",
  "productString": "Controller (XBOX 360 For Windows)",
  "manufacturerString": "©Microsoft Corporation",
  "type": "gamepad",
  "connection": "usb",
  "descriptor": "05010905a101a10009300931150026ffff350046ffff950275108102c0a10009330934150026ffff350046ffff950275108102c0a1000932150026ffff350046ffff950175108102c0a10009400941150026ffff350046ffff950275108102c005091901290a950a7501810205010939150125083500463b10660e00750495018142750295018103750895028103c0",
  "nativeDescriptor": "05010905A1018501093009311500270000000075109502810209330934810209320935810205091901290A150025017501950281027506950181010501093915012508350046C03C660E007504950181428503060046ED01950E091001110050B5",
  "xinput": { "via": "xusbCompanion" },
  "inputReportSize": 18,
  "deviceDescription": "Controller (XBOX 360 For Windows)",
  "triggerMode": "combined"
}
```

**`descriptor`** is the HIDMaestro-emitted descriptor. **`nativeDescriptor`** is the original from a real Xbox 360 controller. They differ because the catalog version uses Vx/Vy velocity usages to carry separate trigger values without DirectInput recognizing them as axes. The native descriptor declares Z + Rz directly; HIDMaestro's emitted version uses Z (combined trigger) + Vx + Vy (separate triggers) so DirectInput sees 5 axes (matching real xusb22.sys behavior) while WGI / browsers see separate triggers via the GameInput registry mapping. See [Cross-API Coverage](../reference/cross-api-coverage.md).

**`inputReportSize`: 18** is the whole report on the wire. The descriptor declares no Report ID, so there is no ID byte: 144 bits of axes, buttons, hat and padding.

**`triggerMode`: "combined"** annotates the descriptor's trigger encoding for this profile. The HIDMaestro-emitted descriptor declares one Z axis carrying `LT - RT` per real xusb22 DI semantics. **All Xbox profiles** present as 5 axes with combined Z in DirectInput regardless of `triggerMode` value: on profiles where `triggerMode == "separate"` (e.g. Xbox Series BT), xinputhid's synthesis layer collapses the descriptor's separate Z + Rz back into combined Z by the time DI reads the preparsed data. WGI and browser see separate triggers through the Vx/Vy + GameInput-mapping path.

**`xinput`** names `"via": "xusbCompanion"`, so this profile lands in **architecture group 2** (non-xinputhid Xbox + XUSB companion), and the companion answers as a wired gamepad.

**`buttonMap`** is **not present**: identity Xbox layout (`HMButton.A` &rarr; descriptor button 0, etc.).

---

## Catalog statistics

As of v2.0.0:

| Metric | Count |
|--------|-------|
| Total profiles | 337 |
| Keyboards and mice | 103 (51 keyboards, 52 mice) |
| Vendor folders | 59 |
| Plain HID profiles | 307 |
| Non-xinputhid Xbox profiles | 10 |
| xinputhid Xbox profiles | 12 |
| USB/IP profiles | 8 (seven composite personas and the GameCube adapter) |
| With FFB descriptors | 14 (SideWinder Force Feedback 2, the Xbox One / Series / Elite family, Amazon Luna BLE) |
| Bluetooth profiles | 26 |
| Wireless-adapter profiles | 4 |

The largest vendor folders are Logitech (46), misc (32, the catch-all), Microsoft (31), Razer (22), Thrustmaster (20), and Sony (17).

---

## See also

- [Custom Profiles](custom-profiles.md): clone, modify, build from scratch, spoof.
- [Profile Extractor](profile-extractor.md): the GUI tool that reads profiles back from real devices.
- [Contributing Profiles](contributing-profiles.md): submit a captured profile via GitHub issue.
- [Cross-API Coverage](../reference/cross-api-coverage.md): the per-API translation a profile drives at runtime.
- [Lifecycle and Teardown](../reference/lifecycle-and-teardown.md): per-architecture-group teardown latencies.
- [`profiles/schema.json`](https://github.com/hifihedgehog/HIDMaestro/blob/master/profiles/schema.json): the canonical JSON Schema.
