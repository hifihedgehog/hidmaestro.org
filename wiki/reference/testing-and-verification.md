# Testing and Verification

The regression battery has 115 scenarios, S01 to S85 and S87 to S116, covering lifecycle, input and output formats, consumer APIs, USB/IP, VR, device identity, the driver catalogs, the Sony reports against the programs that read them, programs side by side, NativeAOT apps, the GameCube adapter persona, the SDK's rounding, profiles and device models as data, the report programs, the protocol engine, a second device on the Switch Pro's mechanisms, the catalog's capture fidelity, removing HIDMaestro from a computer, every profile on both backends, and touchscreens, touchpads and pens. scripts/verify.py provides additional cross-API checks on a live deployment. Report the actual result for each machine. An unavailable fixture is not a passing test.

For the wiki coverage of where these pipelines fit, see [Build and Release](build-and-release.md). For the underlying SDK mechanics they exercise, see [SDK Reference](../sdk/sdk-reference.md) and [Lifecycle and Teardown](lifecycle-and-teardown.md).

---

## `scripts/verify.py`: cross-API correctness

Tests every relevant Windows controller API to verify a deployed virtual is correctly visible to all consumers:

- **XInput** via `xinput1_4.dll` `XInputGetState`
- **DirectInput** via `winmm.joyGetDevCapsW` (and DirectInput8 underneath)
- **HIDAPI / SDL3** via the `hidapi` Python package
- **Browser Gamepad** via headless Chrome / Edge &rarr; `navigator.getGamepads()`
- **WGI / GameInput** via `winrt.windows.gaming.input.RawGameController`
- **HID enumeration order** via `hid.enumerate()` filtered by `HM-CTL-` serial

```cmd
:: Single-controller validation
HIDMaestroTest.exe emulate xbox-360-wired
:: in another terminal:
python scripts\verify.py

:: Multi-controller (4 mixed)
HIDMaestroTest.exe emulate xbox-series-xs-bt xbox-series-xs-bt xbox-360-wired dualsense
python scripts\verify.py --controllers 4
```

Exit code 0 if every API agrees; 1 if any fails. Prints per-API status:

```
[XInput]     4 slots active. LT/RT separate. Slots 0..3.        OK
[DirectInput] 4 axes-and-buttons enumerations. Identities match. OK
[HIDAPI]     6 HID interfaces, 4 with &IG_, 2 with bus_type=BT.  OK
[Browser]    4 STANDARD_GAMEPAD, separate triggers, no dupes.    OK
[WGI]        4 RawGameController. 4 Gamepad. Single-entry each.  OK
[Order]      Creation order matches across XInput/DI/HIDAPI/WGI. OK
[Order]      Browser order is alphabetical (Chromium quirk).     SKIP

PASS
```

---

### What `verify.py` checks per API

#### XInput

```python
state = XINPUT_STATE()
result = xinput.XInputGetState(slot, byref(state))
# result == 0 ⇒ slot active
# result == 1167 ⇒ slot empty
```

For each slot 0..3:

- Active count matches `--controllers` arg (capped at 4 for Xbox-family profiles).
- Slots fill **contiguously from 0**. Slot-1-skip would surface here.
- LT and RT are independent: pressing only LT moves only `bLeftTrigger`. Combined-trigger profiles would show LT-RT delta on `bRightTrigger`.

Also enumerates the XUSB device interface count via `SetupDiEnumDeviceInterfaces(GUID_DEVINTERFACE_XUSB)`, which can exceed `xinput1_4`'s 4-slot cap and shows real PnP layer presence vs. allocator gaps.

#### DirectInput

```python
caps = JOYCAPS2W()
result = winmm.joyGetDevCapsW(joyId, byref(caps), sizeof(caps))
```

Per-controller checks: axis count, button count, hat presence, VID/PID, ProductString. Catches descriptor encoding bugs (wrong axis count, wrong logical max).

#### HIDAPI

```python
import hid
for d in hid.enumerate():
    if 'HM-CTL-' in d['serial_number']:
        # this is a HIDMaestro virtual
```

Filters by serial number prefix to ignore unrelated HID devices. Per-virtual checks:

- VID / PID match expected.
- Product string match expected.
- `bus_type` is 1 (USB) or 2 (Bluetooth) per profile's `connection`. The Bluetooth hardware and compatible IDs (`BTHENUM` or `BTHLEDevice`) show here.
- Path contains `&IG_` for Xbox profiles (HIDAPI skip semantic).

#### Browser Gamepad

Spawns headless Chrome via Selenium against a small static HTML page that calls `navigator.getGamepads()` and reports JSON via WebSocket. Per-virtual checks:

- `mapping == "standard"` for Xbox-family profiles.
- `axes.length` matches expectation per architecture group.
- `buttons[6]` and `buttons[7]` (LT and RT) are distinct.
- No duplicate gamepad entries.

#### WGI / GameInput

```python
import winrt.windows.gaming.input as wgi
controllers = wgi.RawGameController.raw_game_controllers
gamepads = wgi.Gamepad.gamepads
```

Per-virtual:

- One `RawGameController` per virtual.
- One `Gamepad` per virtual (not zero, not two: the duplicate-Gamepad hang).
- `Gamepad.Vibration.LeftMotor / RightMotor` properties writable (round-trip through `OutputReceived` if the test driver subscribes).

#### Order

Creation order should match across XInput, DirectInput, HIDAPI, WGI. Browser's alphabetical-by-GUID ordering is documented as a Chromium quirk and the test reports it as SKIP rather than FAIL.

---

### Running for specific profiles

```cmd
:: Just the 5 axes / 10 button check on Xbox 360 Wired
HIDMaestroTest.exe emulate xbox-360-wired
python scripts\verify.py --filter directinput

:: Browser-only check
python scripts\verify.py --filter browser

:: Multi-controller ordering
python scripts\verify.py --controllers 6 --filter order
```

`--filter` runs only the named API check. Useful for iterating on a specific subsystem without waiting for the full pipeline.

---

## `test/regression/regression_battery.ps1`: lifecycle battery

The 115-scenario battery that drives `HIDMaestroTest.exe` through every interesting create / live-swap / remove / force-kill sequence plus the HID PID 1.0 force-feedback round-trip, the composite personas, the battery reply a pad gives XInput, the driver catalogs for both architectures, Steam's firmware updater against the 2026 Steam Controller persona, the device identity of every family across nine lives, every catalog keyboard and mouse through Raw Input, programs that embed HIDMaestro side by side, NativeAOT and single-file apps, the GameCube adapter persona through Dolphin, Slippi and SDL, and a full removal of HIDMaestro inside Windows Sandbox. It verifies no PnP devnodes are left in the `PRESENT` state after each one.

```powershell
# from an ELEVATED PowerShell, repo root or anywhere
./test/regression/regression_battery.ps1

# specific scenario only
./test/regression/regression_battery.ps1 -Filter 'S08*'

# verbose: prints every stdin command
./test/regression/regression_battery.ps1 -Verbose

# point at a non-default exe (e.g. a published build)
./test/regression/regression_battery.ps1 -Exe C:\path\to\HIDMaestroTest.exe
```

Exit code 0 if every scenario passed, 1 if any failed. Total wall time: 55 minutes on the development laptop, a Lenovo Legion Pro 7 16AFR10H, 75 minutes on the MeLE PCG02 GLE stick PC (slow-hardware target with `HIDMAESTRO_TIMEOUT_SCALE=2`), 44 minutes there with every controller on USB/IP, and 28 minutes on an ARM64 Microsoft Surface Pro. [Platform support](../start/platform-support.md#validation) lists each system's hardware.

### What each scenario catches

| Scenario | Pattern | Catches |
|----------|---------|---------|
| **S01_Single_360_BT_360** | `360 → BT → 360` | The original SwDevice teardown leaving a phantom xinputhid-bound BT child. |
| **S02_Single_360_BT_360_BT** | `+ → BT` | Secondary regression: leftover surfacing only after a 4th swap. |
| **S03_Single_LongCycle_8swaps** | 8 alternating swaps | Repeated DIF_REMOVE and hmswd-remove path under a fixed identity token. |
| **S04_Single_BT_360_BT** | BT first | Initial xinputhid bind path before any non-xinputhid create. |
| **S05_Single_Mixed_Families** | `360 → DS → Switch → BT → 360` | Cross-family swaps (XUSB companion, plain HID, xinputhid gamepad). |
| **S06_Single_SameProfileSwap** | `BT → BT` (same id) | A fixed identity tuple recreates cleanly after teardown destroys the software device. |
| **S07_Multi_CreateAll_Idle** | 4 mixed, idle, quit | Baseline multi-slot teardown via clean process exit. |
| **S08_Multi_SwapOneSlot** | 4 wired, swap slot 1 | Single-slot swap doesn't leak across siblings. |
| **S09_Multi_SwapAllSlots** | 4 wired, swap each slot | Concurrent live-swap of every slot. |
| **S10_Multi_RemoveOne** | 3 mixed, `remove 1` | `Dispose` without replacement leaves no residue. |
| **S11_Multi_MultipleXinputhid** | 3 different xinputhid + swap | xinputhid INF-match handling under multiple concurrent binds. |
| **S12_ForceKill_Recovery** | Hard-kill, then clean session | `RemoveAllVirtualControllers` purges orphans from a force-kill. |
| **S13_AcrossProcess_Recreation** | `proc1 (BT+360) → quit → proc2 (BT+360) + swaps` | The same identity token recreates across processes. Catches the kernel reuse-existing trap. |
| **S14_Single_RapidSwaps_NoSettle** | 4 swaps queued back-to-back, no inter-command sleep | Per-controllerIndex teardown gate + reentrancy in Setup/Teardown. |
| **S15_Multi_SixControllers** | 6 mixed (beyond XInput's 4) + swap slot 5 | Slot-allocator skip + ContainerID encoding for high indices. |
| **S16_Single_SameVidPid** | `xbox-360-wired ↔ xbox-360-arcade-stick` (both 045E:028E) | Registry-reuse path when only profile-level metadata differs. |
| **S17_ForceKill_MidCascade** | Hard-kill 5s into a Series BT teardown's xinputhid filter unbind | Worst-case force-kill timing; phantoms left in mid-cascade state. |
| **S18_Single_AlternatingPattern** | `A → B → A → C → A → B → A` | Registry and devnode state when revisiting prior profiles at one identity. |
| **S19_Multi_RapidMultiSlotSwap** | 4 controllers, swap each slot's profile back-to-back, no settle | PadForge's `ApplyAscendingIndexPreemption` async-dispose path. |
| **S20_Multi_HeterogeneousCascade** | 4 controllers, every family in one batch, then `quit` | `DisposeControllersInParallel` correctness with all four families. |
| **S21_Custom_CreateIdle** | Custom (BEEF:F000) create + idle + quit | Runtime-built profile loads, binds, tears down through the same path. |
| **S22_Custom_SwapCycle** | `Custom ↔ 360 → Custom ↔ BT → Custom ↔ DualSense` | Cross-family swaps to/from a non-embedded faux-VID profile. |
| **S23_Multi_CustomInMix** | 5 mixed (360 + Series BT + DualSense + Switch Pro + Custom) + swap custom | Real PadForge-shape consumer config. |
| **S24_PidFfb_RoundTrip** | DI PID FFB shared-section round-trip on a custom HOTAS | `PublishPidPool / PublishPidState` reach driver's HID feature replies. |
| **S25_PidFfb_AllocFree** | PID FFB allocate-then-free under burst + multi-controller | Two controllers' independent EBI tables; pool exhaustion. |
| **S26_PidFfb_FfbTest** | DI PID FFB end-to-end via SharpDX/DI8 (`FfbTest`) | The PID FFB invariants S24/S25 cover at the SDK boundary actually deliver to a real DI consumer. |
| **S27_Xbox360_Dpad_XInput** | xbox-360-wired d-pad through XUSB companion (`XInputGetState`) | Closes #19: `wButtons.DPAD_*` matches expected mask. |
| **S28_Hat_Resolution_Encoder** | Pure encoder unit-test across hat resolutions 8 / 16 / 360 | v1.3.4 hat-input priority chain: `HMHat / HatRaw / HatHundredths / HatDegrees` produce correct descriptor field values. |
| **S37_Layout_Audit_Check** | Layout schema against descriptor, report lengths with no device, then a live read | A profile's declared layout and its HID descriptor cannot disagree. Every catalog report descriptor's input, output and feature lengths match hid-tools' (`reference_lengths.json`), and so do the report and length the driver is given for each profile, the `InputReportId` value it reads them from, and `dataReportId`. Hand-made descriptors cover Push and Pop, long items and the other items a walker can get wrong. Live: genesis-nso arrives as report 0x3F and never 0x21, microsoft-designer-keyboard's raw frame as its keyboard report 0x01, beside dualshock-4-v2's unchanged 0x01, then logitech-wingman-formula-gp's 5-byte report. |
| **S58_Identity_Derivation** | Identity key derivation, no device | The default key reproduces the index-shaped ids, a consumer key derives deterministic collision-free ids, and persona serials derive as documented. |
| **S59_Identity_Battery** | One controller per family across nine lives | Parent id, ParentIdPrefix, ContainerId, HID children, interface paths, DirectInput GUID, SDL3 path and USB serial stay identical across every life. Also empty shells, two pads of one VID/PID overlapping, and a profile change at one key. |
| **S60_Xusb_Battery** | The XUSB battery reply on xbox-360-wired | The four bytes position by position, the LED reply's own version word, what `XInputGetBatteryInformation` hands a caller, and SDL's power-state mapping over those values. |
| **S63_Ds4_Report** | Every DualShock 4 map, then the Bluetooth persona live under stock SDL3 (issue #64) | Report `0x11` byte 1 without SDL's 0x80 flag, so SDL dropped all input once the persona armed, and motion, battery and touch read from bytes two late. Also the calibration scale, the battery and cable bits, and a near-zero trigger read as a full pull. |
| **S64_Ds3_Sixaxis** | `dualshock-3-full` offline, live, and under stock SDL3 with PCSX2's hints, then `dualshock-3` offline and live (issues #65 and #78) | The native report against SDL, Linux and RPCS3, the joystick and feature reports against DsHidMini's conversions, RPCS3's 0xF2 read and its output report, and a PS3 controller with 16 axes, 11 buttons and every pressure axis in SDL. On `dualshock-3`, the native output report, which reached only `OutputReceived` before v1.10.1, decoded on `OutputDecoded`, and since v2.4.1 its native input report 0x01, sent whole: each HMButton bit alone, each hat direction, the triggers at four values and the right stick at its corner, encoded offline and read back through `ReadFile`, against the bytes SDL's PS3 driver, hid-sony.c and DsHidMini read. |
| **S65_Switch2_Composite** | `switch2-pro-controller-composite` against a capture of a real pad, then live through Windows, PadForge's SDL3 fork with libusb, and the Steam client (issue #66) | Both descriptors, the Microsoft OS 1.0 requests, silence until the start command, the command table, the flash image, the 4 ms clock, reports `0x09` and `0x05` and the motion gate. Live: HidUsb on interface 0 and WinUSB on interface 1, motion read back within 1 percent on every axis, rumble, two personas at once, and Steam adding and reading the pad. |
| **S66_Registry_Ownership** | Real devices' joy.cpl and GameInput keys under identities virtuals use, then create, dispose, cleanup and a fresh context (foundation-sunshine #1138) | Every planted key reads back as planted. A GameInput table written the way v1.11.0 wrote it is removed. `HMOemNameOverride` claimed and released in either order leaves the original `OEMName`, and a killed consumer's writes are undone by the next consumer's first create. Since v2.4.1 a create deletes a per-user `OEMName` its profile's `replacesJoystickNames` lists and writes its `joystickName` to HKLM, while a per-user name the list does not hold and a listed name an `HMOemNameOverride` holds stay. |
| **S67_Wgi_Mapping** | What WGI reads from a DualSense, a DualShock 4 v1 and a game pad built in code, with the XUSB Xbox 360 pad as the same-window positive control (foundation-sunshine #1056) | A DualSense stays a RawGameController with no GameInput key, as a real one does. Where GameInput has written HapticFeedback = DS5 to its key for 054C:0CE6, Windows.Gaming.Input lists no DualSense, real or virtual (microsoftconnect/GameInput #61), and the two listing checks are skipped. A DualShock 4 v1 reads correctly through the mapping Windows ships for it. Only the one shape the table fits gets a table, dropped on dispose. |
| **S68_Vr_Driver_Conflict** | A foreign OpenVR driver registered under `hidmaestro`, in a path registry of the probe's own | `HMVR.FindDriverNameConflicts` lists it and never HIDMaestro's own folder. Without elevation or SteamVR, the SDK's own writes to the OpenVR path registry match, byte for byte, what the shipped vrpathreg.exe wrote for each case. Elevated, and while SteamVR is not running, a registration with a planted vrpathreg.exe in the SteamVR folder runs nothing from it, the write has the user's rights when the process holds a split token, and `UnregisterDriver` throws and keeps its gate when the registry cannot be updated. |
| **S69_Kbm_Descriptors** | Keyboard and mouse descriptors and packers with no device (issue #67) | Builder recipes from before v1.12.0 build the same bytes. The new starters and their guards, the packers against bytes worked out by hand, and every catalog keyboard and mouse parsed, packed and read back. |
| **S70_Kbm_Raw_Input** | Keyboards and mice through Raw Input (issue #67) | Four mice with one VID and PID keep four paths. A 600-report burst and four threads at 250 Hz lose no counts. Absolute and extra-button mice, keyboard LEDs and Scroll Lock, consumer usages, output split at its first byte, and every catalog keyboard and mouse live. A consumer killed with input held leaves the key and button up and the pointer where it was, and the cleanup removes all three of its devices. |
| **S71_Coexistence** | Programs that embed HIDMaestro, side by side as separate processes, with peers built on v1.12.0 and v1.11.0 | Keyless creates land on their own transport indices and each device carries only its own program's input. An identity a live program holds is refused with the holder named, and the holder's devices stay started and unchanged, with their HID handle open and input flowing. A second program's install and create leave the first program's devices, XInput slot, WGI and Raw Input entries alone, and the first program's frame gaps stay within its one-program p99 with a small allowance for run-to-run spread. A killed program's devices go with the next sweep and a live program's stay. Peers built on v1.12.0 and v1.11.0 run beside this release through each branch of the install policy, two programs deploy at once on a machine without the driver, and two USB/IP composites keep each other's imports. A thread acting as a program that is not elevated tries to take the deploy and ledger locks, the claims, events and pipes first. Further sections cover the driver's owner watch, the transport and WinUSB locks, a WinUSB binding that follows a dropped adapter, and pnputil run from System32. Section W runs sweeps beside running programs: a killed program's device whose claims another program holds is left, a sweep holding a dead group's claims while the restarted program creates the same identity, creates beside a running v1.12.0 program landing clear of its indices and an `index:N` below 64 created as asked, the exit handler beside a create in flight and a handler of the program's own, and v1.11.0 GameInput tables kept while their device or a v1.11.0 create in flight needs them. |
| **S72_Protected_Staging** | The staging tree under `%ProgramFiles%\HIDMaestro\Staging` | Every directory on the path is writable only by Administrators and SYSTEM, and `hmswd.exe` is no longer staged in `%TEMP%`. A staged tool overwritten with other bytes of the same length is restored from the embedded copy, a staging directory replaced by a link is moved aside rather than followed, and a deploy prunes the staging of versions no running program uses. |
| **S73_Usbip_Clean_Install** | usbip-win2's host controller installed, used and removed with no vendor installer and no root-hub filter, in Windows Sandbox started without a window | The first sandbox: a composite create installs the host controller from the package the SDK carries. The result is one `ROOT\USBIP_WIN2\UDE` devnode with HIDMaestro's stamp, the package in the driver store, and an install record naming the devnode, its owner token and the package's DriverVer. No usbip2_filter package or service, Apps entry, program folder, task, shortcut or KMDF debug value is left. A planted usbip-win2 uninstall entry is left as it was, and its uninstaller never runs. When two programs create their first composites at the same moment, the host controller is installed once. S45's and S65's probes then run over that install with no filter on the root hub. S45's microphone energy check is a skip there, since the sandbox's audio engine silences every stream. Eight further sandboxes, five on ARM64, each start with a different profile as the first game controller its Windows ever installs: on `Usbip` a plain HID pad, the XUSB function, the GIP function and two Bluetooth Xbox pads, and on x64 a plain HID pad, an xinputhid pad and the XUSB companion on `Umdf2`. Windows starts that first controller's HID collection before it can install it and restarts it at the install. `first_create_check` checks that Windows logged the first install, that the devnodes and HID handles the create handed back stay as they are for four seconds, that a plain pad's read keeps delivering reports, and that an XInput pad holds its slot at the return and on every read after. The last sandbox runs the usbip-win2 part of a full removal. When a driver install binds after its timeout, the next create records the package, unless the record names another DriverVer (another date or another version) or usbip-win2's Apps entry changed since. When another release's package is forced onto HIDMaestro's devnode, neither the next create nor the record update after a move records it, and a default removal keeps the devnode and the package. That package is usbip-win2 0.9.8.0, which the probe's build fetches and checks against `ForeignUsbipPackage.json`. An install cut short before its driver install leaves a driverless devnode, which a default removal takes with its record. Without a record, or with one a program on another pin wrote, the next install finishes the same devnode, and the record then carries this release's DriverVer. When the record is lost and the next install writes it again beside a user's identical package, a default removal keeps that package. R1 to R4: a preview changes nothing, a removal the record proves takes everything, and a reinstall works. An install no record proves is kept, taken when usbip-win2 is included, and refused while another program that uses usbip-win2 is installed. A host controller used since Windows started is kept until a restart, with its persona's records. A held file or folder under usbip-win2's folders, or its held link on the Public desktop, fails the removal with nothing queued for the next start, and the next removal takes it. The host part never loads HIDMaestro.Core.dll, so the probes that run beside it do not skip. Skips where Windows Sandbox is not available. The battery starts it before S01 and collects its result at its slot, since the sandbox is a machine of its own and sits idle through most of the minute its two sandboxes take. |
| **S74_NativeAot_Smoke** | `HIDMaestro.Core` in a NativeAOT app | The whole catalog loads, the driver installs, a UMDF2 controller and a USB/IP composite each carry input, which the app reads back from the HID interface against a neutral control. Each raises `OutputReceived` for an output report, and both go away on dispose. The publish fails on any IL warning. |
| **S75_SingleFile_Smoke** | The same in a trimmed, self-contained, single-file app | The same checks. |
| **S76_Json_Parity** | Source-generated JSON against v1.12.0's reflection-based reading, no device | Every profile reads into the same objects, the lenient `kind` matching holds, and the two value-type initializers survive. During development, with the fill step disabled, it failed on the 68 profiles that depend on it. The probe has no mode that disables the step. Every enum the JSON contract reaches has a converter, and every type the profile model can read has generated metadata. |
| **S77_Pnp_Notify** | PnP notifications, the removal test and the PnP lock | With no device, the removal test and the registration gate get recorded sequences and must not answer before the DEVICEINSTANCEREMOVED notification and the PHANTOM record's removal, and no locate may cancel a removal. The PnP lock keeps its bounds during the exit, and no devnode change is made outside the lock except the listed ones. While a plain HID controller is created and disposed, the SDK's own callback receives the events, the device-interface filter's counted apart from the instance filters'. Every removal of a DualShock 4, an Xbox 360 wired and an Xbox Series BT dispose ends with its devnode gone, and each devnode in the tree when its removal test started leaves on DEVICEINSTANCEREMOVED. |
| **S78_Build_Info** | What a build of the SDK carries, no device | The release build carries the driver and the USB/IP transport for x64 and ARM64 and the OpenVR driver, and its four INFs carry one DriverVer stamp. A variant built with `HMSkipArm64` and `HMSkipUsbip` embeds nothing stale, refuses what it lacks before any machine-wide step, and still runs a UMDF2 controller on x64. |
| **S79_GameCube_Descriptors** | The Wii U GameCube adapter persona's bytes | Every catalog profile compiles as a device model, and copies of the persona with one mistake each are refused before anything machine-wide, with a message naming the profile, the JSON path and the limit. The three 057E:0337 profiles carry the corrected descriptors and one Full. The persona's device, configuration, string and report descriptors are a real WUP-028's as served, as Windows enumerates them before any driver loads, and as libusb reads them through WinUSB after `BindWinUsb`. |
| **S80_GameCube_Protocol** | The adapter's protocol through WinUSB, as libusb hosts drive it | SET_PROTOCOL, silence before `0x13`, each port's input, connection and rumble apart from the others, a controller connected to an empty port at rest or holding a state, the origins, stalls and ignored commands, SET_REPORT read as one command, GET_REPORT answered with the report ID alone, `0x15` and the port reset, and the 8 ms and 1 ms report rates. A Dispose waits for a submit in progress, and idle frames leave an empty port empty. It also runs the port and protocol model in process on exact clock ticks, a reply dropped while another waits and the low-speed poll table included. |
| **S81_GameCube_WinUsb** | `BindWinUsb` | The package ranks below input.inf, a second adapter stays on input.inf, and the bound devnode carries no reinstall flag. A disposed adapter's devnode is marked once it has left, and after a killed program an adapter arriving before the next program's reclaim keeps WinUSB while one arriving after it gets input.inf. The binding's machine-wide locks are taken in their one order. |
| **S82_GameCube_Dolphin** | Dolphin's and Slippi's adapter code, compiled unmodified with the libusb each pins | All four ports read, rumble reaches each wired port alone and none reaches a WaveBird, and a port leaves and returns. It measures submit-to-read latency and the delivered report rate at 8 ms and 1 ms. |
| **S83_GameCube_Sdl** | The official SDL3 3.4.18 build and SDL 3.4.18 built with libusb | The official build lists nothing for the adapter beside a DualShock 4 it lists. The libusb build lists one joystick per connected port, refuses rumble on a WaveBird and without rumble power, and sends each port's rumble to that port. |
| **S84_Perf_Budget** | Every submit path on a live controller: thousands of calls on the DualShock 4, Xbox 360, DualShock 3 and GameCube paths, 200 per run on the keyboard, mouse, consumer and absolute-pointer paths | No allocation, on the worst run for the UMDF2 paths and the median of five runs for the USB/IP paths: `SubmitState` and `SubmitRawReport` on a DualShock 4, `SubmitState` on an Xbox 360, `SubmitKeyboard`, `SubmitMouse`, a GameCube adapter port's `SubmitState` and the controller's, and a USB/IP device's frame, output and audio transfers. The census's walk of the `Enum` keys gives what the configuration manager lists, and falls back to those listings over a key it cannot read. |
| **S85_Handler_Isolation** | Event handlers that throw, and handlers that dispose their own controller | A throwing handler ahead of a counting one on `OutputReceived`, `OutputDecoded` and `KeyboardLedsChanged`: the counting handler gets every event, the keyboard's LED state follows Scroll Lock, and a Bluetooth DualSense still switches to report 0x31. When Dispose gives up waiting for a handler that is still running, the output thread ends once the handler returns and touches nothing Dispose released. An `OutputReceived` handler that disposes its own controller does not wait for its own thread, alone, with two others at once, or through `HMContext.Dispose`. Offline, a `DisposeControllersInParallel` callback that throws for each of 256 controllers, or for a set of one, still has every controller disposed and comes out as one `AggregateException`. |
| **S87_Interop_Decl** | Interop declarations and the method names in the SDK's own text | No `DllImport` is left, `SetupDiGetClassDevsW` takes its enumerator as a pointer, and every method a message or XML doc names exists as written. Live, an Xbox 360 persona's XInput slot count reads back and the phantom sweep runs. |
| **S88_Device_Shortcut** | No device shortcut in the SDK or the drivers, no device | No declared name, file name or string carries a device or vendor word from the catalog outside the probe's allowed names, no vendor or product ID is compared, switched on or assigned in any form, no device name is searched, no profile field set by one catalog profile alone is read, and no region of the 24 device regions and the default device's five is left in a driver source. It failed by design until the last device code became profile data, and passes at 2.0.0. |
| **S89_Device_Oracle** | The device code gives the bytes it gave before the conversion | Replays nine recorded cases, the submit and decode paths, the packers, the Switch 2 Pro responder, the USB/IP feature answers, the UMDF2 driver and companion compiled natively, and the physical descriptors of the reference clones, and passes a difference only when the probe's list of changes names it. |
| **S90_Arith_Roundtrip** | Every raw value comes back, no device | Every raw value of every catalog conversion, normalized three ways, returns through the SDK's own code. A NaN writes the rest, an unwritten stick rests at its center, and the rounding matches `Math.Round`. |
| **S91_Vendor_Blob_Golden** | Vendor-blob reports against golden bytes, no device | Every Sony, Valve and Nintendo vendor-blob report encodes and decodes to its golden SHA-256, and the codec refuses the removed `ds3-battery` type, a missing `max` or `invert`, and parameters an output field ignores. |
| **S92_Profile_Model** | Profiles and device models as data, no device | The catalog and a user's directory load strictly: every defect a file can carry is refused at its JSON path and listed in `HMContext.ProfileLoadIssues`, and a create and a build meet `HMProfileException` for a bad profile. The catalog files of every earlier v1.x tag load except for the removed spellings. Answer tables, value sources and patches, model resolution by name and by identity (no catalog profile takes a group from an identity default), the SDK's half of the version contract, the HID device attributes a profile gives (`hidPid`, `hidVersionNumber`, `hidProductString`, v2.4.1) reaching the driver's values, their copy rule and the forms that drop them, the 2.0.0 deploy policy, and `FromProfile`'s whole copy. |
| **S93_Contract_Live** | The version contract on the live driver, elevated | A fresh-token controller's driver reads its index from the identity entry before its first start, on the ROOT path and the SWD xinputhid path. A device without report IDs answers its feature message after HID class's leading 0. Each catalog profile with a model, read back by `HMDeviceExtractor`, names the model its identity gives it, with the answers the device gave. |
| **S94_Program_Equivalence** | Every report program three ways, no device | Each catalog program, decoder and layout runs through its generated code, the interpreter and a naive evaluator written from the design note, on random states and recorded inputs, plus a seeded corpus of 1,000 random programs, the negative corpus, planted defects and every validation rule with its JSON path. Under the JIT and NativeAOT, where every catalog program must bind its generated code. |
| **S95_Protocol_Engine** | The protocol engine and the device clock, no device | Conditions, matches, register stores, memory, bitmap and prefix replies, bulk replies in read-sized chunks, the overflow rules, GET_REPORT of the layout that would go out, counters, no allocation per command, reply or report, the Triton's IMU register, the clock's grid under each missed-tick rule, and the idle repeat's period, condition and timestamps. |
| **S96_Capture_Fidelity** | Catalog data and driver text against their sources, no device | The INF comments are ASCII, the Xbox 360 profiles carry a real pad's manufacturer string, and `xbox-360-flight-stick` and `ps-move` carry their captured descriptors, with the Move's controls, battery and motion where psmoveapi and RPCS3 read them. |
| **S97_Switch_Family** | A second device on the Switch Pro's mechanisms, no device | `joycon-l-proof`, a Joy-Con (L) built from `switch-pro`'s protocol, state block and report programs, loads, answers SDL's Joy-Con open with nxbt's device info, and its 0x3F stick hat follows dekuNukem's grid in all eight directions and reads centered inside its dead zone. |
| **S101_Uninstall** | Removing HIDMaestro: `HIDMaestroUninstall.exe` and `HMUninstall` (v2.0.1) | On every machine, the tool's `--preview --json` and `HMUninstall.Preview` change nothing against a snapshot of devices, packages, the certificate, registry keys and files. Inside Windows Sandbox, with a program running that holds four controllers (a composite among them), an OEM name override and the OpenVR registration, the tool exits 2, names it and changes nothing. Once that program is killed, the removal leaves no device record, package, certificate, private key, registry key or folder, puts the OEM targets back, takes the OpenVR registration, restarts no USB root hub, and does not follow planted junctions. A program that starts during the removal waits for it to end, then installs again and keeps its controller. A file held open under `%ProgramFiles%\HIDMaestro` waits for the next start, and one under `%ProgramData%\HIDMaestro` stays, reported failed. Without Windows Sandbox and with `HIDMAESTRO_UNINSTALL_FIXTURE=1`, it removes HIDMaestro from that machine, checks it reads clean and installs the driver again. |
| **S102_Loop_Containment** | The SDK's loops on a pass that fails (v2.1.0) | The device clock, the protocol host's tick, the USB/IP input and audio pumps, the audio event thread, the server's accept loop, a connection that ends on the server's own exception, the VR haptic reader and the output reader each outlive a failing pass, wait between passes, log the failures at powers of two and the end of the episode, and cost under 5% of a spinning thread's cycles. A protocol clock period under 0.125 ms is refused, and the audio pump with no waitable timer sleeps instead of spinning. Each case runs offline, in a child process. |
| **S103_Sinput_Persona** | The SInput personas, against SDL's SInput driver (v2.2.0) | Over raw HID, on a controller with a nonzero index, `sinput` answers SDL's features command (output report 0x03, command 0x02) with the issue's 64-byte input report 0x02, SINPUT-LIB-HID's layout with OpenPuck's one finger per touchpad, and `joypad-steam-input` with joypad-os's bytes 0 to 19 and a serial of its own, the last serial byte the controller's index. Data-only frames arrive as report 0x01. Type 2 haptics decode to `leftMotor` and `rightMotor`, type 1 on `sinput` to the louder amplitude's high byte per side, and RGB on `joypad-steam-input` to `lightbarRed`, `lightbarGreen` and `lightbarBlue`. The features command, a player LED write, RGB on `sinput` and type 1 on `joypad-steam-input` decode nothing. With 20 raw frames 0.1 ms apart after each of 100 features commands, every command gets its reply. The unfiltered SDL3 build of PadForge's fork, its revision stamped, then opens two `sinput` pads: their name, standard type, a serial each, accelerometer and gyroscope, two touchpads, rumble without player LED or RGB capabilities, South and the left stick from a submitted frame, rumble decoded on its own pad, a refused color, and no player LED or color on the wire. Then two `joypad-steam-input` pads: their name, a serial each, no sensors and no touchpads, rumble, player LED and RGB capabilities, South and the left stick, rumble and a color decoded on their own pad, and on the wire the features command, each pad's player number, haptics and the color. |
| **S104_Driver_Signing** | Whether Windows installs HIDMaestro's driver package, and which backend a create resolves to (v2.3.0) | The decision over its inputs: the code integrity options the test machines read, the four states the ARM64 Surface was measured in on 2026-11-18, and each condition taken away in turn. The machine rule for `Auto` over the build's payloads and the verdict, a create's resolution over the profile's data and the request, the process override, and the neutral `HMDriverSigningException` of an explicit `Umdf2` request on a refusing machine of the probe's own. On this machine, the verdict agrees with the probe's own read of `SystemCodeIntegrityInformation`, `MachineBackend` with the rule, and `IsDriverInstalled` with the backend it answers for. Windows' own answer (`WinVerifyTrust`) for HIDMaestro's installed catalog and for a catalog of Windows itself, without and with `WTD_CODE_INTEGRITY_DRIVER_MODE`, and for a catalog signed as HIDMaestro signs, with a certificate of the probe's own that it removes. On a machine whose Windows refuses the package and that holds none, an explicit `Umdf2` request throws and writes no certificate, package or payload record, and a program that names no backend installs the USB/IP host controller and creates a controller on it. That part skips where Windows installs the driver and runs on the ARM64 Surface. The certificate part and the last part need elevation, and the last creates a device, under the battery's bench lock. |
| **S105_Xusb_Persona** | The Xbox 360 profiles on USB/IP, under Windows' own XUSB driver (v2.3.0) | The ten profiles whose `xinput.via` is `xusbCompanion` present XUSB functions on the USB/IP backend, model data in `profiles/models/xusb-companion.json`. Offline: each function's descriptors against the retail dumps (a wired pad's four interfaces with the profile's subtype, and for `xbox-360-wireless` the 045E:0719 receiver's eight), the subtype against the UMDF2 companion's answer, the input report's XInput state against the companion's for 20,000 states, the output rules, the compatible ID XUSB10 (XUSB20 for a receiver) for an identity `xusb22.inf` does not list by hardware ID, and the identities `xinputhid.inf` and `dc1-controller.inf` bind refused at load, a receiver's `xinput.information` among them. On the wire, a USB/IP client as the host reads both functions' descriptors and strings, the receiver's `08 80`, link control packet and battery status and its answers to connection requests, the input reports from interrupt IN, and writes rumble and LED requests, which reach the output ring as the companion's 5-byte XInput packets. Live, for `xbox-360-wired` and `xbox-360-wireless` on USB/IP: the devnode starts under the USB/IP root hub with service `xusb22` from `xusb22.inf`, the create returns with the XInput slot taken, every button, the d-pad, Guide, both triggers and both sticks read back through XInputGetState, XInputSetState arrives as the companion's packet, a raw frame of another length is refused, a second pad takes a slot of its own, and `dualsense-composite` beside them reads back over HID. Exit 2 when another program that embeds HIDMaestro is running. |
| **S106_Gip_Persona** | The wired Xbox One S pad as a USB device, under Windows' own GIP driver (v2.3.0) | `xbox-one-s-full` runs on the USB/IP backend with no HID interface and speaks the Gaming Input Protocol. Offline: its descriptor set is the device Microsoft's GIP specification describes, its metadata is Santroller's with the persona's own firmware version, and a mis-authored copy is refused at its mistake. On the wire, a USB/IP client as the host sees Hello every 500 ms until answered, the metadata in fragments paced by the host's acknowledgements, Start, Status and the first input report, Guide and Share, and the Direct Motor command on the output ring in the UMDF2 form's shape. Live: Windows' inbox `dc1-controller` and `xboxgip` bind the device, `xboxgip` holds the metadata it served, a submitted state reads back through XInputGetState, Share reads in the XUSB gamepad state, XInputSetState arrives as the Direct Motor command, GameInput's trigger levels are recorded, Windows.Gaming.Input lists the pad once, and `dualsense-composite` beside it reads back over HID. `family`: each xinputhid profile created as its GIP form reads through XInput, WGI and the HID child's haptics output report. Exit 2 when another program that embeds HIDMaestro is running. |
| **S107_Backend_Parity** | One profile on both backends (v2.3.0) | `parity`: every deployable profile both backends present is created on each backend the machine runs, both on x64 and the USB/IP backend where Windows refuses HIDMaestro's driver, and starts with no problem code. Where both run, the HID class reads the same attributes, button and value caps of every report type and product string on each, and an output report written to the device reaches the program as the same packet. A profile that presents another profile's form on USB/IP is compared with that form on UMDF2, and a form only USB/IP presents, the Joy-Cons' Charging Grip, must show a collection for each HID interface it declares, with its own product string. On USB/IP every HID collection opens the moment the create returns, a form's as a derived device's, each collection of a descriptor that declares several, and one under an interface node where a driver package binds the device as a composite. A USB/IP device that a driver package on the machine binds in place of HID class, as it binds the real device, is named and left out of the USB/IP checks. The output report goes to the first collection that is not a keyboard's, a keypad's or a mouse's, which Windows holds. `long`: input reports over 64 bytes read whole in one `ReadFile` on USB/IP and output reports arrive whole, at the derived speed and pinned to full speed, for a raw-frame device of the probe's own, a device that builds a 362-byte report (joycon-l's Bluetooth profile without its USB form) and a catalog keyboard. `ports`: the create past the host controller's last USB 2.0 port is refused by name and the controllers on the other ports keep their HID interface. `start`: each derived device's HID interface opens the moment its create returns. `oem`: the identity's joy.cpl name while a USB/IP controller lives, and the value before it once it goes. `identity`: one key's HID interface path is the same after a dispose and after a process restart. `twoprograms`: two programs on one host controller keep their own bus locations, and one's dispose leaves the other's device. Exit 2 when another program that embeds HIDMaestro is running. `killedattach`: a program is killed inside the host controller's attach request, the host controller still holds its connection to that program a second later, and the next program's create completes. |
| **S108_Bluetooth_Identity** | A Bluetooth profile is a Bluetooth device on every backend (v2.3.0) | `offline`: what each of the catalog's 26 Bluetooth profiles presents on each backend, its USB device, the marker of its transport and the bus hidapi's rule reads from the node. Then on each backend the machine runs, UMDF2 and USB/IP on x64 and USB/IP on ARM64. `live`: every Bluetooth profile but the Xbox pads is created and its node read as hidapi reads it, with its version, product string and reports, and `dualsense` and `dualsense-composite` as the USB controls. `sdl`: SDL 3.4.18's official release DLL for the machine's architecture, staged beside the tree as `SDL3-release-3.4.18` on x64 and `SDL3-release-3.4.18-arm64` on ARM64, opens each Sony, Nintendo, Stadia and Luna pad and each one's USB profile, reads the bus and the connection, and drives input, rumble and LEDs. |
| **S109_Xusb_Family** | The ten Xbox 360 profiles on each backend (v2.3.0) | Each profile is created on each backend the machine runs and takes a slot. Where both run, XInputGetCapabilities, one input's XInput state, XInputSetState's packet and the product string are the same on both, and UMDF2's HID device has the layout of the profile's descriptor. On USB/IP, xusb22's HID device has that layout too unless the profile's notes state the difference. |
| **S110_Xusb_Battery_Receiver** | The battery of the pad behind the receiver (v2.3.0) | `xusb_battery_check --profile xbox-360-wireless`: the battery the profile states, which is xusb22's answer for the receiver's battery status on USB/IP and the companion's on UMDF2. |
| **S111_Xusb_Wgi_Family** | One WGI device for each Xbox 360 profile (v2.3.0) | `xusb_wgi_single_check --profiles family`: three fresh creates of each of the ten, one RawGameController each, one Gamepad for a pad of the gamepad subtype and none for the others. |
| **S112_Standard_Axes** | A stick's axes when the layout declares no triggers (v2.3.0) | `offline`: every catalog profile with a stick keeps each stick axis's value through `StandardAxes`, and `switch-pro-usb`, `dualshock-3`, `hori-horipad-switch`, `logitech-f310` and `logitech-f710` keep their right stick. `live auto`: the right stick read back in the HID report of `dualshock-3`, `hori-horipad-switch`, `logitech-f310` and `logitech-f710`. `sdl auto`: the right stick through SDL 3.4.18's release DLL for `switch-pro-usb`, `hori-horipad-switch` and `dualshock-3`, with SDL's PS3 hint on. |
| **S113_Bluetooth_Xbox_Hid** | A Bluetooth Xbox pad on USB/IP is the HID device it is over Bluetooth (v2.3.0) | `offline`: each of the five profiles' `bluetoothHid` form, its version, and where each button, stick, trigger and hat direction lands in the report against SDL's and xpadneo's parsers. `live`: each on USB/IP with xinputhid on the device's node as Windows installs it for a real pad: the device tree, XInput control by control, what XInput and Windows.Gaming.Input report it as, the rumble packet, a second create and a plain profile on the same record. `hold` and `guide`: the Xbox button of `xbox-one-s-bt`, which sends it in a report of its own, held through a moved stick and pressed fifty times. |
| **S114_Create_Stands** | What a create hands back stays as it is (v2.3.0) | On each backend the machine runs, UMDF2 and USB/IP on x64 and USB/IP on ARM64, one profile of each way a controller reaches Windows is created while another thread reads XInput as a running game does. From the create's return and for four seconds the devnodes under the device are the same ones and started, the handles opened on its HID collections at the return answer, a plain pad's read keeps delivering reports, and an XInput pad holds its slot on every read. On UMDF2 a last part forces the software companion's race: an xinputhid pad's ParentIdPrefix is written only once its HID child has arrived under a prefix of Windows' own and XInput holds it, and the create must still hand back a device whose child carries the identity's prefix and stays as it is. S73's part F runs the same check with each profile as its Windows' first game controller. |
| **S115_Identity_Fidelity** | Every profile reads to the programs that name controllers as its pins say, on each backend (v2.3.0) | `offline`: `identity-pins.txt` covers every deployable profile, a line that holds for one backend only, or from one Windows build on, follows a comment that says why, no reader is pinned to another device's IDs without a reason, the USB/IP pins read what the real devices on record read (`real-devices.txt`), and, since v2.4.1, each profile whose IDs and connection an inbox INF of the machine names (`xinputhid.inf`, `dc1-controller.inf`, `xusb22.inf`) carries that INF's name as its `deviceDescription`. `live`, on UMDF2 and USB/IP on x64 and on USB/IP on ARM64: each profile is created and read through the HID class with the bus hidapi's rule gives, XInput, Windows.Gaming.Input, SDL 3.4.18 with its default hints, and the id Chrome builds, computed with Chromium's own rules and tables. A profile whose device a driver package from outside Windows and HIDMaestro drives on the machine is named and not compared. |
| **S116_Digitizer** | Touchscreens, touchpads and pens reach Windows as the devices they are (v2.4.0) | `offline`: the touch and pen packer over real touchscreen, touchpad and pen descriptors, read back by the probe's own walk of each descriptor, `HidDescriptorBuilder`'s three starters with their feature answers, and the release slots, which take each report whole or not at all. `live`, on each backend the machine runs: Windows writes Device Mode 2 to a touchscreen and Input Mode 3 to a precision touchpad, contacts and pen states read back through HidP, a 116-byte touch report goes whole, and a 1024-byte report reads back byte for byte while a 1025-byte one is refused. `kill`: on UMDF2 the contacts a killed consumer left down come up with their identifiers, and on USB/IP the device leaves with the consumer. A console session in use gets contacts in range only, with no tip and no click. |

Each scenario covers a specific historical bug or invariant. The full list is the codified history of what has broken in this area before. The rows above are the ones worth reading standalone. The scenario array in [`test/regression/regression_battery.ps1`](https://github.com/hifihedgehog/HIDMaestro/blob/master/test/regression/regression_battery.ps1) is the authoritative full list.

---

### What "PASS" means

Per scenario:

1. **Snapshot every `HIDMAESTRO*` / `VID_045E&PID_028E*` PnP devnode** that `CM_Locate_DevNodeW(NORMAL)` reports as `PRESENT` BEFORE the scenario runs. This is the baseline.
2. **Run the scenario**, then sleep 12 s for kernel cascade to settle.
3. **Snapshot the same set AFTER.**
4. **PASS** iff `(after \ before) == empty`: no new `PRESENT` entries leaked across the scenario.

`PHANTOM` entries (registry residue with no live devnode) are **ignored**. They don't occupy XInput slots, don't show in active-controller lists, and are cosmetic-only registry leftovers from the historic SwDevice behavior. Only `PRESENT` is what consumers actually see.

---

### Diagnosing a FAIL

The script prints leftover instance IDs when a scenario fails:

```
[FAIL] S08_Multi_SwapOneSlot 47832ms
       Leftover: SWD\HIDMAESTRO_VID_045E_PID_0B13&IG_00\HM_0001
```

For deeper inspection, every test process runs with `HIDMAESTRO_DIAG=1` in its environment, so `%TEMP%\HIDMaestro\teardown_diag.log` records every `TeardownController` call (entry/exit/timing) and every `SwdDeviceFactory.Remove` outcome (`hr` plus `present`-after-remove).

On a FAIL, grep that log for the leftover instance ID to see exactly what the SDK did.

---

### Harness mechanics

The harness is **event-driven, not time-based.** The test app emits `[ACK]` on stdout after each stdin command finishes processing, and the harness blocks on that marker. No fixed-sleep settle, no scaling.

This was a hard-won design. Win11 26200's PowerShell 5.1 has several pitfalls that interact:

1. **`Add-Type` C# delegate for `OutputDataReceived`**: never `Register-ObjectEvent` or PS-scriptblock cast. The latter produces silent zero-byte stdout reads on Win11.
2. **Byte-by-byte stdin pump** in the test app: `Console.In.ReadLine()` has a 15-second buffer on Win11 that breaks rapid back-to-back commands.
3. **UTF-8 BOM strip on stdin**: PowerShell's `WriteLine` emits one; the test app strips it.
4. **Named `EventWaitHandle` for quit signal**: cleaner than relying on stdin EOF detection.
5. **`Process.Kill` self-exit** + `HIDMAESTRO_QUIET=1`: ProcessExit handler skips the redundant `RemoveAllVirtualControllers` (per-scenario cleanup already disposed everything).

These five fixes interact; missing any one makes the harness hang on Win11. Preserved as the canonical recipe.

---

### Slow-hardware fixture

The full battery also runs on a MeLE PCG02 GLE fanless stick PC: Intel Celeron J4125 (4 cores, 4 threads), 8 GB LPDDR4-2133, Intel UHD Graphics 600, Windows 10 IoT Enterprise LTSC, version 21H2 (build 19044). It runs at `HIDMAESTRO_TIMEOUT_SCALE=2` over SSH, with no desktop session. At the v2.4.0 gate 110 scenarios passed there and 5 skipped, in 88 minutes on the UMDF2 driver: S54 and S62 need a Steam client, S70 a desktop session's Raw Input devices, and S73 and S101's sandbox half the `wsb` command for Windows Sandbox, which this machine lacks. S101's removal ran on the machine itself instead. Inside passing scenarios, the checks that need a desktop session or a Steam client skip too: the Raw Input checks in S37 and S71, S50's legacy reader app, section Y of S71 and the Steam client checks in S65. Before the UMDF2 run the uninstaller removes HIDMaestro from that machine, so the run's first create installs the driver from nothing.

The slow-hardware result is the reason the harness is **pure ACK-driven** instead of fixed-sleep timed: a fixed sleep that's "enough" on a fast machine isn't enough on a slow one. ACK-driven waits scale with the machine.

The stick PC runs the same `regression_battery.ps1` script. Build the SDK on the development laptop, copy artifacts to the stick PC over SSH (`scp`), run the battery there.

---

## `test/probes/`: one-off investigation tools

The `test/probes/` directory holds investigation tools used during HIDMaestro development. These are not part of the regression battery and are not built by `build_all.cmd`. They are situational and often unfinished:

- `descriptor_swap_check`
- `dinput_enum`
- `dispose_orphan_check`
- `focus_test`
- `gi_enumall`
- `hat_resolution_check`
- `hid_output_report_probe`
- `input_source_counter`
- `native_wgi_vibration`
- `pid_ffb_alloc_free`
- `pid_ffb_roundtrip`
- `pid_setusages_probe`
- `wgi_custom_factory`
- `wgi_dll_string_scan.ps1`
- `wgi_read_probe`
- `wgi_rgc_ffb_probe`
- `wgi_vs_xinput_ab`
- `wudfhost_cpu_sampler`
- `xbox_dpad_xinput_check`
- `xinput_byte_probe`
- `xinput_latency_meter`

Each was built to characterize a specific behavior during an investigation. Some are ProcMon traces, some are C# WinRT probes, some are PowerShell scripts. They're untracked / WIP and **never deleted automatically**: preserved as forensic tools.

---

## CI

GitHub-hosted runners are Windows Server, not Win11 client. The regression battery's PnP behaviors differ on Server (different default services, different xinputhid behavior) so the battery isn't portable to GitHub-hosted CI.

Self-hosted runners on Win11 client could run it, but that's not currently set up. The regression battery stays manual via `pre-tag-validate.cmd`. **No CI is the right answer here**, given Server vs. client divergence.

---

## What gets validated before a release

The pre-tag validation pipeline (`scripts\pre-tag-validate.cmd`) is the gate:

1. Build: `build_all.cmd` with `HMSkipArm64`, `HMSkipUsbip` and `HM_STAMP_TIME` cleared, then `scripts\check_build_layouts.ps1` (v2.0.0), then the test app, the profile extractor and the probe set. `check_build_layouts.ps1` builds the native payloads from the pinned NuGet WDK packages, under the variables an EWDK prompt sets (x64 only) and with roots that hold no kit, runs SDK-project builds of each layout, and checks the `HM_STAMP_TIME` stamping.
2. The Switch Pro protocol check, the Switch descriptor idle check and the Switch Pro SDL3 acceptance.
3. `regression_battery.ps1`: full 115-scenario battery. **115/115 PASS required.**
4. The script prints the result.

The script does not run `verify.py`, `HIDMaestroTest cleanup` or a profile extractor smoke test.

Total: ~30-40 minutes on Ryzen-class. If any step fails, don't tag.

---

## See also

- [Build and Release](build-and-release.md): how validation fits into the tag-and-release flow.
- [Lifecycle and Teardown](lifecycle-and-teardown.md): the create / dispose paths the battery exercises.
- [Cross-API Coverage](cross-api-coverage.md): the per-API behavior `verify.py` checks.
- [Force Feedback](../sdk/force-feedback.md): what S24-S26 validate.
- [Multi-Controller](multi-controller.md): what S07, S15, S20, S23 validate.
- [`test/regression/README.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/test/regression/README.md): the in-repo battery doc.


## ARM64 and USB/IP validation

The v2.4.0 battery passed all 115 scenarios on the Legion Pro 7 laptop. On the desktop PC and on the PCG02 GLE stick PC, 110 passed and 5 skipped on the UMDF2 driver, and on the ARM64 Surface Pro 111 passed and 4 skipped, with the checks that need a Steam client, a desktop session or Windows Sandbox left out. S101 removed HIDMaestro from those three machines themselves. See [platform support](../start/platform-support.md#validation) for the gate result, the ARM64 driver catalog, and the usbip-win2 0.9.8.1 transport.
