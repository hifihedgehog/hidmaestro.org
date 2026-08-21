# Glossary

Terms that show up across this wiki. Most are Windows-internal or HID-spec lingo with HIDMaestro-specific meaning attached.

## Driver framework / kernel

| Term | Meaning |
|------|---------|
| **UMDF2** | User-Mode Driver Framework version 2.15. Microsoft's official user-mode driver framework (search Microsoft Learn for "User-Mode Driver Framework version 2"). UMDF2 drivers compile as DLLs and are hosted by `WUDFHost.exe`; a bug crashes the host process, not the kernel. |
| **WUDFRd** | The kernel-mode reflector that proxies IRPs from the kernel HID stack into the user-mode `WUDFHost` instance hosting the UMDF2 driver DLL. Listed in every HIDMaestro INF as a `LowerFilters` service. |
| **WUDFHost** | The user-mode host process that loads UMDF2 driver DLLs. With `UmdfHostProcessSharing = ProcessSharingDisabled` (HIDMaestro's INFs both set this), each device instance gets its own `WUDFHost.exe` (~8 MB RSS, ~10 threads) instead of pooling into a shared host. |
| **mshidumdf** | `mshidumdf.sys` &mdash; Microsoft's kernel-mode HID minidriver proxy. Acts as the function driver. The HID class stack (`HidClass.sys`) sees a real HID device; HIDMaestro.dll attaches as a UMDF2 lower filter under it. |
| **KMDF** | Kernel-Mode Driver Framework. **Not** what HIDMaestro uses. UMDF2's user-mode constraint is what eliminates the EV-cert + reboot requirement; that's the entire point of the project. |
| **VHF** | Microsoft's Virtual HID Framework. Kernel-only. Mentioned for context &mdash; another approach HIDMaestro deliberately did not take. |
| **WDF** | Windows Driver Frameworks. Umbrella term for KMDF + UMDF. |

## HID stack

| Term | Meaning |
|------|---------|
| **HID** | Human Interface Device. The USB device class that gamepads, keyboards, mice, and joysticks use. The HID protocol is bus-agnostic &mdash; the same descriptor format works over USB, Bluetooth, BLE, and virtual buses. |
| **HID descriptor** | The byte string a HID device returns from the GET_DESCRIPTOR(HID Report) request. Defines every input/output/feature report's field layout. HIDMaestro profiles ship these as a hex string in `descriptor`; `HidDescriptorBuilder` constructs them programmatically. |
| **Report ID** | A 1-byte prefix that can disambiguate multiple report types on the same HID interface. Profiles where the descriptor declares `Report ID (0x85, n)` carry it as the first byte of every input/output/feature report. Not all profiles use one (Xbox Series BT does not; Xbox 360 Wired uses 0x01 for the input). |
| **Input report** | Device-to-host data. Buttons, axes, hat, etc. Polled or read async by `IOCTL_HID_READ_REPORT`. |
| **Output report** | Host-to-device data. Rumble, LED color, adaptive trigger config. Sent via `HidD_SetOutputReport` / `IOCTL_HID_WRITE_REPORT`. Captured by HIDMaestro and surfaced as `HMOutputSource.HidOutput`. |
| **Feature report** | Bidirectional configuration data. Sent via `HidD_SetFeature` (host &rarr; device) and `HidD_GetFeature` (device &rarr; host). HID PID 1.0 force-feedback uses Feature reports for Pool / Block Load / State; some controllers (DualSense, DualShock 4) use them for vendor-specific config. |
| **Preparsed data** | The opaque blob HidD_GetPreparsedData returns to user mode. Internally it's Microsoft's compressed representation of the HID descriptor's report layout. `HidP_GetCaps` and `HidP_GetButtonCaps` parse fields out of it. `HMDeviceExtractor` reconstructs the original descriptor from this blob using a C# port of the libusb/hidapi algorithm. |
| **HID PID 1.0** | HID Physical Interface Device specification, version 1.0 (USB-IF; download from [usb.org/document-library](https://www.usb.org/document-library)). The standard for HID-class force feedback. Defines Report IDs 0x11 (Create New Effect), 0x12 (Block Load), 0x13 (Pool), 0x14 (PID State), 0x1A (Effect Operation), 0x1B (Block Free), 0x1C (Device Control), 0x1D (Device Gain), and the Set Effect / Set Constant Force / Set Periodic / etc. output reports. |

## Cross-API plumbing

| Term | Meaning |
|------|---------|
| **DirectInput** | The legacy Win32 game controller API. Reads HID descriptors directly (preparsed data). Sees axes by HID usage code. Does not understand Vx/Vy velocity usages, which is what lets HIDMaestro carry separate trigger values for WGI / browser without exposing them as DI axes &mdash; every Xbox profile presents in DI as 5 axes with combined Z, matching real `xusb22.sys`. |
| **XInput** | The simplified Xbox-controller API. Discovers controllers via the XUSB device interface GUID (`{EC87F1E3-...}`), not by HID class. Hard-caps at 4 slots regardless of physical controllers. `xinput1_4.dll` is the active version on Win10/11. |
| **XUSB** | Xbox USB protocol. The wire format Xbox controllers use over USB and the device interface class (`{EC87F1E3-...}`) `xinput1_4.dll` walks to find them. HIDMaestro's XUSB companion (`HMXInput.dll`) registers this interface for non-xinputhid Xbox profiles. |
| **WinExInput** | Windows Extended Input. A device interface GUID (`{6C53D5FD-...}`) that historical HIDMaestro versions registered on HID parents. Ghidra decomp of `Windows.Gaming.Input.dll` on Win11 26200 found zero references; it is **not** WGI's actual `GamepadAdded` source. The interface registration is no longer used by the XUSB companion INF. |
| **WGI** | Windows.Gaming.Input. The WinRT API surface that powers `Gamepad.Vibration`, `RawGameController`, `IGameController`, etc. Used by Chromium for browser Gamepad and by UWP / WinUI games. Admits devices via a HIDClass pass-list in `ProviderManagerWorker::OnPnpDeviceAdded`, falling back to an `IsDeviceOrAncestorFilteredBy(L"xinputhid")` check. |
| **Microsoft GameInput** | Microsoft's newer game controller API (`GameInput.dll`). Distinct from the older `Windows.Gaming.Input` (WGI) WinRT surface, but both run through the same kernel-side dispatch on current Windows builds. Reads device-to-Gamepad mapping from `HKLM\...\GameInput\Devices\{VID}{PID}\...`. |
| **SDL3** | Simple DirectMedia Layer version 3. Cross-platform game-input library. Detects gamepads through XInput (`SDL_HINT_JOYSTICK_XINPUT`), HIDAPI, and a RawInput fallback. HIDMaestro is validated against it; SDL3 is not a dependency. |
| **HIDAPI** | The libusb-maintained cross-platform HID library. Skips devices whose path contains `&IG_` (XInput-handled, by design). Detects Bluetooth via the device's CompatibleIDs &mdash; HIDMaestro spoofs `BTHLEDEVICE` for BT-mode profiles so HIDAPI reports `bus_type = BT`. |
| **STANDARD GAMEPAD** | Chromium's "this is a real gamepad with two sticks, four face buttons, four shoulders, two triggers, dpad, start, select" mapping bucket. The browser Gamepad API exposes such devices with `.mapping = "standard"`. HIDMaestro Xbox profiles all hit this bucket because of the Vx/Vy + GameInput-mapping trigger trick. |

## HIDMaestro-specific

| Term | Meaning |
|------|---------|
| **XUSB Companion** | A separate UMDF2 device (`HMXInput.dll`, INF: `hidmaestro_xusb.inf`) created alongside non-xinputhid Xbox profiles like Xbox 360 Wired. Lives at `SWD\HIDMAESTRO\<sid>_NNNN`. Registers the XUSB device interface and serves XInput IOCTLs. Needed because `mshidumdf` suppresses XUSB IOCTLs on HID devices. See [XUSB Companion](../reference/xusb-companion.md). |
| **xinputhid** | `xinputhid.sys` &mdash; Microsoft's inbox kernel filter for Xbox controllers using the GIP (Gaming Input Protocol) descriptor over HID. Binds as an upper filter on HID children matching `[GIP_Hid]` hardware IDs in `xinputhid.inf`. Provides XInput delivery and the 16-button HID descriptor synthesis natively. Used by Xbox Series / Xbox One / Xbox Elite v2 BT profiles. |
| **xinputhid UpperFilter tripwire** | A registry string `"xinputhid"` written to a device's `DEVPKEY_Device_UpperFilters` (via INF `HKR AddReg` or per-instance `SetupAPI`) that satisfies WGI's `IsDeviceOrAncestorFilteredBy` `wcsncmp` check **without** loading `xinputhid.sys`. The filter only attaches to HID-class devices, so a System-class XUSB companion gets the WGI admission it needs without descriptor mutation. See [XUSB Companion](../reference/xusb-companion.md) and [Cross-API Coverage](../reference/cross-api-coverage.md). |
| **driverMode** | Profile-level field. `"xinputhid"` = the profile binds Microsoft's xinputhid kernel filter for native XInput + 16-button synthesis (Xbox Series BT, Xbox One BT, Xbox Elite v2 BT). `null` (default) = plain HID via `mshidumdf`. The choice of `driverMode` plus `vid == 0x045E` selects which of the three architecture groups the profile lands in. |
| **Profile** | A JSON file in `profiles/<vendor>/<slug>.json` describing one real-world controller's identity (VID, PID, product string, manufacturer string) and HID characteristics (descriptor, input report size, trigger mode, connection). 231 ship in the embedded catalog. Every controller HIDMaestro creates is parameterized by exactly one profile. |
| **HMContext** | The SDK's process-wide entry point. Owns the loaded profile catalog, the per-controller index allocator, and the lifecycle of every `HMController` it creates. One per consuming process. |
| **HMController** | A live virtual controller. Created by `HMContext.CreateController(profile)`. Two channels: input (consumer pushes `HMGamepadState` via `SubmitState`) and output (SDK raises `OutputReceived` for rumble/haptics/FFB). Dispose to remove the device. |
| **HMProfile** | An immutable handle to a profile (catalog or runtime-built). Carries identity, descriptor bytes, parsed layout (axis count, button count, hat presence). Can be cloned via `HMProfileBuilder.FromProfile`. |
| **HMGamepadState** | The abstract input frame: sticks `[-1..+1]`, triggers `[0..1]`, buttons bitmask, hat enum (or higher-resolution `HatDegrees` / `HatHundredths` / `HatRaw`). The SDK encodes into the active profile's HID descriptor. |
| **HMOutputPacket** | One captured output report from a host application targeting a virtual. Carries `Source` (HidOutput / HidFeature / XInput), `ReportId`, `Data`, and a monotonic `SeqNo`. Decoded per-profile by the consumer. |
| **HMOemNameOverride** | The static API for overriding the `joy.cpl` / DirectInput OEM-name label for a given VID:PID. Crash-safe via `HKLM\SOFTWARE\HIDMaestroOemOverrides`. |
| **HMDeviceExtractor** | The static API for reading HID descriptors back out of currently-connected physical devices. Used by `HIDMaestroProfileExtractor.exe` and consumers that want a "scan for devices" UI. No admin needed. |

## PnP / device-tree

| Term | Meaning |
|------|---------|
| **PnP** | Plug and Play. Windows' device-tree subsystem. Every devnode has an InstanceId, ContainerID, hardware IDs, compatible IDs, and a stack of upper/lower filter drivers. |
| **Devnode** | One entry in the PnP tree. Identified by `<EnumeratorPrefix>\<Suffix>`, e.g. `ROOT\VID_045E&PID_028E&IG_00\0000` or `SWD\HIDMAESTRO\A7B4_0002`. |
| **DriverStore** | `C:\Windows\System32\DriverStore\FileRepository\`. Where `pnputil` caches every installed driver package. Survives uninstall &mdash; budget for ~40 MB per HIDMaestro version churn on dev machines. |
| **ContainerID** | A devnode property (`DEVPKEY_Device_ContainerId`) grouping multiple devnodes that belong to the same physical device. Two devnodes sharing a ContainerID dedupe in WGI / Settings / `xinput1_4.dll`. HIDMaestro's main HID device and its XUSB companion share `{48494430-4D41-4553-5452-4F00...<idx>}` so they appear as one logical controller. |
| **Null-sentinel ContainerID** | `{00000000-0000-0000-FFFF-FFFFFFFFFFFF}`. Windows assigns this to ROOT-enumerated devnodes when the creator doesn't provide one. Triggers the bit-2 path in `xinput1_4!FUN_18000de2c` that skips XInput slot 0 &mdash; the bug behind the historical "slot 1 is empty" symptom. The SWD migration assigns explicit non-sentinel ContainerIDs to bypass this branch. See [SwDevice and PnP](../reference/swdevice-and-pnp.md). |
| **SWD** | "Software Device". The PnP enumerator name for devices created via the modern `SwDeviceCreate` API in `cfgmgr32.dll`. Devices appear at `HKLM\SYSTEM\CurrentControlSet\Enum\SWD\<enumerator>\<suffix>`. SwDevice lets the creator specify an explicit `pContainerId`, which is the linchpin of the slot-1-skip fix. |
| **SWDeviceLifetimeParentPresent** | The SwDevice lifetime flag that keeps the device alive as long as its PnP parent is present (i.e. across process exit). HIDMaestro uses this so a virtual outlives the creating SDK process and can be cleanly removed via `DIF_REMOVE` later. The only documented teardown path is to re-`SwDeviceCreate` with identical args (returns a fresh handle), downgrade lifetime to `Handle`, then `SwDeviceClose`. |
| **DIF_REMOVE** | The SetupAPI device-installation function code that removes a devnode. Used by HIDMaestro for non-SwD devices and as a fallback for survivors after SwD parent close. |
| **CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED** | The PnP notification kind fired when a devnode is fully gone (not just handle-closed). HIDMaestro blocks on this in v1.3.1's removal ordering so the caller knows the kernel has propagated the cascade, not just that `SwDeviceClose` returned. |
| **Phantom devnode** | A registry entry under `HKLM\SYSTEM\CurrentControlSet\Enum\SWD\<...>` with no live devnode. Cosmetic registry residue from `SWDeviceLifetimeParentPresent` cleanup; ignored by every consumer-visible API including XInput slot allocation. The regression battery treats them as PASS. |
| **Sticky reuse-fast-path** | Windows PnP behavior on Win11 26100/26200: a `SwDeviceCreate` call with an `(enumerator + instanceId + ContainerId)` tuple identical to a prior same-boot call takes a fast path that creates an empty devnode shell (no Service / Driver bound, no interface class) and returns S_OK. The session-unique instance-ID suffix bypasses this. See [SwDevice and PnP](../reference/swdevice-and-pnp.md). |
| **&IG_** | "Interface Group" marker substring in Xbox device paths (e.g. `VID_045E&PID_028E&IG_00`). Chromium's RawInput backend skips devices with `&IG_` in the path; HIDAPI skips them too (XInput handles them). SDL3 falls through to its RawInput backend for these and maps by VID/PID anyway. One substring controls three different detection paths. |
| **BTHLEDEVICE** | The CompatibleIDs string Windows assigns to Bluetooth Low Energy HID devices. HIDAPI checks for it to set `bus_type = BT`. HIDMaestro spoofs this from user mode for BT-mode profiles so SDL3's BT-specific parsing path activates. No real Bluetooth hardware is required. |

## Build / signing

| Term | Meaning |
|------|---------|
| **Inf2Cat** | Microsoft tool that generates a `.cat` catalog file containing hashes of every file the INF references. Required for INF + binary signature validation. Shipped in the SDK's embedded payload from the WDK (`%WindowsSDKDir%\bin\<sdk-ver>\x64\Inf2Cat.exe`). |
| **signtool** | Microsoft Authenticode signing tool. Signs the catalog and binaries with the per-machine self-signed certificate. Shipped in the SDK's embedded payload. |
| **TrustedPublisher** | The Windows certificate store that lets a self-signed driver install without prompting "Windows can't verify the publisher". HIDMaestro adds its self-signed cert here on first install. |
| **EV certificate** | An "Extended Validation" code-signing certificate. Required by Windows for drivers signed for kernel mode. Costs $300+/year; project-fatal for hobbyists. **Not** required for HIDMaestro &mdash; UMDF2 + self-signed + TrustedPublisher trust path is sufficient. |
| **WHQL** | Windows Hardware Quality Labs. Microsoft's driver certification process. **Not** required for HIDMaestro. UMDF2 + self-signed lets the consumer's machine trust the cert without crossing the WHQL boundary. |
| **`bcdedit /set testsigning`** | The Windows boot flag that disables driver signature enforcement. **Not** required for HIDMaestro &mdash; the trusted self-signed cert is enough. Mentioned because every other "no EV cert" project on Windows requires it; HIDMaestro is the exception. |

## Other

| Term | Meaning |
|------|---------|
| **GIP** | Gaming Input Protocol. Microsoft's modern Xbox controller protocol. The 14-byte GIP-format buffer the SDK writes into shared memory carries Xbox 360-compatible state for the XUSB companion to translate into `IOCTL_XUSB_GET_STATE` responses. |
| **Vx / Vy** | HID velocity usages (Generic Desktop Page 0x01, Usages 0x40 and 0x41 per HID Usage Tables 1.5 §4 &mdash; [usb.org/document-library](https://www.usb.org/document-library)). Used by HIDMaestro to carry separate trigger values without DirectInput recognizing them as axes. DirectInput sees 5 axes; Microsoft GameInput / WGI enumerate Vx/Vy as additional axes via the `GameInput\Devices` registry mapping and read separate triggers from them. |
| **EBI** | Effect Block Index. HID PID 1.0 §5.5 &mdash; the 1-byte handle the device assigns to a Create New Effect request. The SDK's PID State shared section carries an `EbiAllocBitmap` (32-bit; 32 simultaneous effects) and the driver atomically allocates from it inside the `SetFeature(0x11)` IOCTL handler so DirectInput's follow-up `GetFeature(0x12 Block Load)` reads consistent state. Mirrors vJoy's `Ffb_GetNextFreeEffect`. |
| **Seqlock** | A reader-writer synchronization protocol. Writer increments a sequence number, writes data, increments sequence number again. Reader samples seqno before and after; mismatch = retry. HIDMaestro uses this for the input shared-memory channel and the PID state mirror. Writer is single-threaded; reader is single-threaded; no kernel synchronization primitive in the hot path. |
| **MultiPadTester** | Nefarius's recommended XInput / WGI multi-slot tester. Canonical tool for HIDMaestro multi-controller validation. Updated upstream (per `nefarius/MultiPadTester#15`) to remove the historical 4-slot WGI cap; if a user reports only 4 slots, ask them to update first. |

## See also

- [Architecture Overview](../reference/architecture-overview.md) &mdash; how all of the above pieces fit together.
- [Cross-API Coverage](../reference/cross-api-coverage.md) &mdash; which terms apply at which downstream consumer.
- [Profile System](../profiles/profile-system.md) &mdash; how `driverMode`, `connection`, and VID determine the runtime path.
