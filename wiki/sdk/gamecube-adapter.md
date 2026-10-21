# Wii U GameCube Adapter

`gamecube-adapter`, new in v2.0.0, is Nintendo's Wii U GameCube adapter, WUP-028 (057E:0337), the four-port adapter Melee players use. It runs on the USB/IP transport, so Dolphin, Slippi and SDL open it through libusb as they open a real one. The adapter is a profile and nothing else. Its four ports, its command protocol and its WinUSB binding are the profile's JSON, run by mechanisms any profile can use, and nothing in the SDK names the adapter.

Source: [`profiles/nintendo/gamecube-adapter.json`](https://github.com/hifihedgehog/HIDMaestro/blob/master/profiles/nintendo/gamecube-adapter.json), the design note's [adapter section](https://github.com/hifihedgehog/HIDMaestro/blob/master/docs/design/coexistence.md#the-wii-u-gamecube-adapter-persona) with every source and measurement, and the probes that verify it, [`test/probes/gc_*`](https://github.com/hifihedgehog/HIDMaestro/tree/master/test/probes).

---

## Which profile to pick

| Profile | What it is | Who reads it |
|---|---|---|
| `gamecube-adapter` | The adapter's USB device on the USB/IP transport: one HID interface, four ports in report `0x21` once a host writes `0x13` | Dolphin, Slippi and SDL built with libusb, after `BindWinUsb` |
| `gamecube-adapter-hid` | The adapter's 214-byte report descriptor on HIDMaestro's UMDF2 driver | Nothing. Windows' HID parser rejects the descriptor and the device fails with Code 10, as a real adapter does on Windows' HID driver. Seen in a development experiment. No battery scenario creates this profile |

`joypad-gc-adapter` is joypad-os's emulation of the adapter, with the different 70-byte descriptor that firmware serves. It is not Nintendo's device.

As of v2.0.0 a data frame on either UMDF2 profile fills input report 0x21, 38 bytes on `gamecube-adapter-hid` and 37 on `joypad-gc-adapter`. Through v1.12.0 the driver sent both as report 0x11, an output report's ID, at 1 byte. See [The report a data frame fills](../profiles/profile-system.md#the-report-a-data-frame-fills-v200).

## Driving it

```csharp
using var adapter = ctx.CreateController(ctx.GetProfile("gamecube-adapter")!);
adapter.BindWinUsb();

adapter.Ports[0].SubmitState(new HMGamepadState
{
    Buttons = HMButton.A | HMButton.LeftTriggerClick,
    Axes = new Dictionary<HMAxis, float>
    {
        [HMAxis.X] = 0.5f, [HMAxis.Y] = 0.0f,     // main stick pushed up
        [HMAxis.Rx] = 0.5f, [HMAxis.Ry] = 0.5f,   // C-stick centered
        [HMAxis.Z] = 1.0f, [HMAxis.Rz] = 0.0f,    // L bottomed out, R released
    },
});
adapter.Ports[2].Connect("wireless");             // a WaveBird on port 3, at rest
adapter.Ports[1].Connect("wired", new HMGamepadState { Buttons = HMButton.A });   // port 2, plugged in holding A
adapter.Ports[3].Disconnect();                    // nothing on port 4
```

Each port has its own connection, its own input and its own rumble. A submit to one port leaves the others as they were, and a port keeps its number when its controller leaves and returns. `HMController.SubmitState` goes to port 1.

A controller connected to an empty port reports itself at rest, with both sticks centered and the triggers and buttons released, until the program's first submit. Hosts take a controller's origin from its first report, so a port that reported zeros there would read a resting stick as pushed into a corner. `Connect(connection, state)` plugs a controller in already holding a state: the connection and the input go out in one report, as a controller plugged in with a button held reports it. That form refuses the empty connection, which holds no controller. `Disconnect()` unplugs, and so does the one-argument `Connect` given the empty connection's name. Connecting a port that already holds a controller with `Connect(connection)`, to change its connection, keeps its input as last submitted. A disconnected port's data bytes are zero.

`HMButton.A`, `B`, `X` and `Y` are the controller's A, B, X and Y, `Start` is Start, and `RightBumper` is Z. L and R report their analog travel on the trigger axes and their clicks as `LeftTriggerClick` and `RightTriggerClick`, which the program sets once a trigger bottoms out. The main stick is the left stick, the C-stick the right stick, and the D-pad comes from `Hat`. `SubmitRaw` takes a port's eight data bytes exactly as the adapter sends them.

A port holds one of `Ports.Connections`: `empty`, `wired` (the default), `wireless` for a WaveBird that is talking to its receiver (status 0x22), or `wirelessNotCommunicating` for a WaveBird that is not (status 0x20). Dolphin, SDL and ToadKing's driver read 0x20 as a connected WaveBird, and Nintendont reads it as an empty port. `Ports.Flags["rumblePower"]` is the adapter's second USB cable, which powers the controllers' motors. It starts on.

## Rumble

Output report `0x11` carries one motor command per port, the port's output field `rumble`: 0 stop, 1 run, 2 stop hard. Each port raises its own `OutputChanged`, and `GetOutput("rumble")` reads the last command. `OutputDecoded` carries them as `port1.rumble` to `port4.rumble`.

The hosts decide when to send it. SDL refuses rumble on a WaveBird and on a port without rumble power, and sends 2 under its rumble-brake hint. Dolphin sends none to a WaveBird. The SDK reports the command and leaves the motor to the program.

## Dolphin, Slippi and SDL

Dolphin, Slippi and SDL open the adapter through libusb, which needs WinUSB, libusbK or libusb0 on the device. Windows binds its HID driver to a WUP-028 instead, and the device fails with Code 10. `BindWinUsb()` binds WinUSB to the virtual adapter's devnode and installs it on no other device, so the persona needs no Zadig. A real adapter that arrives while the virtual one is bound gets its own instance and the driver Windows gives it.

The binding's package matches only a vendor-scoped compatible ID, behind fifteen IDs no device carries, so it ranks below input.inf for every real device. Before it binds, the call reads the devnode's driver list and refuses if no other driver outranks the package. It records the binding, then installs on the one devnode with `DiInstallDevice`. When a dropped connection brings the adapter back on another devnode, the binding moves to that devnode.

A restore never changes the driver of a devnode that is present, so the binding outlasts the controller for as long as a device sits on that devnode. Once the devnode is gone, it is marked to install Windows' HID driver at its next arrival by the first of these: a HIDMaestro program disposing a controller, its cleanup (`RemoveAllVirtualControllers`), its reclaim of the controllers of a program that has ended, a binding that moves to the devnode a dropped adapter came back on, or the follow-up that watches the devnode for five minutes after its holder lets go. A program reclaims when it installs the driver or creates its first controller.

This is a trade, and it can reach a real adapter. Every WUP-028 carries the same serial, so a real one can take the instance while the virtual one is gone, its connection down or its controller disposed. It then opens on WinUSB, as after Zadig, until it is unplugged. After a kill it can open on WinUSB again at its next plug-in, until a teardown, cleanup, reclaim, re-bind or follow-up finds the devnode gone and marks it. On Windows' HID driver a WUP-028 fails with Code 10, and libusb hosts need WinUSB, so this is the state many owners pick with Zadig on purpose.

| A real adapter arrives | It gets |
|---|---|
| while the virtual adapter is bound | its own port-named instance on input.inf, as without HIDMaestro |
| after the virtual adapter was disposed | the instance on input.inf, marked once the virtual adapter's devnode left |
| after the virtual adapter's program was killed, once a HIDMaestro program has reclaimed its hold | input.inf |
| after the virtual adapter's program was killed, before any reclaim | the instance's WinUSB, as after Zadig, for as long as it is present, and again at its next plug-in if no teardown, cleanup, reclaim or follow-up has run since it was unplugged |
| while the virtual adapter's connection is down, in the 30 s before usbip-win2 imports it again | the instance's WinUSB, which it keeps while it is present |
| on the instance the virtual adapter left when it came back on another devnode | WinUSB while it is present. The instance is marked once it is gone, and its next arrival gets input.inf |
| on an instance Zadig bound before | Zadig's binding, which `BindWinUsb` never touches |

Dolphin's and Slippi's own adapter code, compiled unmodified, reads all four ports, and so does SDL 3.4.18 built with libusb. The official SDL3 build for Windows has no libusb, and lists no adapter, real or virtual, with or without Zadig. SDL lists one gamepad per connected port, with player index 0 to 3 for ports 1 to 4.

## Timing

The adapter's endpoints declare 8 ms, so a host reads it 125 times a second, and the adapter reads its controllers every 1.19971 ms. A report carries what the adapter's latest read found, as a real adapter's does. A submit therefore reaches the wire at the first host poll after the adapter's next controller read.

Melee players overclock the adapter by making Windows poll it every millisecond. The adapter then delivers about 833 reports a second, because a poll that finds no new controller read gets nothing, and about 1000 with controllers in exactly ports 1 and 2. USB/IP has no host schedule to overclock, so the persona models the host poll. `DeviceProtocol.HostPollInterval` is 8 ms by default, and setting it to 1 ms serves the adapter as an overclocked host reads it. The descriptors stay as they are.

```csharp
adapter.DeviceProtocol!.HostPollInterval = TimeSpan.FromMilliseconds(1);
```

Measured during development at commit d740d2c, on the development laptop, a 16-core Lenovo Legion Pro 7 on Windows 11, not on the release build: 1200 submits, forty in each of 30 runs, each at a random offset from the poll grid, submit to read at p50 and p95, and reports a second counted at the device, p50 over the 30 runs. The battery checks bounds, not these values: each read within the poll period plus the adapter's controller read plus 2 ms, and the rates within ranges around 125, 833 and 1000.

| Host | 8 ms poll | 1 ms poll | Reports a second at 1 ms, four ports | Exactly ports 1 and 2 |
|---|---|---|---|---|
| Dolphin | 4.77 ms, 8.84 ms | 1.55 ms, 2.31 ms | 832.0 | 997.5 |
| Slippi | 4.83 ms, 8.93 ms | 1.53 ms, 2.22 ms | 832.4 | 997.5 |
| SDL | 5.06 ms, 8.36 ms | 1.51 ms, 2.33 ms | 832.4 | 998.1 |

At 8 ms the device sent 125.0 reports a second to each host. An overclocked real adapter sends about 833 a second with four ports and about 1000 with exactly ports 1 and 2.

## How it works

The descriptors match the 57 public dumps of 057E:0337 field for field, except bMaxPacketSize0, which the dumps split between 8 and 64 and the persona reports as 8, and seven units' strings. They are USB 2.00, full speed, the 214-byte report descriptor that nine of the dumps print, interrupt IN `0x81` of 37 bytes and interrupt OUT `0x02` of 5 bytes. The dumps mask the serial. `15/07/2014` is the serial every source that shows one reports. Windows names a second adapter present at the same time after its port, for the virtual adapter as for a real one.

Like the adapter, the persona sends no reports until a host writes `0x13`. Replies to `0x12` and `0x14` go out before it. From then on each host poll gets report `0x21`: the report ID and nine bytes per port, a status byte, two button bytes, the sticks and the analog L and R. `0x11` sets each port's motor, `0x12` reads each port's origin, its stick and trigger values when its controller connected, `0x14` stops the reports, and `0x15` stops the adapter until the host resets its port. A command whose reply finds another reply still waiting changes the adapter's state, and its reply is dropped. A SET_REPORT(Output) is one command, its whole data stage less a leading byte that matches the report ID in wValue, so the report a HID stack sends, `11 01 00 00 00` with ID 0x11, reads as command 0x01 and is ignored. GET_REPORT answers the requested report ID alone and stalls report ID 0 or a one-byte request. Those three follow loopj's adapter firmware under tinyusb, since no capture of a real adapter shows them. SET_PROTOCOL succeeds.

All of it is data. `extendedReport.ports` gives the four port blocks, their status byte, connections, flag, origin snapshot and fields. `extendedOutputReport.ports` gives the motor commands. The top-level `protocol` gives the states the commands set, when the input endpoint answers, the adapter's 1.19971 ms controller read and its faster read for ports 1 and 2, the command rules and their replies, how many replies can wait, how a SET_REPORT is read, the halt after `0x15`, and the answers to SET_PROTOCOL, GET_STATUS and GET_REPORT. `usbConfiguration.winUsb` gives the interface GUID the binding registers. The SDK checks all of it when the file loads and compiles it again at create, so a profile that declares it wrongly is refused before the create takes anything machine-wide. See [Profile System](../profiles/profile-system.md#devices-with-ports-and-protocols-v200).

## Known issues

- usbip-win2 gives Windows the adapter's own full speed, and Windows' USB hub driver treats every device on that host controller as high speed. So usbip-win2 rewrites the interrupt endpoints' bInterval to 7, the same 8 ms period in microframes, and a host that reads the configuration descriptor through Windows sees bInterval 7 where a real adapter reports 8.
- The persona never sees a host arm remote wakeup, so a host that sends SET_FEATURE(DEVICE_REMOTE_WAKEUP) and then reads GET_STATUS sees the bit clear. No source read for this release shows which layer above usbip-win2 completes that request.
- A program killed while its adapter is bound leaves that instance on WinUSB for as long as a device is present on it. The instance is marked only once it is gone, as the table above shows.
- The uninstall-grade cleanup removes no devnode. A WinUSB package that a gone devnode still uses stays in the driver store, ranked below the driver Windows gives the device. A package it keeps is noted by INF name in `HKLM\SOFTWARE\HIDMaestroPackagesLeft`, value `WinUsb` (`REG_MULTI_SZ`), and the first sweep of each later program that finds the note removes the noted packages no devnode, present or gone, still uses, and keeps the rest noted.
- What a real adapter does after `0x15`, `0x16` and `0x17` comes from one survey of a real unit, and no host in the references sends them. The persona stops answering after `0x15` until a port reset, and resumes after a stall on the next `0x13`.

## What is verified

Battery scenarios S79 to S83:

- S79 compiles every catalog profile's device model and compares the persona's bytes with the dumps three ways: as served, as Windows enumerates them before any driver loads, and as libusb reads them through WinUSB.
- S80 runs the protocol through WinUSB: SET_PROTOCOL, GET_STATUS, silence before `0x13`, each port's input, connection and rumble while the others keep their bytes, a controller connected to an empty port at rest or holding a state, `0x12`, `0x14`, stalls, `0x15`, SET_REPORT read as one command, GET_REPORT answered with the report ID alone, and the 8 ms and 1 ms rates. It resets the port from inside the process, since WinUSB has no device reset to send. On live controllers it also checks a Dispose that waits for a submit in progress and idle frames that leave an empty port empty, and in process a reply dropped while another waits and the low-speed poll table.
- S81 covers the binding: its rank below input.inf, one devnode bound beside a second adapter, the mark set once a disposed adapter's devnode has left, a killed owner's instance with an adapter arriving before and after the reclaim, and the order of the machine-wide locks a binding takes. S71 covers a binding that follows a dropped adapter beside another program's adapter.
- S82 compiles Dolphin's and Slippi's adapter code unmodified, each with the libusb its tree pins, and reads all four ports, origins, rumble, a WaveBird and a port leaving and returning.
- S83 runs the official SDL3 3.4.18 build, which lists nothing for the adapter while it lists a DualShock 4 created in the same run, and SDL 3.4.18 built with libusb, which reads every port's input, player index, connection and rumble.

Not run: a real WUP-028 beside the persona.
