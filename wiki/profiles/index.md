---
title: Profiles
---

# Profiles

Every controller HIDMaestro can emulate is a JSON file. 234 ship in the
embedded catalog across 32 vendors, and runtime-built profiles authored
via `HMProfileBuilder` work identically.

- **[Profile System](profile-system.md)**: the
  `profiles/<vendor>/<slug>.json` schema, every field, the three runtime
  classifications, and a verbatim Xbox 360 Wired profile dissection.
- **[Custom Profiles](custom-profiles.md)**: clone-and-modify,
  build-from-scratch, and spoof patterns, with concrete
  `HMProfileBuilder` examples.
- **[Profile Extractor](profile-extractor.md)**: the standalone tool in
  every release ZIP that captures a connected controller into a
  ready-to-deploy profile JSON.
- **[Contributing Profiles](contributing-profiles.md)**: how to submit a
  profile for a device you own, and what the review checks.
