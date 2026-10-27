# References

Authoritative sources for every load-bearing claim in this wiki. Each entry covers a specific topic plus the wiki pages that cite it.

A note on linking: this page deliberately avoids deep `learn.microsoft.com` URLs that may have moved during one of Microsoft's documentation reshuffles. For Microsoft-published material, the topic, header, or symbol name is cited verbatim: search Microsoft Learn for the exact symbol and the page is one click away. GitHub repos and stable spec roots are linked directly.

If a wiki page makes a claim that isn't backed by something here, it falls into one of three buckets: (a) author-empirical, validated by the regression battery in `test/regression/regression_battery.ps1`; (b) directly traceable to HIDMaestro's own source under [github.com/hifihedgehog/HIDMaestro](https://github.com/hifihedgehog/HIDMaestro); (c) Ghidra decomp from this project's investigations, archived under [`docs/investigations/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations).

---

## HID specification

The USB-IF specifications are the canonical source for every byte-layout, descriptor-item, and usage-code claim. Documents are at [usb.org/document-library](https://www.usb.org/document-library); search by the exact title.

- **USB HID 1.11 specification.** Defines report descriptors, input/output/feature reports, the Item Format encoding (used by `HidDescriptorBuilder.AddRaw`), and `HidD_GetPreparsedData` semantics. Backs every byte-level descriptor claim in [HID Descriptor Builder](../sdk/hid-descriptor-builder.md) and [Profile System](../profiles/profile-system.md).

- **USB HID Usage Tables (HUT) 1.5.** Defines the Generic Desktop Page (Usage Page 0x01), where:
  - 0x30 X, 0x31 Y, 0x32 Z, 0x33 Rx, 0x34 Ry, 0x35 Rz, 0x39 Hat Switch
  - **0x40 Vx, 0x41 Vy**: the velocity usages used in [Cross-API Coverage](cross-api-coverage.md) for the separate-trigger trick.
  - 0x04 Joystick, 0x05 Game Pad: the application TLCs used by `HidDescriptorBuilder.Joystick()` / `Gamepad()`.

- **HID Physical Interface Device (PID) 1.0.** Defines Report IDs 0x11 Create New Effect, 0x12 Block Load, 0x13 PID Pool, 0x14 PID State, 0x1A Effect Operation, 0x1B Block Free, 0x1C Device Control, 0x1D Device Gain, plus the Physical Interface Device usage page (0x0F) and every effect-type code referenced by `HidDescriptorBuilder.AddPidFfbBlock`'s emitted bytes. Backs [Force Feedback](../sdk/force-feedback.md) section by section.

---

## Microsoft Windows driver framework

For symbols below, search [learn.microsoft.com](https://learn.microsoft.com/) by exact name unless a verified URL is given.

- **User-Mode Driver Framework (UMDF) 2**: the framework HIDMaestro.dll runs under. Topic: "Getting started with UMDF version 2." Defines `EvtIoDeviceControl`, `WDFDEVICE` lifetime, queue dispatch policies, and the WUDFRd reflector model. Backs [UMDF2 Driver Internals](umdf2-driver-internals.md) and [Architecture Overview](architecture-overview.md).

- **`UmdfHostProcessSharing` directive**: topic: "Specifying WDF Directives in INF Files." Documents `ProcessSharingEnabled` (default) vs `ProcessSharingDisabled` (HIDMaestro's choice). Backs the per-instance WUDFHost claim in [Architecture Overview](architecture-overview.md) and [Multi-Controller](multi-controller.md).

- **`mshidumdf.sys`**: the Windows-shipped HID minidriver proxy that hosts UMDF2 HID drivers. The reference sample is Microsoft's [`vhidmini2`](https://github.com/microsoft/Windows-driver-samples/tree/main/hid/vhidmini2) (in the public Windows-driver-samples repo on GitHub).

- **`SwDeviceCreate` (cfgmgr32 / swdevice.h)**: topic: "SwDeviceCreate function." The `pContainerId` parameter is the linchpin of the slot-1-skip fix in [SwDevice and PnP](swdevice-and-pnp.md). The `SWDeviceLifetimeParentPresent` lifetime flag and the only-documented-teardown-path are described in the same topic.

- **`SetupDiCreateDeviceInfoW`**: topic: "SetupDiCreateDeviceInfoW function." The older device-creation API used by HIDMaestro for plain HID profiles. Does NOT expose ContainerID assignment (the gap that forced the SwDevice migration).

- **`DEVPKEY_Device_ContainerId`**: topic by exact name. Defines the GUID that groups multiple devnodes as one logical device, including the null sentinel `{00000000-0000-0000-FFFF-FFFFFFFFFFFF}` that triggers the slot-1-skip path documented in [SwDevice and PnP](swdevice-and-pnp.md).

- **`pnputil`**: topic: "PnPUtil command syntax." The `/add-driver`, `/install`, `/delete-driver`, `/remove-device` semantics referenced in [Driver Install and Signing](driver-install-and-signing.md) and [Lifecycle and Teardown](lifecycle-and-teardown.md).

- **`CM_NOTIFY_ACTION` enumeration**: topic by exact name. Defines `CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED`, used as the kernel-side guarantee in [SwDevice and PnP](swdevice-and-pnp.md)'s SwD-first removal ordering.

- **HID class architecture (HidClass.sys)**: topic: "HID Architecture." Backs the kernel-side stack diagram in [UMDF2 Driver Internals](umdf2-driver-internals.md).

- **`RAWMOUSE` structure**: topic by exact name. It carries five buttons, flags an absolute pointer with `MOUSE_MOVE_ABSOLUTE`, and defines `MOUSE_MOVE_NOCOALESCE` because Windows merges consecutive moves. Backs the second button collection and the note on merged moves in [Keyboards and Mice](../sdk/keyboards-and-mice.md).

- **`xinputhid.inf [GIP_Hid]`**: the inbox INF that binds `xinputhid.sys` as a HID upper filter for Xbox Series / One / Elite v2 BT controllers. Lives at `C:\Windows\INF\xinputhid.inf` on every Win10/11 install. The `[GIP_Hid]` Match section is the documented mechanism for [Profile System](../profiles/profile-system.md)'s xinputhid Xbox group.

---

## XInput / Xbox controller protocol

- **XInput.** Topic: "XInput Game Controller APIs" on Microsoft Learn. The 4-slot cap, `XInputGetState`, `XInputSetState`, `XINPUT_STATE` packet layout. Backs [Cross-API Coverage](cross-api-coverage.md)'s XInput section.

- **`XInputGetStateEx`**: ordinal 100 export of `xinput1_3.dll` / `xinput1_4.dll`. Returns `XINPUT_GAMEPAD_GUIDE` (0x0400) in `wButtons`. Not in Microsoft's public XInput documentation; widely documented in community projects (search "XInputGetStateEx ordinal 100"). Backs the Guide button claims throughout the wiki.

- **`GUID_DEVINTERFACE_XUSB`** = `{EC87F1E3-C13B-4100-B5F7-8B84D54260CB}`. Defined in `Xinput.h`. The interface class `xinput1_4.dll` walks for discovery.

- **XUSB / GIP wire format**: not officially documented by Microsoft. HIDMaestro's understanding comes from Ghidra decomp of `xinput1_4.dll` and `xusb22.sys` plus empirical probing of `xinputhid.sys`, archived in [`docs/investigations/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations). The IOCTL codes (`0x80006000` `IOCTL_XUSB_GET_INFORMATION`, `0x8000E004` `IOCTL_XUSB_GET_CAPABILITIES`, etc.) match the empirical probe results in [XUSB Companion](xusb-companion.md).

---

## Microsoft GameInput and Windows.Gaming.Input

- **Microsoft GameInput** (the modern API): product page at [gaming.microsoft.com](https://www.microsoft.com/en-us/gaming) (search "GameInput") and developer docs on Microsoft Learn. The product name HIDMaestro user-facing copy uses (per the [Glossary](../start/glossary.md) entry).

- **Windows.Gaming.Input** (the older WinRT surface): the WinRT API exposed by `Windows.Gaming.Input.dll`. Documented on Microsoft Learn under the `Windows.Gaming.Input` namespace.

- **GameInput device mapping registry**: the `HKLM\SYSTEM\CurrentControlSet\Control\GameInput\Devices\` hive. Not Microsoft-documented; HIDMaestro's understanding is reverse-engineered. Investigation: [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04).

- **`ProviderManagerWorker::OnPnpDeviceAdded` classifier pass-list**: reverse-engineered via Ghidra decomp of `Windows.Gaming.Input.dll` on Win11 26200. Source: same investigation. Backs the dispatch claims in [Cross-API Coverage](cross-api-coverage.md) and the System-class choice in [XUSB Companion](xusb-companion.md).

- **`IsDeviceOrAncestorFilteredBy` `wcsncmp` against `"xinputhid"`**: same Ghidra source. Backs the UpperFilter tripwire in [XUSB Companion](xusb-companion.md).

---

## DirectInput / DInput8 / pid.dll

- **DirectInput.** Topic: "DirectInput" under "Previous Versions" on Microsoft Learn. The 8-axis enumeration (X, Y, Z, Rx, Ry, Rz, Slider0, Slider1), POVs, button caps. Backs the DirectInput claims in [Cross-API Coverage](cross-api-coverage.md).

- **`pid.dll` PID FFB enumerator**: the DirectInput-shipped DLL that walks HID PID descriptors and exposes effects to DI consumers. Closed-source Microsoft component. The Gamepad-TLC AV in `PID_EffectOperation+0x52` is documented in [HIDMaestro issue #16](https://github.com/hifihedgehog/HIDMaestro/issues/16); reproducible against the canonical four-feature vJoy descriptor on Windows 10/11.

- **Ownership claims and deploy locking (v2.0.0)**: [CreateNamedPipeW](https://learn.microsoft.com/windows/win32/api/namedpipeapi/nf-namedpipeapi-createnamedpipew) documents `FILE_FLAG_FIRST_PIPE_INSTANCE`, the claim every program, transport index and identity takes, and that a pipe instance is deleted when the last handle closes. [WaitNamedPipeW](https://learn.microsoft.com/windows/win32/api/namedpipeapi/nf-namedpipeapi-waitnamedpipew) documents the liveness probe that opens no handle. [Object Namespaces](https://learn.microsoft.com/windows/win32/sync/object-namespaces) documents the private namespace the machine-wide locks live in, `HIDMaestro.Admin\Deploy` and the rest: "The caller must be within the specified boundary for the create operation to succeed", and the boundary holds the Administrators SID. No Microsoft page documents the pipe prefix `ProtectedPrefix\Administrators\` the claims live under. James Forshaw's "Named Pipe Secure Prefixes" (2017) describes it, and the SDK's source names the smss.exe and npfs.sys builds read for it. Back [Programs Side by Side](../sdk/programs-side-by-side.md).

- **Marking a gone devnode for reinstall (v2.0.0)**: [Determining Whether a Device is Plugged In](https://learn.microsoft.com/windows-hardware/drivers/install/determining-whether-a-device-is-plugged-in) gives `CM_Get_DevNode_Status` returning `CR_NO_SUCH_DEVINST` as the test for an unplugged device's devnode, and `CONFIGFLAG_REINSTALL` as the mark that reinstalls it at its next arrival. Back the WinUSB restore in [Wii U GameCube Adapter](../sdk/gamecube-adapter.md#dolphin-slippi-and-sdl).

- **Installing on one device (v2.0.0)**: [DiInstallDevice](https://learn.microsoft.com/windows/win32/api/newdev/nf-newdev-diinstalldevice) installs the best match the driver store holds on the named device and no other. [SetupAPI functions that simplify driver installation](https://learn.microsoft.com/windows-hardware/drivers/install/setupapi-functions-that-simplify-driver-installation) documents that `UpdateDriverForPlugAndPlayDevices` installs the package on all present devices with a matching hardware or compatible ID, which is why a create no longer uses it. Back [Driver Install and Signing](driver-install-and-signing.md).

- **PnP notifications without a managed delegate (v2.0.0)**: [CM_Unregister_Notification](https://learn.microsoft.com/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_unregister_notification) waits for pending callbacks to finish, which is why the `GCHandle` the dispatcher reads is freed after it returns.

- **Build layouts (v2.0.0)**: [Install the WDK using NuGet](https://learn.microsoft.com/windows-hardware/drivers/install-the-wdk-using-nuget) lists the Windows SDK as a requirement of the NuGet WDK. Microsoft's windows-drivers-rs reads `WDKContentRoot` and `Version_Number` in an EWDK prompt (`crates/wdk-build/src/utils.rs`) and points `WDKContentRoot` at the target architecture's package in CI (`.github/actions/install-wdk/action.yaml`). Back the settings in [Build and Release](build-and-release.md).

- **Inf2Cat's manifest and search order (v2.0.0)**: [Internal Manifest vs External Manifest](https://learn.microsoft.com/archive/blogs/junfeng/internal-manifest-vs-external-manifest) and [Dynamic-link library search order](https://learn.microsoft.com/windows/win32/dlls/dynamic-link-library-search-order) back dropping `inf2cat.exe.manifest` and `Microsoft.Kits.Logger.dll`.

- **vJoy reference descriptor**: [github.com/njz3/vJoy](https://github.com/njz3/vJoy) maintains the descriptor headers (`hidReportDesc.h`, `hidReportDescSingle.h`, `hidReportDescFfb.h`). The four-feature descriptor that triggers the `pid.dll` AV.

---

## Library source code

- **HIDAPI**: [github.com/libusb/hidapi](https://github.com/libusb/hidapi). The Windows backend at `windows/hid.c` is where the bus type detection (USB / Bluetooth / SPI), the `BTHENUM` and `BTHLEDEVICE` compatible ID checks (back the Bluetooth identity in [Cross-API Coverage](cross-api-coverage.md)), and the `&IG_` skip logic live. The preparsed-data reconstruction algorithm `HMDeviceExtractor` ports lives in `windows/hidapi_descriptor_reconstruct.c` (originally contributed by the Chromium WebHID team).

- **SDL3**: [github.com/libsdl-org/SDL](https://github.com/libsdl-org/SDL). The XInput / RawInput / HIDAPI fallback hierarchy is in `src/joystick/windows/`. The `SDL_HINT_JOYSTICK_XINPUT` hint is documented at [wiki.libsdl.org](https://wiki.libsdl.org/) (search the hint name).

- **SDL community gamepad mapping database**: [github.com/mdqinc/SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB). The community-maintained `gamecontrollerdb.txt`. Spoofed-VID/PID profiles in [Custom Profiles](../profiles/custom-profiles.md) inherit mappings from here.

- **Linux HID drivers**: `drivers/hid/hid-playstation.c` (DualSense and DualShock 4: report layouts, calibration parsing, the Bluetooth feature CRC) and `drivers/hid/hid-sony.c` (DualShock 3: report offsets, battery codes, motion scale) in the kernel's [HID tree](https://git.kernel.org/pub/scm/linux/kernel/git/hid/hid.git/).

- **RPCS3**: [github.com/RPCS3/rpcs3](https://github.com/RPCS3/rpcs3). `rpcs3/Input/ds3_pad_handler.cpp` and `.h` are the DualShock 3 read sequence and output report the `dualshock-3-full` persona answers. `ds4_pad_handler.cpp` and `dualsense_pad_handler.cpp` check the Bluetooth calibration CRC.

- **PCSX2**: [github.com/PCSX2/pcsx2](https://github.com/PCSX2/pcsx2). `pcsx2/Input/SDLInputSource.cpp` sets SDL's sixaxis hint on Windows and binds pressure axes for a pad SDL reports as a PS3 controller with 16 axes and 11 buttons.

- **DS4Windows**: [github.com/schmaldeo/DS4Windows](https://github.com/schmaldeo/DS4Windows), the maintained fork. `DS4Windows/DS4Library/DS4Sixaxis.cs` parses the DualShock 4 calibration per transport without absolute values.

- **switch2_controller_research**: [github.com/ndeadly/switch2_controller_research](https://github.com/ndeadly/switch2_controller_research). The Switch 2 controllers' command protocol (`commands.md`), reports (`hid_reports.md`), descriptors and flash layout, and `captures/usb/rumble-procon-gccon.pcapng`, the link-layer capture of a console driving a Pro Controller 2 that `switch2-pro-controller-composite` reproduces.

- **SDL's Switch 2 driver**: `src/joystick/hidapi/SDL_hidapi_switch2.c` in SDL3. The start sequence, report `0x05` parsing, the sensor constants and the rumble encoding the Switch 2 Pro persona answers.

- **Switch 2 device emulations**: [VIIPER](https://github.com/Alia5/VIIPER)'s `device/ns2pro` over USB/IP, [switch2-controllers-windows10-gyro](https://github.com/TommyWabg/switch2-controllers-windows10-gyro)'s `src/usbip_server.py`, and [XinHeLianSheng-Pro2-Bridge](https://github.com/LeonChrome/XinHeLianSheng-Pro2-Bridge)'s `usb_switch2_vendor.c`. The last two serve the Microsoft OS 1.0 descriptors the persona serves. [switch2-controllers](https://github.com/Nadeflore/switch2-controllers)' `controller.py` gives the rumble frame's bit layout.

- **libusb**: [github.com/libusb/libusb](https://github.com/libusb/libusb). `libusb/os/windows_winusb.c` reads a device's `DeviceInterfaceGUIDs` or `DeviceInterfaceGUID` to reach an interface on WinUSB.

- **usbip-win2 host controller install (v2.0.1)**: [github.com/vadimgrn/usbip-win2](https://github.com/vadimgrn/usbip-win2) at tag `v.0.9.8.1`. `userspace/devnode/main.cpp` lines 232-295 are the two calls `devnode.exe install` makes, which the SDK makes itself. `userspace/innosetup/setup.iss` line 176 adds the root-hub filter with pnputil, and `drivers/ude_filter/usbip2_filter.inf` lines 32-43 make it an extension INF on `USB\ROOT_HUB30`, which is why its install restarts every USB 3 root hub. `drivers/ude/device.cpp` lines 405-411 and `drivers/ude/filter_request.cpp` are why SET_CONFIGURATION and SET_INTERFACE need the filter. Back the install in [Driver Install and Signing](driver-install-and-signing.md#usbip-transport).
- **Programs that run usbip-win2's installer (v2.0.1)**: Handheld Companion's `HandheldCompanion.iss` lines 568-577 and `utils/Utils.iss` lines 75-113, and VIIPER's `scripts/install.ps1` lines 120-132. Back what happens when they find HIDMaestro's install.

- **Wii U GameCube adapter hosts (v2.0.0)**: Dolphin (`Source/Core/InputCommon/GCAdapter.cpp`), Slippi's Dolphin fork (the same file, and `LibusbUtils.cpp`), SDL (`src/joystick/hidapi/SDL_hidapi_gamecube.c`, and `src/hidapi/SDL_hidapi.c`, which opens 057E:0337 only through libusb), eden (`src/input_common/drivers/gc_adapter.cpp`), RMG (`Source/RMG-Input-GCA/main.cpp`), gcfeeder and Nintendont (`kernel/HID.c`, `PADReadGC.c`). They back the command protocol, the report `0x21` layout and the status bits in [Wii U GameCube Adapter](../sdk/gamecube-adapter.md). [github.com/dolphin-emu/dolphin](https://github.com/dolphin-emu/dolphin), [github.com/libsdl-org/SDL](https://github.com/libsdl-org/SDL).

- **Wii U GameCube adapter devices (v2.0.0)**: 57 `lsusb` and `usb-devices` dumps of 057E:0337 from linux-hardware.org back the descriptors. The firmwares of loopj (usb-gamecube-controller-adapter) and pico-rectangle copy the strings, pico-rectangle and HOJA-LIB-ESP32 the report descriptor, and HOJA-LIB-RP2040 holds notes from a real adapter on its status values. joypad-os emulates the adapter with a different, 70-byte descriptor. A command survey of a real adapter (GBAtemp thread 388169, 2015) gives what `0x11` to `0x17` do, François-Xavier Carton's Linux driver series (hid-gamecube-adapter v3, 2020) gives the report layout and the 37-byte read, and Arte's guide to overclocking the adapter gives the 1.19971 ms controller read and the 833 and 1000 reports a second.

- **libusb Windows backend (v2.0.0)**: `libusb/os/windows_winusb.c` turns on `ALLOW_PARTIAL_READS` for every endpoint, reads `DeviceInterfaceGUIDs` to open a WinUSB device, and skips a device whose install state is not 0, which is why `BindWinUsb` leaves no reinstall flag on the bound devnode. The USB device emulation behind the persona is [Write a UDE client driver](https://learn.microsoft.com/windows-hardware/drivers/usbcon/writing-a-ude-client-driver), and the endpoint polling periods are the tables under [USB_ENDPOINT_DESCRIPTOR](https://learn.microsoft.com/windows-hardware/drivers/ddi/usbspec/ns-usbspec-_usb_endpoint_descriptor).

- **Linux HID core and hid-tools**: `drivers/hid/hid-core.c` in the kernel's HID tree and the report descriptor parser in [hid-tools](https://gitlab.freedesktop.org/libevdev/hid-tools). The SDK's descriptor parser assigns usage pages, Delimiter alternative sets and the empty value of a key array (`hid_array_value_is_valid`) as they do.

- **Keyboard and mouse descriptors**: each of the 103 keyboard and mouse profiles copies one interface's report descriptor from a public dump: usbhid-dump output posted in project issues, libinput recordings, or the Linux kernel's HID selftests (`tools/testing/selftests/hid/`).

- **Chromium gamepad implementation**: [source.chromium.org/chromium/chromium/src/+/main:device/gamepad/](https://source.chromium.org/chromium/chromium/src/+/main:device/gamepad/). The platform-specific backends are under `device/gamepad/{windows,linux,mac}/`. The `&IG_` skip in the Raw Input backend is in `raw_input_data_fetcher_win.cc`.

---

## Reference virtual-controller projects

- **DsHidMini**: [github.com/nefarius/DsHidMini](https://github.com/nefarius/DsHidMini). The architectural ancestor of HIDMaestro: UMDF2 + xinputhid for DualShock 3 emulation. Provides the proven UMDF2-as-HID-minidriver pattern. Its SXS mode is the model for `dualshock-3-full`: the report descriptor (`driver/HID/03_SXS_Col1_Joystick.h`, BSD 3-Clause), the joystick and feature report conversions (`DsHid.c`, `HID.FeatureReport.c`), and the output command handling (`HID.Reports.c`).

- **ViGEmBus**: [github.com/nefarius/ViGEmBus](https://github.com/nefarius/ViGEmBus). The retired-but-still-used kernel-mode virtual controller bus driver. Referenced as "what HIDMaestro replaces." Its `Bus_FileClose` in `sys/Driver.cpp` unplugs a client's devices when the client's process exits, the precedent for the owner pipe in [Keyboards and Mice](../sdk/keyboards-and-mice.md).

- **vJoy**: the active-maintenance fork at [github.com/njz3/vJoy](https://github.com/njz3/vJoy) is the canonical source for `hidReportDescFfb.h` (the four-feature descriptor that traps `pid.dll`).

- **VHF (Microsoft Virtual HID Framework)**: kernel-only; the alternative HIDMaestro deliberately avoids. Topic: "Virtual HID Framework (VHF)" on Microsoft Learn.

---

## .NET / SDK / signing toolchain

For .NET API symbols below, search [learn.microsoft.com/en-us/dotnet/api/](https://learn.microsoft.com/en-us/dotnet/api/) by exact name.

- **.NET self-signed certificate generation**: `System.Security.Cryptography.X509Certificates.CertificateRequest`. The API HIDMaestro uses in [Driver Install and Signing](driver-install-and-signing.md) to mint the per-machine self-signed cert.

- **Driver signing**: the trust path that lets a self-signed cert in `Cert:\LocalMachine\TrustedPublisher` install a UMDF2 driver without WHQL submission. Search Microsoft Learn for "Driver Signing" / "Driver signing requirements" for the current authoritative description.

- **`Inf2Cat.exe`**: topic by exact name on Microsoft Learn. Embedded in the SDK alongside the WDK-required dependencies.

- **`signtool.exe`**: topic by exact name on Microsoft Learn.

---

## Internal HIDMaestro investigations

These archive Ghidra decomp output, ProcMon traces, registry dumps, and empirical probe results that back claims throughout the wiki.

- [`docs/investigations/issue3-dual-xinputhid-saturation-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/issue3-dual-xinputhid-saturation-2026-04): the multi-controller WUDFHost CPU saturation investigation. Backs the `UmdfHostProcessSharing = ProcessSharingDisabled` claim in [Architecture Overview](architecture-overview.md) and [Multi-Controller](multi-controller.md).

- [`docs/design/coexistence.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/docs/design/coexistence.md): the 2.0.0 design note for programs side by side, with every mechanism, measurement and source behind [Programs Side by Side](../sdk/programs-side-by-side.md), [Wii U GameCube Adapter](../sdk/gamecube-adapter.md), the build settings and the NativeAOT work.

- [`docs/design/data-driven-devices.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/docs/design/data-driven-devices.md): the design note for devices as profile data, behind the [report field parameters](../profiles/profile-system.md#report-field-parameters-v200) and the [values on the wire](../profiles/profile-system.md#values-on-the-wire-v200).

- [`docs/MIGRATION.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/docs/MIGRATION.md): the repository's copy of [Moving from 1.x](../start/migration.md).
- [`docs/UNINSTALL.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/docs/UNINSTALL.md): the repository's source for [Removing HIDMaestro](../start/removing-hidmaestro.md).

- [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04): the WGI dispatch / `IsDeviceOrAncestorFilteredBy` / classifier pass-list / `IOCTL_XUSB_WAIT_FOR_INPUT` 29-byte format reverse engineering. Backs all of [XUSB Companion](xusb-companion.md) and [Cross-API Coverage](cross-api-coverage.md)'s WGI sections.

- [HIDMaestro README](https://github.com/hifihedgehog/HIDMaestro/blob/master/README.md): primary source for the catalog count, performance numbers, and validation results referenced in [Multi-Controller](multi-controller.md) and [Lifecycle and Teardown](lifecycle-and-teardown.md).

- [HIDMaestro issue #16](https://github.com/hifihedgehog/HIDMaestro/issues/16): the four-feature pid.dll AV report. Backs [Force Feedback](../sdk/force-feedback.md)'s "only one Feature report" rule.

- [HIDMaestro issue #19](https://github.com/hifihedgehog/HIDMaestro/issues/19): the Xbox 360 d-pad XInput regression. Backs the v1.3.3 fix in [XUSB Companion](xusb-companion.md).

- [`test/regression/regression_battery.ps1`](https://github.com/hifihedgehog/HIDMaestro/blob/master/test/regression/regression_battery.ps1): the 101-scenario battery that empirically validates lifecycle latency, multi-controller behavior, force-kill recovery, PID FFB round-trip, the composite personas, the battery reply a pad gives XInput and the device identity of every family. Backs every "verified" / "tested" claim in [Lifecycle and Teardown](lifecycle-and-teardown.md) and [Testing and Verification](testing-and-verification.md).

---

## Web standards

- **W3C Gamepad API**: [w3.org/TR/gamepad/](https://www.w3.org/TR/gamepad/). The W3C standard implemented by Chromium (Edge / Chrome / Brave / Opera), Firefox, Safari, and others. The `mapping = "standard"` STANDARD_GAMEPAD bucket referenced in [Cross-API Coverage](cross-api-coverage.md) is at [w3.org/TR/gamepad/#remapping](https://www.w3.org/TR/gamepad/#remapping).

- **WebHID API**: [wicg.github.io/webhid/](https://wicg.github.io/webhid/). The browser API that motivated the Chromium WebHID team's Windows preparsed-data reconstruction algorithm now ported into HIDMaestro's `HMDeviceExtractor`.

---

## How to verify a specific claim

1. **Code-traceable** (function names, line numbers, byte layouts) &rarr; check the file path + line in [github.com/hifihedgehog/HIDMaestro](https://github.com/hifihedgehog/HIDMaestro).
2. **Spec-traceable** (HID descriptor items, PID Report IDs, usage codes) &rarr; cross-reference the appropriate USB-IF spec at [usb.org/document-library](https://www.usb.org/document-library).
3. **Microsoft-API-traceable** &rarr; search [learn.microsoft.com](https://learn.microsoft.com/) by the exact symbol or topic name; that's the contract. `pnputil` command output is the runtime behavior.
4. **Library-behavior-traceable** &rarr; the GitHub source links above are authoritative; behavior changes by version are tracked in their release notes.
5. **Reverse-engineered** &rarr; the `docs/investigations/` directory has the Ghidra output, ProcMon traces, and registry dumps that back the claim.
6. **Author-empirical** &rarr; reproduce via `regression_battery.ps1` or the `verify.py` cross-API harness on Windows 11 26100/26200 with the latest HIDMaestro release.

If a claim is contested and none of the above apply, file an issue: [github.com/hifihedgehog/HIDMaestro/issues](https://github.com/hifihedgehog/HIDMaestro/issues).

---

## See also

- [Glossary](../start/glossary.md): one-line definitions for every term.
- [Architecture Overview](architecture-overview.md): the assembled architecture every other page refers back to.
- [HIDMaestro README](https://github.com/hifihedgehog/HIDMaestro/blob/master/README.md): the primary author-curated summary.
