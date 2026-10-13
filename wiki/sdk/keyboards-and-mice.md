# Keyboards and Mice

New in v1.12.0, a profile can be a keyboard or a mouse. The catalog holds 51 keyboards and 52 mice from 32 vendors. Each is the report descriptor of one interface of a real device, taken from public dumps: usbhid-dump output posted in project issues, libinput recordings and the Linux kernel's HID selftests. It answers [issue #67](https://github.com/hifihedgehog/HIDMaestro/issues/67).

Source: the profiles under [`profiles/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/profiles) whose `type` is `keyboard` or `mouse`, the packers in [`Internal/KeyboardMousePacker.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/Internal/KeyboardMousePacker.cs), the descriptor parser in [`Internal/HidReportMap.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/Internal/HidReportMap.cs), and the probes that verify them, [`test/probes/kbm_offline_check`](https://github.com/hifihedgehog/HIDMaestro/tree/master/test/probes/kbm_offline_check) and [`test/probes/kbm_live_check`](https://github.com/hifihedgehog/HIDMaestro/tree/master/test/probes/kbm_live_check).

---

## What Windows sees

A keyboard or mouse profile is created like any other plain HID profile and reaches Windows as the device its descriptor describes. Windows' keyboard and mouse class drivers open its collections and Raw Input lists each one as its kind. A Scroll Lock pressed on a virtual keyboard turns Scroll Lock on, and the mouse moves the cursor.

A profile carries one interface of the real device. Its other interfaces, including the ones vendor configuration tools talk to, are not emulated. Keyboard and mouse profiles get no GameInput mapping and no joy.cpl name.

## Driving one

```csharp
using var mouse = ctx.CreateController(ctx.GetProfile("logitech-g502-hero")!, "mouse-1");
mouse.SubmitMouse(new HMMouseState { X = 25, Y = -10, Buttons = HMMouseButtons.Left });
mouse.SubmitMouse(new HMMouseState());

using var keyboard = ctx.CreateController(ctx.GetProfile("keychron-q6")!);
keyboard.SubmitKeyboard(HMKeyModifiers.LeftShift, new[] { HMKey.A });
keyboard.SubmitKeyboard(HMKeyModifiers.None, ReadOnlySpan<HMKey>.Empty);
```

| Method | What it sends |
|---|---|
| `SubmitMouse(in HMMouseState)` | `Buttons`, relative `X` and `Y`, `Wheel` and `Pan`. A movement larger than the descriptor's field is split across as many reports as it takes. |
| `SubmitKeyboard(HMKeyModifiers, ReadOnlySpan<HMKey>)` | The modifiers and every key held down. A report without a key releases it. More keys than the report holds report ErrorRollOver, as a real keyboard does. |
| `SubmitConsumer(ReadOnlySpan<ushort>)` | Consumer-page usages such as volume and media keys, on a profile that declares a consumer collection. |

Each packs into the reports the profile's descriptor declares, with or without report IDs, so a mouse whose buttons and motion sit in separate reports gets both. A method throws `InvalidOperationException` when the descriptor declares no collection of that kind.

## Every report arrives

A gamepad reports state, so only the newest report matters. A mouse reports movement, which adds up, and a keyboard reports presses and releases, which must all arrive. For keyboards and mice the driver confirms each report Windows has taken, and the SDK sends the next only after that, at most one per millisecond, the interval of a full-speed USB device. A burst of 600 one-count moves lost nothing, and neither did four mice driven from four threads at 250 Hz each.

A wait for the confirmation gives up after 200 ms. After three misses in a row the controller stops waiting until a confirmation arrives again, so a device Windows has stopped reading does not hold up the caller. `DeliversEveryReport` says whether a controller works this way. It is false on a gamepad and on a driver older than v1.12.0.

Windows merges consecutive mouse moves into one `WM_INPUT` message, so a reader that counts messages sees fewer than were sent. The movement adds up to the same total.

## Buttons past five

Raw Input's `RAWMOUSE` carries five buttons. A mouse built with `HidDescriptorBuilder.VendorButtons` gets a second, vendor-page collection, and `SubmitMouse` sends buttons six and up there. Raw Input lists that collection as a HID device of its own.

## Absolute pointers

`HidDescriptorBuilder.Mouse(absolute: true)` builds a pointer that takes 0 to 32767. It reaches Raw Input flagged `MOUSE_MOVE_ABSOLUTE`, on Windows' 0 to 65535 scale.

## Keyboard LEDs

Windows sends a keyboard its LED state when it arrives and on every change, and resends it to the keyboards already present when another arrives. `KeyboardLedsChanged` raises each state as `HMKeyboardLeds` flags (`NumLock`, `CapsLock`, `ScrollLock`, `Compose`, `Kana`), and `KeyboardLeds` holds the latest. The arrival state comes while `CreateController` is still running, before a handler can be attached, so attach the handler and then read the property.

## Stable paths and timing

Four mice with one VID and PID are four Raw Input devices, and each identity key gets the same device path back on every life, as with every other profile. Creating a mouse took 388 to 467 ms, and Raw Input listed it by the time `CreateController` returned. `Dispose` took 95 to 202 ms.

## When the consumer goes away

If the consuming process ends with a key or button down, however it ends, the driver lets go of it: keys and buttons go up, relative motion stops, and an absolute pointer stays where it was. Without that, Windows repeats a held key until the device is removed, 32 times in 1.5 s as measured. The SDK holds one end of a named pipe for each controller and the driver keeps a read pending on it, so the driver learns of the exit when the pipe closes. `Dispose` sends the same release itself before teardown, and `ReleasesOnConsumerExit` says whether the driver watches.

The devices a dead consumer leaves are removed by the next session's cleanup, or by `RemoveAllVirtualControllers`. Windows will not disable a keyboard, and while one is up it will not disable the device above it either, so the cleanup removes a keyboard with `SetupDiRemoveDevice`, children first, the order `Dispose` uses.

## Building one in code

`HidDescriptorBuilder` has starters:

| Starter | Builds |
|---|---|
| `Mouse(buttons = 5, absolute = false, wheel = true, pan = true, reportId = 0)` | A relative 16-bit mouse, or an absolute pointer |
| `Keyboard(keys = 6, leds = true, reportId = 0)` | The boot keyboard layout |
| `KeyboardNkro(leds = true, reportId = 0)` | A keyboard with a bit for every key |
| `ConsumerControl(slots = 1, reportId = 0)` | Consumer-page usages |
| `VendorButtons(count, reportId)` | The second collection for buttons six and up |

## What is verified

Battery scenario S69 runs with no device. It checks that builder recipes from before v1.12.0 build the same bytes, the new starters and their guards, the packers against bytes worked out by hand, and every catalog keyboard and mouse parsed, packed and read back.

Battery scenario S70 runs through Raw Input:

- Four mice with one VID and PID get four paths, and the same four come back when they are created again in reverse order.
- A 600-report burst and four threads at 250 Hz lose no counts.
- An absolute mouse arrives flagged `MOUSE_MOVE_ABSOLUTE`, and buttons six and eight arrive through the vendor collection.
- Two keyboards, one without report IDs and one with Report ID 2, each hold the LED state Windows sent on arrival, and a Scroll Lock pressed on one reaches both as the new state.
- A consumer usage arrives as a HID report, and output and feature reports reach `OutputReceived` split at their first byte.
- Every catalog keyboard and mouse starts, reaches Raw Input as its kind and confirms delivery.
- A consumer killed while it holds a key, a mouse button and an absolute pointer leaves the key and button up and the pointer where it was, and the cleanup after it removes all three of its devices.
