# Performance and limits

## Timeouts and sizes

- `build.timeout_s`: default 600, max 7200 s (per build step).
- `sim timeout_s`: default 20, max 600 s per QEMU run.
- MCP inline images: max 4 per call, each ≤ 4 MiB; overflow reported
  under `images_skipped`.
- Renders are stdlib PNGs (8-bit RGB, zlib level 9, byte-deterministic);
  sizes scale with content (pin map rows, check count, transcript
  length); typically tens of KiB.
- `sim` transcripts are matched by line index, not wall-clock time —
  QEMU logs carry no timestamps.

## Coverage limits

- MCU profiles: only `esp32s3` and `rp2040` are bundled. Other parts
  need a new profile file (see [development.md](development.md)).
- QEMU fidelity: `core` runs assert on printed lines + optional
  semihosting exit code (`qemu-arm`); `qemu-esp` asserts lines only.
  QEMU is not the hardware: no electrical behavior, no RF, no real
  timing, no peripheral-accurate models beyond the chosen machines.
- `firmware debug` output is advisory and never changes a verdict.
- Vision reviews and impressions are advisory too.
- Static gates cannot see behavior — they check the contract,
  assignments, netlist match, power budget and generated header only.
- The plugin is Docker-only: `firmware_launcher.py` fails closed when
  no pinned `firmware-tools` image resolves.
- No flashing of real devices; human sign-off stays mandatory.
