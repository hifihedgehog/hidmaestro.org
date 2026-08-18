# VR Controllers

`HMVRController` instantiates a pair of virtual VR motion controllers inside SteamVR (HIDMaestro issue #32). This page covers the mental model, the API, the dependency story, and precisely what is and is not verified.

Source: [`driver/openvr/`](https://github.com/hifihedgehog/HIDMaestro/tree/master/driver/openvr) (the native OpenVR driver), [`HMVRController.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/HMVRController.cs), [`HMVR.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/HMVR.cs).

---

## Why this is not an HMController

A VR controller is not an OS device. It exists only inside a VR runtime's session: games never enumerate it, they ask the runtime "where is the left hand, and what is its trigger doing." So HIDMaestro's VR support is an **OpenVR driver DLL that SteamVR's vrserver loads**, embedded in `HIDMaestro.Core.dll` and registered with `vrpathreg` on first use. Nothing UMDF2, nothing PnP, no descriptor.

OpenVR's driver API is the one public door on Windows. It is not in competition with OpenXR: OpenXR standardizes the game-to-runtime boundary, deliberately left the runtime-to-device boundary to each vendor (the planned device plugin layer never shipped after 1.0), and SteamVR is itself an OpenXR runtime. One OpenVR driver therefore serves native OpenVR games AND OpenXR games running on SteamVR, which is the default PCVR configuration. Out of reach: Oculus-native titles and OpenXR sessions pinned to Meta's runtime, both closed to third-party devices.

## The dependency, stated plainly

SteamVR is required, free, and almost always already present on a machine that plays PCVR (for lighthouse headsets it IS the headset driver). HIDMaestro never installs it, never launches a user's copy, and machines without it are untouched: `HMVR.IsSteamVRInstalled` reports false and everything else works as before.

For a machine without the Steam client there is a verified Steam-free install path using Valve's own command-line tool, no account needed:

```
curl -L -o steamcmd.zip https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip
steamcmd +force_install_dir "C:\SteamVR" +login anonymous +app_update 250820 validate +quit
```

Discovery handles both shapes: Steam-client installs are found through the registry, steamcmd installs through `HMVR.SetSteamVRPathHint` or the conventional `C:\SteamVR`.

## API

```csharp
public static class HMVR
{
    public static bool IsSteamVRInstalled { get; }
    public static bool IsSteamVRRunning { get; }
    public static string? SteamVRPath { get; }
    public static void SetSteamVRPathHint(string steamVrDir);   // admin
    public static bool EnsureDriverRegistered();                // admin
    public static void UnregisterDriver();                      // admin
}

public sealed class HMVRController : IDisposable
{
    public HMVRController();                       // creates + claims the IPC channel
    public bool DriverConnected { get; }           // driver attached inside vrserver
    public bool ControllersLive { get; }           // both hands registered
    public void SubmitState(in HMVRState state);   // both hands, once per frame
    public event EventHandler<HMVRHapticEventArgs> HapticReceived;
    public HMVRHmdPose GetHmdPose();               // real headset pose, for head-as-input
}
```

`HMVRState` carries per hand: an `HMVRButton` mask (System, A, B with touch variants, trigger/grip/stick clicks), trigger and grip `[0..1]`, stick X/Y `[-1..+1]`, and an optional pose override (meters + unit quaternion, SteamVR standing universe). With no override the driver anchors the hands ahead of the headset, so pointing works by looking. With an override the consumer owns hand placement, which is how stick-driven or gyro-driven virtual hands are built.

`GetHmdPose` is the reverse direction: the driver publishes the real headset pose every server frame, so a consumer can map head lean onto any flat-game input (the PadForge #49 request) without FreePIE-class tooling.

`EnsureDriverRegistered` extracts the embedded driver to `%ProgramData%\HIDMaestro\openvr\hidmaestro` (a stable path, because vrpathreg stores absolute paths), registers it, and is content-hash idempotent. Registration hot-plugs into a running SteamVR. Controllers appear only while a consumer holds the channel: no consumer, no phantom devices, and a dead consumer flips them to disconnected within seconds.

## Hand roles

SteamVR distinguishes a *device* from a *hand*. Haptics and the "Waiting" window address devices. `/user/hand/left`, `/user/hand/right`, and SteamVR's own Test Controller page address roles, and the runtime decides which device holds each role. `Prop_ControllerRoleHint_Int32` only hints. The property that actually influences the decision is `Prop_ControllerHandSelectionPriority_Int32`, which the driver sets on both hands at activation (HIDMaestro issue #51).

The default is `1000`, matching VRCHOTAS's mapped-controller value. Left unset the property reads back `0`, the same value SteamVR's own Index profile ends up with, which leaves the winner to an unstated runtime tiebreak on a machine that has both. A positive value states the answer.

That default means the virtual hands take the roles from real controllers while a consumer is live. On a machine where the real hardware should keep them, set the priority negative in `steamvr.vrsettings`, the same register Valve's own Oculus Touch profile uses with `hand_priority: -1`:

```json
"driver_hidmaestro": {
   "hand_selection_priority": -1000
}
```

The driver logs the value it used and whether it came from settings or its built-in fallback, so `vrserver.txt` answers "which number is live" directly.

## The legacy input lane (`GetControllerState`)

Two client APIs read controller input from SteamVR. Games on the modern SteamVR Input system read *actions* through their action manifest. Background tools and older titles read the *legacy* API, `IVRSystem::GetControllerState`, and that lane only carries data vrserver generates through the controller profile's `legacy_binding`. The driver ships one (`legacy_bindings_hidmaestro.json`, HIDMaestro issue #55), mapped by the convention every Valve-shipped binding uses:

| Legacy slot | Virtual control |
| --- | --- |
| axis0 | joystick position (+ `k_EButton_Axis0` on stick click) |
| axis1 | trigger pull (+ `k_EButton_Axis1` on trigger click) |
| axis2 | grip pull (+ `k_EButton_Axis2` and `k_EButton_Grip` on grip click) |
| `k_EButton_A` / `k_EButton_ApplicationMenu` | A / B, with touch |
| `k_EButton_System` | system |

The driver also declares `Prop_Axis0Type_Int32` through `Prop_Axis2Type_Int32` (joystick, trigger, trigger), because vrserver does not synthesize those for `IVRDriverInput` drivers and legacy consumers classify axes by them.

Two behaviors of this lane worth knowing before debugging an "empty state" report, both measured:

- **Legacy state follows SteamVR's input focus.** A client that reads all-zero state with `unPacketNum` frozen at 0 while poses stream fine should check `IVRSystem::IsInputAvailable()`. On a headless rig with no scene application, nothing holds input focus and background clients read zeros indefinitely, while the same read from a scene application (one that pumps `WaitGetPoses`) streams within milliseconds. On a normal rig with a game running, background readers see the state whenever input is not captured.
- **The binding routes by `/user/hand/left|right`,** so a hand without an assigned role reads empty even with the binding present. Check roles first (see Hand roles above).

## Lifecycle and ordering

Any start order works. The driver (loaded whenever SteamVR runs) polls for the consumer's shared-memory channel, and the consumer's properties (`DriverConnected`, `ControllersLive`) report progress. Dispose releases the channel claim.

## Verification status (v1.6.2)

Machine-verified end-to-end on two headless rigs (real SteamVR, null HMD, no headset, no Steam client), by `test/probes/vr_controller_smoke` (battery scenario S50): payload extraction, vrpathreg registration, vrserver loading the driver, deferred device registration, both controllers enumerating as connected `TrackedDeviceClass_Controller` with HIDMaestro serials through Valve's own `openvr_api`, hand roles held by both hands, the legacy axis-type declarations, a haptic pulse round-tripping client → vrserver → driver → `HapticReceived` with correct hand attribution, the consumer-restart cycle, and the legacy lane: a spawned scene-app reader observes `GetControllerState` packets advancing at 90 Hz with every axis tracking the submitted state and every mapped button landing on its legacy bit. The IPC protocol is additionally pinned byte-for-byte between the C# and C++ mirrors, both by S50's driver-role phase and by `static_assert`s compiled into the driver.

Not verified without a headset, and stated here rather than implied: input values read back through the SteamVR Input action-binding system under a real game's action manifest, in-game interaction feel, and the elevated-consumer/medium-integrity-vrserver ACL case (the rig runs vrserver elevated, while the SDDL grants Interactive explicitly for the real case). Real-hardware reports belong in HIDMaestro #32.

## The generic controller identity

The controllers present as `hidmaestro_controller` (manufacturer HIDMaestro, serials `HMVR-LEFT-0001` / `HMVR-RIGHT-0001`) with a full input profile: system, A, B, trigger, grip, joystick, haptics. Games that use SteamVR Input rebinding work with it directly. Games that only ship bindings for specific controller types (Index, Vive, Touch) may need a community binding or SteamVR's controller rebinding UI. Impersonating an Index controller identity is deliberately not done in this release: partial impersonation (without skeletal input) risks breaking the games it aims to help, and the honest generic identity is rebindable everywhere.
