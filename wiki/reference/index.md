---
title: Technical Reference
---

# Technical Reference

Every layer of HIDMaestro from the C# SDK down to the kernel-side HID
stack. Read the first five in order for the full picture.

- **[Architecture Overview](architecture-overview.md)**: the stack diagram
  from SDK to driver, per-controller WUDFHost processes, and the three
  architecture groups.
- **[UMDF2 Driver Internals](umdf2-driver-internals.md)**: `driver.c`, the
  IOCTL dispatch table, the device context, and the event-driven worker.
- **[XUSB Companion](xusb-companion.md)**: how Xbox-family profiles get
  XInput without a kernel driver.
- **[SwDevice and PnP](swdevice-and-pnp.md)**: device creation, container
  IDs, and the XInput slot-0 story.
- **[Shared Memory Protocol](shared-memory-protocol.md)**: the three
  sections per controller, the seqlock, and the named events.
- **[Cross-API Coverage](cross-api-coverage.md)**: how DirectInput,
  XInput, SDL3/HIDAPI, the browser Gamepad API, and WGI are each
  satisfied.
- **[Multi-Controller](multi-controller.md)**: verified mixed-type
  operation and per-API ordering.
- **[Lifecycle and Teardown](lifecycle-and-teardown.md)**: create paths,
  removal ordering, and round-trip latencies by archetype.
- **[Driver Install and Signing](driver-install-and-signing.md)**: the
  embedded payload, certificate generation, and the idempotent install.
- **[Build and Release](build-and-release.md)**: the two-phase build and
  the release recipe.
- **[Testing and Verification](testing-and-verification.md)**:
  `scripts/verify.py` and the 41-scenario regression battery.
- **[References](references.md)**: authoritative sources for every
  load-bearing claim in these docs.
