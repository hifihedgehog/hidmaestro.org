# References

Authoritative sources for every load-bearing claim in this wiki. Each entry covers a specific topic plus the wiki pages that cite it.

A note on linking: this page deliberately avoids deep `learn.microsoft.com` URLs that may have moved during one of Microsoft's documentation reshuffles. For Microsoft-published material, the topic, header, or symbol name is cited verbatim &mdash; search Microsoft Learn for the exact symbol and the page is one click away. GitHub repos and stable spec roots are linked directly.

If a wiki page makes a claim that isn't backed by something here, it falls into one of three buckets: (a) author-empirical, validated by the regression battery in `test/regression/swap_regression.ps1`; (b) directly traceable to HIDMaestro's own source under [github.com/hifihedgehog/HIDMaestro](https://github.com/hifihedgehog/HIDMaestro); (c) Ghidra decomp from this project's investigations, archived under [`docs/investigations/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations).

---

## HID specification

The USB-IF specifications are the canonical source for every byte-layout, descriptor-item, and usage-code claim. Documents are at [usb.org/document-library](https://www.usb.org/document-library); search by the exact title.

- **USB HID 1.11 specification.** Defines report descriptors, input/output/feature reports, the Item Format encoding (used by `HidDescriptorBuilder.AddRaw`), and `HidD_GetPreparsedData` semantics. Backs every byte-level descriptor claim in [HID Descriptor Builder](../sdk/hid-descriptor-builder.md) and [Profile System](../profiles/profile-system.md).

- **USB HID Usage Tables (HUT) 1.5.** Defines the Generic Desktop Page (Usage Page 0x01), where:
  - 0x30 X, 0x31 Y, 0x32 Z, 0x33 Rx, 0x34 Ry, 0x35 Rz, 0x39 Hat Switch
  - **0x40 Vx, 0x41 Vy** &mdash; the velocity usages used in [Cross-API Coverage](cross-api-coverage.md) for the separate-trigger trick.
  - 0x04 Joystick, 0x05 Game Pad &mdash; the application TLCs used by `HidDescriptorBuilder.Joystick()` / `Gamepad()`.

- **HID Physical Interface Device (PID) 1.0.** Defines Report IDs 0x11 Create New Effect, 0x12 Block Load, 0x13 PID Pool, 0x14 PID State, 0x1A Effect Operation, 0x1B Block Free, 0x1C Device Control, 0x1D Device Gain, plus the Physical Interface Device usage page (0x0F) and every effect-type code referenced by `HidDescriptorBuilder.AddPidFfbBlock`'s emitted bytes. Backs [Force Feedback](../sdk/force-feedback.md) section by section.

---

## Microsoft Windows driver framework

For symbols below, search [learn.microsoft.com](https://learn.microsoft.com/) by exact name unless a verified URL is given.

- **User-Mode Driver Framework (UMDF) 2** &mdash; the framework HIDMaestro.dll runs under. Topic: "Getting started with UMDF version 2." Defines `EvtIoDeviceControl`, `WDFDEVICE` lifetime, queue dispatch policies, and the WUDFRd reflector model. Backs [UMDF2 Driver Internals](umdf2-driver-internals.md) and [Architecture Overview](architecture-overview.md).

- **`UmdfHostProcessSharing` directive** &mdash; topic: "Specifying WDF Directives in INF Files." Documents `ProcessSharingEnabled` (default) vs `ProcessSharingDisabled` (HIDMaestro's choice). Backs the per-instance WUDFHost claim in [Architecture Overview](architecture-overview.md) and [Multi-Controller](multi-controller.md).

- **`mshidumdf.sys`** &mdash; the Windows-shipped HID minidriver proxy that hosts UMDF2 HID drivers. The reference sample is Microsoft's [`vhidmini2`](https://github.com/microsoft/Windows-driver-samples/tree/main/hid/vhidmini2) (in the public Windows-driver-samples repo on GitHub).

- **`SwDeviceCreate` (cfgmgr32 / swdevice.h)** &mdash; topic: "SwDeviceCreate function." The `pContainerId` parameter is the linchpin of the slot-1-skip fix in [SwDevice and PnP](swdevice-and-pnp.md). The `SWDeviceLifetimeParentPresent` lifetime flag and the only-documented-teardown-path are described in the same topic.

- **`SetupDiCreateDeviceInfoW`** &mdash; topic: "SetupDiCreateDeviceInfoW function." The older device-creation API used by HIDMaestro for plain HID profiles. Does NOT expose ContainerID assignment (the gap that forced the SwDevice migration).

- **`DEVPKEY_Device_ContainerId`** &mdash; topic by exact name. Defines the GUID that groups multiple devnodes as one logical device, including the null sentinel `{00000000-0000-0000-FFFF-FFFFFFFFFFFF}` that triggers the slot-1-skip path documented in [SwDevice and PnP](swdevice-and-pnp.md).

- **`pnputil`** &mdash; topic: "PnPUtil command syntax." The `/add-driver`, `/install`, `/delete-driver`, `/remove-device` semantics referenced in [Driver Install and Signing](driver-install-and-signing.md) and [Lifecycle and Teardown](lifecycle-and-teardown.md).

- **`CM_NOTIFY_ACTION` enumeration** &mdash; topic by exact name. Defines `CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED`, used as the kernel-side guarantee in [SwDevice and PnP](swdevice-and-pnp.md)'s SwD-first removal ordering.

- **HID class architecture (HidClass.sys)** &mdash; topic: "HID Architecture." Backs the kernel-side stack diagram in [UMDF2 Driver Internals](umdf2-driver-internals.md).

- **`xinputhid.inf [GIP_Hid]`** &mdash; the inbox INF that binds `xinputhid.sys` as a HID upper filter for Xbox Series / One / Elite v2 BT controllers. Lives at `C:\Windows\INF\xinputhid.inf` on every Win10/11 install. The `[GIP_Hid]` Match section is the documented mechanism for [Profile System](../profiles/profile-system.md)'s xinputhid Xbox group.

---

## XInput / Xbox controller protocol

- **XInput.** Topic: "XInput Game Controller APIs" on Microsoft Learn. The 4-slot cap, `XInputGetState`, `XInputSetState`, `XINPUT_STATE` packet layout. Backs [Cross-API Coverage](cross-api-coverage.md)'s XInput section.

- **`XInputGetStateEx`** &mdash; ordinal 100 export of `xinput1_3.dll` / `xinput1_4.dll`. Returns `XINPUT_GAMEPAD_GUIDE` (0x0400) in `wButtons`. Not in Microsoft's public XInput documentation; widely documented in community projects (search "XInputGetStateEx ordinal 100"). Backs the Guide button claims throughout the wiki.

- **`GUID_DEVINTERFACE_XUSB`** = `{EC87F1E3-C13B-4100-B5F7-8B84D54260CB}`. Defined in `Xinput.h`. The interface class `xinput1_4.dll` walks for discovery.

- **XUSB / GIP wire format** &mdash; not officially documented by Microsoft. HIDMaestro's understanding comes from Ghidra decomp of `xinput1_4.dll` and `xusb22.sys` plus empirical probing of `xinputhid.sys`, archived in [`docs/investigations/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations). The IOCTL codes (`0x80006000` `IOCTL_XUSB_GET_INFORMATION`, `0x8000E004` `IOCTL_XUSB_GET_CAPABILITIES`, etc.) match the empirical probe results in [XUSB Companion](xusb-companion.md).

---

## Microsoft GameInput and Windows.Gaming.Input

- **Microsoft GameInput** (the modern API) &mdash; product page at [gaming.microsoft.com](https://www.microsoft.com/en-us/gaming) (search "GameInput") and developer docs on Microsoft Learn. The product name HIDMaestro user-facing copy uses (per the [Glossary](../start/glossary.md) entry).

- **Windows.Gaming.Input** (the older WinRT surface) &mdash; the WinRT API exposed by `Windows.Gaming.Input.dll`. Documented on Microsoft Learn under the `Windows.Gaming.Input` namespace.

- **GameInput device mapping registry** &mdash; the `HKLM\SYSTEM\CurrentControlSet\Control\GameInput\Devices\` hive. Not Microsoft-documented; HIDMaestro's understanding is reverse-engineered. Investigation: [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04).

- **`ProviderManagerWorker::OnPnpDeviceAdded` classifier pass-list** &mdash; reverse-engineered via Ghidra decomp of `Windows.Gaming.Input.dll` on Win11 26200. Source: same investigation. Backs the dispatch claims in [Cross-API Coverage](cross-api-coverage.md) and the System-class choice in [XUSB Companion](xusb-companion.md).

- **`IsDeviceOrAncestorFilteredBy` `wcsncmp` against `"xinputhid"`** &mdash; same Ghidra source. Backs the UpperFilter tripwire in [XUSB Companion](xusb-companion.md).

---

## DirectInput / DInput8 / pid.dll

- **DirectInput.** Topic: "DirectInput" under "Previous Versions" on Microsoft Learn. The 8-axis enumeration (X, Y, Z, Rx, Ry, Rz, Slider0, Slider1), POVs, button caps. Backs the DirectInput claims in [Cross-API Coverage](cross-api-coverage.md).

- **`pid.dll` PID FFB enumerator** &mdash; the DirectInput-shipped DLL that walks HID PID descriptors and exposes effects to DI consumers. Closed-source Microsoft component. The Gamepad-TLC AV in `PID_EffectOperation+0x52` is documented in [HIDMaestro issue #16](https://github.com/hifihedgehog/HIDMaestro/issues/16); reproducible against the canonical four-feature vJoy descriptor on Windows 10/11.

- **vJoy reference descriptor** &mdash; [github.com/njz3/vJoy](https://github.com/njz3/vJoy) maintains the descriptor headers (`hidReportDesc.h`, `hidReportDescSingle.h`, `hidReportDescFfb.h`). The four-feature descriptor that triggers the `pid.dll` AV.

---

## Library source code

- **HIDAPI** &mdash; [github.com/libusb/hidapi](https://github.com/libusb/hidapi). The Windows backend at `windows/hid.c` is where the bus type detection (USB / Bluetooth / SPI), the `BTHLEDEVICE` CompatibleIDs check (backs the BT-spoof claim in [Cross-API Coverage](cross-api-coverage.md)), and the `&IG_` skip logic live. The preparsed-data reconstruction algorithm `HMDeviceExtractor` ports lives in `windows/hidapi_descriptor_reconstruct.c` (originally contributed by the Chromium WebHID team).

- **SDL3** &mdash; [github.com/libsdl-org/SDL](https://github.com/libsdl-org/SDL). The XInput / RawInput / HIDAPI fallback hierarchy is in `src/joystick/windows/`. The `SDL_HINT_JOYSTICK_XINPUT` hint is documented at [wiki.libsdl.org](https://wiki.libsdl.org/) (search the hint name).

- **SDL community gamepad mapping database** &mdash; [github.com/mdqinc/SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB). The community-maintained `gamecontrollerdb.txt`. Spoofed-VID/PID profiles in [Custom Profiles](../profiles/custom-profiles.md) inherit mappings from here.

- **Chromium gamepad implementation** &mdash; [source.chromium.org/chromium/chromium/src/+/main:device/gamepad/](https://source.chromium.org/chromium/chromium/src/+/main:device/gamepad/). The platform-specific backends are under `device/gamepad/{windows,linux,mac}/`. The `&IG_` skip in the Raw Input backend is in `raw_input_data_fetcher_win.cc`.

---

## Reference virtual-controller projects

- **DsHidMini** &mdash; [github.com/nefarius/DsHidMini](https://github.com/nefarius/DsHidMini). The architectural ancestor of HIDMaestro: UMDF2 + xinputhid for DualShock 3 emulation. Provides the proven UMDF2-as-HID-minidriver pattern.

- **ViGEmBus** &mdash; [github.com/nefarius/ViGEmBus](https://github.com/nefarius/ViGEmBus). The retired-but-still-used kernel-mode virtual controller bus driver. Referenced as "what HIDMaestro replaces."

- **vJoy** &mdash; the active-maintenance fork at [github.com/njz3/vJoy](https://github.com/njz3/vJoy) is the canonical source for `hidReportDescFfb.h` (the four-feature descriptor that traps `pid.dll`).

- **VHF (Microsoft Virtual HID Framework)** &mdash; kernel-only; the alternative HIDMaestro deliberately avoids. Topic: "Virtual HID Framework (VHF)" on Microsoft Learn.

---

## .NET / SDK / signing toolchain

For .NET API symbols below, search [learn.microsoft.com/en-us/dotnet/api/](https://learn.microsoft.com/en-us/dotnet/api/) by exact name.

- **.NET self-signed certificate generation** &mdash; `System.Security.Cryptography.X509Certificates.CertificateRequest`. The API HIDMaestro uses in [Driver Install and Signing](driver-install-and-signing.md) to mint the per-machine self-signed cert.

- **Driver signing** &mdash; the trust path that lets a self-signed cert in `Cert:\LocalMachine\TrustedPublisher` install a UMDF2 driver without WHQL submission. Search Microsoft Learn for "Driver Signing" / "Driver signing requirements" for the current authoritative description.

- **`Inf2Cat.exe`** &mdash; topic by exact name on Microsoft Learn. Embedded in the SDK alongside the WDK-required dependencies.

- **`signtool.exe`** &mdash; topic by exact name on Microsoft Learn.

---

## Internal HIDMaestro investigations

These archive Ghidra decomp output, ProcMon traces, registry dumps, and empirical probe results that back claims throughout the wiki.

- [`docs/investigations/issue3-dual-xinputhid-saturation-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/issue3-dual-xinputhid-saturation-2026-04) &mdash; the multi-controller WUDFHost CPU saturation investigation. Backs the `UmdfHostProcessSharing = ProcessSharingDisabled` claim in [Architecture Overview](architecture-overview.md) and [Multi-Controller](multi-controller.md).

- [`docs/investigations/wgi-silent-sink-2026-04/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/docs/investigations/wgi-silent-sink-2026-04) &mdash; the WGI dispatch / `IsDeviceOrAncestorFilteredBy` / classifier pass-list / `IOCTL_XUSB_WAIT_FOR_INPUT` 29-byte format reverse engineering. Backs all of [XUSB Companion](xusb-companion.md) and [Cross-API Coverage](cross-api-coverage.md)'s WGI sections.

- [HIDMaestro README](https://github.com/hifihedgehog/HIDMaestro/blob/master/README.md) &mdash; primary source for the catalog count, performance numbers, and validation results referenced in [Multi-Controller](multi-controller.md) and [Lifecycle and Teardown](lifecycle-and-teardown.md).

- [HIDMaestro issue #16](https://github.com/hifihedgehog/HIDMaestro/issues/16) &mdash; the four-feature pid.dll AV report. Backs [Force Feedback](../sdk/force-feedback.md)'s "only one Feature report" rule.

- [HIDMaestro issue #19](https://github.com/hifihedgehog/HIDMaestro/issues/19) &mdash; the Xbox 360 d-pad XInput regression. Backs the v1.3.3 fix in [XUSB Companion](xusb-companion.md).

- [`test/regression/swap_regression.ps1`](https://github.com/hifihedgehog/HIDMaestro/blob/master/test/regression/swap_regression.ps1) &mdash; the 28-scenario battery that empirically validates lifecycle latency, multi-controller behavior, force-kill recovery, and PID FFB round-trip. Backs every "verified" / "tested" claim in [Lifecycle and Teardown](lifecycle-and-teardown.md) and [Testing and Verification](testing-and-verification.md).

---

## Web standards

- **W3C Gamepad API** &mdash; [w3.org/TR/gamepad/](https://www.w3.org/TR/gamepad/). The W3C standard implemented by Chromium (Edge / Chrome / Brave / Opera), Firefox, Safari, and others. The `mapping = "standard"` STANDARD_GAMEPAD bucket referenced in [Cross-API Coverage](cross-api-coverage.md) is at [w3.org/TR/gamepad/#remapping](https://www.w3.org/TR/gamepad/#remapping).

- **WebHID API** &mdash; [wicg.github.io/webhid/](https://wicg.github.io/webhid/). The browser API that motivated the Chromium WebHID team's Windows preparsed-data reconstruction algorithm now ported into HIDMaestro's `HMDeviceExtractor`.

---

## How to verify a specific claim

1. **Code-traceable** (function names, line numbers, byte layouts) &rarr; check the file path + line in [github.com/hifihedgehog/HIDMaestro](https://github.com/hifihedgehog/HIDMaestro).
2. **Spec-traceable** (HID descriptor items, PID Report IDs, usage codes) &rarr; cross-reference the appropriate USB-IF spec at [usb.org/document-library](https://www.usb.org/document-library).
3. **Microsoft-API-traceable** &rarr; search [learn.microsoft.com](https://learn.microsoft.com/) by the exact symbol or topic name; that's the contract. `pnputil` command output is the runtime behavior.
4. **Library-behavior-traceable** &rarr; the GitHub source links above are authoritative; behavior changes by version are tracked in their release notes.
5. **Reverse-engineered** &rarr; the `docs/investigations/` directory has the Ghidra output, ProcMon traces, and registry dumps that back the claim.
6. **Author-empirical** &rarr; reproduce via `swap_regression.ps1` or the `verify.py` cross-API harness on Windows 11 26100/26200 with the latest HIDMaestro release.

If a claim is contested and none of the above apply, file an issue: [github.com/hifihedgehog/HIDMaestro/issues](https://github.com/hifihedgehog/HIDMaestro/issues).

---

## See also

- [Glossary](../start/glossary.md) &mdash; one-line definitions for every term.
- [Architecture Overview](architecture-overview.md) &mdash; the assembled architecture every other page refers back to.
- [HIDMaestro README](https://github.com/hifihedgehog/HIDMaestro/blob/master/README.md) &mdash; the primary author-curated summary.
