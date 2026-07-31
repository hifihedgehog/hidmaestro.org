---
title: Home
hide:
  - navigation
  - toc
---

<div class="pf-hero" markdown>
<p class="pf-kicker">HIDMaestro Documentation</p>

# Ship a controller in minutes. Trace it to the wire.

<p class="pf-lede">HIDMaestro creates virtual game controllers that look
like real hardware to Windows. These docs serve two readers at once. Start
and the SDK pages get an application developer to a live controller fast.
The Technical Reference goes as deep as IOCTL dispatch tables and shared
memory layouts, for people who want to know exactly what the driver
does.</p>

[Get started](start/index.md){ .md-button .md-button--primary }
[Technical Reference](reference/index.md){ .md-button }

</div>

<div class="pf-cards">
  <a href="start/">
    <span class="pf-eyebrow">New here</span>
    <h3>Start</h3>
    <p>Reference the SDK, install the driver, and create your first virtual controller. No prior knowledge assumed.</p>
  </a>
  <a href="sdk/">
    <span class="pf-eyebrow">The API</span>
    <h3>SDK</h3>
    <p>The public C# surface: contexts, controllers, descriptors, force feedback, output passthrough, and name overrides.</p>
  </a>
  <a href="profiles/">
    <span class="pf-eyebrow">Every device</span>
    <h3>Profiles</h3>
    <p>The JSON profile system, 227 built-in controllers, custom and cloned devices, and the extractor that captures yours.</p>
  </a>
  <a href="troubleshooting/">
    <span class="pf-eyebrow">Something broke</span>
    <h3>Troubleshooting</h3>
    <p>Symptoms, causes, and fixes for driver installs, missing devices, XInput slots, and output that never arrives.</p>
  </a>
  <a href="reference/">
    <span class="pf-eyebrow">Go deep</span>
    <h3>Technical Reference</h3>
    <p>Architecture, driver internals, the shared memory protocol, PnP lifecycle, and how every gaming API is satisfied.</p>
  </a>
</div>

## What HIDMaestro is

A C# SDK and matching UMDF2 driver. Add the SDK to your app, call
`HMContext.InstallDriver()` once, and `HMContext.CreateController(profile)`
whenever you need a virtual gamepad. It replaces ViGEmBus and vJoy with one
user-mode driver, 227 embedded profiles, runtime-built custom profiles,
HID PID 1.0 force feedback, and live-swap teardown that does not leak PnP
state.

## What HIDMaestro is not

A standalone app. There is no UI to drive HIDMaestro on its own. Consumers
like [PadForge](https://padforge.org/) wrap the SDK with their own input
pipeline. If you want to use HIDMaestro through a UI, install PadForge.

HIDMaestro is free and open source, MIT licensed. The code, issues, and
releases live at
[github.com/hifihedgehog/HIDMaestro](https://github.com/hifihedgehog/HIDMaestro).
