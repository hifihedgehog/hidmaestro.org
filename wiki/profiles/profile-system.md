# Profile System

Every controller HIDMaestro can emulate is a JSON file in `profiles/<vendor>/<slug>.json`. 228 ship in the embedded catalog across 32 vendors (Microsoft, Sony, Nintendo, Logitech, Thrustmaster, Fanatec, MOZA, SimuCUBE, VKB, VIRPIL, WinWing, Honeycomb, Hori, 8BitDo, Razer, Steelseries, Valve, and 16 more). Runtime-built profiles authored via `HMProfileBuilder` use the identical schema and run through identical machinery.

This page documents the JSON schema field-by-field, the three runtime architecture groups a profile can fall into, and how the SDK resolves a profile into a deployable virtual device at `CreateController` time.

---

## On-disk layout

```
profiles/
  schema.json                       # JSON Schema document for all profiles
  scraped_descriptors.json          # 50+ raw descriptors recovered from real devices
  linux-kernel-fixed-descriptors.json  # patched descriptors from the Linux kernel
  microsoft/
    xbox-360-wired.json
    xbox-series-xs-bt.json
    xbox-elite-v2.json
    ...22 Microsoft profiles
  sony/
    dualsense.json
    dualsense-edge.json
    dualshock-4-v1.json
    dualshock-3.json
    ...13 Sony profiles
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
    ...19 Thrustmaster profiles
  ...28 more vendor folders
```

Vendor folder names are slugs of the manufacturer (`thrustmaster`, `8bitdo`, `vkbsim`). File names are slugs of the model (`xbox-360-wired`, `t-flight-hotas-x`, `dualsense-edge-bt`).

The full vendor list at v1.3.4: 8bitdo, amazon, asetek, cammus, ch-products, fanatec, flydigi, google, heusinkveld, honeycomb, hori, logitech, microsoft, misc, moza, nacon, nintendo, pxn, razer, sega, simagic, simucube, snk, sony, steelseries, taito, thrustmaster, turtle-beach, valve, virpil, vkbsim, winwing.

The `misc/` vendor catches everything else &mdash; arcade controllers, niche racing pedals, devices the contributor couldn't slot into a clean vendor namespace.

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
| `id` | string | Unique slug, e.g. `"xbox-360-wired"`. Used by `HMContext.GetProfile`. Must match the filename. |
| `name` | string | Human-readable display name shown in UIs. |
| `vendor` | string | Manufacturer name. Doesn't need to be a slug. |
| `vid` | string | USB Vendor ID as a 4-digit hex string with `0x` prefix. |
| `pid` | string | USB Product ID, same format. |
| `productString` | string | The string returned by `IOCTL_HID_GET_STRING (HID_STRING_ID_IPRODUCT)`. **This is what `joy.cpl` and games see.** Match the real device exactly. SDL3's controller database keys off this. See [when revisions disagree](#when-hardware-revisions-disagree). |
| `type` | string | Controller category. One of: `gamepad`, `wheel`, `joystick`, `flightstick`, `hotas`, `arcadestick`, `pedals`, `other`. |
| `connection` | string | Connection type the profile represents. One of: `usb`, `bluetooth`, `wireless-adapter`. |

### Optional fields

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `manufacturerString` | string \| null | null | The string returned for manufacturer query. Defaults to `vendor` if null. |
| `descriptor` | string \| null | null | HID report descriptor as a continuous hex string. Null = profile is a placeholder, not deployable. |
| `inputReportSize` | int \| null | derived | Total wire size of the input report in bytes (data **+ 1 for Report ID** if the descriptor declares one). When null, derived at runtime from the descriptor. |
| `nativeDescriptor` | string \| null | null | The original physical device's descriptor before any HIDMaestro-side modifications. Kept as a record; not used at runtime. |
| `deviceDescription` | string \| null | `productString` | The Device Manager display name (`FriendlyName` PnP property). Some catalog profiles (Logitech F310) carry a curated `deviceDescription` distinct from `productString`. |
| `triggerMode` | string \| null | null | Profile-level annotation describing the descriptor's trigger encoding: `combined` (descriptor declares one Z axis carrying `LT - RT`), `separate` (descriptor declares independent Z + Rz), or null for non-gamepad. **Note:** every Xbox profile surfaces in DirectInput as 5 axes with combined Z regardless of this annotation &mdash; the velocity-usage trick + xinputhid synthesis collapse separate-trigger descriptors into the canonical `xusb22.sys` 5-axis shape. WGI / browser see separate triggers via Vx/Vy + GameInput registry mapping. |
| `driverMode` | string \| null | null | One of: `xinputhid` (binds Microsoft's xinputhid kernel filter for GIP-over-HID profiles like Xbox Series BT / One BT / Elite v2 BT), `xusb22` (binds the legacy xusb22 upper filter), or null/`hid` (plain HID via `mshidumdf`). The catalog's Xbox-VID profiles overwhelmingly use `null` plus the implicit XUSB companion path; `xusb22` is supported in the deserializer but rarely needed because the SwD-enumerated companion serves the same role with explicit ContainerID control. |
| `driverPid` | string \| null | null | PID override for hardware-ID matching only. The driver's INF-bind process matches against this PID; applications still see the real `pid` field via `HidD_GetAttributes`. Used for xinputhid-bound profiles where the real PID would be claimed by GameInput / HIDAPI &mdash; a sentinel like `0x0001` here makes those backends skip the device so SDL3 falls through to its XInput backend with the correct identity. |
| `companionOnly` | bool | false | If true, the runtime skips main-HID-device creation and runs only the XUSB companion. DI reads from XInput (5 axes), browser reads from XInput (separate triggers). Used for cases where real hardware uses xusb22.sys without an HID interface. |
| `buttonMap` | int[] \| null | identity | Optional remapping table. Index = `HMButton` bit position; value = descriptor button index. Sony profiles use this to swap A/B/X/Y &harr; Cross/Circle/Square/Triangle. `-1` means "abstract bit not in this descriptor" (the bit is dropped, never identity-mapped). Values at or past the declared button count address the contiguous 1-bit vendor run continuing the button array, where the DualSense Edge's paddles and Fn buttons live on real hardware (v1.5.1, issue #48). |
| `axisMap` | object \| null | heuristic | Axis semantic override. Keys are hex HID usage codes (`"0x32"` for Z); values are semantic names (`"leftStickX"`, `"rightTrigger"`). Sony profiles override `Z/Rz &rarr; rightStick`. |
| `sdlMapping` | string \| null | null | v1.5.0+. SDL gamepad mapping body, everything after the GUID and name, trailing comma included. Set it for pads SDL reaches through DirectInput and has no database entry for, which SDL would otherwise expose as roleless joysticks. See [SDK Reference](../sdk/sdk-reference.md) for the consumer side. |
| `triggerButtons` | int[] \| null | null | Two-element array `[LT_button_index, RT_button_index]`. When triggers are nonzero, the corresponding buttons engage automatically (DS4/DualSense L2/R2 digital buttons). |
| `extendedReport` | object \| null | null | v1.3.5+. Vendor-blob input layout. When present, `HMController.SubmitState` packs reports per the field list rather than via the descriptor-driven encoder. Used for profiles where the descriptor declares a single opaque vendor-defined field (Sony BT 0x31, future profiles with similar shape). See section below. |
| `extendedOutputReport` | object \| null | null | v1.3.5+. Vendor-blob output layout. When present, the SDK decodes incoming output reports of the declared report ID and surfaces parsed-field events via `HMController.OutputDecoded`. Pairs with `HMOutputEncoder.Encode` for the inverse direction. |
| `notes` | string \| null | null | Implementation notes, descriptor provenance, quirks. Free-form. |

The full JSON Schema lives in `profiles/schema.json`.

### When hardware revisions disagree

"Match the real device exactly" stops being a complete instruction when a manufacturer changes a string mid-life and leaves nothing on the wire to tell the revisions apart. A DualSense sold in 2020 reports `Wireless Controller`. One sold today reports `DualSense Wireless Controller`. Both report `bcdDevice` 0x0100 and the same 054C:0CE6, so no field a profile could branch on distinguishes them, and a profile serves one string or the other.

HIDMaestro's rule for that case is that the current revision wins, since a consumer keyed to a retired string is already broken against real hardware a user can buy. As of v1.4.5 `dualsense` and `dualsense-composite` serve `DualSense Wireless Controller`. The launch string remains available on `dualsense-bt`, whose `dualsense-bt-full` sibling carries the current one, so both are reachable from the catalog and a consumer that needs the older identity can ask for it by profile id.

Write the reasoning into `notes` when you make this call in a profile of your own. The next person to compare the profile against a descriptor dump will find the mismatch and needs to know it was a decision.

---

## Vendor-blob fields (`extendedReport` / `extendedOutputReport`)

Some controllers' descriptors declare their input as a single opaque vendor-defined field — Sony BT (DualSense, DualSense Edge, DS4 BT) is the canonical example, but Switch Pro and various wheels follow the same pattern. The descriptor doesn't say which bytes carry sticks vs buttons vs gyro vs CRC; the wire format is firmware convention.

Pre-v1.3.5 the SDK couldn't pack these — it would fall back to whatever simpler input report the descriptor declared first (Sony BT: Report 1, 9 bytes), which Steam Input misclassified and parsers like `dualsense-tester` couldn't read. v1.3.5 makes the byte layout data: profile JSON describes every field's type, position, and bit range; the SDK walks the field list as a generic codec.

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
| `uint8` | both | Plain byte; encode reads `Initial`, decode returns `byte` |
| `uint8-rolling` | both | Per-controller monotonic counter (input); plain byte (output) |
| `uint8-axis` | both | Bipolar axis. Encode: `byte = center + clamp(value, ±1) × 127`. Decode: `value = (byte - center) / 127.0` (returns `float`) |
| `uint8-trigger` | both | Unipolar 0..255 axis. Encode/decode mirror with /255 |
| `hat-octant` | both | 4-bit hat in declared bit range. `HMHat.None` → `neutralValue` (typically 8); 1..8 → 0..7 |
| `button-mask` | both | Named-button bitmask. `buttons` is an ordered list of `HMButton` names (LSB-first within the declared bit range). `"_"` is a placeholder slot |
| `rgb24` | output | 3 contiguous bytes packed as R, G, B |
| `crc32-le` | both | CRC-32/ISO-HDLC (poly 0xEDB88320) over `scope.prefix` + report bytes `[scope.from..scope.to]`, stored LE in the declared 4-byte range |
| `bytes-passthrough` | both | Opaque byte slice. `parsed[semantic]` is `byte[]` of the declared range length |
| `bytes-zero` | encode | Explicit zero-fill (default for unmapped bytes) |

`semantic` is the dictionary key consumers see in `OutputDecoded.Fields` and pass to `HMOutputEncoder.Encode`. Pick names per your domain.

### Field positioning syntax

- `"byte": N` — single byte at offset N (0-indexed; byte 0 is the report ID)
- `"bytes": "N-M"` — inclusive range [N..M] (used by `crc32-le`, `rgb24`, `bytes-passthrough`)
- `"bits": "L-H"` — sub-byte bit range [L..H] within the byte/byte-range

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

Set `extendedReport` only when the descriptor's first declared input is an opaque vendor blob and the wire format requires firmware-convention byte placement. For controllers whose descriptors fully describe the input report (Xbox 360 wired, DualSense USB, Switch Pro, every plain-HID gamepad), the descriptor-driven encoder packs correctly without an `extendedReport` block — leave it null/unset.

`extendedOutputReport` is independent: even when the input descriptor is fully self-describing, declaring an `extendedOutputReport` lets consumers use `HMOutputEncoder.Encode(profile, fields)` to produce wire-format bytes for driving real devices without inline byte-packing. v1.3.5 ships output blocks for DS5 USB (Report 0x02), DS5 Edge USB, DS4 v1/v2 USB (Report 0x05), in addition to BT output blocks for the DS5 family (Report 0x31) and DS4 BT (Report 0x11).

When `extendedReport` is set, the descriptor should declare the matching report ID first so the kernel HID stack delivers the right ID to consumers. The Sony BT profiles in v1.3.5 reorder their descriptors to put Report 0x31 (DS5 family) or Report 0x11 (DS4 family) INPUT before Report 1.

---

## Three runtime architecture groups

The profile fields determine which of three architecture groups the runtime instance lands in. Disposal speed, device-tree shape, and downstream API mechanics all vary by group. See [Lifecycle and Teardown](../reference/lifecycle-and-teardown.md) for the per-group teardown latency table.

### 1. Plain HID (~200 ms create, ~80 ms dispose)

Profiles where `driverMode` is **not** `"xinputhid"` and `vid` is **not** Microsoft (`0x045E`).

Includes DualSense, DualShock 4, all Logitech wheels, Thrustmaster HOTAS, flight sticks, pedals, arcade sticks, and most of the 228-profile catalog (~204 profiles).

```
ROOT\VID_054C&PID_0CE6\NNNN          ← UMDF2 driver (mshidumdf host)
  └─ HID\VID_054C&PID_0CE6\...       ← raw HID PDO, no upper filter
```

Lightest stack. One `DIF_REMOVE` on the ROOT parent tears down the entire tree. No XUSB companion device, no Microsoft upper filter.

### 2. Non-xinputhid Xbox (~200-700 ms create, ~135 ms dispose)

Xbox-VID profiles (`vid == 0x045E`) where `driverMode` is null. XInput is delivered via a separate SWD-enumerated XUSB companion device running `HMXInput.dll`. WGI dispatch also runs through that companion, admitted by the xinputhid UpperFilter tripwire.

Includes Xbox 360 Wired (`xbox-360-wired`), Xbox 360 Type 2, Xbox 360 Wireless, Xbox 360 dance pad, Xbox 360 Arcade Stick, Xbox 360 Wheel V1/V2, Xbox 360 Guitar V1/V2, Xbox Adaptive (with caveats &mdash; this is a 6-profile group).

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
  │                                    attach — wrong device class).
  └─ XUSB interface → XInput slot + WGI Gamepad
```

Medium stack, fast on both sides post-v1.3.2. Two device trees to tear down. The XUSB companion runs its own WUDFHost instance hosting `HMXInput.dll`, which needs its own PnP release cycle.

### 3. xinputhid Xbox (~150-600 ms create, ~500 ms dispose)

Profiles with `driverMode: "xinputhid"`. These match `xinputhid.inf [GIP_Hid]` by hardware ID (`HID\VID_045E&PID_0B13&IG_00`), which binds Microsoft's `xinputhid.sys` as an upper filter on the HID child. xinputhid provides XInput delivery and 16-button HID descriptor synthesis natively: no XUSB companion needed, single Device Manager entry.

Includes Xbox Series BT (`xbox-series-xs-bt`), Xbox One S BT, Xbox One Original (BT), Xbox Elite v2 BT &mdash; the 4-profile group that uses Microsoft's GIP-over-HID protocol over Bluetooth.

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

> The 16-button synthesis is a **known trade-off**. Win11's xinputhid replaces the source descriptor's button declaration with a 15+ button Xbox One layout. This is incompatible with profiles that need the Xbox 360's 10-button fidelity through DirectInput (`btnfix.c` exists in the repo as an experimental approach but is incomplete &mdash; the trade-off stands as of v1.3.4). For Xbox 360 Wired the catalog profile uses driverMode=null + XUSB companion to keep 10 buttons through DI; for Xbox Series BT it accepts 16 buttons because the source descriptor already has 12 and the +4 are dead bits.

---

## How `CreateController` resolves a profile

1. **Index allocation.** Linear scan from 0; first free index wins. Locked.
2. **Architecture group selection.** Branch on `vid == 0x045E` and `driverMode`:
   - `(false, null)` &rarr; plain HID
   - `(true, null)` &rarr; non-xinputhid Xbox (XUSB companion)
   - `(true, "xinputhid")` &rarr; xinputhid Xbox
3. **Container ID assignment.** Per-controller GUID `{48494430-4D41-4553-5452-4F00...<idx>}` (ASCII "HIDMAESTRO" + 16-bit index). Shared by the main HID and any companion so xinput1_4 and Settings dedupe them. See [SwDevice and PnP](../reference/swdevice-and-pnp.md).
4. **Per-instance registry write.** Writes `ControllerIndex`, `Vid`, `Pid`, `ProductString`, `ManufacturerString`, `DeviceDescription`, `ReportDescriptor` (REG_BINARY), `BTHLEDEVICE` flag, etc. to `HKLM\SOFTWARE\HIDMaestro\Controller<index>` and the device's HW key. The driver reads these at `EvtDeviceAdd`.
5. **Device creation.** Plain HID via `SetupDiCreateDeviceInfoW`; SWD profiles via `SwDeviceCreate` (called through `hmswd.exe` to bypass a .NET P/Invoke incompat).
6. **PnP wait.** Polls the HID child for `DN_STARTED`. Up to 10 s on slow machines; typically <100 ms.
7. **XInput slot-claim wait** for Xbox profiles. Capped at 500 ms post-v1.3.2 to avoid 13-14 s freezes when xinputhid's allocator is in a stuck state.
8. **UpperFilter writes** for non-xinputhid Xbox profiles. INF carries it on the companion; SDK writes per-instance on the main HID device.
9. **Friendly-name application.** Best-effort; finalize via `HMContext.FinalizeNames` after all controllers are created.

The full per-archetype sequence lives in `DeviceOrchestrator.cs`'s `SetupController` (~600 lines). See [Lifecycle and Teardown](../reference/lifecycle-and-teardown.md) for the disposal counterpart.

---

## Loading the catalog

```csharp
// Embedded catalog (228 profiles)
ctx.LoadDefaultProfiles();

// Custom directory of JSON profiles
ctx.LoadProfilesFromDirectory(@"C:\my-profiles");

// Mix both — embedded first, then custom (custom IDs win on collision)
ctx.LoadDefaultProfiles();
ctx.LoadProfilesFromDirectory(@"C:\my-overrides");

// Lookup
HMProfile? p = ctx.GetProfile("xbox-360-wired");

// Enumerate
foreach (var profile in ctx.AllProfiles)
    Console.WriteLine($"{profile.Id} — {profile.Name}");
```

Profiles are loaded into the context's catalog. Duplicate IDs are skipped (first wins). Schema files (`schema.json`) are ignored.

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

The modded profile isn't registered in the catalog &mdash; it's used directly for one `CreateController` call. See [Custom Profiles](custom-profiles.md) for the full clone / build / spoof patterns.

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
  "inputReportSize": 18,
  "deviceDescription": "Controller (XBOX 360 For Windows)",
  "triggerMode": "combined"
}
```

**`descriptor`** is the HIDMaestro-emitted descriptor. **`nativeDescriptor`** is the original from a real Xbox 360 controller. They differ because the catalog version uses Vx/Vy velocity usages to carry separate trigger values without DirectInput recognizing them as axes. The native descriptor declares Z + Rz directly; HIDMaestro's emitted version uses Z (combined trigger) + Vx + Vy (separate triggers) so DirectInput sees 5 axes (matching real xusb22.sys behavior) while WGI / browsers see separate triggers via the GameInput registry mapping. See [Cross-API Coverage](../reference/cross-api-coverage.md).

**`inputReportSize`: 18** is data + 1 Report ID byte (the descriptor declares Report ID 0x01).

**`triggerMode`: "combined"** annotates the descriptor's trigger encoding for this profile. The HIDMaestro-emitted descriptor declares one Z axis carrying `LT - RT` per real xusb22 DI semantics. **All Xbox profiles** present as 5 axes with combined Z in DirectInput regardless of `triggerMode` value &mdash; on profiles where `triggerMode == "separate"` (e.g. Xbox Series BT), xinputhid's synthesis layer collapses the descriptor's separate Z + Rz back into combined Z by the time DI reads the preparsed data. WGI and browser see separate triggers through the Vx/Vy + GameInput-mapping path.

**`driverMode`** is **not present** &mdash; null = plain HID via mshidumdf. With `vid == 0x045E`, this profile lands in **architecture group 2** (non-xinputhid Xbox + XUSB companion).

**`buttonMap`** is **not present** &mdash; identity Xbox layout (`HMButton.A` &rarr; descriptor button 0, etc.).

---

## Catalog statistics

As of v1.3.4:

| Metric | Count |
|--------|-------|
| Total profiles | 228 |
| Vendor folders | 32 |
| Plain HID profiles | ~204 |
| Non-xinputhid Xbox profiles | ~6 |
| xinputhid Xbox profiles | ~4 |
| With FFB descriptors | ~30 (Logitech G-series, Thrustmaster wheels, Fanatec wheels, MOZA, SimuCUBE) |
| Bluetooth profiles | ~50 |
| Wireless-adapter profiles | ~10 |

The largest single-vendor folders are Thrustmaster (19), Logitech (24), Microsoft (22), and Sony (13).

---

## See also

- [Custom Profiles](custom-profiles.md) &mdash; clone, modify, build from scratch, spoof.
- [Profile Extractor](profile-extractor.md) &mdash; the GUI tool that reads profiles back from real devices.
- [Contributing Profiles](contributing-profiles.md) &mdash; submit a captured profile via GitHub issue.
- [Cross-API Coverage](../reference/cross-api-coverage.md) &mdash; the per-API translation a profile drives at runtime.
- [Lifecycle and Teardown](../reference/lifecycle-and-teardown.md) &mdash; per-architecture-group teardown latencies.
- [`profiles/schema.json`](https://github.com/hifihedgehog/HIDMaestro/blob/master/profiles/schema.json) &mdash; the canonical JSON Schema.
