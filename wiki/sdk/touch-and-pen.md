# Touchscreens, Touchpads and Pens

New in v2.4.0, a profile can be a touchscreen, a precision touchpad or a pen. Windows reads each one as it reads the hardware. It writes Device Mode 2 to a touchscreen, and Input Mode 3 to a touchpad once the touchpad's capabilities and certification reports pass, the step that makes it a precision touchpad.

Source: the types in [`HMDigitizer.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/HMDigitizer.cs), the packer in [`Internal/DigitizerPacker.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/Internal/DigitizerPacker.cs), the three starters in [`HidDescriptorBuilder.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/HidDescriptorBuilder.cs), and the probe that verifies them, [`test/probes/digitizer_check`](https://github.com/hifihedgehog/HIDMaestro/tree/master/test/probes/digitizer_check).

---

## Building one

`HidDescriptorBuilder` has a starter for each kind, and `HMProfileBuilder.FromDescriptorBuilder` puts the answers their feature reports need into the profile: the most contacts, a touchpad's capabilities and certification, and the configuration reports Windows writes.

```csharp
var screen = new HMProfileBuilder()
    .Id("example-touchscreen").Name("Example Touchscreen").Vendor("Example")
    .Vid(0x1209).Pid(0x0001).ProductString("Example Touchscreen").ManufacturerString("Example")
    .Type("touchscreen").Connection("usb")
    .FromDescriptorBuilder(new HidDescriptorBuilder().Touchscreen(contacts: 10))
    .Build();
using var touch = ctx.CreateController(screen);
HMTouchLayout t = screen.Touch!;
touch.SubmitTouch(new[] { new HMTouchContact { Id = 0, X = t.X.Maximum / 2, Y = t.Y.Maximum / 2 } });
touch.SubmitTouch(ReadOnlySpan<HMTouchContact>.Empty);   // lifts the contact where it was

var penProfile = new HMProfileBuilder()
    .Id("example-pen").Name("Example Pen").Vendor("Example")
    .Vid(0x1209).Pid(0x0002).ProductString("Example Pen").ManufacturerString("Example")
    .Type("pen").Connection("usb")
    .FromDescriptorBuilder(new HidDescriptorBuilder().Pen())
    .Build();
using var pen = ctx.CreateController(penProfile);
HMPenLayout p = penProfile.Pen!;
pen.SubmitPen(new HMPenState { InRange = true, X = p.X.Maximum / 2, Y = p.Y.Maximum / 2 });
pen.SubmitPen(new HMPenState { Tip = true, X = p.X.Maximum / 2, Y = p.Y.Maximum / 2, Pressure = 128 });
pen.SubmitPen(new HMPenState());   // out of range
```

| Starter | What it builds |
|---|---|
| `Touchscreen(contacts, reportId)` | A touchscreen of 1 to 20 contacts in one report, each with Tip Switch, In Range, Confidence, an 8-bit Contact Identifier, and X, Y, Width and Height from 0 to 32767, then Scan Time and Contact Count. Feature reports answer the Contact Count Maximum and hold the Device Mode Windows writes. Ten contacts make a 104-byte report. |
| `Touchpad(contacts, widthMm, heightMm, reportId)` | A precision touchpad of 1 to 5 contacts in the layout [mac-precision-touchpad](https://github.com/imbushuo/mac-precision-touchpad) gives Windows for an Apple trackpad, with X and Y from 0 to 4095 over the size in millimeters, Button 1 as the click, and Microsoft's default certification blob. |
| `Pen(reportId)` | Microsoft's sample pen: Tip Switch, Barrel Switch, Invert, Eraser and In Range, X from 0 to 21240 and Y from 0 to 15980, Tip Pressure from 0 to 255, and X and Y Tilt from -127 to 127. |

A profile whose own descriptor has a touchscreen, touchpad or pen collection works the same way, from a capture of a device you own or a descriptor you write. The packer finds the collections by their top-level usage on the Digitizer page: Touch Screen for a touchscreen, Touch Pad for a touchpad, and Pen or Digitizer for a pen. A touch collection counts only when each finger carries what Windows requires of a contact: Tip Switch, Contact Identifier, X and Y, with Contact Count in the report.

`HMProfile.Touch` and `HMProfile.Pen` describe what the descriptor carries:

| Member | Meaning |
|---|---|
| `HMTouchLayout.IsTouchpad` | A touchpad rather than a touchscreen |
| `ContactsPerReport`, `MaxContacts` | The contacts one report carries, and the most one submit can carry |
| `MaxContactId` | The largest Contact Identifier the descriptor can hold |
| `X`, `Y`, `Width`, `Height`, `Pressure`, `Azimuth` | Each field's logical range, null for a field the finger lacks |
| `Buttons` | A touchpad's buttons, Button 1 first |
| `HasInRange` | Whether a contact, or the pen, can hover |
| `HMPenLayout.X`, `Y`, `Pressure`, `TiltX`, `TiltY`, `Twist`, `Buttons` | The pen's ranges and the buttons and modes its report carries |

## Driving one

| Member | What it does |
|---|---|
| `SubmitTouch(ReadOnlySpan<HMTouchContact>, HMMouseButtons)` | Reports every contact down or in range now, by identifier, at positions in the descriptor's own logical range, and a touchpad's buttons. A contact the last submit had and this one does not is lifted where it was. An empty span lifts them all. |
| `SubmitPen(in HMPenState)` | Reports the pen: in range or not, the tip, its buttons and modes, position, pressure, tilt and twist. A pen out of range reports every switch off at its last position. |
| `TouchDeviceMode` | The Device Mode or Input Mode Windows last wrote, or null until it writes one. |

An `HMTouchContact` carries `Id`, `X`, `Y`, `Hover` (in range without touching), `Palm` (Confidence off, for a contact that is not a finger), `Width`, `Height`, `Pressure` and `Azimuth`. An `HMPenState` carries `InRange`, `Tip`, `Buttons` (`Barrel`, `Eraser`, `Invert`, `SecondaryBarrel`), `X`, `Y`, `Pressure`, `TiltX`, `TiltY` and `Twist`. A tip down is in range.

`SubmitTouch` throws `InvalidOperationException` on a profile with no touchscreen or touchpad collection, and `ArgumentException` for more contacts than `MaxContacts`, one identifier twice, or an identifier past `MaxContactId`, before anything is sent. `SubmitPen` throws `InvalidOperationException` on a profile with no pen collection.

## How Windows reads it

- More contacts than one report carries go out in Windows' hybrid form: as many reports as they take, the first with the whole Contact Count and the rest with 0, all with one Scan Time.
- A contact hovers only on a descriptor whose fingers declare In Range. On one without it, such as the Elan screen of the Dell XPS 13 9360, a hovering contact reads as lifted.
- Windows configures a touchscreen and a touchpad through their configuration collection, which Windows' own MTConfig driver holds, so Windows' write arrives as the device starts and a program's own write there never reaches the device. `TouchDeviceMode` keeps the value from the first write.
- On the Surface Pro, Windows listed a virtual pen and touchscreen as pointer devices, a pen in range moved the cursor to its place within 16 ms of each submit, and one tap on bare desktop moved the cursor to the tap's point.

## Every report arrives, and nothing is left down

Touch and pen reports are delivered as keyboard and mouse reports are: the driver confirms each one Windows takes, and the SDK sends the next only after that, at most one per millisecond. A submit returns once the previous report has been delivered.

If the program ends with contacts down, however it ends, the UMDF2 driver lifts each one, in as many reports as they take, and lets go of a held touchpad button. `Dispose` sends the same lifts first. On USB/IP the device leaves with the program.

## Reports longer than 80 bytes

A touch report can be long: the Elan screen sends 116 bytes and the ten-contact starter 104. From v2.4.0 an input report of up to 1024 bytes goes whole on both drivers, through a second shared section, and a feature answer can be up to 1024 bytes, where it could be 64. A precision touchpad answers a 257-byte certification report. A UMDF2 driver older than 2.4.0 carries 80 bytes, so on one the SDK refuses a longer report with `NotSupportedException` before any byte goes. [Shared Memory Protocol](../reference/shared-memory-protocol.md) has the section's layout.

## Verification

Battery scenario S116 packs real touchscreens', touchpads' and pens' descriptors offline, then creates each kind on both backends, reads its reports back through Windows' HID parser, checks the Device Mode and Input Mode Windows writes, and kills a consumer with contacts down. On a machine whose console session is in use it sends contacts in range only, with no tip and no click.
