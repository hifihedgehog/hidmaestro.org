# Driver installation and signing

Standard profiles use HIDMaestro's UMDF2 DLLs and a locally trusted signing certificate. Composite profiles use bundled Microsoft-signed USB/IP kernel-driver packages.

## Native payloads

The AnyCPU SDK selects native files from the operating system architecture, including when an x64 consumer runs under emulation on ARM64 Windows.

| Resource | Purpose |
|---|---|
| HIDMaestro.dll | Main HID driver |
| HMXInput.dll | XInput companion |
| hmswd.exe | Device creation and USB/IP root helper |
| hidmaestro.inf, hidmaestro_xusb.inf | Architecture-specific, stamped INFs |
| signtool.exe and dependencies | Signing tools for the selected OS |
| Inf2Cat.exe and dependencies | Catalog generation |
| Profile JSON files | Controller identities and report layouts |

Official releases embed the drivers, helpers and signing tools for x64 and ARM64. A build from source can leave out the ARM64 payload or the USB/IP transport, and `HMBuildInfo` reports what a build carries (see [Build and Release](build-and-release.md)). One Inf2Cat serves both architectures. It is an x64 .NET program, which Windows 11 on ARM64 runs under its x64 emulation. Catalog generation uses 10_X64 for x64 and 10_RS3_ARM64 for ARM64.

## Local certificate

The installer creates CN=HIDMaestroTestCert if it is absent from the machine certificate store. It uses RSA-2048, SHA-256, PKCS#1 signing, and the Code Signing EKU. The certificate expires ten years after creation.

The private key is persisted in LocalMachine\My. The certificate is also installed in LocalMachine\Root and LocalMachine\TrustedPublisher.

The installer signs HIDMaestro.dll and HMXInput.dll, generates catalogs for their INFs, signs those catalogs, and adds the packages through PnP. It does not enable Windows test-signing mode.

## Staging

As of v2.0.0, everything the elevated SDK runs or hands to pnputil is staged per version and per operation under `%ProgramFiles%\HIDMaestro\Staging\<version>-<hash>\<operation>`, where the hash is the first 16 hex characters of the embedded driver payload's SHA-256. The operations are `driver` (the embedded driver binaries, both INFs, signtool and Inf2Cat), `package` (one deploy's binaries and INFs, signed and cataloged), `swd` (hmswd.exe), `usbip` (the usbip-win2 installer), `usbip-ude` (the host controller package forced onto an older transport) and `winusb-<profile id>` (one profile's WinUSB package). A deploy stages the binaries fresh into `package` and checks their SHA-256 again just before signing, so another process staging the payload cannot put unsigned bytes under a package being signed. Through v1.12.0 the payload went to `%TEMP%`, which a process of the same user that is not elevated can write.

Program Files grants Users read and execute and nothing else, so no program without elevation can create a folder there before HIDMaestro does. `%ProgramData%` lets Users add folders, which is why staging moved, before release, from `%ProgramData%` to `%ProgramFiles%`. Every directory from `%ProgramFiles%\HIDMaestro` down is created with its security descriptor in the same call, `O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)`, so none exists with an inherited ACL.

Each use checks every directory on its path. A directory passes when it is not a reparse point, its owner is Administrators or SYSTEM, and no allow entry grants a write-class right (write data, append data, write attributes or extended attributes, delete, delete child, change permissions, take ownership) to anyone but SYSTEM, Administrators and TrustedInstaller. `%ProgramFiles%\HIDMaestro` is reset in place when SYSTEM or Administrators own it and nobody else may change its permissions or owner or delete it or its entries, and refused with `InvalidOperationException` otherwise, since a hostile one there is another program's. `Staging`, a version or an operation directory that fails is moved aside to `<name>.untrusted-<guid>` and created again. One that cannot be moved is refused when it is hostile in the same sense, and reset in place when only its permissions are wrong. A moved-aside tree is left where it is and never deleted. A directory another program creates between the check and the create is refused too.

Every elevated use of a staged file runs inside a pin. `Staging` and each directory below it down to the one in use are held open without delete sharing, which no rename or delete of them can get past. Each staged file is held for reading with read sharing only, which no write, rename or delete gets past, and checked against its SHA-256 through that hold: the embedded bytes, or the pinned release hash for the usbip-win2 files. A driver binary is checked right before signtool rewrites it and held once signed. The pin lasts until the use is over: the driver package's sign, catalog and add, hmswd's runs, the usbip-win2 installer's run, the host controller package's install and each WinUSB package's catalog and add. A file is written under a temporary name, verified, then renamed into place, and reuse trusts no file size. hmswd.exe always comes from the embedded resource, never from beside the assembly.

An elevated child gets a protected TEMP. hmswd, the usbip-win2 installer, signtool and Inf2Cat run with their own staging directory as working directory, TEMP and TMP. pnputil and devcon get `%ProgramFiles%\HIDMaestro\childtemp\<process id>-<start time>`, a folder per process with the staging descriptor. An elevated tool that cannot have one does not run with the user's `%TEMP%`: the operation fails with `InvalidOperationException`, and a cleanup that only tries skips the tool and logs it. reg.exe and sc.exe, run from System32, keep the caller's TEMP.

The diagnostic logs, `teardown_diag.log` under `HIDMAESTRO_DIAG=1` and `setup_timing.log` under `HIDMAESTRO_TIMING=1`, stay in `%TEMP%\HIDMaestro` and are written with the user's own rights: the elevated half of a split UAC token writes them through a medium-integrity token of the same user. So is the USB/IP read log at the path `HIDMAESTRO_DIAG_READS` names. hmswd's exit code and output go into `teardown_diag.log` when diagnostics are on. The per-create `hmswd_<enumerator>_<suffix>.log` is no longer written, and hmswd.exe keeps no self-log at all, run by the SDK or by hand, so `hmswd_self.log` is never written.

The staging directory is reused across launches. A deploy deletes the staging of every version that no running program's owner record names, and the `childtemp` folder of every process that no longer runs. A moved-aside directory is never pruned. The installed-manifest check avoids repeating deployment when this build's driver packages are already installed, and on that path nothing is staged at all.

The OpenVR driver is the one exception and stays under `%ProgramData%\HIDMaestro\openvr\hidmaestro`. SteamVR loads the driver name `hidmaestro` from one registered path, and a v1.12.0 program running beside this one registers that path again, so a driver moved anywhere else would be registered twice. Nothing the elevated SDK runs, loads or hands to a tool lives there. See [VR Controllers](../sdk/vr-controllers.md).

Installing and creating virtual devices requires administrator privileges. Reading the profile catalog does not.

## Which driver a machine runs

Several programs that embed HIDMaestro 2.0.0 can share a machine. Every driver deploy holds the machine-wide deploy lock, `HIDMaestro.Admin\Deploy`, for one call, and re-reads the installed state once it holds it. The lock is a mutex in a private namespace that only an elevated program can create or open, so no other program can take it first. The USB/IP transport's install holds a lock of its own, `HIDMaestro.Admin\Transport` (see [USB/IP transport](#usbip-transport)). [Programs Side by Side](../sdk/programs-side-by-side.md#machine-wide-locks) lists every lock. The installed version is the newest `DriverVer` among the `hidmaestro.inf` packages in the driver store. Stamps compare by release version first, then build date, then build number.

| Installed driver | `InstallDriver` | `HMContext.LastDriverInstall` |
|---|---|---|
| none | installs this SDK's | `Installed` |
| this SDK's payload | nothing | `AlreadyCurrent` |
| this SDK's stamp, both packages present, its record missing | restores the record, reinstalls nothing | `AlreadyCurrent` |
| this SDK's stamp, a package missing | adds the missing package and moves no device onto it | `Installed` |
| newer | keeps it: a driver is never downgraded | `KeptNewer` |
| older, from 1.x or an older 2.0.0 build, nothing on it | a full deploy that removes the old packages | `Upgraded` |
| older, devices or a create of another program on it | adds this build's packages beside the old ones and updates no present device | `Upgraded` |

The 2.0.0 driver takes precedence over every older one, and nothing is refused because another program's devices hold an older driver. The add beside it updates no present device, so those controllers keep the driver their host loaded until their device restarts, while every device a 2.0.0 program creates binds the newest package. Programs built on 1.x must move to 2.0.0: see [Moving from 1.x](../start/migration.md).

A create installs the driver on its own devnode only, with `DiInstallDevice`. With no driver named, `DiInstallDevice` searches the driver store for the best match, and that search was about half of a DualShock 4 create's time. Since v2.0.0 the SDK keeps the INF the search chose for a set of hardware and compatible IDs, with the state of the driver store it chose in: the installed-payload record every deploy rewrites and the last write of the store's `FileRepository` folder. While both are unchanged, a create builds the driver list from that one INF (`DI_ENUMSINGLEINF`), takes the best rank and passes that driver to `DiInstallDevice`. The choice is kept in the process and under `HKLM\SOFTWARE\HIDMaestro\StoreDriverChoice`, one value per set of IDs, so a program's first create skips the search too, and the key goes with `SOFTWARE\HIDMaestro` when the packages are removed. A failure, a tie of ranks or a missing INF forgets the choice, and the create searches as before. Through v1.12.0 a create used `UpdateDriverForPlugAndPlayDevices` with the profile's hardware ID, which installs the package on every present device of that ID.

## WinUSB binding packages

`HMController.BindWinUsb()` generates a driver package per profile from its descriptors, `hmwinusb_<profile id>.inf`, signs its catalog with the same local certificate, and adds it to the driver store without installing it anywhere. The add runs under the deploy lock, and the devnode work under `HIDMaestro.Admin\WinUsb`. The INF includes and needs winusb.inf and registers the profile's interface GUID. It matches only the vendor-scoped compatible ID `USB\COMPAT_VID_vvvv&Class_cc&SubClass_ss&Prot_pp`, behind fifteen IDs no device carries, so it ranks below input.inf for every real device. The bind confirms that another driver outranks the package on the devnode, then installs it there alone with `DiInstallDevice`. No driver is ever installed on a present devnode after that. Once the binding's last holder lets go and the devnode is gone, it gets `CONFIGFLAG_REINSTALL`, so its next arrival installs by rank. The uninstall-grade cleanup removes no devnode, and keeps a WinUSB package that a gone devnode still uses. A package it keeps is noted by INF name in `HKLM\SOFTWARE\HIDMaestroPackagesLeft`, value `WinUsb` (`REG_MULTI_SZ`), and the first sweep of each later program that finds the note removes the noted packages no devnode, present or gone, still uses, and keeps the rest noted. See [Wii U GameCube Adapter](../sdk/gamecube-adapter.md#dolphin-slippi-and-sdl).

## USB/IP transport

The SDK contains the unmodified usbip-win2 0.9.8.1 installers, one for x64 and one for ARM64. The x64 one is the [release asset](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.8.1). The ARM64 one is the same tag's build from the project's signing service, posted in [usbip-win2#13](https://github.com/vadimgrn/usbip-win2/issues/13), since the release page carries x64 only. Their Microsoft driver signatures are retained. Each is checked against its pinned SHA-256 at build time, and the extracted copy is checked again before it runs. A copy that fails the hash is replaced from the embedded bytes and never executed.

Deployment has four cases. If the host controller that answers is one HIDMaestro installed, 0.9.7.7 or 0.9.7.5, and nothing has used it in this Windows session, the SDK moves it to 0.9.8.1: it stages the embedded usbip2_ude INF, SYS and CAT, verified against their pinned hashes, and the hmswd.exe helper forces that INF onto the controller with UpdateDriverForPlugAndPlayDevices under a time limit. The filter is not touched, and the old package is deleted only once the 0.9.8.1 image is the one the service loads. If any other usbip-win2 host controller answers, the SDK uses it as it is, in whichever of the 0.9.7.x, 0.9.8.0 and 0.9.8.1 request layouts it speaks. If usbip-win2 is in the driver store and its host controller is not answering, the SDK restarts that device through CfgMgr and does not reinstall, because reinstalling would first remove the filter bound to every USB root hub. Only when no usbip-win2 exists, neither in the driver store nor as an installer record under `{199505b0-b93d-4521-a8c7-897818e0205a}_is1`, in any of the three places the installer itself looks, whose uninstaller file is still there, does the SDK run the installer for the machine's architecture and wait for the host controller to appear. It never runs the vendor uninstaller, and it never runs the installer over an existing copy, which would uninstall that copy first.

The install, the restart of a host controller that stopped answering, and the move off an older one run on a thread of their own under the machine-wide lock `HIDMaestro.Admin\Transport`, and read the machine again once they hold it. Of two programs whose first composites arrive together, one installs and the other finds the host controller. A UMDF2 create never waits for this lock. A restart whose PnP work outlives its time limit keeps the lock until that work returns, for as long as its program runs. The installer declares no setup mutex, so before it starts one the SDK waits up to five minutes for any usbip-win2 installer still running, such as one a killed program left. An installer that ends with an error does not fail the create on its own: the SDK waits for every usbip-win2 installer to end and reads the machine. With the driver package in the store, a host controller that answers counts as installed. A machine with nothing of usbip-win2 on it gets the installer once more. Anything between fails the create. `InstallUsbipBackend`'s progress callback runs on the caller's thread with no machine-wide lock held, and an exception it throws is dropped. pnputil runs from System32 by its full path.

As of v2.0.0 the installer runs with the smallest set it allows:

```
/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /COMPONENTS=main,client /TASKS=vcredist /NOICONS
```

That leaves out the GUI, the SDK headers, the debug symbols, the desktop icon and the Start menu folder. `main` and `client` cannot be deselected. `client` is the drivers. The VC++ runtime stays, because `devnode.exe` and the `libusbip.dll` it loads need it. `/NORESTART` is required, since the installer restarts the machine without asking otherwise. What the installer leaves and its command line cannot remove: `usbip.exe`, `devnode.exe`, `libusbip.dll`, `resources.dll` and `Readme.md` under Program Files, the uninstaller and its Apps entry, the scheduled task "USBip Detach All On Reboot Or Shutdown", and the VC++ runtime. Battery scenario S73 runs the install in Windows Sandbox and finds no Start menu folder, desktop shortcut, GUI, SDK or debug file afterward, the VC++ runtime in place, and a composite persona carrying input. It also checks that a machine holding the installer's record and its uninstaller file, without its driver, gets a refusal instead of an uninstall.

See [platform support](../start/platform-support.md) for the version choice and validation limits.
