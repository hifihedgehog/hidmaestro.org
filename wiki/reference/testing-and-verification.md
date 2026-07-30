# Testing and Verification

Two test pipelines: `scripts/verify.py` for cross-API correctness on a live deployment, and `test/regression/swap_regression.ps1` for the 28-scenario lifecycle battery. Both gate the release pipeline; a tag without 28/28 PASS doesn't ship.

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
- `bus_type` is 1 (USB) or 2 (Bluetooth) per profile's `connection`. The BTHLEDEVICE spoof shows here.
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
- One `Gamepad` per virtual (not zero, not two &mdash; the duplicate-Gamepad hang).
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

## `test/regression/swap_regression.ps1`: lifecycle battery

The 28-scenario battery that drives `HIDMaestroTest.exe` through every interesting create / live-swap / remove / force-kill sequence plus the HID PID 1.0 force-feedback round-trip, and verifies no PnP devnodes are left in the `PRESENT` state after each one.

```powershell
# from an ELEVATED PowerShell, repo root or anywhere
./test/regression/swap_regression.ps1

# specific scenario only
./test/regression/swap_regression.ps1 -Filter 'S08*'

# verbose: prints every stdin command
./test/regression/swap_regression.ps1 -Verbose

# point at a non-default exe (e.g. a published build)
./test/regression/swap_regression.ps1 -Exe C:\path\to\HIDMaestroTest.exe
```

Exit code 0 if every scenario passed, 1 if any failed. Total wall time: 16-25 minutes on Ryzen-class, ~75 minutes on Atom Z8350 fixture (slow-hardware target with `HIDMAESTRO_TIMEOUT_SCALE=2`).

### The 28 scenarios

| Scenario | Pattern | Catches |
|----------|---------|---------|
| **S01_Single_360_BT_360** | `360 → BT → 360` | The original SwDevice teardown leaving a phantom xinputhid-bound BT child. |
| **S02_Single_360_BT_360_BT** | `+ → BT` | Secondary regression: leftover surfacing only after a 4th swap. |
| **S03_Single_LongCycle_8swaps** | 8 alternating swaps | Suffix-allocator stress + repeated DIF_REMOVE+hmswd-remove path. |
| **S04_Single_BT_360_BT** | BT first | Initial xinputhid bind path before any non-xinputhid create. |
| **S05_Single_Mixed_Families** | `360 → DS → Switch → BT → 360` | Cross-family swaps (XUSB companion, plain HID, xinputhid gamepad). |
| **S06_Single_SameProfileSwap** | `BT → BT` (same id) | Per-call unique suffix lets identical-profile recreation work. |
| **S07_Multi_CreateAll_Idle** | 4 mixed, idle, quit | Baseline multi-slot teardown via clean process exit. |
| **S08_Multi_SwapOneSlot** | 4 wired, swap slot 1 | Single-slot swap doesn't leak across siblings. |
| **S09_Multi_SwapAllSlots** | 4 wired, swap each slot | Concurrent live-swap of every slot. |
| **S10_Multi_RemoveOne** | 3 mixed, `remove 1` | `Dispose` without replacement leaves no residue. |
| **S11_Multi_MultipleXinputhid** | 3 different xinputhid + swap | xinputhid INF-match handling under multiple concurrent binds. |
| **S12_ForceKill_Recovery** | Hard-kill, then clean session | `RemoveAllVirtualControllers` purges orphans from a force-kill. |
| **S13_AcrossProcess_Recreation** | `proc1 (BT+360) → quit → proc2 (BT+360) + swaps` | Per-process suffix prefix actually varies. Catches the kernel reuse-existing trap. |
| **S14_Single_RapidSwaps_NoSettle** | 4 swaps queued back-to-back, no inter-command sleep | Per-controllerIndex teardown gate + reentrancy in Setup/Teardown. |
| **S15_Multi_SixControllers** | 6 mixed (beyond XInput's 4) + swap slot 5 | Slot-allocator skip + ContainerID encoding for high indices. |
| **S16_Single_SameVidPid** | `xbox-360-wired ↔ xbox-360-arcade-stick` (both 045E:028E) | Registry-reuse path when only profile-level metadata differs. |
| **S17_ForceKill_MidCascade** | Hard-kill 5s into a Series BT teardown's xinputhid filter unbind | Worst-case force-kill timing; phantoms left in mid-cascade state. |
| **S18_Single_AlternatingPattern** | `A → B → A → C → A → B → A` | Suffix allocator state when revisiting prior profiles. |
| **S19_Multi_RapidMultiSlotSwap** | 4 controllers, swap each slot's profile back-to-back, no settle | PadForge's `ApplyAscendingIndexPreemption` async-dispose path. |
| **S20_Multi_HeterogeneousCascade** | 4 controllers, every family in one batch, then `quit` | `DisposeControllersInParallel` correctness with all four families. |
| **S21_Custom_CreateIdle** | Custom (BEEF:F000) create + idle + quit | Runtime-built profile loads, binds, tears down through the same path. |
| **S22_Custom_SwapCycle** | `Custom ↔ 360 → Custom ↔ BT → Custom ↔ DualSense` | Cross-family swaps to/from a non-embedded faux-VID profile. |
| **S23_Multi_CustomInMix** | 5 mixed (360 + Series BT + DualSense + Switch Pro + Custom) + swap custom | Real PadForge-shape consumer config. |
| **S24_PidFfb_RoundTrip** | DI PID FFB shared-section round-trip on a custom HOTAS | `PublishPidPool / PublishPidState` reach driver's HID feature replies. |
| **S25_PidFfb_AllocFree** | PID FFB allocate-then-free under burst + multi-controller | Two controllers' independent EBI tables; pool exhaustion. |
| **S26_PidFfb_FfbTest** | DI PID FFB end-to-end via SharpDX/DI8 (`FfbTest`) | The PID FFB invariants S24/S25 cover at the SDK boundary actually deliver to a real DI consumer. |
| **S27_Xbox360_Dpad_XInput** | xbox-360-wired d-pad through XUSB companion (`XInputGetState`) | Closes #19 &mdash; `wButtons.DPAD_*` matches expected mask. |
| **S28_Hat_Resolution_Encoder** | Pure encoder unit-test across hat resolutions 8 / 16 / 360 | v1.3.4 hat-input priority chain: `HMHat / HatRaw / HatHundredths / HatDegrees` produce correct descriptor field values. |

Each scenario covers a specific historical bug or invariant. The full list is the codified history of what's broken in this area before.

---

### What "PASS" means

Per scenario:

1. **Snapshot every `HIDMAESTRO*` / `VID_045E&PID_028E*` PnP devnode** that `CM_Locate_DevNodeW(NORMAL)` reports as `PRESENT` BEFORE the scenario runs. This is the baseline.
2. **Run the scenario**, then sleep 12 s for kernel cascade to settle.
3. **Snapshot the same set AFTER.**
4. **PASS** iff `(after \ before) == empty` &mdash; no new `PRESENT` entries leaked across the scenario.

`PHANTOM` entries (registry residue with no live devnode) are **ignored**. They don't occupy XInput slots, don't show in active-controller lists, and are cosmetic-only registry leftovers from the historic SwDevice behavior. Only `PRESENT` is what consumers actually see.

---

### Diagnosing a FAIL

The script prints leftover instance IDs when a scenario fails:

```
[FAIL] S08_Multi_SwapOneSlot 47832ms
       Leftover: SWD\HIDMAESTRO_VID_045E_PID_0B13&IG_00\<suffix>_0001
```

For deeper inspection, every test process runs with `HIDMAESTRO_DIAG=1` in its environment, so `%TEMP%\HIDMaestro\teardown_diag.log` records every `TeardownController` call (entry/exit/timing) and every `SwdDeviceFactory.Remove` outcome (`hr` plus `present`-after-remove).

On a FAIL, grep that log for the leftover instance ID to see exactly what the SDK did.

---

### Harness mechanics

The harness is **event-driven, not time-based.** The test app emits `[ACK]` on stdout after each stdin command finishes processing, and the harness blocks on that marker. No fixed-sleep settle, no scaling.

This was a hard-won design. Win11 26200's PowerShell 5.1 has several pitfalls that interact:

1. **`Add-Type` C# delegate for `OutputDataReceived`** &mdash; never `Register-ObjectEvent` or PS-scriptblock cast. The latter produces silent zero-byte stdout reads on Win11.
2. **Byte-by-byte stdin pump** in the test app &mdash; `Console.In.ReadLine()` has a 15-second buffer on Win11 that breaks rapid back-to-back commands.
3. **UTF-8 BOM strip on stdin** &mdash; PowerShell's `WriteLine` emits one; the test app strips it.
4. **Named `EventWaitHandle` for quit signal** &mdash; cleaner than relying on stdin EOF detection.
5. **`Process.Kill` self-exit** + `HIDMAESTRO_QUIET=1` &mdash; ProcessExit handler skips the redundant `RemoveAllVirtualControllers` (per-scenario cleanup already disposed everything).

These five fixes interact; missing any one makes the harness hang on Win11. Preserved as the canonical recipe.

---

### Slow-hardware fixture

The full battery also runs on an Intel Atom Z8350 (4 cores @ 1.44 GHz, 4 GB RAM, Win10 IoT LTSC 19044). Same 28/28 PASS at `HIDMAESTRO_TIMEOUT_SCALE=2`. Validated on each release.

The slow-hardware result is the reason the harness is **pure ACK-driven** instead of fixed-sleep timed &mdash; a fixed sleep that's "enough" on a fast machine isn't enough on Atom; ACK-driven scales naturally.

The Atom fixture runs the same `swap_regression.ps1` script. Build the SDK on the dev box, copy artifacts to the Atom (SMB share or SSH `scp`), run the battery there. ~75 minutes wall time for the full 28 scenarios.

---

## `test/probes/`: one-off investigation tools

The `test/probes/` directory holds investigation tools used during HIDMaestro development. These are not part of the regression battery and are not built by `build_all.cmd`. They're WIP / situational and are listed in MEMORY for future-Claude awareness:

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

Each was built to characterize a specific behavior during an investigation. Some are ProcMon traces, some are C# WinRT probes, some are PowerShell scripts. They're untracked / WIP and **never deleted automatically** &mdash; preserved as forensic tools.

---

## CI

GitHub-hosted runners are Windows Server, not Win11 client. The regression battery's PnP behaviors differ on Server (different default services, different xinputhid behavior) so the battery isn't portable to GitHub-hosted CI.

Self-hosted runners on Win11 client could run it, but that's not currently set up. The regression battery stays manual via `pre-tag-validate.cmd`. **No CI is the right answer here**, given Server vs. client divergence.

---

## What gets validated before a release

The pre-tag validation pipeline (`scripts\pre-tag-validate.cmd`) is the gate:

1. Clean build &mdash; no stale Resources/ snapshots.
2. `verify.py --controllers 4` &mdash; cross-API correctness on a multi-controller deployment.
3. `swap_regression.ps1` &mdash; full 28-scenario battery. **28/28 PASS required.**
4. `HIDMaestroTest cleanup` &mdash; verify no leftover devnodes after the battery.
5. Profile extractor smoke test &mdash; the GUI tool opens, populates, extracts.

Total: ~30-40 minutes on Ryzen-class. If any step fails, don't tag.

---

## See also

- [Build and Release](build-and-release.md) &mdash; how validation fits into the tag-and-release flow.
- [Lifecycle and Teardown](lifecycle-and-teardown.md) &mdash; the create / dispose paths the battery exercises.
- [Cross-API Coverage](cross-api-coverage.md) &mdash; the per-API behavior `verify.py` checks.
- [Force Feedback](../sdk/force-feedback.md) &mdash; what S24-S26 validate.
- [Multi-Controller](multi-controller.md) &mdash; what S07, S15, S20, S23 validate.
- [`test/regression/README.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/test/regression/README.md) &mdash; the in-repo battery doc.
