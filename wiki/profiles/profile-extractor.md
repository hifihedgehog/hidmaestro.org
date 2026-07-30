# Profile Extractor

`HIDMaestroProfileExtractor.exe` is a standalone WPF tool that produces a HIDMaestro profile JSON from any HID device currently plugged into Windows. It ships in every release ZIP under `HIDMaestroProfileExtractor/`. No admin required, no live input capture, no gameplay involvement &mdash; the tool reads only the cached HID descriptor Windows has already parsed.

The same `HMDeviceExtractor` API the GUI calls is also available to consumers that want a "scan for connected devices" flow inside their own UI (PadForge does this), and via the `HIDMaestroTest extract-profile` CLI command for scripting.

If you want to **submit** an extracted profile to the catalog, see [Contributing Profiles](contributing-profiles.md) &mdash; this page covers the tool itself. For the SDK API behind the tool, see [SDK Reference#hmdeviceextractor](../sdk/sdk-reference.md#hmdeviceextractor).

---

## Getting the tool

Download the latest release ZIP from [GitHub Releases](https://github.com/hifihedgehog/HIDMaestro/releases/latest). Extract anywhere. The extractor is at `HIDMaestroProfileExtractor/HIDMaestroProfileExtractor.exe`.

The extractor is bundled in **every** HIDMaestro release ZIP since v1.1.14. If a release ZIP doesn't contain it, treat that as a release packaging bug.

The tool is self-contained (.NET 10 single-file publish): one EXE, no separate DLLs to drop alongside it. ~80 MB. Includes `HIDMaestro.Core.dll` embedded as a resource; the only API the tool calls is `HMDeviceExtractor`.

---

## Using the tool

1. **Plug the device in.** USB, BT, or any other path Windows recognizes as HID. The tool only reads what Windows has already enumerated; if the device doesn't show up in `joy.cpl`, the tool can't see it either.
2. **Run `HIDMaestroProfileExtractor.exe`.** Non-admin. The window opens with a populated dropdown of every HID-class device currently visible.
3. **Pick the device.** The dropdown label is `VID_XXXX:PID_YYYY (UsageLabel) ProductString [ManufacturerString]`. The tool defaults the selection to the first HID gamepad / joystick (top-level usage 0x05 or 0x04) it finds.
4. **Click Extract.** The Profile JSON, a parsed-layout summary, and the descriptor in hex appear in three tabs.
5. **Save or copy.** Save the JSON to disk, or copy it to clipboard.

The output is the exact JSON format the shipped catalog uses. Save under `profiles/<vendor-slug>/<model-slug>.json` and `LoadProfilesFromDirectory` will pick it up.

---

## The three preview tabs

After extraction, the tool shows three views of the same data:

### Profile JSON

The save-and-ship JSON. Schema matches `profiles/schema.json` exactly:

```json
{
  "id": "logitech-dual-action",
  "name": "Logitech Dual Action",
  "vendor": "Logitech",
  "vid": "0x046D",
  "pid": "0xC216",
  "productString": "Logitech Dual Action",
  "manufacturerString": "Logitech",
  "deviceDescription": "Logitech Dual Action",
  "type": "joystick",
  "connection": "usb",
  "descriptor": "05010904a101a10009010102...",
  "inputReportSize": null,
  "notes": "Extracted by HMDeviceExtractor on 2026-05-01 14:32:18 UTC. Descriptor reconstructed from Windows preparsed data (HIDAPI algorithm); logically equivalent to the physical device's HID report descriptor but not guaranteed byte-identical."
}
```

`inputReportSize` is deliberately left null on extract &mdash; `HidP_GetCaps`'s `ReportByteLength` includes a Report ID byte for some no-Report-ID devices on certain Windows builds, producing an off-by-one vs. what the descriptor actually writes. Leaving it null lets the SDK derive the correct value from the reconstructed descriptor at `CreateController` time.

`notes` is timestamped and includes a provenance disclaimer. A maintainer reviewing a contribution will want to know how the descriptor was obtained.

### Layout summary

A human-readable view computed from `HMProfile`'s public API:

```
Profile: Logitech Dual Action
  Id:                 logitech-dual-action
  Vendor:             Logitech
  VID:PID:            0x046D:0xC216
  Product String:     Logitech Dual Action
  Manufacturer:       Logitech
  Type:               joystick
  Connection:         usb
  Declared inputSize: 0 byte(s)

Descriptor summary (via HMProfile public API):
  Buttons:    12
  Axes:       4
  Hat:        yes
  Stick bits: 8
  Trigger bits: 0
  Deployable: True
```

Use this to sanity-check the extraction before saving. If the button count / axis count / hat presence don't match what the device actually has, the descriptor reconstruction may have hit an edge case (rare, but worth flagging in a contribution).

### Descriptor hex

The raw descriptor bytes as a 16-byte-per-row hex dump. Useful for diffing against a known-good descriptor or for hand-inspecting unusual fields.

---

## What "extraction" actually does

The tool calls `HMDeviceExtractor.Extract(device)`. Internally:

1. **Open the device path** with `CreateFileW(GENERIC_NONE, FILE_SHARE_READ | WRITE, ...)`.
2. **Query attributes** via `HidD_GetAttributes` &rarr; VID, PID, version.
3. **Query strings** via `HidD_GetProductString`, `HidD_GetManufacturerString`, `HidD_GetSerialNumberString`.
4. **Query preparsed data** via `HidD_GetPreparsedData` &rarr; opaque blob with Microsoft's compressed representation of the descriptor.
5. **Reconstruct the descriptor** via the libusb/hidapi C# port (Chromium WebHID team's reverse engineering of the preparsed-data layout).
6. **Build the profile** with inferred `type`, `connection`, slug-from-product-string ID, timestamped notes.
7. **Return** as `HMProfile`.

Step 5 is the interesting one. Windows doesn't expose the original device descriptor bytes through any user-mode API &mdash; only the preparsed blob. The [HIDAPI algorithm](https://github.com/libusb/hidapi/blob/master/windows/hidapi_descriptor_reconstruct.c) (originally contributed by the Chromium WebHID team) walks the blob's `LinkCollection`, `ButtonCaps`, `ValueCaps`, and Usage tables and emits a HID descriptor byte stream that, when re-parsed by `HidP_GetCaps`, produces the same preparsed blob (within the bounds of legal HID descriptor variations).

The output is **logically equivalent** to the device's real descriptor: same report IDs, field layouts, logical ranges, usage pages, sizes. It's not byte-for-byte identical &mdash; the original descriptor might have used a 2-byte Logical Maximum where the reconstruction emits a 4-byte form, or the order of unrelated items might differ. For HIDMaestro's purpose (creating a virtual that behaves the same as the physical), logical equivalence is the correct fidelity bar; filter drivers can mutate the descriptor before it reaches user mode anyway.

The reconstruction code is ~1000 lines of `HidDescriptorReconstructor.cs` &mdash; the longest single source file in the SDK after `DeviceOrchestrator.cs` and `DeviceManager.cs`.

---

## Devices the tool can't extract

Some devices return preparsed data that the HIDAPI algorithm can't reconstruct. The tool reports:

```
Extract failed: Descriptor reconstruction returned 0 bytes. The device's preparsed
data may be non-standard; a byte-level capture (Wireshark + USBPcap on Windows, or
hidraw on Linux) would be needed for this device.
```

This typically happens with:

- **Vendor-private descriptors** that use undocumented usage pages or non-standard report layouts. Some early Logitech wheels and Nacon devices fall here.
- **Compound devices** where multiple top-level collections share quirky vendor-specific items.
- **Composite USB devices** where the HID interface isn't the primary &mdash; the cached preparsed data may be stale or incomplete.

For these, capture the actual descriptor bytes from the wire:

- **Windows**: USBPcap + Wireshark with the HID URB-CONTROL filter.
- **Linux**: `cat /sys/class/hid/<id>/report_descriptor | xxd -p -c 256`.

Then drop the bytes into the `descriptor` field of a hand-authored profile JSON. See [Custom Profiles](custom-profiles.md) for the manual-spoof pattern.

---

## CLI alternative

`HIDMaestroTest.exe extract-profile` does the same thing as the GUI:

```cmd
:: List all extractable HID devices
HIDMaestroTest.exe list-hid

:: Extract by VID:PID and write to a file
HIDMaestroTest.exe extract-profile --vid 046D --pid C216 --out logitech-dual-action.json

:: Extract by full device path (use list-hid output)
HIDMaestroTest.exe extract-profile --path "\\?\HID#VID_046D&PID_C216#..." --out my-profile.json
```

The CLI is non-elevated &mdash; same as the GUI. Useful for scripted contribution workflows.

---

## When to use the GUI vs the CLI vs the API

| Scenario | Recommended path |
|----------|-----------------|
| End user wants to contribute a profile from a controller they own | **GUI** &mdash; `HIDMaestroProfileExtractor.exe` |
| You're scripting batch extraction across many devices | **CLI** &mdash; `HIDMaestroTest extract-profile` |
| Your consumer has its own UI and wants "scan for devices" inline | **API** &mdash; `HMDeviceExtractor.ListDevices()` + `HMDeviceExtractor.Extract(dev)` |
| You want raw byte fidelity (descriptor reconstruction isn't enough) | Capture from the wire (USBPcap / hidraw), hand-author the JSON |

PadForge uses the API path: its Devices page shows every connected HID device and offers an inline "Extract profile" button that calls `HMDeviceExtractor.Extract` and displays the JSON in a modal. The user can then save it or post it directly to the GitHub contribution issue.

---

## Source

- GUI: [`tools/HIDMaestroProfileExtractor/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/tools/HIDMaestroProfileExtractor) (~200 lines of WPF code-behind plus a single XAML window).
- API: [`sdk/HIDMaestro.Core/HMDeviceExtractor.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/HMDeviceExtractor.cs).
- Algorithm: [`sdk/HIDMaestro.Core/Internal/HidDescriptorReconstructor.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/Internal/HidDescriptorReconstructor.cs).

---

## See also

- [Contributing Profiles](contributing-profiles.md) &mdash; the user-facing flow for submitting an extracted profile.
- [Custom Profiles](custom-profiles.md) &mdash; deploy an extracted profile via `HMContext.CreateController`.
- [Profile System](profile-system.md) &mdash; the JSON schema the extractor emits.
- [SDK Reference](../sdk/sdk-reference.md) &mdash; the `HMDeviceExtractor` API in context.
