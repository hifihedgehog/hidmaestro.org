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

Drivers, helpers, and signing tools are embedded for x64 and ARM64. Inf2Cat is the shared x86 tool. Catalog generation uses 10_X64 for x64 and 10_CO_ARM64 for ARM64.

## Local certificate

The installer creates CN=HIDMaestroTestCert if it is absent from the machine certificate store. It uses RSA-2048, SHA-256, PKCS#1 signing, and the Code Signing EKU. The certificate expires ten years after creation.

The private key is persisted in LocalMachine\My. The certificate is also installed in LocalMachine\Root and LocalMachine\TrustedPublisher.

The installer signs HIDMaestro.dll and HMXInput.dll, generates catalogs for their INFs, signs those catalogs, and adds the packages through PnP. It does not enable Windows test-signing mode.

## Extraction and reuse

The UMDF2 payload is extracted to a directory named from its manifest hash under the temporary directory. That manifest includes the selected drivers, helper, and INFs. Different architectures produce different hashes.

The staging directory is cached across launches. It is not deleted after each install. The installed-manifest check avoids repeating deployment when matching driver packages are already available.

Installing and creating virtual devices requires administrator privileges. Reading the profile catalog does not.

## USB/IP transport

The SDK contains the unmodified signed packages from [usbip-win2 0.9.7.7](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.7.7). Their Microsoft signatures are retained.

The updater uses an administrator-only staging directory. It refuses an update while USB/IP imports are active, adds the new packages in place, and creates or restarts the required USB/IP host controller. It does not invoke the vendor uninstaller or delete the shared root-hub filter package.

Readiness requires matching configured binary hashes, loaded driver paths, and IOCTL layout. On Windows 11 24H2 and later, the loaded-image query needs SeDebugPrivilege. The query uses a temporary impersonation token and restores the caller's context.

A staged package is not necessarily active. The updater checks activation before reporting success. See [platform support](../start/platform-support.md) for compatibility and validation limits.
