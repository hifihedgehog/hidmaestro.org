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

## Lifecycle and ordering

Any start order works. The driver (loaded whenever SteamVR runs) polls for the consumer's shared-memory channel, and the consumer's properties (`DriverConnected`, `ControllersLive`) report progress. Dispose releases the channel claim.

## Verification status (v1.6.0)

Machine-verified end-to-end on a headless rig (real SteamVR, null HMD, no headset, no Steam client), by `test/probes/vr_controller_smoke` (battery scenario S50): payload extraction, vrpathreg registration, vrserver loading the driver, deferred device registration, both controllers enumerating as connected `TrackedDeviceClass_Controller` with HIDMaestro serials through Valve's own `openvr_api`, and a haptic pulse round-tripping client → vrserver → driver → `HapticReceived` with correct hand attribution. The IPC protocol is additionally pinned byte-for-byte between the C# and C++ mirrors, both by S50's driver-role phase and by `static_assert`s compiled into the driver.

Not verified without a headset, and stated here rather than implied: input values read back through the SteamVR Input action-binding system (the driver updates its components, but no client-side assert exists without bindings), in-game interaction feel, and the elevated-consumer/medium-integrity-vrserver ACL case (the rig runs vrserver elevated, while the SDDL grants Interactive explicitly for the real case). Real-hardware reports belong in HIDMaestro #32.

## The generic controller identity

The controllers present as `hidmaestro_controller` (manufacturer HIDMaestro, serials `HMVR-LEFT-0001` / `HMVR-RIGHT-0001`) with a full input profile: system, A, B, trigger, grip, joystick, haptics. Games that use SteamVR Input rebinding work with it directly. Games that only ship bindings for specific controller types (Index, Vive, Touch) may need a community binding or SteamVR's controller rebinding UI. Impersonating an Index controller identity is deliberately not done in this release: partial impersonation (without skeletal input) risks breaking the games it aims to help, and the honest generic identity is rebindable everywhere.
