# OEM Name Override

`HMOemNameOverride` overrides the label `joy.cpl` and DirectInput consumers show for a given USB VID:PID. Use it when you want a HIDMaestro virtual (or any device sharing that VID:PID) to display a specific name in `joy.cpl` and DirectInput, overriding any Windows-shipped pre-populated label.

The implementation is more involved than "write one registry value" because Windows pre-populates clone PIDs in registry locations the obvious-looking write doesn't reach. The API exists because there is **no** simpler reliable way to override the label.

---

## The three label sources

The DirectInput / `joy.cpl` label is sourced from **three** registry locations. Windows pre-populates at least one of them for many common clone PIDs (e.g. `VID_0079&PID_0006` ships with the label "PC TWIN SHOCK Gamepad"). To reliably override, all three must be written:

| Location | Value name | Reader |
|----------|-----------|--------|
| `HKLM\SYSTEM\CurrentControlSet\Control\MediaProperties\PrivateProperties\DirectInput\VID_####&PID_####\OEM\` | `"OEM Name"` (with space) | DirectInput consumers |
| `HKLM\SYSTEM\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM\VID_####&PID_####\` | `"OEMName"` (no space) | MME `joy.cpl` |
| `HKCU\System\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM\VID_####&PID_####\` | `"OEMName"` (no space) | per-user `joy.cpl` (preloaded by Windows for clone PIDs) |

Per-user (HKCU) takes precedence over HKLM `Joystick` and is the **first place Windows checks** for many clone PIDs. Writing only the HKLM `DirectInput` path leaves the HKCU clone label intact, and `joy.cpl` continues showing the wrong name.

`HMOemNameOverride.Set` writes all three under a global mutex, capturing the prior value of each before any are mutated.

---

## API

```csharp
public static class HMOemNameOverride
{
    public static void Set(ushort vid, ushort pid, string label);
    public static void Clear(ushort vid, ushort pid);
    public static int  RecoverOrphans();
    public static IReadOnlyList<HMOemNameOverrideEntry> ListActive();
}

public sealed class HMOemNameOverrideEntry
{
    public string  VidPid { get; }
    public string? OriginalOemName { get; }
    public bool    OriginalKeyExisted { get; }
}
```

All methods require admin (HKLM write access). Throw `UnauthorizedAccessException` if the calling process isn't elevated.

### `Set(vid, pid, label)`

```csharp
HMOemNameOverride.Set(0x0079, 0x0006, "My Custom Gamepad");
```

Writes all three registry locations with the new label, in a single transaction under a global mutex. Captures the prior value of each target to a HIDMaestro-owned pending record at `HKLM\SOFTWARE\HIDMaestroOemOverrides\VID_xxxx&PID_xxxx` **before** any target is mutated.

If a prior `Set` for this VID:PID is already active, this replaces the label but **keeps the originally-captured value** for restore purposes. Re-calling `Set` is safe and cumulative.

Throws `ArgumentNullException` if `label` is null.

### `Clear(vid, pid)`

```csharp
HMOemNameOverride.Clear(0x0079, 0x0006);
```

Restores the pre-Set DirectInput OEM-name label for `(vid, pid)`. Replays the pending record to restore all three target locations independently. If no prior `Set` is tracked for this VID:PID, this is a no-op.

For each target, the restore matches what Set captured:

- If the target key **existed** with a value, the value is reset to the original.
- If the target key **existed** without the named value, the named value is deleted (key remains).
- If the target key **did not exist**, the entire subkey is deleted.

After all three restores succeed, the pending record at `HKLM\SOFTWARE\HIDMaestroOemOverrides\VID_xxxx&PID_xxxx` is deleted.

### `RecoverOrphans()`

```csharp
int restored = HMOemNameOverride.RecoverOrphans();
```

Scans the pending hive at `HKLM\SOFTWARE\HIDMaestroOemOverrides` and restores every prior override left behind by a crashed, force-killed, or otherwise uncleanly-exited consumer. Returns the count restored.

**Safe to call on every consumer startup.** No-op if no orphan records exist.

### `ListActive()`

```csharp
foreach (var entry in HMOemNameOverride.ListActive())
{
    Console.WriteLine($"  {entry.VidPid} (was: {entry.OriginalOemName ?? "<no original value>"})");
}
```

Enumerates every override currently tracked by the pending hive. Useful for diagnostics or for showing the user which virtuals are currently overriding their `joy.cpl` label.

`HMOemNameOverrideEntry`:

| Property | Meaning |
|----------|---------|
| `VidPid` | Canonical registry form, e.g. `"VID_0079&PID_0006"`. |
| `OriginalOemName` | The label captured before `Set` ran. Null if the OEM key existed without the named value. |
| `OriginalKeyExisted` | True if the DirectInput OEM subkey existed when Set first ran. False means the subkey will be deleted on restore. |

---

## Crash safety

The pending hive at `HKLM\SOFTWARE\HIDMaestroOemOverrides` is written **before** any registry mutation. The state machine looks like this:

1. **Consumer calls `Set(vid, pid, "label")`.** Acquires global mutex.
2. **Pending record written** capturing all three targets' prior values.
3. **All three targets written** with the new label.
4. **Mutex released.**
5. ...consumer runs, virtual is live, `joy.cpl` shows "label"...
6. **Consumer calls `Clear(vid, pid)`** (or process ends).
7. Acquires global mutex.
8. Reads pending record.
9. Replays each target: reset value, delete value, or delete subkey per `OriginalKeyExisted`.
10. Pending record deleted.
11. Mutex released.

If the process dies between steps 4 and 6 &mdash; that is, the override is in place but `Clear` never ran &mdash; the pending hive still has the record. The next `RecoverOrphans()` call replays the record and restores the original.

Steps 2 and 3 happen under the same mutex, so a crash mid-sequence leaves the system in a recoverable state: either step 2 didn't complete (no override in effect, no orphan record &mdash; nothing to recover) or step 3 partially completed (`RecoverOrphans` restores what step 3 mutated even if only some of the three writes landed).

The captured per-target state lets `Clear` and `RecoverOrphans` restore each target independently, which matters when only one of the three keys existed pre-`Set`.

---

## Usage pattern

The canonical pattern in a consumer with multiple virtuals is:

```csharp
// Once at consumer startup, before creating any virtuals:
int restored = HMOemNameOverride.RecoverOrphans();
if (restored > 0)
    Logger.Info($"Recovered {restored} orphan OEM-name override(s) from prior session");

// For each virtual where you want a custom joy.cpl label:
HMOemNameOverride.Set(profile.VendorId, profile.ProductId, "PadForge Slot 0");
using var ctrl = ctx.CreateController(profile);

// At virtual teardown:
ctrl.Dispose();
HMOemNameOverride.Clear(profile.VendorId, profile.ProductId);
```

For consumers that lock to single-instance execution (PadForge does), `RecoverOrphans` at startup plus a paired `Set`/`Clear` per virtual covers the full lifecycle.

For consumers that may run multiple instances simultaneously, the global mutex serializes write attempts. The pending record is per-VID:PID, so two consumers overriding two different VID:PIDs don't conflict; two consumers fighting over the same VID:PID will have whichever `Set` call ran last win, and the other consumer's `Clear` will restore the original (skipping the intermediate label).

---

## Caveats

### System-wide visibility

The HKLM `DirectInput` and HKLM `Joystick` targets are system-wide per VID:PID. If a real device with that VID:PID is connected while your override is active, DirectInput consumers see the override label for it too.

For VID:PIDs where you have a virtual but no real device connected (e.g. an Xbox 360 controller spoofed when no physical 360 is attached), this is exactly what you want. For VID:PIDs that might collide with a connected real device, choose your label accordingly.

### Per-user vs per-machine

The HKCU `Joystick` target is per-calling-user. On a single-user workstation that matches the DirectInput scope visually; on a multi-user machine, only the user who called `Set` sees the `joy.cpl` label change &mdash; the HKLM paths still carry the override for DirectInput consumers regardless of user.

### Cache lifetime in DirectInput / `joy.cpl`

Both DirectInput and `joy.cpl` cache OEM names per-process on first enumeration. A `joy.cpl` window that was already open when the override changes keeps showing the stale label until it is closed and re-opened. Games that were already running behave the same way. **Set before opening `joy.cpl` or launching games.**

### Admin requirement

All four methods require admin (HKLM write access). Read-only diagnostics like `ListActive` could in principle work without elevation but the API is admin-only for consistency &mdash; if you can't write, you also can't recover orphans, so denying the read closes a confusing failure mode where listing reports overrides the consumer can't actually clear.

---

## Why not just write `HKLM\...\DirectInput\...`

The naive approach &mdash; write `HKLM\...\DirectInput\VID_xxxx&PID_xxxx\OEM\"OEM Name"` and call it done &mdash; works for VID:PIDs Windows hasn't preloaded. Most clones come with a preloaded HKCU label that wins the precedence battle, and the user sees no change.

Writing only HKLM `DirectInput` was the v1.x.0 implementation. Real-world bug reports came in for clone-PID controllers showing pre-populated names like "PC TWIN SHOCK Gamepad" even after Set was called. The fix is the three-target write under a global mutex, captured before mutation. Issue #7.

---

## Implementation

The full sequence lives in `OemNameOverrideStore.cs` (~325 lines). The API surface is `HMOemNameOverride.cs` (~150 lines). Three named registry-key constants, three target descriptors, a global mutex, and the pending-hive layout. Read those files for the byte-level details.

---

## See also

- [SDK Reference](sdk-reference.md) &mdash; the raw `HMOemNameOverride` API surface in context.
- [Quickstart](../start/quickstart.md) &mdash; usage in the example/SdkDemo walkthrough (Step 0 + Step 3a).
- [`docs/oem-name-override.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/docs/oem-name-override.md) &mdash; the long-form rationale doc shipped in the repo.
