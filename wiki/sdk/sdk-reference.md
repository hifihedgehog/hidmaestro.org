# SDK Reference

The full public surface of `HIDMaestro.Core.dll`. Five primary types: `HMContext` (process-wide entry point), `HMController` (live virtual device), `HMProfile` (immutable profile handle), `HMProfileBuilder` (custom-profile builder), and `HMGamepadState` (abstract input frame). Plus `HidDescriptorBuilder`, `HMDeviceExtractor`, `HMOemNameOverride`, the PID FFB output types, the port types of devices that carry several controllers, `HMBuildInfo`, and the SDK's exceptions.

This page documents every method's contract, thread safety, throw conditions, and the underlying mechanics that affect when you'd call which.

The deep-dive subjects each get their own page:

- [HID Descriptor Builder](hid-descriptor-builder.md): `HidDescriptorBuilder` API.
- [Force Feedback](force-feedback.md): `PublishPidPool` / `PublishPidBlockLoad` / `PublishPidState` / `GetCurrentPidBlockLoad`.
- [Output Passthrough](output-passthrough.md): `OutputReceived` event, `HMOutputPacket`, `HMOutputSource`.
- [OEM Name Override](oem-name-override.md): `HMOemNameOverride.Set` / `Clear` / `RecoverOrphans` / `ListActive`.
- [Wii U GameCube Adapter](gamecube-adapter.md): `HMController.Ports`, `DeviceProtocol` and `BindWinUsb` on a four-port adapter.
- [Programs Side by Side](programs-side-by-side.md): what programs that embed HIDMaestro on one machine can expect of each other.
- [Custom Profiles](../profiles/custom-profiles.md): the `HMProfileBuilder` patterns.
- [Profile Extractor](../profiles/profile-extractor.md): `HMDeviceExtractor` API used by the GUI tool.

---

## HMContext

The SDK's process-wide entry point. One per consuming application. Owns the loaded profile catalog, the per-controller index allocator, and the lifecycle of every `HMController` it creates.

```csharp
public sealed class HMContext : IDisposable
{
    public HMContext();
}
```

### Lifecycle

- Construct one at app startup. Disposing the context disposes every controller it owns.
- The constructor is non-blocking. It kicks off three background prewarm tasks (staging the driver payload when a deploy is coming, profile catalog parse, GameInput service warm-up) so the first `InstallDriver` / `LoadDefaultProfiles` / `CreateController` call hides 200-500 ms of cold-start cost in the consumer's think-time budget. Failures are silently swallowed, and the foreground call retries.
- Multiple contexts in one process work. Each numbers its own slots, and transport indices and identities are claimed machine-wide, so two contexts never collide. There is no good reason to create more than one.

### Driver lifecycle

```csharp
public bool IsDriverInstalled { get; }
public void InstallDriver();
public HMDriverInstallOutcome? LastDriverInstall { get; }

public static void RemoveAllVirtualControllers();
public static void RemoveAllVirtualControllers(bool preserveInstall);
public static void RemoveAllVirtualControllers(HMCleanupScope scope, bool preserveInstall);
```

`IsDriverInstalled` is true when both HIDMaestro driver packages, `hidmaestro.inf` and `hidmaestro_xusb.inf`, are in the driver store, whatever their version. Does not require admin. When the driver store cannot be read, as when the pnputil listing fails, it answers false, logs why and lets `InstallDriver` report the failure. It throws only `ObjectDisposedException`. The internal `DriverBuilder.IsDriverInstalled()` throws `InvalidOperationException` on a failed listing, where it returned false.

`InstallDriver` first removes the controllers of programs that exited without removing theirs, then deploys. It stages the embedded driver files under `%ProgramFiles%\HIDMaestro\Staging`, in a directory only Administrators and SYSTEM can write, checks each against its embedded SHA-256, installs the self-signed code-signing certificate, signs the binaries and registers them with `pnputil`. When the installed driver is this build's, it returns after the sweep without deploying. The first of `InstallDriver`, the first create and `RemoveAllVirtualControllers()` in a process also starts the once-per-process phantom cleanup on a background thread, which the call does not wait for (see [Programs Side by Side](programs-side-by-side.md#exit-and-the-phantom-cleanup)). **Requires admin** (`UnauthorizedAccessException` if not elevated), except that a process that is not elevated and finds this build's driver installed gets `AlreadyCurrent`, with no sweep. Throws `InvalidOperationException` if a signing or `pnputil` step fails, and `HMPayloadMissingException` in a build that carries no driver for the machine's architecture. See [Driver Install and Signing](../reference/driver-install-and-signing.md) for the full sequence.

As of v2.0.0 several programs that embed HIDMaestro can share one machine, so a deploy decides which driver the machine runs. Deploys take the machine-wide deploy lock, `HIDMaestro.Admin\Deploy`, a mutex in a namespace only elevated programs can open, so of two programs calling `InstallDriver` at once, one deploys and the other finds the result current. `LastDriverInstall` reports what the last call on this context did:

| `HMDriverInstallOutcome` | Meaning |
|---|---|
| `AlreadyCurrent` | The installed driver is this SDK's. Nothing changed. |
| `Installed` | No driver was installed and this SDK installed its own, or this SDK's driver was installed with one of its two packages missing and the missing one was added. |
| `Upgraded` | An older driver was installed, from 1.x or an older 2.0.0 build. With nothing on it, this SDK deployed in full and removed the old packages. With devices or a create of another program on it, this SDK added its packages beside the old ones and updated no present device. |
| `KeptNewer` | A newer driver is installed. A driver is never downgraded, and this SDK runs on the newer one. |

The 2.0.0 driver takes precedence over every older one, and nothing is refused because another program's devices hold an older driver. Programs built on HIDMaestro 1.x must move to 2.0.0: see [Moving from 1.x](../start/migration.md).

`RemoveAllVirtualControllers` is static and instance-free, and **requires admin**. Without a scope, which is `HMCleanupScope.Orphaned`, it removes the controllers of programs that exited without removing theirs. With `preserveInstall` false it then removes the driver packages, the WinUSB packages no devnode uses and `HKLM\SOFTWARE\HIDMaestro`, but only when no HIDMaestro device is present, no other program that embeds HIDMaestro runs, and the caller has no controller. A running program with no controllers still keeps the packages. In a process that is not elevated both overloads return without doing anything. A running program's controllers, the caller's own included, are never touched. Dispose a controller to remove it. Both overloads also remove the GameInput tables HIDMaestro wrote through v1.11.0 where no running program uses them: a table stays while a present device or any `Controller<N>` configuration carries its VID and PID, and every table stays while an input section that nothing explains shows a v1.11.0 create in flight. They no longer remove phantom records on every call. The first of them, unless `InstallDriver` or a create came first, starts the once-per-process phantom cleanup, and a later call removes no phantom. With `preserveInstall` true the driver packages and `HKLM\SOFTWARE\HIDMaestro` stay, which keeps the next `InstallDriver` on its fast path. Use that from a program's own launch or exit sweep.

`HMCleanupScope.Everything` removes every HIDMaestro controller and USB/IP import on the machine, whoever made it and whether or not that program still runs. That is the remove-everything cleanup every release before v2.0.0 did, and what an uninstall, a test harness or a support tool wants. `HIDMaestroTest cleanup` calls it with `preserveInstall: false`. With that, it then removes the driver packages and `HKLM\SOFTWARE\HIDMaestro` with no check for other programs or the caller's controllers. A controller the calling program still holds is left with no device: its submits and PID calls return and reach nothing, its output events stop, `DriverVersion` is null, `DeliversEveryReport` and `ReleasesOnConsumerExit` are false, and a keyboard or mouse submit no longer waits for delivery. It keeps its transport index and sections until disposed, so dispose it after the sweep. Another running program's controllers lose their devices too, but keep reading the removed driver's state: their `DriverVersion` names it, `DeliversEveryReport` and `ReleasesOnConsumerExit` stay true, their keyboard and mouse submits wait up to 200 ms on each of the next three frames, and a protocol controller's next send waits up to 200 ms for the reply the device never delivered.

A program that exits normally without disposing its controllers has their devices removed as it exits. The SDK's exit handler waits at most 10 seconds for the phantom cleanup and a create in flight, then removes the devices to the end, as `Dispose` does. When that wait runs out, or a device does not leave, the devices stay until the next sweep of any program on v2.0.0 or later, as a killed program's do. See [Programs Side by Side](programs-side-by-side.md#exit-and-the-phantom-cleanup).

A context dropped without `Dispose` keeps its controllers, their transport indices and their identity keys until the process exits. A create of one of those keys in that process throws `HMResourceInUseException` until then, and the message says so.

### Profile catalog

```csharp
public IReadOnlyList<HMProfile> AllProfiles { get; }
public HMProfile? GetProfile(string id);
public int LoadDefaultProfiles();
public int LoadProfilesFromDirectory(string profilesDir);
public IReadOnlyList<HMProfileLoadIssue> ProfileLoadIssues { get; }   // v2.0.0
```

`AllProfiles` returns every profile loaded into this context, sorted by stable ID. Empty until you call one of the `LoadProfiles*` methods.

`GetProfile(id)` looks up by stable ID slug (e.g. `"xbox-360-wired"`, `"dualsense"`, `"thrustmaster-t300rs"`). Returns null if no such profile is loaded. Case-insensitive.

`LoadDefaultProfiles` loads the embedded catalog (337 entries shipping inside `HIDMaestro.Core.dll`) and returns the count added. An id already loaded refuses the later file.

`LoadProfilesFromDirectory(path)` loads `*.json` from a directory matching the [Profile System](../profiles/profile-system.md) schema. Useful for shipping a curated subset, or for hot-loading runtime-modified profiles. Schema validation files (`schema.json`) are skipped, and so is a `models` folder at the directory's top, which holds named device models and identity defaults for the directory's profiles (see [Device models](../profiles/profile-system.md#device-models-v200)). Files load recursively, in ordinal path order. Does not auto-load the embedded catalog: call both if you want catalog + custom.

As of v2.0.0 profiles load strictly, and no load throws for a file's content. A file that does not parse, a key the schema lacks, a key written twice, a value a check refuses, a removed spelling or an id already loaded refuses the file, and `ProfileLoadIssues` lists it:

```csharp
public sealed class HMProfileLoadIssue
{
    public string File { get; }
    public string? ProfileId { get; }
    public string JsonPath { get; }       // such as "$.protocol.rules[3].reply[1].length"
    public string Reason { get; }
    public HMProfileLoadIssueKind Kind { get; }   // Refused, NotAProfile, ModelProblem
}
```

`NotAProfile` is a file with no `id`. `ModelProblem` is a profile that loaded with a device model problem, which `HMProfile.DeviceModelProblem` also states. Check `ProfileLoadIssues` after a load to see why a profile is missing.

### Controller lifecycle

```csharp
public HMController CreateController(HMProfile profile);
public HMController CreateController(HMProfile profile, string? identityKey);
public HMController CreateControllerAt(int index, HMProfile profile);
public HMController CreateControllerAt(int index, HMProfile profile, string? identityKey);
public IReadOnlyCollection<HMController> ActiveControllers { get; }

public void DisposeControllersInParallel(
    IEnumerable<HMController> controllers,
    Action<HMController, long>? perControllerCallback = null);

public void FinalizeNames();
```

`CreateController(profile)` takes the lowest slot free in this context (linear scan from 0) and a machine-wide transport index and identity, then runs the per-archetype `SetupController` orchestration (registry write &rarr; `pnputil /add-driver` if needed &rarr; SwDevice or SetupAPI device creation &rarr; PnP wait &rarr; XInput slot-claim wait), and returns once the device is fully bound and ready to receive input. **Requires admin.**

Throws:

- `ArgumentNullException` if `profile` is null.
- `HMResourceInUseException` when a live controller anywhere on the machine, in this program or another, holds the identity key, or when no transport index is free. It derives from `InvalidOperationException`. For an identity key a v2.0.0 or later program holds, it names that program. See [Exceptions](#exceptions-v200) for the other cases.
- `HMPayloadMissingException` when this build lacks what the profile runs on: the UMDF2 driver, or the USB/IP transport for a composite persona. Thrown before any machine-wide step.
- `HMProfileException` (v2.0.0) for every defect of the profile itself, before any machine-wide step: no descriptor, a descriptor hex string that is not whole hex bytes, a layout that does not fit the descriptor, and a device model that does not compile. It derives from `InvalidOperationException` and names the profile, its file, the JSON path and the reason. It replaces the `ArgumentException` a profile with no descriptor threw and the `HMLayoutValidationException` a layout threw, which a create no longer throws.
- `HMDriverVersionException` (v2.0.0) once the device has started, when its driver does not serve this SDK's protocol 4 or could not read a value the create wrote. The create removes its device first. See [Exceptions](#exceptions-v200).
- `InvalidOperationException` if device-node creation fails or the driver install fails, and when the driver fails the device's start, within one 25 ms poll, naming the device and its problem code. As of v2.0.0 a failed start waits while Windows has a device installation pending, unless the driver set its error word, since a device Windows flagged for reinstall fails its start until the queued install restarts it. A wait that runs out fails the create on any problem the device shows. A create that fails after its device exists removes that device by its instance ID. As of v2.0.0 also when another program holds the machine-wide PnP lock for ten minutes, when the device's prior life is still there after its removal, when the wait for Windows' pending installs fails, when what the registration gate removed comes back three times, and when a gamepad or XUSB companion is not made, where the create used to succeed without it. See [Registrations and removals](programs-side-by-side.md#registrations-and-removals).

A create waits up to 30 seconds for Windows' pending device installs before it registers a devnode, through `CMP_WaitNoPendingInstallEvents`. Learn says not to call that function "while processing any events inside of a system-initiated callback function that is expected to return within a short amount of time", which includes a service's `ServiceMain` and its control handler ([CM_WaitNoPendingInstallEvents](https://learn.microsoft.com/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_waitnopendinginstallevents)), so a service should not call `CreateController` from either.

The returned `HMController` is live. Dispose it to remove the device, or dispose the entire context to remove all controllers it owns.

`CreateControllerAt(index, profile)` is the same except it pins to a slot of this context. Used by live profile-switch workflows where you want to dispose the controller at slot N and replace it with a different profile while keeping N stable. Throws `InvalidOperationException` if the slot is in use, and `ArgumentOutOfRangeException` for a negative index. The transport index is N when no other program on the machine uses N, and otherwise the lowest free index, from 64 while a program built on v1.12.0 runs (see [`TransportIndex`](#transport-index-and-driver-version-v200)).

#### Identity keys (v1.8.0)

The `identityKey` overloads give the controller a durable identity. Every device path, the ContainerId and, for a USB/IP persona, the USB serial derive from the key, so a controller created again with the same key comes back at the same paths after a dispose, a process restart, a reboot or a driver upgrade. Programs that store a binding against a device path (SDL joystick path, RawInput name, GameInput device path) or a USB serial (Steam's per-controller configuration) keep it across those lives.

Name the controller the way your program thinks of it, such as a slot number plus a profile id:

```csharp
using var pad = ctx.CreateController(profile, "slot0:" + profile.Id);
```

Rules:

- A null, empty or blank key uses the transport index (`index:<N>`), which is what the one-argument overloads do. `HMController.IdentityKey` reports the effective key. The form `index:<N>` is reserved for that default: it names the identity of index N wherever it is passed. While a program built on v1.12.0 runs, a create with `index:<N>` and N below 64 takes that identity as asked, on a transport index from 64. That program gives the same identity to its own controller on index N, and its next create there replaces a devnode of that name.
- Keys are trimmed and case-sensitive. As of v2.0.0 one identity is held by one live controller on the whole machine, in whichever program created it. A second create with a held key throws `HMResourceInUseException`, and does no PnP work, so the holder's devices stay as they were. The exception names a holder on v2.0.0 or later. A v1.12.0 holder is named only as a running program built on HIDMaestro 1.12.0. While no live record lists the key, the create first waits up to 120 seconds for the claim, since another program's sweep holds it while it removes a dead program's device of that identity.
- A keyless controller's transport index, and so its default identity, can differ between runs when other programs that embed HIDMaestro are running. Pass a key for paths that must stay put. When another program's sweep holds the identity of the chosen index, a keyless create waits up to 120 seconds for it, as a keyed create does, and keeps its index.
- A different profile at the same key keeps the identity and refreshes the descriptor.
- DirectInput's instance GUID is DirectInput's own per-VID/PID ordinal and is not derived from the key; it moves when a same-VID/PID pad in front of it leaves.

The per-family mechanism is in [SwDevice and PnP](../reference/swdevice-and-pnp.md#stable-device-identity).

`ActiveControllers` returns a snapshot of every live controller this context owns. Order is creation order.

`DisposeControllersInParallel(controllers, perCallback)` disposes a set of controllers from parallel threads, with the per-controller HID orphan sweep suppressed and run once at the end. Every devnode removal holds the machine-wide PnP lock, so the removals run one after another and the batch takes about the sum of the controllers' removals. Use from any caller that already has a list to dispose together (e.g. a test harness's end-of-run cleanup, a consumer's app exit). The per-controller wall-clock for each `Dispose` call is reported via the optional callback, and includes the time that controller's removals waited behind the others'. A callback that throws stops nothing: every controller is disposed, the orphan sweep runs, and the exceptions come out afterward in one `AggregateException`, with one controller as with many (v2.0.0). Single-element or empty inputs degrade to plain serial dispose. Internal context disposal uses an equivalent path.

`FinalizeNames` re-applies friendly names to every live controller. Call **once after creating ALL controllers**: there is a Windows PnP race where the first controller's friendly name gets overwritten by the second controller's driver-bind activity. Re-applying after PnP has settled makes the writes stick. Polls each HID child for `DN_STARTED` (driver fully bound) before re-applying; on fast machines exits in <100 ms, on slow machines adapts up to 5 s.

### Disposal

```csharp
public void Dispose();
```

Disposes every live `HMController`, runs a final orphan sweep, and tears down the prewarm threads. Idempotent. With several controllers it takes about the sum of their removals, which run one at a time under the PnP lock.

---

## HMController

A live virtual controller. Created by `HMContext.CreateController`; dispose to remove the device. Two channels: input (consumer pushes state) and output (SDK raises rumble/haptics/FFB events).

```csharp
public sealed class HMController : IDisposable
{
    public HMProfile Profile { get; }
}
```

### Transport index and driver version (v2.0.0)

```csharp
public int TransportIndex { get; }
public IReadOnlyList<string> SectionNames { get; }
public Version? DriverVersion { get; }
```

`TransportIndex` is the machine-wide index the controller's shared sections, events, owner pipe and registry key are named with, and the `ControllerIndex` the driver reads. A program running alone gets its slot number here, as every release before v2.0.0 did. When another program on the machine already uses that index, the controller gets the lowest free one, so the value can differ between runs. While a program built on v1.12.0 runs, the search starts at 64: slot 0 on 64, slot 1 on 65. A keyless controller's identity, paths and container id, every controller's HID serial and MAC bytes, a byte of the XUSB capabilities, the USB/IP bus id and a keyless composite's USB serial and instance id move with the index. A keyed controller keeps its paths and container id. A program restarted after a crash gets its old index back only when it is 64 or more. See [Programs Side by Side](programs-side-by-side.md#transport-index).

`SectionNames` lists the kernel object names of the controller's shared-memory contract: `Global\HIDMaestroInput<N>`, `InputEvent`, `CompanionInputEvent`, `InputAck`, `InputAckEvent`, `Output`, `OutputEvent`, `PidState` and `Version`, each with the same `Global\HIDMaestro` prefix and `<N>` suffix, then the owner pipe `\\.\pipe\HIDMaestroOwner<N>`. A create makes the owner pipe first, before any section. When a v1.12.0 program started on the same index meanwhile, the create is refused there, and nothing of that program's is written over. Native writers that open the sections themselves read the names here rather than assuming N is the slot. See [Shared Memory Protocol](../reference/shared-memory-protocol.md).

`DriverVersion` is the version of the HIDMaestro driver the controller runs on, as the driver reports it in `Global\HIDMaestroVersion<N>`. It is null until the driver has started the device, on a driver older than v2.0.0, which reports none, and on a composite persona, which runs on the USB/IP transport.

### Input

```csharp
public void SubmitState(in HMGamepadState state);
public void SubmitRawReport(ReadOnlySpan<byte> report);
```

`SubmitState` translates the abstract `HMGamepadState` into the active profile's HID report layout and writes it to shared memory. Cadence is set by the consumer: there is no internal pump thread. Typical rates: 1000 Hz for high-fidelity input passthrough (PadForge), 250 Hz for bench testing, 8 Hz for a profile that's only sending the occasional button event.

For a profile with an XUSB companion (`"xinput": {"via": "xusbCompanion"}`), the same call also packs a 14-byte GIP-format buffer for the companion to read on `IOCTL_XUSB_GET_STATE`. Every other profile skips this packing entirely (~60-80 instructions per frame saved).

`SubmitRawReport(report)` pushes a raw HID input report for data `HMGamepadState` doesn't model, such as vendor extensions. Pass **data bytes only**: do NOT include a Report ID prefix. The driver prepends the Report ID automatically. For profiles with no Report ID, pass the full report as-is. As of v2.0.0 that report is the one the SDK tells the driver: the descriptor's first input report with game pad fields, a keyboard's or mouse's first input report, or the profile's `dataReportId`, at the profile's `inputReportSize` when it sets one. See [The report a data frame fills](../profiles/profile-system.md#the-report-a-data-frame-fills-v200).

Throws `ArgumentException` if `report` is empty or exceeds the 256-byte shared-section payload capacity. A device that builds its own reports (`HMProfile.BuildsItsOwnReports`: `switch-pro`, `switch-pro-usb`, `dualshock-3-full` and `switch2-pro-controller-composite`) takes `SubmitRawReport` and `SubmitRawExtendedReport` as its state block, verbatim and of the state block's size, and throws `ArgumentException` naming the size for any other length. Which report it sends, and when, belongs to the device. See [Switch 2 Pro with Motion](switch2-pro.md).

The output of either method becomes visible through every downstream API simultaneously: `XInputGetState`, `joy.cpl`, browser Gamepad, SDL3, WGI. See [Cross-API Coverage](../reference/cross-api-coverage.md) for the per-API translation.

### Keyboards and mice (v1.12.0)

```csharp
public void SubmitMouse(in HMMouseState state);
public void SubmitKeyboard(HMKeyModifiers modifiers, ReadOnlySpan<HMKey> keys);
public void SubmitConsumer(ReadOnlySpan<ushort> usages);

public bool DeliversEveryReport { get; }
public bool ReleasesOnConsumerExit { get; }
public HMKeyboardLeds? KeyboardLeds { get; }
public event Action<HMController, HMKeyboardLeds>? KeyboardLedsChanged;
```

Each submit method packs into the reports the profile's descriptor declares and throws `InvalidOperationException` when the descriptor has no collection of its kind. `HMMouseState` holds `Buttons` (`HMMouseButtons`, `Left` to `Button16`), `X`, `Y`, `Wheel` and `Pan`. `X` and `Y` are counts on a relative pointer and a position inside the field's range on an absolute one. `SubmitKeyboard` takes the modifiers (`HMKeyModifiers`) and every key held, by HID usage (`HMKey`). An empty span releases them, and more keys than the report holds report ErrorRollOver. `SubmitConsumer` takes Consumer-page usages, such as 0x00E9 Volume Increment.

On a keyboard or mouse, `DeliversEveryReport` is true and each submit returns once the previous report has been delivered, at most one report per millisecond. `ReleasesOnConsumerExit` is true when the driver lets go of every held key and button if the process ends without disposing. `KeyboardLeds` holds the LED state Windows last sent, and `KeyboardLedsChanged` raises each change. See [Keyboards and Mice](keyboards-and-mice.md).

### Ports, device protocols and WinUSB (v2.0.0)

```csharp
public HMPortSet Ports { get; }
public HMDeviceProtocol? DeviceProtocol { get; }
public HMWinUsbBinding BindWinUsb();
```

`Ports` holds the controller ports of a device that carries several controllers in one report, as the profile's `extendedReport.ports` declares them. It is empty for a profile with one controller. On a device with ports, `SubmitState` submits to port 1. See [HMPortSet and HMPort](#hmportset-and-hmport-v200).

`DeviceProtocol` is set for a USB/IP device whose profile declares a `protocol`, and null otherwise. See [HMDeviceProtocol](#hmdeviceprotocol-v200).

`BindWinUsb` binds WinUSB to this controller's virtual USB/IP device so libusb hosts such as Dolphin can open it, for a profile that declares `usbConfiguration.winUsb`. Nothing the device reports changes, and the driver goes on this device's devnode alone. The binding is recorded. When usbip-win2 imports the device again after a dropped connection, the binding moves to the devnode it came back on.

A restore never changes the driver of a present devnode, so a device that sits on the devnode keeps WinUSB after the controller is disposed or its program ends. Once the devnode is gone, it is marked to install by rank at its next arrival by the first of these: a HIDMaestro program disposing a controller, its cleanup, its reclaim of the controllers of a program that has ended, a binding that moves to the devnode a dropped adapter came back on, or the follow-up that watches the devnode for five minutes after its holder lets go. A real device of the same serial that takes the instance while the virtual one is gone opens on WinUSB until it is unplugged. After a kill it can open on WinUSB again at its next plug-in, until a teardown, cleanup, reclaim, re-bind or follow-up finds the devnode gone and marks it. **Requires admin.** It returns:

| `HMWinUsbBinding` | Meaning |
|---|---|
| `Bound` | WinUSB is now bound to the virtual device. |
| `AlreadyBound` | The device already carried WinUSB, libusbK or libusb0, a driver libusb opens, for example from Zadig. Nothing changed. |
| `OtherDriver` | The device carries a driver from outside Windows, which this call leaves alone. Nothing changed. |

Throws `InvalidOperationException` when the profile runs on the UMDF2 driver or declares no `winUsb`, when the device does not appear within 10 s, when WinUSB does not start on the devnode within 10 s, when another program holds the machine-wide WinUSB lock for two minutes or the deploy lock for ten, and when no driver Windows has for the device ranks above the package, which would let Windows choose it for every real device of that kind. Throws `TimeoutException` when the registry ledger's lock, or v1.12.0's mutex beside it, stays held for 30 s, scaled by `HIDMAESTRO_TIMEOUT_SCALE`, and `ObjectDisposedException` when the controller is disposed while the call waits. See [Wii U GameCube Adapter](gamecube-adapter.md).

### Output (rumble / haptics / FFB / LEDs)

```csharp
public event Action<HMController, HMOutputPacket>? OutputReceived;
```

Raised on the SDK's output-polling thread (~125 Hz, ~8 ms cadence) whenever a host application sends a rumble, haptic, FFB, feature, or LED command to this virtual. Multiple invocations per poll iteration are normal (DirectInput PID FFB writes Set Effect &rarr; Set Constant Force &rarr; Effect Operation Start within 1-3 ms; the ring buffer drains all three on the next poll).

Handlers run on the polling thread, **not the consumer's UI thread**. Marshal back to UI thread if needed. Keep handlers cheap: the ring buffer holds 64 slots × 256-byte payload; if a reader stalls past ~512 ms while the producer is bursting, the oldest packets get overwritten.

`HMOutputPacket` carries `Source` (HidOutput / HidFeature / XInput), `ReportId`, `Data` (a `ReadOnlyMemory<byte>` over the SDK's reusable buffer: copy if you need it past the handler return), and a monotonic `SeqNo`.

See [Output Passthrough](output-passthrough.md) for the wire format and consumer-side decoding patterns.

### Output (parsed-field, v1.3.5+)

```csharp
public event EventHandler<HMOutputDecodedEventArgs>? OutputDecoded;

public sealed class HMOutputDecodedEventArgs : EventArgs
{
    public byte ReportId { get; init; }
    public IReadOnlyDictionary<string, object> Fields { get; init; }
    public ReadOnlyMemory<byte> RawBytes { get; init; }
    public bool CrcValid { get; init; }
}
```

Fires alongside `OutputReceived` whenever an inbound output report matches the profile's `extendedOutputReport.reportId`. `Fields` is keyed by the JSON spec's `semantic` names; values map to runtime types per the field type (see [Profile System](../profiles/profile-system.md) / [Output Passthrough](output-passthrough.md) for the type table).

Use `OutputDecoded` when the profile JSON describes the byte layout (Sony BT 0x31 in v1.3.5; future profiles by JSON addition only). Fall back to `OutputReceived` for raw bytes or for profiles without an `extendedOutputReport` block.

```csharp
ctrl.OutputDecoded += (_, e) =>
{
    if (e.Fields.TryGetValue("rightMotor", out var rm)) ApplyMotor((byte)rm);
    if (e.Fields.TryGetValue("lightbar",   out var rgb)
        && rgb is byte[] c) ApplyLightbar(c[0], c[1], c[2]);
};
```

The inverse direction, synthesizing parsed fields and encoding wire bytes, uses `HMOutputEncoder.Encode`:

```csharp
public static class HMOutputEncoder
{
    public static byte[] Encode(HMProfile profile, IReadOnlyDictionary<string, object> fields);
}
```

Returns the full on-wire report buffer including report ID at byte 0 and (if the spec declares a `crc32-le` field) the CRC32 footer. Throws `InvalidOperationException` if `profile.ExtendedOutputReport` is null.

### HID PID 1.0 force feedback

```csharp
public void PublishPidPool(ushort ramPoolSize, byte simultaneousEffectsMax,
                           bool deviceManagedPool, bool sharedParameterBlocks);
public void PublishPidBlockLoad(byte effectBlockIndex, PidLoadStatus loadStatus,
                                ushort ramPoolAvailable);
public void PublishPidState(byte effectBlockIndex, PidStateFlags flags);
public HMPidBlockLoad GetCurrentPidBlockLoad();
```

The four shared-section publish/read methods. The driver answers `HidD_GetFeature` for the canonical PID Report IDs (Pool 0x13, Block Load 0x12, State 0x14) directly from a per-controller shared state section the consumer fills via these methods.

`PublishPidPool` is the gate: until called at least once, the driver returns `STATUS_NO_SUCH_DEVICE` for the Pool Report so DirectInput cleanly concludes "device exists but no FFB" rather than retrying. First call enables FFB on this controller; subsequent calls update pool state.

`PublishPidBlockLoad` is now optional (v1.1.37+). The driver allocates EBIs synchronously inside its `SetFeature(0x11 Create New Effect)` IOCTL handler: the consumer reads the assigned EBI via `GetCurrentPidBlockLoad` rather than writes its own. Manual writes are still supported (overwrite the driver's allocation) but no longer needed for the canonical handshake.

`PublishPidState` reflects current device state for the most-recently-referenced effect: paused, actuators enabled, safety switch, effect playing, etc. Update on Effect Operation Start/Stop, Device Reset, Device Pause, or Actuators Enable/Disable.

The descriptor must declare the PID FFB block. Use `HidDescriptorBuilder.AddPidFfbBlock`: that method emits the canonical "minimum viable" block with exactly the right report-ID / collection / usage shape. Do **not** add additional Feature reports inside the same Application Collection; the four-feature variant from vJoy's reference descriptor causes `pid.dll` to AV. See [Force Feedback](force-feedback.md) for the full architecture.

### Disposal

```csharp
public void Dispose();
```

Removes the virtual device from PnP, frees the per-controller shared memory section, signals the output-polling thread to stop, and releases handles. Idempotent: safe to call multiple times. Called automatically when the owning `HMContext` is disposed.

As of v2.0.0 each devnode removal holds the machine-wide PnP lock from its call through its removal test, so a dispose waits while another program registers or removes a device. Called from the program's own `ProcessExit` handler, that wait comes out of one 10-second budget the process shares, and a controller it cuts short keeps its devices and its record entry for the SDK's exit handler or the next sweep. See [Registrations and removals](programs-side-by-side.md#registrations-and-removals).

The public `HIDMaestro.Internal` calls changed with it. `DeviceManager.WaitForDeviceRemoval(id, timeout)` waits for the DEVICEINSTANCEREMOVED notification of a devnode present at the call, up to 2 s past the devnode's leaving, where it returned once a locate failed. A HID child removed with its parent counts on the parent's notification. `DeviceManager.RemoveDevice` and `RemoveOrphanHidChildren` take the PnP lock, so they need an elevated process to touch a present devnode, and `RemoveDevice` throws `InvalidOperationException` with nothing removed when another program holds the lock for ten minutes.

---

## HMGamepadState

The abstract input frame.

```csharp
public struct HMGamepadState
{
    public Dictionary<HMAxis, float>? Axes;   // every analog input, keyed by HID usage

    public HMButton Buttons;                  // bitmask
    public HMHat Hat;                         // 8-direction enum

    public float?  HatDegrees;                // 0 = North, clockwise. [0, 360)
    public int?    HatHundredths;             // hundredths of a degree, 0..35999
    public ushort? HatRaw;                    // raw descriptor field value (LogicalMin..LogicalMax)

    // Sony-specific surface (touchpad, IMU, battery, button pressure) keeps
    // native representation. See HMGamepadState.cs for the full set of fields.
}
```

`Axes` is the single drive surface for every analog input (v1.3.9). Values are uniformly `[0.0, 1.0]`: 0.5 is centered for signed axes (sticks, twist rudders), 0.0 is released for unsigned axes (triggers, throttles, sliders, pedals). The SDK iterates each declared analog field in the active profile's descriptor, reads the dict by HID usage, and writes the report. Axes the consumer doesn't write default to centered (signed) or released (unsigned); axes the descriptor doesn't declare are silently ignored.

```csharp
// HOTAS with stick + slider + rudder + throttle, all in one dict
state.Axes = new Dictionary<HMAxis, float>
{
    [HMAxis.X]        = 0.55f,   // stick X, slightly right of center
    [HMAxis.Y]        = 0.35f,   // stick Y, slightly below center
    [HMAxis.Slider]   = 0.75f,   // throttle slider
    [HMAxis.Rudder]   = 0.25f,   // rudder pedal
    [HMAxis.Throttle] = 1.00f,   // secondary throttle full
};
```

Null `Axes` is the hot-path-cost-free idle case: the encoder's dict walk is gated on `axes != null && Count > 0`. Allocate the dict once in your input pump and reuse.

The Sony surface keeps native units. `GyroPitch`, `GyroYaw` and `GyroRoll` carry 16 counts per degree per second, and `AccelX`, `AccelY` and `AccelZ` carry 8192 per g. `SensorTimestamp` counts 1/3 µs ticks, microseconds times 3, the DualSense's own unit. The DualShock 4 profiles divide it by 16 into that pad's ticks and, while it is 0, stamp the time since the controller's first report instead. `TouchpadPacketCounter` fills the DualShock 4 touch report's packet-counter byte. `BatteryLevel` runs from 0 to 10.

Ten `Pressure*` fields (v1.10.0) carry how hard a DualShock 3's pressure-sensitive buttons are pressed, 0 to 255: `PressureA` (cross), `PressureB` (circle), `PressureX` (square), `PressureY` (triangle), `PressureLeftBumper`, `PressureRightBumper`, and the four `PressureDpad*` directions. A pressed button left at 0 is sent as 255. Only `dualshock-3-full` carries them. See [DualShock 3 and Pressure](dualshock-3.md).

Two pad pressure fields (v2.0.2), `TouchpadFinger0Pressure` and `TouchpadFinger1Pressure`, carry how hard each trackpad is pressed, 0 to 1, on the Steam Deck and the 2026 Steam Controller, whose two pads are finger 0 and finger 1. They follow the pressure buttons' rule: a touching finger left at 0 is sent at full pressure, so a consumer that only sends touch presses fully, and a nonzero pressure is sent as given. NaN reads as 0, and a value outside 0 to 1 is clamped.

Six calibrated motion fields carry SDL's sensor frame: `AccelGX`, `AccelGY` and `AccelGZ` in g, and `GyroDpsX`, `GyroDpsY` and `GyroDpsZ` in degrees per second. `switch-pro`, since v1.11.0 `switch2-pro-controller-composite`, and since v2.0.2 `steam-deck-composite`, `steam-controller-composite` and `steam-controller-2` read them and convert them to each device's own axes and counts, so a consumer that reads motion from SDL submits it as it reads it. See [Switch 2 Pro with Motion](switch2-pro.md).

For data `HMGamepadState` does not model, such as vendor extensions, use `SubmitRawReport` with bytes you assembled per the profile's descriptor.

### `HMGamepadStateHelpers.StandardAxes`: ergonomic 6-slot shortcut

Most consumers want the canonical `(LX, LY, RX, RY, LT, RT)` convention. The static helper resolves those into the active profile's actual axis keys (Sony's Z=right-stick, Rx=left-trigger axis map is honored automatically) and returns a fresh dict ready to assign to `state.Axes`.

```csharp
ctrl.SubmitState(new HMGamepadState
{
    Axes = HMGamepadStateHelpers.StandardAxes(ctrl.Profile,
        leftStickX: 0.5f, leftStickY: 0.5f,
        rightStickX: 0.5f, rightStickY: 0.5f,
        leftTrigger: 0.0f, rightTrigger: 0.0f),
    Buttons = HMButton.A,
    Hat = HMHat.North,
});
```

Use the helper for tests and demos. For 1000 Hz hot paths, allocate one `Dictionary<HMAxis, float>` and update entries directly by HMAxis key: same code path, no per-frame dict allocation. Discover which axes a profile exposes via `HMProfile.Sticks` / `HMProfile.Triggers` (variable-length lists derived from the layout's role tags) or `HMProfile.AvailableAxes` (every `HMAxis` the descriptor declares).

### `HMAxis` enum

```csharp
public enum HMAxis : ushort
{
    None = 0,

    // Generic Desktop (page 0x01): (page << 8 | usage)
    X = 0x0130, Y = 0x0131, Z = 0x0132, Rx = 0x0133, Ry = 0x0134, Rz = 0x0135,
    Slider = 0x0136, Dial = 0x0137, Wheel = 0x0138, Hat = 0x0139,
    Vx = 0x0140, Vy = 0x0141, Vz = 0x0142,
    Vbrx = 0x0143, Vbry = 0x0144, Vbrz = 0x0145, Vno = 0x0146,

    // Simulation Controls (page 0x02)
    Aileron = 0x02B0, AileronTrim = 0x02B1, AntiTorque = 0x02B2,
    CollectiveControl = 0x02B5, DiveBrake = 0x02B6,
    Elevator = 0x02B8, ElevatorTrim = 0x02B9,
    Rudder = 0x02BA, Throttle = 0x02BB,
    LandingGear = 0x02BE, ToeBrake = 0x02BF,
    WingFlaps = 0x02C3, Accelerator = 0x02C4, Brake = 0x02C5,
    Clutch = 0x02C6, Shifter = 0x02C7, Steering = 0x02C8,
    TurretDirection = 0x02C9, BarrelElevation = 0x02CA,
    DivePlane = 0x02CB, Ballast = 0x02CC,
    BicycleCrank = 0x02CD, HandleBars = 0x02CE,
    FrontBrake = 0x02CF, RearBrake = 0x02D0,
}
```

The enum value encodes `(UsagePage << 8) | Usage` so it's a stable identifier consumers can switch on. Generic Desktop covers stick, trigger, slider, dial, wheel, and the velocity (Vx/Vy/Vz/Vbrx/Vbry/Vbrz/Vno) usages. Simulation Controls covers the analog flight, automotive, marine, and cycling control set.

### Hat priority chain (v1.3.4)

The encoder picks the first non-null in the order: `HatDegrees` &rarr; `HatHundredths` &rarr; `HatRaw` &rarr; `Hat`. Use:

- `Hat` for XInput-style 8-way d-pads.
- `HatDegrees` when your source produces a continuous angle (e.g. analog hat from a stick).
- `HatHundredths` for vJoy-migration paths or when keeping float off the hot path matters.
- `HatRaw` when you have queried `HMProfile.HatLogicalMin` / `HatLogicalMax` and want bit-exact descriptor values.

For a 16-position HOTAS hat, `HatDegrees = 22.5f` snaps to ENE. For a 360-position pro flight stick, `HatDegrees = 47.3f` lands at the closest declared position.

### HMButton

```csharp
[Flags] public enum HMButton : uint
{
    None         = 0,
    A            = 1u << 0,
    B            = 1u << 1,
    X            = 1u << 2,
    Y            = 1u << 3,
    LeftBumper   = 1u << 4,
    RightBumper  = 1u << 5,
    Back         = 1u << 6,    // Select / Share / View
    Start        = 1u << 7,    // Options / Menu
    LeftStick    = 1u << 8,    // L3
    RightStick   = 1u << 9,    // R3
    Guide        = 1u << 10,   // Xbox / PS / Home
    Touchpad     = 1u << 11,   // PS touchpad click
    Share        = 1u << 12,   // Xbox Series Share button

    RightPaddle  = 1u << 13,   // rear paddle, right side
    LeftPaddle   = 1u << 14,   // rear paddle, left side
    Misc1        = 1u << 15,   // vendor-extra slot (Switch 2 C, DualSense mic mute)

    RightPaddle2 = 1u << 16,   // second paddle pair, right side (Edge right Fn, Valve R5)
    LeftPaddle2  = 1u << 17,   // second paddle pair, left side (Edge left Fn, Valve L5)

    RightTouchpad   = 1u << 18,   // right trackpad click (Steam Deck, Steam Controllers)
    LeftStickTouch  = 1u << 19,   // capacitive touch on the stick tops
    RightStickTouch = 1u << 20,
    LeftGripTouch   = 1u << 21,   // capacitive touch on the grips (Steam Controller 2)
    RightGripTouch  = 1u << 22,

    LeftTriggerClick  = 1u << 23,   // a trigger's digital click, apart from its travel
    RightTriggerClick = 1u << 24,

    LeftTouchpad = Touchpad,   // left trackpad click on a two-trackpad controller

    Cross    = A,    // Sony alias
    Circle   = B,
    Square   = X,
    Triangle = Y,
}
```

`RightPaddle` and `LeftPaddle` are named by side rather than by number, because the pads that have them disagree on numbering and agree on side. SDL splits them the same way with `SDL_GAMEPAD_BUTTON_RIGHT_PADDLE1` and `LEFT_PADDLE1`. The Switch 2 Pro's GR and GL map here.

`Misc1` is the vendor-extra slot with no cross-vendor meaning: the Switch 2 family's C button (opens GameChat on real hardware) and the DualSense's mic mute. SDL models both as `SDL_GAMEPAD_BUTTON_MISC1`.

`RightPaddle2` and `LeftPaddle2` are the second paddle pair, added in v1.5.1 for the DualSense Edge's front Fn buttons. SDL folds those into `RIGHT_PADDLE2` / `LEFT_PADDLE2` in its PS5 Edge mapping. The Steam Deck's and Steam Controllers' lower rear buttons, R5 and L5, map here too, with the upper R4 and L4 on the first pair.

`RightTouchpad` is the right trackpad's click on the Steam Deck, the Steam Controller and the Steam Controller 2. SDL reports it as `SDL_GAMEPAD_BUTTON_MISC2` on the Deck and the Steam Controller 2. The left trackpad's click is `Touchpad`, which `LeftTouchpad` names too. Bits 19 to 22 are capacitive touch, on the thumbstick tops of the Deck and the Steam Controller 2 and on the Steam Controller 2's grips, which SDL reports through `SDL_GamepadCapSenseType` rather than as buttons.

`LeftTriggerClick` and `RightTriggerClick` are a trigger's own digital click, apart from its analog travel. The GameCube controller's L and R report both: the analog value, and a click once the trigger bottoms out. A profile names these where its report carries the click, and the trigger axis stays the analog value.

Bits 13 to 15 were added in v1.5.0, 16 and 17 in v1.5.1, 18 to 22 in v1.12.0, and 23 and 24 in v2.0.0. All are additive, so a consumer only needs to care if it switches exhaustively over the enum.

The SDK applies the active profile's `buttonMap` (where present) to translate from the abstract `HMButton` bit position to the descriptor button index. Sony profiles remap so `HMButton.A &rarr; Cross`, `HMButton.X &rarr; Square`, etc. Xbox profiles use identity mapping.

`HMButton.Guide` reaches XInput consumers via `XInputGetStateEx` as the undocumented `XINPUT_GAMEPAD_GUIDE` (0x0400) bit. Reaches WGI / browser via the System Main Menu HID usage on xinputhid profiles, or via the GIP buffer's `btnHigh` bit 6 (0x40) on XUSB-companion profiles: the companion translates 0x40 to `XINPUT_GAMEPAD_GUIDE` in `IOCTL_XUSB_GET_STATE`.

### HMHat

```csharp
public enum HMHat : byte
{
    None      = 0,
    North     = 1, NorthEast = 2, East = 3, SouthEast = 4,
    South     = 5, SouthWest = 6, West = 7, NorthWest = 8,
}
```

The SDK encodes into whatever the profile's descriptor declares. For an 8-position hat the wire values are 0..7 (with the encoder writing N=0, NE=1, etc.). For a 16-position hat the SDK fills the right value at the right resolution; consumers not using `HMHat`'s 8-way step should switch to `HatDegrees` / `HatRaw`.

---

## HMProfile

An immutable handle to a profile.

```csharp
public sealed class HMProfile
{
    // Identity
    public string Id { get; }
    public string Name { get; }
    public string Vendor { get; }
    public ushort VendorId { get; }
    public ushort ProductId { get; }
    public string ProductString { get; }
    public string ManufacturerString { get; }
    public string DisplayName { get; }
    public string Type { get; }     // "gamepad", "wheel", "joystick", "hotas", ...

    // Connection / driver
    public string  Connection { get; }    // "usb", "bluetooth", "wireless-adapter"
    public string? DriverMode { get; }    // "xinputhid" or null, the alias of xinput.via "xinputhid"
    public XInputSpec? XInput { get; }    // v2.0.0: the xinput block, a copy
    public string? TriggerMode { get; }   // "combined", "separate", or null

    // Descriptor
    public bool   IsDeployable { get; }
    public bool   BuildsItsOwnReports { get; }   // v2.0.0
    public int    InputReportSize { get; }
    public byte[]? GetDescriptorBytes();  // returns a defensive copy
    public string? DescriptorHex { get; }

    // Parsed layout
    public int   ButtonCount { get; }
    public int   AxisCount { get; }
    public IReadOnlyList<HMAxis> AvailableAxes { get; }
    public bool  HasHat { get; }
    public int?  HatLogicalMin { get; }
    public int?  HatLogicalMax { get; }
    public int   StickBits { get; }
    public int   TriggerBits { get; }

    // v1.3.9: authored physical layout (discriminated union, 16 kinds)
    public HMLayout? Layout { get; }
    public IReadOnlyList<HMSimpleStick>   Sticks { get; }    // derived from Layout role tags
    public IReadOnlyList<HMSimpleTrigger> Triggers { get; }
    public int StickCount { get; }
    public int TriggerCount { get; }
    // Per-kind accessors: AsGamepad(), AsWheel(), AsHotas(), ... return the
    // concrete HMLayout subtype when Layout matches that kind, else null.

    // Customization tables
    public int[]?                       ButtonMap { get; }
    public Dictionary<string,string>?   AxisMap { get; }
    public string?                      SdlMapping { get; }
    public string?                      Notes { get; }

    // Vendor-blob layout (null when the profile JSON has none)
    public ExtendedReportSpec? ExtendedReport { get; }        // input direction
    public ExtendedReportSpec? ExtendedOutputReport { get; }  // output direction
    public bool HasExtendedInput { get; }
    public bool HasExtendedOutput { get; }

    // v2.0.0: the device model
    public bool HasDeviceModel { get; }
    public IReadOnlyDictionary<string, string> DeviceModelSource { get; }   // per group: own, named:<id>, identity:<entry>, none
    public string? DeviceModelProblem { get; }
}
```

Profiles are immutable. Mutation goes through `HMProfileBuilder.FromProfile(existing)`: build a new profile with the changes you want.

`IsDeployable` is false for catalog entries that carry no descriptor yet, and `CreateController` throws `HMProfileException` for those. 240 of the 337 embedded profiles are deployable. The remaining 97 are identity-only entries awaiting a descriptor capture.

`HatLogicalMin` / `HatLogicalMax` are the HID-spec values declared in the descriptor. For an octant hat, `Min=0 Max=7` (or equivalents); for a 16-position hat `Min=0 Max=15`; for a 360-position continuous hat `Min=0 Max=359`. The count of distinct positions is `Max - Min + 1`.

`ButtonMap` is the optional remapping table from `HMButton` bit position (index into the array) to descriptor button index (the value). Null = identity (Xbox layout). Sony's table reorders so Cross/Circle/Square/Triangle land at the right bit.

Two extensions since v1.5.1. A `-1` entry means the profile does not carry that button: the bit is dropped instead of falling through to identity, which is what stopped `HMButton.Share` from aliasing onto the PS button on Sony pads. And a value at or past the declared button count addresses the contiguous 1-bit vendor-page run that continues the button array, when the descriptor has one. The DualSense family declares 15 buttons and then a 13x1-bit vendor field, and the Edge's back paddles and Fn buttons live in that field's bits on real hardware, invisible to DirectInput but read from the raw report by SDL, Steam Input and DS4Windows. The Edge profiles map them there (16 = left Fn 0x10 through 19 = right paddle 0x80), so the descriptor stays byte-identical to a real Edge's.

`AxisMap` is the optional axis semantic override. Keys are hex HID usage codes (e.g. `"0x32"` for Z), values are semantic names (`"leftStickX"`, `"rightTrigger"`, etc.). Sony profiles override `Z/Rz &rarr; rightStick` and `Rx/Ry &rarr; triggers` because Sony's descriptor uses Generic Desktop usages differently from Xbox's.

`SdlMapping` is the profile's SDL gamepad mapping, or null when SDL already knows the device. It matters for one specific case. SDL only exposes a joystick through its gamepad API when a mapping exists for that device's GUID, and it synthesizes one only for devices its HIDAPI, RawInput, WGI or XInput backends claim. A pad that reaches SDL through DirectInput gets a mapping from SDL's built-in database or from nowhere. So a controller newer than the SDL build in use, or one whose vendor protocol SDL drives over a transport a HID profile cannot present, arrives with axes and buttons but no roles: no A/B/X/Y, no triggers, no dpad. The Switch 2 Pro is the shipped example.

The string is everything after the GUID and the name, trailing comma included, because the GUID is per-device and only exists once SDL has enumerated the pad. A consumer prepends the two device-specific fields:

```csharp
// once per joystick SDL reports, before opening it as a gamepad
var guid = FormatSdlGuid(SDL_GetJoystickGUIDForID(id));   // 32 lowercase hex chars
if (profile.SdlMapping != null)
    SDL_AddGamepadMapping($"{guid},{profile.Name},{profile.SdlMapping}");
```

Registering it is idempotent and safe even when SDL already has a mapping for that GUID, since SDL replaces the entry. Consumers that never touch SDL can ignore the property.

`AxisCount` is the count of every analog input axis the descriptor declares. For SideWinder Force Feedback 2 that's `4` (X, Y, Rz, Slider); for a Logitech G29 with three pedals, `4` (X plus three 8-bit pedals); for an Xbox 360 Wired with the Vx/Vy hidden-trigger pair, `7`.

`AvailableAxes` returns every `HMAxis` the descriptor declares as an analog input, in descriptor order. Combined with `state.Axes`, this is the discovery + drive pair for descriptor-aware binding UIs ("Map physical input to virtual axis: \[dropdown of AvailableAxes\]") without hard-coding which axes a given profile exposes. Empty array when the profile has no descriptor.

### `Layout` and the simple-slot framework (v1.3.9)

`HMProfile.Layout` is a discriminated union with 16 concrete kinds: `gamepad`, `joystick`, `flight_stick`, `hotas`, `wheel`, `pedals`, `shifter`, `handbrake`, `single_axis_accessory`, `arcade_stick`, `dance_pad`, `guitar`, `motion_wand`, `remote`, `controller_adapter`, `unspecified`. Each kind carries the structured fields that make sense for it (sticks, triggers, pedals, wheel rotation range, hat location, paddle count, rumble kind, IMU presence). Consumers render the right widget per profile by matching the layout's kind:

```csharp
switch (pad.Layout)
{
    case HMWheelLayout w:
        RenderWheelGauge(w.RotationRangeDegrees, w.Pedals);
        break;
    case HMHotasLayout h:
        RenderHotasView(h.Stick, h.ThrottlePrimary, h.StickRudder);
        break;
    case HMGamepadLayout g:
    default:
        RenderStandardGamepad();
        break;
}
```

For consumers that just want "give me sticks and triggers for the simple framework," `Profile.Sticks` and `Profile.Triggers` are variable-length lists derived deterministically from the layout's role tags:

- Gamepad &rarr; 2 sticks + 2 triggers.
- Wheel + 3 pedals &rarr; 1 stick (steering on `XAxis`, clutch on `YAxis`) + 2 triggers (accelerator, brake).
- Pedals-only box &rarr; 0 sticks + 2 or 3 triggers.
- Stick-only joystick &rarr; 1 stick + 0 triggers (or 1 throttle if the layout declares one).

Each entry surfaces the `HMAxis` key the consumer writes through. `HMGamepadStateHelpers.StandardAxes(profile, leftStickX, leftStickY, ..., leftTrigger, rightTrigger)` maps the canonical 6-slot convention into the right axis keys for the active profile (so a Sony pad's Z=right-stick mapping is honored automatically).

Profiles whose physical layout is unknown or undocumented declare `kind: "unspecified"` (`HMUnspecifiedLayout`); 33 of the 133 profiles that carry a layout fall into this bucket rather than fabricate one. The classifier still resolves their descriptor's standard usages into the simple slots.

---

## HMProfileBuilder

Fluent builder for runtime-built profiles. Three patterns: clone-and-modify, build-from-scratch, spoof. See [Custom Profiles](../profiles/custom-profiles.md) for the full walkthrough; this section is the API reference.

```csharp
public sealed class HMProfileBuilder
{
    public HMProfileBuilder Id(string id);
    public HMProfileBuilder Name(string name);
    public HMProfileBuilder Vendor(string vendor);
    public HMProfileBuilder Vid(ushort vid);
    public HMProfileBuilder Pid(ushort pid);
    public HMProfileBuilder ProductString(string s);
    public HMProfileBuilder ManufacturerString(string s);
    public HMProfileBuilder DeviceDescription(string? desc);
    public HMProfileBuilder Type(string type);            // "gamepad", "wheel", "hotas", ...
    public HMProfileBuilder Connection(string conn);      // "usb", "bluetooth", ...
    public HMProfileBuilder DriverMode(string? mode);     // "xinputhid" or null
    public HMProfileBuilder XInput(string? json);         // v2.0.0: the xinput block's JSON
    public HMProfileBuilder BluetoothTransport(string? transport);      // "classic" or "le"
    public HMProfileBuilder BluetoothVendorIdSource(string? source);    // "usb" or "bluetooth"
    public HMProfileBuilder TriggerMode(string? mode);    // "combined", "separate", or null
    public HMProfileBuilder Notes(string? notes);

    public HMProfileBuilder Descriptor(byte[] bytes);
    public HMProfileBuilder DescriptorHex(string hex);
    public HMProfileBuilder InputReportSize(int size);
    public HMProfileBuilder FromDescriptorBuilder(HidDescriptorBuilder builder);

    public HMProfileBuilder ButtonMap(int[]? map);
    public HMProfileBuilder TriggerButtons(int[]? map);
    public HMProfileBuilder AxisMap(Dictionary<string,string>? map);

    public HMProfileBuilder FromProfile(HMProfile source);

    // v2.0.0: the device model
    public HMProfileBuilder DeviceModelFrom(string? name);
    public HMProfileBuilder DeviceModel(string? value);    // "none" or null
    public HMProfileBuilder DriverPid(string? pid);
    public HMProfileBuilder FeatureAnswers(string? json);  // the featureStubs JSON
    public HMProfileBuilder ClearDeviceModel();

    public HMProfile Build();
}
```

`Build()` returns an `HMProfile`, and throws `HMProfileException` for its own errors, such as a builder given no VID or PID. A copy keeps its source's VID and PID, and an explicit `Vid(0)` or `Pid(0)` builds. The result can be passed directly to `HMContext.CreateController`.

### `FromDescriptorBuilder` (preferred)

`FromDescriptorBuilder(builder)` takes both the descriptor bytes and the input report wire size from a `HidDescriptorBuilder`. The wire size is derived as `InputReportByteSize + 1` when the descriptor carries a Report ID, and `InputReportByteSize` otherwise. This replaces the easy-to-get-wrong:

```csharp
// Wrong way (works without Report ID, breaks with it)
.Descriptor(b.Build()).InputReportSize(b.InputReportByteSize + 1)
```

with:

```csharp
// Right way: the +1 byte for Report ID is decided automatically
.FromDescriptorBuilder(b)
```

If you forget the `+1`, the kernel sizes the input buffer wrong, HidClass preparsed data is misaligned, and `pid.dll` resolves Feature reports to Report ID 0 instead of the declared values. PadForge tracked this bug across several iterations of issue #16; `FromDescriptorBuilder` makes it impossible to hit.

### `FromProfile` clone

```csharp
var custom = new HMProfileBuilder()
    .FromProfile(ctx.GetProfile("dualsense")!)
    .Id("dualsense-custom")
    .Pid(0x1234)
    .Build();
```

Initializes every field from an existing profile, then individual setters override. As of v2.0.0 it copies the whole profile, its device model keys and `deviceModelFrom` included. Replacing a copy's descriptor drops the keys its report format governs, so a copy that takes `FromDescriptorBuilder` loses `buttonMap`, `triggerButtons`, `axisMap` and `triggerMode`. `Vid` and `Pid` on a copy of a USB/IP persona write into its USB device descriptor too. `ClearDeviceModel` drops the report model and the model the profile names, and keeps `driverPid`, so the model the new identity gives applies. Good for "DualSense but with a different PID" or "Xbox 360 Wired with a custom product string for joy.cpl labeling".

### `ButtonMap` and `AxisMap`

For full control over button/axis routing through your custom descriptor. See [Custom Profiles](../profiles/custom-profiles.md).

---

## HidDescriptorBuilder

Fluent HID-descriptor authoring without touching hex. Full reference on its own page: [HID Descriptor Builder](hid-descriptor-builder.md).

```csharp
public sealed class HidDescriptorBuilder
{
    public HidDescriptorBuilder Gamepad();
    public HidDescriptorBuilder Joystick();

    public HidDescriptorBuilder AddStick(string name, int bits = 16);
    public HidDescriptorBuilder AddTrigger(string name, int bits = 8);
    public HidDescriptorBuilder AddButtons(int count);
    public HidDescriptorBuilder AddHat(int positions = 8);
    public HidDescriptorBuilder AddPidFfbBlock();
    public HidDescriptorBuilder AddRaw(byte[] bytes);

    // Keyboard and mouse starters (v1.12.0)
    public HidDescriptorBuilder Mouse(int buttons = 5, bool absolute = false,
                                      bool wheel = true, bool pan = true, byte reportId = 0);
    public HidDescriptorBuilder Keyboard(int keys = 6, bool leds = true, byte reportId = 0);
    public HidDescriptorBuilder KeyboardNkro(bool leds = true, byte reportId = 0);
    public HidDescriptorBuilder ConsumerControl(int slots = 1, byte reportId = 0);
    public HidDescriptorBuilder VendorButtons(int count, byte reportId);

    public byte[] Build();
    public int InputReportByteSize { get; }
    public bool DescriptorContainsReportId();
}
```

---

## HMDeviceExtractor

Read HID descriptors back out of currently-connected physical devices. The same API powers `HIDMaestroProfileExtractor.exe` and the `HIDMaestroTest extract-profile` CLI command. See [Profile Extractor](../profiles/profile-extractor.md) for the user-facing tool.

```csharp
public static class HMDeviceExtractor
{
    public static IReadOnlyList<HMHidDeviceInfo> ListDevices();
    public static HMProfile Extract(HMHidDeviceInfo device);
    public static HMProfile ExtractByVidPid(ushort vid, ushort pid);
    public static HMProfile ResolveDeviceModel(HMProfile profile);   // v2.0.0
    public static string ToJson(HMProfile profile);
}
```

`ListDevices` enumerates every HID-class device. Returns one entry per HID interface (a single physical device with multiple top-level collections appears multiple times: pick by `TopLevelUsage`). Non-elevated.

`Extract(device)` reconstructs the descriptor from `HidD_GetPreparsedData` using the libusb/hidapi algorithm (Chromium WebHID team's reverse engineering of Microsoft's preparsed-data layout). Output is logically equivalent to the device's real descriptor, with the same report IDs, field layouts, logical ranges, usage pages and sizes, but it is not byte-for-byte identical. For HIDMaestro's purpose (creating a virtual that behaves the same as the physical), logical equivalence is the correct fidelity bar; filter drivers can mutate the descriptor before it reaches user mode anyway. Non-elevated.

Throws `InvalidOperationException` if the device disconnected between enumeration and extraction, or if preparsed data can't be reconstructed.

`ExtractByVidPid(vid, pid)` is a convenience wrapper that finds the first matching device and extracts. Throws if no match.

As of v2.0.0 `Extract` writes the `deviceModelFrom` the profile's identity gives it, so the saved JSON states the device's behavior. It reads the bus from the parent devnode's compatible IDs, as hidapi and SDL do, so a Bluetooth device extracts as `bluetooth` with its `bluetoothTransport` and, for a Bluetooth SIG vendor ID, `bluetoothVendorIdSource`, and `ToJson` writes both. `ResolveDeviceModel(profile)` returns a copy that names that model for a profile with no model keys, no `deviceModelFrom` and no `"deviceModel": "none"` of its own, and returns any other profile unchanged.

`ToJson(profile)` serializes to the JSON format used by the shipped catalog. Output can be saved to `profiles/<vendor>/<slug>.json` and picked up by `LoadProfilesFromDirectory`.

---

## HMHidDeviceInfo

```csharp
public sealed class HMHidDeviceInfo
{
    public ushort  VendorId { get; }
    public ushort  ProductId { get; }
    public ushort  VersionNumber { get; }
    public string? ProductString { get; }
    public string? ManufacturerString { get; }
    public string? SerialNumberString { get; }
    public ushort  TopLevelUsagePage { get; }
    public ushort  TopLevelUsage { get; }      // 0x04 = Joystick, 0x05 = Gamepad
    public ushort  InputReportByteLength { get; }
    public string  DevicePath { get; }
}
```

Lightweight description of one currently-connected HID interface. Returned by `HMDeviceExtractor.ListDevices`.

---

## HMOemNameOverride

Static API for overriding the joy.cpl / DirectInput OEM-name label per VID:PID. Crash-safe via the pending-override hive at `HKLM\SOFTWARE\HIDMaestroOemOverrides`. Full reference: [OEM Name Override](oem-name-override.md).

```csharp
public static class HMOemNameOverride
{
    public static void Set(ushort vid, ushort pid, string label);
    public static void Clear(ushort vid, ushort pid);
    public static int  RecoverOrphans();
    public static IReadOnlyList<HMOemNameOverrideEntry> ListActive();
}
```

---

## HMPortSet and HMPort (v2.0.0)

The controller ports of a device that carries several controllers in one report, such as a multi-port adapter, a multitap or a receiver. Get the set from `HMController.Ports`.

```csharp
public sealed class HMPortSet : IReadOnlyList<HMPort>
{
    public HMController Controller { get; }
    public int Count { get; }
    public HMPort this[int index] { get; }        // Ports[0] is port 1
    public HMPortFlags Flags { get; }
    public IReadOnlyList<string> Connections { get; }
    public IReadOnlyList<string> OutputNames { get; }
}

public sealed class HMPort
{
    public int Number { get; }                    // from 1, as the device numbers it
    public HMPortSet Ports { get; }
    public string Connection { get; }
    public bool IsConnected { get; }
    public void Connect(string? connection = null);
    public void Connect(string? connection, in HMGamepadState state);
    public void Disconnect();
    public void SubmitState(in HMGamepadState state);
    public void SubmitRaw(ReadOnlySpan<byte> data);
    public int GetOutput(string name);
    public event EventHandler<HMPortOutputEventArgs>? OutputChanged;
}

public sealed class HMPortFlags
{
    public IReadOnlyList<string> Names { get; }
    public bool this[string name] { get; set; }
}

public sealed class HMPortOutputEventArgs : EventArgs
{
    public HMPort Port { get; }
    public string Name { get; }
    public int Value { get; }
}
```

Each port has its own connection, input and output. The device sends one report for all of them, so a submit to one port leaves the others as they were. A port's number never changes: a program that puts a returning controller back on its old port gets that port on the wire.

`Connections` names what a port can hold, in the profile's order. The first is the empty port, and the second is the one `Connect` uses when given none. `Connect` plugs something in. A port that held nothing reports a controller at rest, sticks centered and triggers and buttons released, until the next submit, and a port that held something keeps its input as last submitted. `Connect(connection, in state)` plugs it in already holding `state`, in one report, and throws `ArgumentException` for the empty connection. `Disconnect` empties the port and zeroes its data bytes, as an empty port's are. `Connection`, `IsConnected`, `Connect` and `Disconnect` throw `InvalidOperationException` when the device's ports carry no status byte. The one-argument `Connect` given the empty connection's name does what `Disconnect` does.

`SubmitState` sets the port's input from the SDK's gamepad state through the profile's port fields. `SubmitRaw` sets the port's data bytes exactly, in the device's own units, and throws `ArgumentException` for the wrong length. An empty port takes the profile's default connection first, in both. A port submit rewrites the whole report from the ports' state, so it replaces a report sent with `SubmitRawExtendedReport`. Build reports with one or the other.

`Flags` are device-wide switches every port's status byte shows, such as the GameCube adapter's second USB cable that powers the controllers' motors. Setting one to a new value rewrites every port's status byte and sends the report. Setting it to the value it has sends nothing. An unknown name throws `ArgumentException`.

`OutputNames` are each port's output fields, as the profile's `extendedOutputReport.ports` declares them. `GetOutput` returns the host's last value for one: zero until a host sets it, and again after the device returns to its initial state at a port reset or detach. It throws `ArgumentException` for a name the ports do not declare, and `InvalidOperationException` on a device with no `extendedOutputReport.ports`. `OutputChanged` is raised on the controller's output thread when a host changes one of the port's fields, and when that return sets one back to zero. Handlers must be thread-safe. An exception a handler throws is caught and dropped, as `OutputReceived` drops them.

## HMDeviceProtocol (v2.0.0)

The protocol of a USB/IP device whose profile declares a `protocol`: the registers and counters the host's commands and the device's clock set, and the host poll the device is served at. Get it from `HMController.DeviceProtocol`.

```csharp
public sealed class HMDeviceProtocol
{
    public IReadOnlyList<string> StateNames { get; }
    public bool GetState(string name);
    public uint GetRegister(string name);
    public IReadOnlyList<string> CounterNames { get; }
    public uint GetCounter(string name);
    public TimeSpan DescriptorPollInterval { get; }
    public TimeSpan HostPollInterval { get; set; }
}
```

`GetState` reports whether a named state is on now, such as the GameCube adapter's `polling`, which the host's 0x13 command turns on. `GetRegister` reads a register's value, as wide as the profile declares it, and `GetCounter` a counter's: reports sent, frames, reads or clock periods. An unknown name throws `ArgumentException`.

`DescriptorPollInterval` is the poll period the input endpoint's descriptor gives, as Windows schedules it. `HostPollInterval` is the period the device is served at. Set it faster for a host that polls the device more often than its descriptor asks, as Melee players' adapter overclock does. The descriptors never change. Windows polls a low-speed interrupt endpoint every 8, 16 or 32 ms, a full-speed one every 1, 2, 4, 8, 16 or 32 ms and a high-speed one every 125, 250 or 500 microseconds or 1, 2 or 4 ms, and any other value throws `ArgumentOutOfRangeException`. The setter throws `InvalidOperationException` on a device that builds its reports and sends them on its own clock, such as `switch2-pro-controller-composite`, and on one whose protocol names no input endpoint, such as `steam-controller-2`.

## HMBuildInfo (v2.0.0)

What this build of `HIDMaestro.Core.dll` carries. Official releases carry everything. A build from source can leave payloads out (see [Build and Release](../reference/build-and-release.md)), and then refuses whatever needs them with `HMPayloadMissingException` before any machine-wide step.

```csharp
public static class HMBuildInfo
{
    public static IReadOnlyList<Architecture> DriverArchitectures { get; }
    public static IReadOnlyList<Architecture> UsbipArchitectures { get; }
    public static bool HasOpenVrDriver { get; }
    public static bool IsComplete { get; }
}

public enum HMPayload { Driver = 0, UsbipTransport = 1, OpenVrDriver = 2 }
```

Each answer is read once from the assembly's own embedded resources, so it describes the bytes the build holds, whatever settings built it. `DriverArchitectures` lists the architectures the UMDF2 driver is carried for, and every controller except a composite persona needs the one matching the machine. `UsbipArchitectures` lists them for the USB/IP transport composite personas ride, and is empty in a build made with `HMSkipUsbip`. `IsComplete` is true when the build carries both for x64 and ARM64, and the OpenVR driver. `HMContext.IsUsbipBackendAvailable` is false in a build without the transport for the machine.

## Exceptions (v2.0.0)

All four derive from `InvalidOperationException`, so code that catches that keeps working.

```csharp
public sealed class HMResourceInUseException : InvalidOperationException
{
    public string Resource { get; }           // such as "identity key 'slot-1'"
    public int? OwnerProcessId { get; }
    public string? OwnerImagePath { get; }
    public string? OwnerSdkVersion { get; }
}

public sealed class HMDriverVersionException : InvalidOperationException
{
    public HMDriverVersionProblem Problem { get; }   // ProtocolNotServed or ValueNotRead
    public Version InstalledVersion { get; }
    public Version MinimumVersion { get; }
    public IReadOnlyList<string> Blockers { get; }
}

public sealed class HMProfileException : InvalidOperationException
{
    public string ProfileId { get; }
    public string? File { get; }
    public string JsonPath { get; }
    public string Reason { get; }
}

public sealed class HMPayloadMissingException : InvalidOperationException
{
    public HMPayload Payload { get; }
    public Architecture? Architecture { get; }   // null for the OpenVR driver
}
```

`HMResourceInUseException` is thrown by a create that asks for something another live controller holds: its identity key, a transport index when none is left, or the ParentIdPrefix its identity derives. It is also thrown when a v1.12.0 program starts on the create's transport index during the create, when another program made one of the index's events after the index was chosen, and for a key a context of the same process dropped without `Dispose` still holds. A refused create removes only what it made, so the other program's devices and configuration stay. When no index is left because other programs made objects under the SDK's names, the message counts those indices and names one. The owner fields are set only for an identity key that a program built on HIDMaestro 2.0.0 or later holds. Every other refusal leaves them null, and names the holder in its message at most.

`HMDriverVersionException` is thrown by a UMDF2 create once its device has started, when the driver that started it does not serve this SDK's protocol 4 (`Problem` is `ProtocolNotServed`) or could not read a value the create wrote (`ValueNotRead`). The create removes its device first. A create installs its own driver over an older one, so `ProtocolNotServed` means a newer driver that dropped protocol 4, which needs an SDK of its release, or a mis-stamped one. No deploy throws it.

`HMProfileException` is thrown by a create, and by `HMProfileBuilder.Build`, for a defect of the profile itself. `File` is null for a profile built in code.

`HMPayloadMissingException` is thrown when this build lacks a payload the call needs. See [HMBuildInfo](#hmbuildinfo-v200).

## Output / FFB types

```csharp
public readonly struct HMOutputPacket
{
    public readonly HMOutputSource Source;
    public readonly byte ReportId;
    public readonly ReadOnlyMemory<byte> Data;
    public readonly uint SeqNo;
}

public enum HMOutputSource : byte
{
    HidOutput  = 0,    // HidD_SetOutputReport / dinput8 PID effects / HIDAPI write
    HidFeature = 1,    // HidD_SetFeature
    XInput     = 2,    // XInputSetState (XUSB-wire 5-byte vibration)
}

public enum PidLoadStatus : byte { Success = 1, Full = 2, Error = 3 }

[Flags] public enum PidStateFlags : byte
{
    None                   = 0,
    DeviceIsPaused         = 1 << 0,
    ActuatorsEnabled       = 1 << 1,
    SafetySwitch           = 1 << 2,
    ActuatorOverrideSwitch = 1 << 3,
    ActuatorPower          = 1 << 4,
    EffectPlaying          = 1 << 5,
}

public readonly struct HMPidBlockLoad
{
    public byte EffectBlockIndex { get; }
    public PidLoadStatus LoadStatus { get; }
    public ushort RAMPoolAvailable { get; }
}
```

See [Output Passthrough](output-passthrough.md) and [Force Feedback](force-feedback.md) for the full decoding patterns and consumer-side templates.

---

## Thread safety summary

| Method / event | Caller thread | SDK behavior |
|----------------|---------------|--------------|
| `HMContext.InstallDriver` | Any (admin) | Blocks. Deploys are serialized machine-wide by the deploy lock, `HIDMaestro.Admin\Deploy`, across threads and programs. |
| `HMContext.CreateController` | Any (admin) | Blocks until device fully bound. Lock-protected against concurrent index allocation. Waits while another program of v2.0.0 or later registers or removes a devnode, up to ten minutes. |
| `HMController.SubmitState` / `SubmitRawReport` | Any | Seqlock write, ~250 ns per call. On a profile with an idle clock (the Valve personas), a per-controller lock serializes it with the idle repeat. Can be called from any thread but typically the consumer's input-poll thread. |
| `HMPort.SubmitState` / `SubmitRaw` / `Connect` / `Disconnect`, `HMPortFlags` setter | Any | Under the controller's submit lock, so ports can be written from several threads. |
| `HMPort.OutputChanged` | SDK output thread | NOT the consumer's thread, as with `OutputReceived`. |
| `HMController.OutputReceived` | SDK poll thread | NOT the consumer's thread. Marshal back if needed. Keep handlers cheap (<512 ms total). |
| `HMController.PublishPid*` | Any | Lock-protected per-controller (so pool/state writes don't tear). Cheap. |
| `HMOemNameOverride.Set` / `Clear` | Any (admin) | Global mutex around all three registry writes. |
| `HMDeviceExtractor.ListDevices` / `Extract` | Any | Read-only. Re-enumerates on every call. |

A handler that throws stops nothing else. The nine events the SDK raises on its own threads, `OutputReceived`, `OutputDecoded` and `KeyboardLedsChanged` on the output reader, a port's `OutputChanged`, the USB audio events and `HapticReceived`, run each handler in turn and drop what one throws. The next handler and the SDK's own handling of the same output packet still run, and `HIDMAESTRO_DIAG=1` writes each dropped exception to the diagnostic log. Through v1.12.0 a throwing handler kept the handlers after it from running and made the SDK skip the rest of the packet. On a composite's USB/IP connection it closed the connection, and on the audio pump, the thread pool or the VR haptic reader it ended the program. Walking the handlers allocates nothing.

A handler may dispose its own controller. `HMController.Dispose` called from that controller's `OutputReceived`, `OutputDecoded` or `KeyboardLedsChanged` handler, or from a port's `OutputChanged` handler, does not wait for the output thread that runs the handler. Once the handler returns, the thread raises the rest of that packet's events on the disposed controller and ends without reading another packet. `HMContext.Dispose` and `DisposeControllersInParallel` called from a handler dispose that handler's controller on the handler's own thread and the others from parallel threads. Every exception `DisposeControllersInParallel`'s per-controller callback throws comes out in one `AggregateException` after the batch ends, with one controller as with many, and every controller is disposed first. `HMContext.Dispose` drops what each controller's dispose throws. `HMVRController.Dispose` called from its `HapticReceived` handler returns at once too.

---

## See also

- [Quickstart](../start/quickstart.md): the SDK methods in their canonical order.
- [HID Descriptor Builder](hid-descriptor-builder.md): full `HidDescriptorBuilder` reference.
- [Force Feedback](force-feedback.md): PID FFB descriptor authoring + publish/read patterns.
- [Output Passthrough](output-passthrough.md): output ring buffer mechanics and decoding.
- [Wii U GameCube Adapter](gamecube-adapter.md): ports, a device protocol and a WinUSB binding on one persona.
- [Programs Side by Side](programs-side-by-side.md): ownership claims, transport indices and sweeps across programs.
- [Custom Profiles](../profiles/custom-profiles.md): `HMProfileBuilder` patterns end-to-end.
- [Profile System](../profiles/profile-system.md): the JSON schema `HMProfile` corresponds to.
