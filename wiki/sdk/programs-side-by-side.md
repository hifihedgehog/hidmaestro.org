# Programs Side by Side

As of v2.0.0, two or more programs that embed HIDMaestro run on one machine. Between programs on v2.0.0 or later, none removes, replaces or writes to another's controllers, driver or files, except through the remove-everything cleanup described under [Sweeps](#sweeps). A program built on HIDMaestro 1.x still can, as [Programs built on 1.x](#programs-built-on-1x) describes, and programs built on 1.x must move to 2.0.0. Through v1.12.0 two programs that each created a first controller both got index 0 and wrote each other's shared sections.

Source: the design note, [`docs/design/coexistence.md`](https://github.com/hifihedgehog/HIDMaestro/blob/master/docs/design/coexistence.md), which records each mechanism with its sources, and [`test/probes/coexist_check`](https://github.com/hifihedgehog/HIDMaestro/tree/master/test/probes/coexist_check), which runs programs side by side.

---

## What a program can rely on

Each of these holds between programs on v2.0.0 or later.

- Its controllers stay its own. No other program removes, replaces or writes to them while it runs, unless that program calls `RemoveAllVirtualControllers(HMCleanupScope.Everything, ...)`, which removes every HIDMaestro controller on the machine. A controller the calling program still holds is then left with no device until it disposes it: `DriverVersion` is null, `DeliversEveryReport` and `ReleasesOnConsumerExit` are false, and its submits reach nothing. Another program's controllers lose their devices without that change and still read the removed driver's state.
- Creates do not collide. Each controller claims a machine-wide transport index, which names its shared sections, events, owner pipe and registry key. A program running alone gets its slot numbers, as before, unless an index's names were taken by another program or a keyed create reclaims a dead program's device on another index. Two programs that each create a first controller get indices 0 and 1, unless a program built on v1.12.0 runs, as described under [Transport index](#transport-index).
- An identity belongs to one controller. Asking for an identity key another live controller holds, in any program, throws `HMResourceInUseException`. When the holder runs v2.0.0 or later, the exception names its process, image and SDK version. A v1.12.0 holder is named only as a running program built on HIDMaestro 1.12.0. The refused create does no PnP work, so the holder's devices stay as they were.
- Sweeps remove only what exited programs left. `InstallDriver`, the cleanup a program runs on its first create, and `RemoveAllVirtualControllers()` remove a device only when its program is gone.
- One driver deploy at a time, and never a downgrade. An older installed driver is upgraded whatever runs on it, and a newer one is kept. A program's running controllers keep the driver their host loaded until their device restarts.
- No program registers a device while another removes one. Every devnode registration and removal holds one machine-wide lock, as described under [Registrations and removals](#registrations-and-removals).
- Nothing runs elevated from a folder users can write. What the SDK runs elevated or hands to pnputil is staged under `%ProgramFiles%\HIDMaestro\Staging`, and every file staged from the SDK's embedded payload is checked against its SHA-256 before it runs. A WinUSB package's INF is generated from the profile, not embedded.

## Claims

A program takes an ownership claim before its first machine-wide write and holds it until it exits. Each controller claims its transport index and its identity the same way. A claim is a named pipe created with `FILE_FLAG_FIRST_PIPE_INSTANCE` and one instance. Creating it is the check: the second claimant learns it lost from the same call that would have won. Windows deletes the pipe when the process ends, however it ends, so a killed program's claims go with it. Probing a claim opens no handle, so a sweep cannot keep a dead program's claim alive.

The claims live under the pipe prefix `ProtectedPrefix\Administrators\`, where only a process whose token has Administrators enabled can create a pipe, so a program that is not elevated cannot take a claim first and pass for a running owner. A program that is not elevated takes no claim at all. In such a program, `RemoveAllVirtualControllers()` and `RemoveAllVirtualControllers(bool)` return without doing anything, `InstallDriver` returns `AlreadyCurrent` when this build's driver is installed, and a create, a deploy or anything else that takes a claim or a machine-wide lock throws `UnauthorizedAccessException`.

| Claim | Pipe | Held for |
|---|---|---|
| Owner | `\\.\pipe\ProtectedPrefix\Administrators\HIDMaestro.Owner.<owner id>` | the program, from its first machine-wide write |
| Transport index | `\\.\pipe\ProtectedPrefix\Administrators\HIDMaestro.Index.<N>` | the controller's life |
| Identity | `\\.\pipe\ProtectedPrefix\Administrators\HIDMaestro.Identity.<token>` | the controller's life |

Beside its owner claim, each program writes a record under `HKLM\SOFTWARE\HIDMaestroOwners\<owner id>`: its process id, image path, start time and SDK version, the staging directory it uses, its USB/IP server port once it has one, and one entry per live controller with its identity, transport index, backend and profile, and later its devnode instance id or vhci port. A controller's entry is written before any PnP work and removed once its devices are gone. A record whose owner claim no longer exists describes a program that has exited.

## Transport index

`HMController.TransportIndex` is the slot number when no other program uses that index, and otherwise the lowest free one. A keyless controller's default identity derives from its transport index, so when other programs are running, a keyless controller can land on another index and another identity than last time. Pass an identity key for device paths that must stay put, as the [identity key contract](sdk-reference.md#identity-keys-v180) has said since v1.8.0.

While a program built on v1.12.0 runs, a create's search starts at index 64 instead: slot 0 on 64, slot 1 on 65. A running v1.12.0 program's next create takes the lowest index free among its own controllers, whatever else runs, and replaces a device of that index's default identity as its own prior life, so a lower index would put this program's device in its path. The SDK knows such a program runs from a present device whose owner pipe the driver watches, from a USB/IP import no record names whose index's owner pipe is held, or, while a present device's index cannot be read, from the registry ledger, as described under [Sweeps](#sweeps). Everything derived from the index moves with it:

- a keyless controller's identity token, such as `HM_0064`, and with it its instance path, ParentIdPrefix, container id and HID interface path
- every controller's HID serial (`HM-CTL-0064` and up), the DualSense pairing MAC byte and the Switch Pro MAC's last byte
- a byte of the XUSB capabilities
- the USB/IP bus id, `1-<index+1>`, and a keyless composite's USB serial and USB instance id

A keyed controller keeps its paths, container id and composite USB serial, and its HID serial and MAC bytes follow the index. A program restarted after a crash gets its old index back only when that index is 64 or more. A key of the form `index:N` names index N's default identity, the one a v1.12.0 program gives its own controller on that index. While such a program runs, a create with `index:N` and N below 64 takes that identity as asked, on an index from 64, and the v1.12.0 program's next create on index N replaces a devnode of that name.

Native writers that open the shared sections themselves read the names from `HMController.SectionNames`, or compute them from `TransportIndex`. See [Shared Memory Protocol](../reference/shared-memory-protocol.md).

## Identity

The identity claim is taken before any PnP work. A create that asks for an identity key a live controller holds, in any program or in another context of the same program, is refused with `HMResourceInUseException`. Another program's sweep holds an identity's claim while it removes the device a dead program left under it, and no record lists the identity then. So while no live record lists the identity, a keyed create waits for the claim, up to 120 seconds, and then takes its census again. A keyless create waits the same way for the identity of its transport index, and keeps that index.

A context dropped without `Dispose` keeps its controllers, their transport indices and their identity keys until the process exits. A create of one of those keys in that process is refused until then, and the exception's message says so.

A v1.12.0 program takes no identity claim. When a present device carries the identity and that device's v1.12.0 program runs, the create is refused the same way.

## Sweeps

A sweep removes a present device only on proof that its program is gone. A census of the owner records and the present HIDMaestro devices decides:

| Present device | Its program | Action |
|---|---|---|
| In a record whose owner claim is gone | exited | removed, with everything the record lists, unless a running program holds the device's index or identity |
| In a live record | running | left alone, the caller's own included |
| In no live record, its index or identity claim held | a running program on v2.0.0 or later | left alone |
| In no record, its `HIDMaestroOwner<N>` pipe held by a running v1.12.0 program, as below | a running v1.12.0 program | left alone |
| In no record, no owner pipe, `Global\HIDMaestroInputAck<N>` present | a v1.12.0 program that has exited | removed |
| In no record, no owner pipe, no InputAck section | a program older than v1.12.0, state unknown | left alone |

A device with an identity token belongs to the record that lists its token. Only a device older than identity tokens is matched to a record by its index, since a running v1.12.0 program takes indices without looking at other programs. A program on v2.0.0 or later takes its claims before it writes its record entry, so a device whose index or identity claim is held is a running program's, with or without a record.

The census reads a device's index from its `Device Parameters\ControllerIndex`, and logs why when it reads none: no value, no key, or a key it may not read. A keyless device's token, `HM_<index>`, names its index, so the census takes the index from there and the allocator skips that one index. A keyed device with no readable index is tied to no owner pipe. With no record naming it, it counts as the device of a program whose state is unknown, and a sweep leaves it. A dead record that names it still makes it removable.

While such a device is present, the census looks for a running v1.12.0 program in the registry ledger. A v1.12.0 create writes a holder `<pid>-<start>-<index>` under `HKLM\SOFTWARE\HIDMaestroRegistryLedger\JoystickOem\<VID&PID>\Holders` before its devnode exists, for every controller but a keyboard or mouse, and removes it at teardown. A v2.0.0 program writes the same holders only after its owner record, and its exit deletes the record only once its holders are gone. So a holder on an index below 64 whose process runs and that no live record names belongs to a v1.12.0 program, and it raises the floor to 64. The census reads the holders, then the records, then the holders again, and counts a holder both reads have. It also counts an index that no live record and no present device accounts for when its owner pipe is held beside its input section and an acknowledgement section without the ended marker. One case stays unseen: a v1.12.0 program of only keyboards and mice, or one whose ledger write failed, whose device's index cannot be read, on an index a running v2.0.0 program holds. A device a closed program left raises no floor.

A v1.12.0 program creates its owner pipe unprotected, so any program can create one under the same name, and a held pipe alone does not keep a device. The driver is that pipe's client. When its owner watch connects, it records the pipe's server process and owner, and that the watch is connected, in the device's `Device Parameters\HIDMaestro` registry key. When the watch ends, it records that it is no longer connected and marks the end of the watch in the device's `InputAck` section. Where those records exist, the pipe stops counting once they show the watched program gone: the watch has ended, or the server it named no longer runs. Where they do not, as on a driver older than v2.0.0, the pipe counts only while `Global\HIDMaestroInput<N>` and `Global\HIDMaestroInputAck<N>` exist and the acknowledgement section does not mark the watch ended. A program that is not elevated can create neither section.

A device from a program older than v1.12.0 leaves no sign of whether its program still runs, so it is never removed on a guess. `RemoveAllVirtualControllers(HMCleanupScope.Everything, preserveInstall)` removes it, along with every other HIDMaestro device on the machine, a running program's included. That is what an uninstaller, a test harness or a support tool calls.

A sweep takes each dead group's index and identity claims before it acts on the group, and keeps them until every group it removes, and every orphaned HID child it removes after them, is out of the device tree, waiting up to 10 seconds for each orphan. A create on v2.0.0 or later takes both claims before it writes its configuration or makes a device, so none lands on a group a sweep holds, and a sweep skips a group whose claims another program holds. A v1.12.0 program takes no claim, so its owner pipe is checked again right before each removal. A group the sweep cannot confirm gone keeps its configuration and its dead record, so the next sweep still sees a dead owner's device.

USB/IP imports are matched to their program by the server port its record names. An import whose server no longer listens is detached.

The default cleanup, `RemoveAllVirtualControllers()` and `(bool)`, also removes the GameInput tables HIDMaestro wrote through v1.11.0, as v1.12.0's cleanup did, where no running program uses them. A table stays while a present device or any `Controller<N>` configuration carries its VID and PID, and every table stays while an input section exists that nothing explains, which is a v1.11.0 create still in flight.

## Exit and the phantom cleanup

A program that exits normally without disposing its controllers has their devices removed by the SDK's own `ProcessExit` handler. The handler waits at most 10 seconds, in all, for the phantom cleanup below and for a create in flight, then removes the devices to the end, as `Dispose` does. Its removals take the PnP lock within what is left of those 10 seconds, counting only the time another program holds it. The devices stay present, in the program's record, until a program on v2.0.0 or later next sweeps, when:

- a create of the program still holds on at the 10 seconds, on another thread, waiting for another program's sweep or behind a transport install
- one phantom uninstall of the cleanup outlasts the 10 seconds
- a device does not leave
- another program holds the PnP lock past what is left of the 10 seconds
- under .NET, a thread inside a create calls `Environment.Exit`

The exit deletes the program's record only once its GameInput and joy.cpl holds are released, and a hold of its own that still stands keeps the record until the process ends. A killed program runs no exit handler, and its devices go with the next sweep of any program on the machine.

A `Dispose` or cleanup the program calls from its own `ProcessExit` handler waits for another program's hold of the PnP lock within one 10-second budget the whole process shares. A controller it cuts short keeps its devices and its record entry. The runtime runs `ProcessExit` handlers in the order they were added, and the SDK adds its own at the program's first create, `InstallDriver` or cleanup. When the program's handler came first, the SDK's handler runs next and removes such a controller within its own 10 seconds. Otherwise the next sweep removes it.

The records Windows keeps of removed devices, the phantoms, go with a cleanup that runs once per process on a background thread, started by the first of `InstallDriver`, the first create and `RemoveAllVirtualControllers()`. The call that starts it does not wait for it, and a later call removes no phantom. A create in the program, and the `Everything` cleanup, wait while it runs: one pass over the phantoms and their uninstalls, and two passes over interface registrations, with at most 5 seconds of waiting in all, for the PnP lock and for Windows to let each phantom go. Each uninstall runs under the identity claim of the phantom's controller, and a phantom whose claim another program holds is skipped.

When the program's first such call comes inside a `ProcessExit` handler of its own, the call runs the cleanup on the calling thread before it returns. The SDK learns that exit has begun from `AssemblyLoadContext.Default.Unloading`, which the runtime raises before `ProcessExit`. Under .NET it cannot learn it when no code that refers to the SDK ran or was compiled before exit began, such as in a program that uses the SDK only inside that handler, and the cleanup then ends with the process. The next process's first cleanup removes what is left.

## Driver deploys

Deploys take the machine-wide deploy lock, `HIDMaestro.Admin\Deploy` (see [Machine-wide locks](#machine-wide-locks)). Of two programs calling `InstallDriver` at once, one deploys and the other finds the result current. The installed version is the newest `DriverVer` among the `hidmaestro.inf` packages in the driver store.

| Installed driver | What `InstallDriver` does | `LastDriverInstall` |
|---|---|---|
| none | installs its own | `Installed` |
| its own, with both packages present | nothing | `AlreadyCurrent` |
| its own, with a package missing | adds the missing package and installs nothing else | `Installed` |
| newer | keeps it, and runs on it | `KeptNewer` |
| older, from 1.x or an older 2.0.0 build, nothing on it | a full deploy that removes the old packages | `Upgraded` |
| older, devices or a create of another program on it | adds this build's packages beside the old ones and updates no present device | `Upgraded` |

The 2.0.0 driver takes precedence over every older one, and nothing is refused because another program's devices hold an older driver. The add beside it updates no present device, so those controllers keep the driver their host loaded until their device restarts, while every device a 2.0.0 program creates binds the newest package.

A create installs the driver on its own devnode only, with `DiInstallDevice`. Through v1.12.0 it used `UpdateDriverForPlugAndPlayDevices` with the profile's hardware ID, which installs on every present device of that ID.

## Machine-wide locks

The locks are mutexes in a private object namespace whose boundary holds the Administrators SID and whose DACL admits SYSTEM and Administrators. A program that is not elevated can neither create nor open it, so no such program can take a lock first and hold every HIDMaestro program behind it. Each name below is the namespace alias, `HIDMaestro.Admin`, and the lock's own name.

| Lock | Held for |
|---|---|
| `HIDMaestro.Admin\Deploy` | a driver deploy past its fast path, the deploy gate of a UMDF2 create, the driver package removal, the add of a WinUSB package, the test certificate's creation, and the public `DriverBuilder` steps `SignDrivers`, `GenerateCatalogs` and `RemoveOldDriverPackages`. Waits 10 minutes, then throws `InvalidOperationException` |
| `HIDMaestro.Admin\Transport` | the usbip-win2 install, the repair of a host controller that stopped answering, and the move off an older host controller, each on a thread of its own, so a UMDF2 create never waits for them |
| `HIDMaestro.Admin\WinUsb` | the devnode work of a WinUSB binding: a bind's claim and install, a restore, and the cleanup |
| `HIDMaestro.Admin\WinUsbFollowUp.<entry>` | one per WinUSB entry, held by the program that watches that entry's devnode until it is gone |
| `HIDMaestro.Admin\Ledger` | every registry ledger and OEM name override operation, on the registry keys a virtual shares with real devices. Most calls wait without a bound. WinUSB claims, restores and package note reads give up after 30 s, scaled by `HIDMAESTRO_TIMEOUT_SCALE`, with `TimeoutException` |
| `HIDMaestro.Admin\Staging` | a program's note of the staging directory it uses, and a deploy's prune of the directories no running program names |
| `HIDMaestro.Admin\Pnp` | each devnode registration and each removal, and the other devnode work listed under [Registrations and removals](#registrations-and-removals). Waits 10 minutes, then throws `InvalidOperationException`. Once the process is exiting, it waits only what is left of the exit's 10 seconds |

The ledger's lock also takes v1.12.0's `Global\HIDMaestro-OEM-Recovery` after its own, because v1.12.0 programs write the same GameInput and joy.cpl keys under that name, and any program can create that name first. When SYSTEM or Administrators owns it, the lock waits for it as v1.12.0 does. When anyone else owns it, or its owner cannot be read, the lock waits five seconds and goes on without it. Once a wait has run its full five seconds, later acquisitions in that process wait 500 ms, until one takes the mutex or finds it owned by SYSTEM or Administrators again. Both bounds are scaled by `HIDMAESTRO_TIMEOUT_SCALE`. A caller's own bound, the 30 seconds of the WinUSB claims and restores, covers both mutexes, and a wait it cuts short throws `TimeoutException` whoever owns the legacy mutex. OEM name override calls wait without a bound.

A program takes them in one order, deploy, then WinUSB, then the ledger, and never the other way around. The transport lock is taken on a thread that holds no other machine-wide lock. The PnP lock comes after the deploy lock and before the staging lock, and is never held with the WinUSB, follow-up, ledger or transport locks. The staging lock is taken last, with nothing else taken under it.

## Registrations and removals

Every devnode registration and removal a program on v2.0.0 or later makes holds the machine-wide lock `HIDMaestro.Admin\Pnp`, so no such program registers a device while another removes one. One hold covers one registration or one removal, never both. The lock is held for:

- each devnode registration, from the registration gate's last checks through `DIF_REGISTERDEVICE`, or `SwDeviceCreate` for the two software companions
- each removal and uninstall, from its call through its removal test: a device with its children, its fallbacks and the SWD helper's close, each orphaned HID child, and each phantom record
- a full deploy's `pnputil /add-driver /install`, which reinstalls every present devnode the package matches, other programs' controllers included
- each create's bus type stamp on the parent it made
- the ghost XUSB interface sweep and the interface-class cleanup, each per devnode

These change devnodes without the lock: the surprise removal a `Dispose` asks of a ROOT device's driver when a program refuses its removal query (v2.0.0), a USB/IP import's attach and detach, the host controller's driver update on a transport swap, a WinUSB bind's `DiInstallDevice`, a registration's `DiInstallDevice` once its hold has ended, and every program built before v2.0.0. So do, on a controller's own devnodes or on residue, the naming writes after a registration, `RestartDevice`, the package removal's `pnputil /delete-driver`, the usbip-win2 host controller's repair and installer, and a WinUSB restore's reinstall flag on a devnode that has left. S77 lists each of these calls and fails on a devnode change made anywhere else outside the lock. Its source check does not see the surprise removal, which the SDK starts by signaling an event.

Another program waits up to ten minutes for the lock, then throws `InvalidOperationException`. Threads of one process queue on an in-process gate first, so the bound counts only other programs' holds. The longest hold is one removal, whose budgets add up to about 150 seconds for a devnode with a few children.

### The registration gate

Everything that takes time happens before the lock. Rivals for the device's ParentIdPrefix are removed. hidclass names a child after its parent's enumerator segment and ParentIdPrefix, so as of v2.0.0 a rival is a parent under the create's enumerator, in ROOT or SWD, on a prefix the create's child can arrive under, or the same token under another HIDMaestro ROOT enumerator. A prior life of its id that is still in the tree or, for a ROOT id, still on record is removed too, each removal in a hold of its own. The gate then waits up to 30 seconds for Windows' pending device installs with `CMP_WaitNoPendingInstallEvents`. Last, it takes the lock and looks once more, removing and waiting for nothing. When a rival or a prior life has come back, or an install is pending while the 30 seconds have time left, it lets the lock go and goes round again, up to three times for what came back. An install still pending when the 30 seconds end does not stop the registration, since it can belong to any device on the machine, and is logged. A failed wait refuses the registration, and so does a prior life whose removal ends `NotGone`.

Learn says not to call `CMP_WaitNoPendingInstallEvents` "while processing any events inside of a system-initiated callback function that is expected to return within a short amount of time", which includes a service's `ServiceMain` and its control handler ([CM_WaitNoPendingInstallEvents](https://learn.microsoft.com/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_waitnopendinginstallevents)). A service should not call `CreateController` from either.

A software companion's create that runs past its 15 seconds is retried after 1.5 seconds and then 3 seconds, on the same id and inside the same hold, with a removal test on the id after each attempt that timed out. A device still in the tree ends the attempts.

### The removal test

Every removal ends on a test with one of three outcomes. The devnode must be out of the tree, so a `CM_LOCATE_DEVNODE_NORMAL` locate fails. An uninstall, a ROOT or HID id removed with `SetupDiRemoveDevice` or `CM_Uninstall_DevNode`, also needs its record gone, so a `CM_LOCATE_DEVNODE_PHANTOM` locate fails. A devnode that was in the tree when the wait began must then deliver `CM_NOTIFY_ACTION_DEVICEINSTANCEREMOVED` within 2 seconds more. A HID child removed with its parent counts on the parent's notification.

| Outcome | When | What follows |
|---|---|---|
| `Removed` | the notification arrived | nothing |
| `GoneWithoutRemoved` | the devnode and its record are gone, and the notification is not | logged and counted, never refused |
| `NotGone` | the devnode, or the record an uninstall should have deleted, is still there when the budget ends | the next registration of that id is refused |

Through v1.12.0 a failed NORMAL locate ended the wait. No locate passes `CM_LOCATE_DEVNODE_CANCELREMOVE`, which cancels a removal in progress.

Each removal gets the budget it needs. A parent removed with `SetupDiRemoveDevice` or `SwDeviceClose`, which can wait on open handles, gets its caller's: 120 seconds for a create's prior life. A removal whose call finishes its work before it returns gets 2 seconds: a child, a fast removal, an orphan, a phantom, and the pnputil and devcon fallbacks. A software device's record is never waited for. The `Everything` cleanup now waits up to 2 seconds per removal, where it waited for none, and a teardown's surviving HID child waits 2 seconds, where it waited its caller's 120.

The HID orphan sweep looks for an orphan's parent again under the lock, and leaves a child whose parent came back while it waited.

### Creates that now fail

A create throws `InvalidOperationException`:

- when another program holds the PnP lock for ten minutes
- when its ROOT devnode's prior life, or that devnode's record, is still there after its removal
- when another program still holds its previous device open and Windows has that device marked for removal, within about 2 s, and the message says so
- when a software companion's prior life is still in the tree after its removal
- when the wait for pending installs fails
- when what the gate removed comes back three times
- when a gamepad or XUSB companion is not made, for any reason, and the message names it. Through v1.12.0 the create succeeded without it: an xinputhid controller had no other device, and an Xbox 360 controller got no XInput.

A failed create's cleanup removes what it made, its parent by the instance ID the registration gave it, so a plain HID parent under `ROOT\HIDClass`, which no sweep by index reaches, goes too. A create no longer restarts a leftover `ROOT\XNACOMPOSITE\0000`. Since v1.8.0 that devnode belongs to a program built before v1.8.0 or is residue, so the restart could take another program's devnode down.

### The cost

Removals run one at a time, in a program and across programs, so a dispose of several controllers takes about the sum of their removals, where it took about the longest one, and another program's create or removal waits that long too. Each removal also waits for its notification, up to 2 seconds more when it is late. No dispose time for v2.0.0 has been measured, and every dispose figure elsewhere on this site was measured before v2.0.0.

## Programs built on 1.x

Programs built on HIDMaestro 1.x must move to 2.0.0. [Moving from 1.x](../start/migration.md) lists every change a 1.x program meets.

A v2.0.0 program takes precedence over a 1.x program. It installs its driver over any older one, whatever runs on it, and refuses nothing because a 1.x program is in the way. Its sweeps still never remove the controllers of a running v1.12.0 program, which they recognize by its owner pipes and by what the driver records about them. A 1.x program's running controllers keep the driver they loaded until their device restarts. On the 2.0.0 driver a 1.x controller keeps its input and output and gets no feature answers, which the driver serves only for a 2.0.0 SDK's controller, so a Sony profile created by a 1.x program loses its calibration, pairing and firmware replies, and a Bluetooth DualSense or DualShock 4 its extended report.

A 1.x program makes no such promise:

- A running v1.12.0 program's `InstallDriver` and its first create in a session each remove every HIDMaestro device on the machine, v2.0.0 controllers included, and its `InstallDriver` replaces the installed driver with its own whenever the payload differs. Every older program does the same.
- With no controller present at the moment of the v2.0.0 program's create, it leaves no sign, so that create does not start at 64, and the v1.12.0 program's next create can take the v2.0.0 program's low index.
- Its `CreateControllerAt(index)` takes whatever index it is given.
- It reaches index 64 with 65 controllers alive at once.
- A v1.12.0 program whose device's index cannot be read is found by the registry ledger holder each of its creates writes, except one that runs only keyboards and mice.

- v1.8.0 and v1.8.1 must not run on a machine that runs a later release. They run no ParentIdPrefix rival scan, and a v1.8.x create of `index:N` beside a later release's `HM_000N` parent on the same enumerator makes the machine stop at every boot.

Moving every program on the machine to 2.0.0 is the fix.

## What is verified

- S71 runs programs side by side as separate processes. Keyless creates land on their own indices, and each device carries only its own program's input. An identity a live program holds is refused with the holder named. A second program's install and create leave the first program's devices, XInput slot, WGI and Raw Input entries alone, and the first program's frame gaps stay within its one-program p99, with a small allowance for the spread between two baseline runs. A killed program's devices go with the next sweep while a live program's stay. Peers built on v1.12.0 and v1.11.0 run beside this release through each branch of the install policy. Sections E6 and E7 reach the policy through a create alone: beside a running v1.12.0 program's controller, a generic pad's input arrives, a `dualsense-bt` answers SDL's calibration read and an `xbox-360-wired` gets its XUSB interface on this release's companion while the older controller keeps its device and driver, and once that program has gone the same creates upgrade the driver in full. Two programs deploy at once on a machine without the driver, two USB/IP composites keep each other's imports, and a killed program's claims go even while a child it started still runs. Further sections pit a thread acting as a program that is not elevated against the SDK's and the driver's machine-wide names, the deploy and ledger locks and the claims included, and cover the driver's owner watch, the transport and WinUSB locks, a WinUSB binding that follows a dropped adapter, and pnputil run from System32. Section W runs sweeps beside running programs: a killed program's device whose claims another program holds is left, a sweep holding a dead group's claims while the restarted program creates the same identity, creates beside a running v1.12.0 program landing clear of its indices, and an `index:N` below 64 created as asked, the exit handler beside a create in flight and a handler of the program's own, and v1.11.0 GameInput tables kept while their device or a v1.11.0 create in flight needs them.
- S77 feeds the removal test and the registration gate recorded sequences, with no device, and fails when either answers before the DEVICEINSTANCEREMOVED notification and the PHANTOM record's removal, or a locate cancels a removal. It checks the PnP lock's bounds during the exit and fails on a devnode change made outside the lock other than the ones listed above. Its live part disposes a DualShock 4, an Xbox 360 wired and an Xbox Series over Bluetooth and fails on a removal that ended with its devnode still there, on a devnode that left without DEVICEINSTANCEREMOVED, and on a refused registration.
- S72 checks the staging. Every directory on the path is writable only by Administrators and SYSTEM, and `hmswd.exe` is no longer staged in `%TEMP%`. A staged tool overwritten with other bytes of the same length is restored from the embedded copy, a staging directory replaced by a link is moved aside rather than followed, and a deploy prunes the staging of versions no running program uses. Its offline part also runs the census over registry keys, with no device: a device whose transport index cannot be read, the ledger holders that raise the floor of 64, and the exit that keeps its record while a hold of its own stands.
