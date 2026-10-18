# ADR-0030: SDCC toolchain for PIC14 targets

## Status

Accepted — implemented in the same change that introduces `pic16hv753`.

## Context

VibeBB products occasionally land on Microchip 8-bit PIC parts such as the
PIC16HV753 (high-voltage analog MCU). The `firmware-tools` image needs a
compiler that emits PIC14 code. Options:

1. **Ubuntu `sdcc` apt package.** Debian builds SDCC without
   `device/non-free`, so the packaged compiler answers
   `cannot generate code for target 'pic14'` for every PIC part.
   Unusable for PIC work.
2. **Upstream binary tarball.** SDCC publishes prebuilt Linux binaries,
   but only for amd64 and without a release channel the dependency
   checker can track cleanly.
3. **Upstream source release (chosen).** `sdcc-src-<ver>.tar.bz2` is
   published with a known sha256 and builds cleanly on ubuntu:26.04
   (`gcc`, `bison`, `flex`, `zlib1g-dev`, `python3`,
   `libboost-graph-dev`, plus `gputils` for the PIC assembler/linker).

The pic14 backend invokes `gpasm`/`gplink` at compile time, so `gputils`
must exist in the runtime image, not just the build stage. The linker
maps the PIC16HV753 program flash (words `0x0000-0x07FF`) onto Intel HEX
byte addresses `0x0000-0x0FFF` and the config words onto `0x4000-0x400F`;
the `pic16hv753` profile's memory regions describe that byte map and the
memory gate consumes the `.hex` image directly.

Upstream marks the PIC ports "unmaintained"; the pic14 port is therefore
verified inside the image with a real PIC16HV753 compile (config word +
reset loop) instead of a version probe alone.

## Decision

- Build SDCC `4.6.0` from the sha256-pinned `sdcc-src-4.6.0.tar.bz2` in a
  dedicated Docker stage and copy `/opt/sdcc` into the runtime image.
  Build every upstream port so renamed `--disable-*-port` flags cannot
  break the image across releases (4.5.0 → 4.6.0 renamed `ez80_z80` and
  added `r4k`/`r5k`/`r6k`/`f8l`/`pdk16`).
- Add `gputils` to the runtime apt list: sdcc calls `gpasm`/`gplink` for
  every PIC14 compile.
- Verify PIC16HV753 in the image twice: a compile smoke test in the SDCC
  stage and again in the runtime verification chain (hex output plus the
  config-word record at `0x400E`), and `sdcc` joins the `doctor` and
  `measure_image_tools` probes.
- Track `SDCC_VERSION` through the SourceForge `best_release.json`
  endpoint in `check_dependency_updates.py`.

## Consequences

- Contracts can use `mcu.profile: "pic16hv753"` with a `make` backend
  that invokes `sdcc -mpic14 -p16hv753 --use-non-free`; the
  `fw.memory_budget` gate reads the Intel HEX image (new `read_image`
  path in `src/firmware/elf.py`), and `CORE_MACHINE` maps `pic14` cores
  to the `ihex` artifact kind.
- `--use-non-free` is required: PIC device headers/libraries live under
  `device/non-free` in sdcc, which is exactly what Debian removes.
- Intel HEX carries no RAM segments, so RAM budget accounting for pic14
  is nominal (flash usage is real; RAM usage reports 0 B).
- SDCC is GPL-2.0-or-later, gputils GPL-2.0-or-later: both ship as
  separate executables invoked as subprocesses only, per ADR-0004.
