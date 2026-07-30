# Contributing Profiles

This is the **user-facing** page for submitting a controller profile to the catalog. The catalog ships with HIDMaestro and gets pulled into every consumer (PadForge, anyone else integrating the SDK), so contributing your device's profile means every HIDMaestro user can emulate it without owning one themselves.

You don't need to know how the descriptor is reconstructed, what UMDF2 is, or what an XUSB companion does. You just need a controller you own, a few minutes, and a GitHub account.

---

## Quick steps

1. **Plug the controller in.** USB, Bluetooth, or any other path Windows recognizes.
2. **Run [HIDMaestroProfileExtractor.exe](https://github.com/hifihedgehog/HIDMaestro/releases/latest)**. It's bundled in every HIDMaestro release ZIP under `HIDMaestroProfileExtractor/`. Non-admin.
3. **Pick your device** from the dropdown. Hit **Extract**. The Profile JSON appears in the right pane.
4. **Open the [profile contribution issue template](https://github.com/hifihedgehog/HIDMaestro/issues/new?template=profile-contribution.yml)**.
5. **Paste the JSON** into the Profile JSON field. Fill in the device name, VID:PID (the dropdown showed it), connection mode, Windows build.
6. **Submit.**

A maintainer will review, run the profile against the verification battery, possibly tweak the slug or add it to a vendor folder, and merge. The next HIDMaestro release ships your profile.

---

## What goes in the issue

The [profile contribution template](https://github.com/hifihedgehog/HIDMaestro/issues/new?template=profile-contribution.yml) walks you through it, but here's a tour:

### Device

The plain-language name. Examples:

- `Fanatec CSL DD Pro`
- `8BitDo SN30 Pro (USB mode)`
- `Logitech G29 (PS4 dial)`
- `Thrustmaster T16000M FCS`

Match what the manufacturer calls the product. If the device has multiple modes (Switch / DirectInput / XInput), state which mode the capture was in.

### VID:PID

The extractor's dropdown shows it as `VID_XXXX:PID_YYYY`. Copy that.

### Connection / mode

| Option | When to pick |
|--------|-------------|
| **USB** | Wired through a USB cable (or USB-A receiver for wireless devices that present as USB). |
| **Bluetooth** | Native Bluetooth pairing. Some controllers behave differently on BT vs USB &mdash; submit one profile per mode if so. |
| **BLE** | Bluetooth Low Energy. Newer wheels and some HOTAS sticks use this. |
| **Wireless adapter** | Vendor-specific receivers (Xbox Wireless Adapter for Windows, Logitech Lightspeed). |
| **Other** | Anything else &mdash; mention what in the Notes field. |

### Windows build

Run `winver` or check Settings &rarr; System &rarr; About. Looks like `10.0.26200.8246`. Mostly for context if the maintainer hits a "this descriptor only works on certain builds" issue, which has happened.

### Profile JSON

Paste the full JSON from the extractor's **Profile JSON** tab. Or attach the `.json` file you saved.

Don't hand-edit the JSON before submitting. The extractor's output is the format the catalog expects; manual edits break the maintainer's review flow because they have to re-derive what's been changed and why.

### Notes (optional)

Anything unusual about the device:

- Multiple HID interfaces (you captured one specific collection)
- Mode switches (which mode you captured)
- Firmware version
- Haptic / rumble behavior (e.g. "vibrates only when sent specific output report ID 0x05")
- Vendor calibration utilities you used before extraction

The example in the template:

> *"Device has two HID collections (Joystick + Gamepad). Captured the Gamepad one because that's what Chrome surfaces. DInput mode, firmware 1.04."*

That's the shape that helps a maintainer review faster.

### Checklist

Three boxes the template requires:

1. **I physically own this device.** &mdash; profiles are extracted from real hardware. Synthesized / guessed descriptors don't go in the catalog.
2. **The JSON was produced by `HIDMaestroProfileExtractor` without manual edits.** &mdash; ensures the profile matches what real users will see when running their own extraction.
3. **I'm okay with redistribution under the HIDMaestro license** (MIT). &mdash; the catalog ships with the SDK and reaches every downstream consumer.

---

## What the maintainer reviews

A profile contribution gets:

| Check | What | Pass condition |
|-------|------|----------------|
| **Schema validity** | Run against `profiles/schema.json` | All required fields present, types correct |
| **VID/PID uniqueness** | Search the existing catalog | Either it's a new VID:PID or there's a clear reason for a duplicate (different mode, regional variant) |
| **Descriptor sanity** | Eye-check the parsed layout in the extractor's **Layout** tab | Button count / axis count / hat presence look right for the device |
| **Slug naming** | Maintainer adjusts to match catalog conventions | `<vendor>-<model>` or `<vendor>-<model>-<mode>` |
| **Vendor folder** | Maintainer files it into the right `profiles/<vendor>/` | New vendor folders are fine; if your vendor doesn't exist yet, the maintainer creates it |
| **Cross-API behavior** | If the maintainer can replicate your device, they run `HIDMaestroTest emulate <id>` and `python scripts/verify.py` | All five APIs see the device with sane state |

Most contributions go straight in. Edge cases (descriptors the reconstruction algorithm produced something weird for, devices with multiple modes that need separate profiles, devices whose VID:PID Windows pre-populates with a clone label that needs `OEM Name` override hints) get a comment thread.

---

## Connection-mode profiles

Many controllers behave differently on USB vs Bluetooth. Different VID, different PID, different descriptor, different button layout. **Submit one profile per mode** if your device supports multiple.

Examples in the catalog:

- `dualshock-4-v1.json` (USB) and `dualshock-4-v1-full.json` (BT, full extended report)
- `dualsense.json` (USB) and `dualsense-bt.json` (BT) and `dualsense-bt-full.json` (BT extended)
- `xbox-360-wired.json` and `xbox-360-wireless.json` (different PIDs, different connection)
- `g29.json` (USB Logitech G driver mode) and `g29-ps4.json` (USB PS4 mode &mdash; different PID)

If you're not sure which mode produces which JSON, run the extractor in each mode and submit both.

---

## What if the descriptor reconstruction fails

Some devices return preparsed data the HIDAPI algorithm can't reconstruct. The extractor reports:

> *"Extract failed: Descriptor reconstruction returned 0 bytes. The device's preparsed data may be non-standard..."*

For these:

1. **Capture from the wire.** USBPcap + Wireshark on Windows, or `cat /sys/class/hid/<id>/report_descriptor` on Linux.
2. **Open an issue** linking the binary descriptor capture, the device's VID:PID, and the failure path. Don't paste binary data in the JSON field; attach the file.
3. The maintainer (or another contributor) hand-authors the descriptor and lands the profile.

This is rare. The HIDAPI algorithm covers ~98% of HID devices well; only vendor-private-page or unusual composite layouts trip it.

---

## Tips for high-quality contributions

- **Run the extractor in the device's "default" mode.** If your DualSense has a "performance mode" toggle, capture standard mode first &mdash; that's what most users will encounter.
- **Pick the right top-level collection.** Devices with multiple collections (Joystick + Gamepad on the same VID:PID) appear multiple times in the dropdown. Pick the one whose `(UsageLabel)` matches what you want games to see &mdash; (Gamepad) for gamepad-shaped controllers, (Joystick) for sticks/wheels.
- **Test the round-trip.** After extracting, save the JSON to `C:\my-profiles\<id>.json`, then `HIDMaestroTest.exe emulate --profile-dir C:\my-profiles <id>` and check `joy.cpl` shows your device with the right name. If it doesn't, the extraction may have grabbed the wrong collection &mdash; try a different dropdown entry.
- **Capture both wired and wireless** if your device supports both. Two contributions, two issues.
- **Include firmware version** in Notes if you know it. Some controllers' descriptors changed across firmware revisions.

---

## What happens after merge

The maintainer:

1. Adds your profile to `profiles/<vendor>/<slug>.json`.
2. Commits with a message like `add Logitech G29 PS4-mode profile (#142)`.
3. Includes it in the next release. Your profile ships in the embedded catalog inside `HIDMaestro.Core.dll`.
4. Every HIDMaestro consumer (PadForge etc.) picks it up automatically when they reference the new SDK version.

The contributor is credited in the commit message and (if you opt in) in the changelog.

---

## License

Profile JSONs are MIT-licensed (the same license as the rest of HIDMaestro). When you check the box on the contribution template, you're agreeing to that license. The descriptor bytes you contribute are reproductions of HID descriptor data; HID descriptors aren't typically copyrightable as they're functional data, but the MIT license covers the JSON wrapping and any notes you write.

The maintainer doesn't ask for a CLA. The license box is the contract.

---

## See also

- [Profile Extractor](profile-extractor.md) &mdash; the tool that produces the JSON you're contributing.
- [Profile System](profile-system.md) &mdash; the schema the JSON conforms to.
- [Profile contribution issue template](https://github.com/hifihedgehog/HIDMaestro/issues/new?template=profile-contribution.yml) &mdash; the form to fill out.
- [Latest release](https://github.com/hifihedgehog/HIDMaestro/releases/latest) &mdash; download the extractor.
