# Acquisition

Scripted acquisition and collection of artifacts from a device, reusing CleanerScope's
adb tooling.

This layer is responsible only for pulling raw artifacts off a connected/authorized
device (or emulator) and staging them for the tools in `tools/` to read — it does not
perform any analysis or reasoning itself.

Typical responsibilities:

- Enumerate and pull the artifact sources the agent's tools depend on (usage stats,
  logcat buffers, package manager state, etc.) via `adb`.
- Write acquired artifacts into `data/` in a layout the tools expect.
- Record acquisition metadata (device id, timestamp, command used) alongside each
  artifact for chain-of-custody purposes.

Only run acquisition against devices you are authorized to examine.
