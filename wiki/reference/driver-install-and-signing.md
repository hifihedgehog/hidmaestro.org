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

Drivers, helpers, and signing tools are embedded for x64 and ARM64. Inf2Cat is the shared x86 tool. Catalog generation uses 10_X64 for x64 and 10_ARM64 for ARM64.

## Local certificate

The installer creates CN=HIDMaestroTestCert if it is absent from the machine certificate store. It uses RSA-2048, SHA-256, PKCS#1 signing, and the Code Signing EKU. The certificate expires ten years after creation.

The private key is persisted in LocalMachine\My. The certificate is also installed in LocalMachine\Root and LocalMachine\TrustedPublisher.

The installer signs HIDMaestro.dll and HMXInput.dll, generates catalogs for their INFs, signs those catalogs, and adds the packages through PnP. It does not enable Windows test-signing mode.

## Extraction and reuse

The UMDF2 payload is extracted to a directory named from its manifest hash under the temporary directory. That manifest includes the selected drivers, helper, and INFs. Different architectures produce different hashes.

The staging directory is cached across launches. It is not deleted after each install. The installed-manifest check avoids repeating deployment when matching driver packages are already available.

Installing and creating virtual devices requires administrator privileges. Reading the profile catalog does not.

## USB/IP transport

The SDK contains the unmodified installers from [usbip-win2 0.9.7.5](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.7.5), one for x64 and one for ARM64. Their Microsoft signatures are retained. Each is verified against the upstream release's SHA-256 at build time, and the extracted copy is verified again before it runs. A copy that fails the hash is replaced from the embedded bytes and never executed.

Deployment has three cases. If a usbip-win2 host controller answers, the SDK uses it as it is, whatever its version. If usbip-win2 is in the driver store and its host controller is not answering, the SDK restarts that device through CfgMgr and does not reinstall, because reinstalling would first remove the filter bound to every USB root hub. Only when no usbip-win2 exists does the SDK run the installer for the machine's architecture, silently, and wait for the host controller to appear. It never runs the vendor uninstaller.

See [platform support](../start/platform-support.md) for the version choice and validation limits.
