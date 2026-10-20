---
title: Start
---

# Start

Everything between an empty project and a live virtual controller.

- **[Installation](installation.md)**: reference `HIDMaestro.Core.dll` from
  a release ZIP or build from source. The driver install is
  self-bootstrapping: no EV certificate, no test-signing mode, no manual
  signing. Windows 10/11 x64 and Windows 11 ARM64, .NET 10, admin required for
  `CreateController`.
- **[Quickstart](quickstart.md)**: the `example/SdkDemo` walkthrough. Load
  the embedded profile catalog, install the driver, create a DualSense and
  an Xbox 360 Wired side by side, push input, capture rumble.
- **[Glossary](glossary.md)**: XUSB, WinExInput, SWD, ContainerID, &IG_,
  mshidumdf, GIP. The terms that show up everywhere else in these docs.
- **[Moving from 1.x](migration.md)**: programs built on HIDMaestro 1.x
  must move to 2.0.0. Every profile key 2.0.0 refuses, every changed
  exception, and what changes on the wire, at create, at cleanup and on
  the driver.
