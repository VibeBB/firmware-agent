# Cppcheck 2.19.0 to 2.22.0 adoption review

Reviewed 2026-10-07 while replacing the resolute apt `cppcheck` package
(2.19.0-1build1) with the checksum-pinned Debian unstable `.deb`
(2.22.0-1) fetched from `snapshot.debian.org`.

The official Cppcheck release notes for 2.20.0, 2.21.0, and 2.22.0 were
reviewed end to end.

## 2.20.0

- The built-in `unix*` and `win*` platforms now treat plain `char` as
  signed. The firmware analysis invocation declares no `--platform`, so
  analysis now assumes a signed-char target. Bare-metal Arm/RISC-V ABIs
  use unsigned `char`, so char-signedness-dependent checks (e.g.
  `checkCondition` on `char` comparisons) can differ from the target
  truth in either direction. Evaluated `--funsigned-char`: not adopted —
  the `Analysis` contract has no option surface for it and findings gated
  on signedness have not been observed; recorded here for re-evaluation if
  a signed-char false finding appears.
- Build-flag changes (`BUILD_TESTS` -> `BUILD_TESTING`, CMake >= 3.22)
  and inline polyspace suppression comment support are not applicable:
  the image consumes the distro binary and uses XML suppressions.

## 2.21.0

- New checks adopted implicitly by the existing
  `--enable=warning,style,performance,portability` gate:
  `funcArgNamesDifferentUnnamed`, `uninitMemberVarNoCtor`,
  `fcloseInLoopCondition`, and the MISRA C 10.3 improvement (boolean
  literals in arithmetic). No suppression or opt-in is required; the
  static-analysis gate gets stronger with no invocation change.
- New `--exitcode-suppress` CLI option and the `engine` element in rule
  XML are not adopted: the gate uses `--error-exitcode=0` and does not
  author custom rules.
- `-I`/`-isystem`/`--sysroot` uptake from `compile_commands.json` is not
  adopted: analysis sources/includes come from the `.fw.json` contract,
  not a compilation database.

## 2.22.0

- Many fuzzer-reported crash fixes: directly reduces
  analysis-infrastructure failures on unusual sources.
- New checks `wrongfeofUsage`, `algorithmOutOfBounds`,
  `unreachableSwitchCase`, and the `ftell` t-mode diagnostic are adopted
  implicitly through the same `--enable` set.
- C++23 `if consteval` parsing, XML suppression `macro` attribute, and
  CTU-aware warning hashes require no action (`std` is capped at c++20;
  suppressions stay path/line based).
- simplecpp 1.9.1 ships inside the same `.deb`; no separate pin.

## syntaxError suppression re-check

`examples/smart-kettle/smart-kettle.fw.json` suppresses
`syntaxError` at `fw/sim/sim_main.c:15` for the Cppcheck 2.19 misparse of
the GCC local-register binding documented in
[cppcheck-2.19-adoption.md](cppcheck-2.19-adoption.md). The suppression
is pinned to one file and line and remains in place under 2.22; the e2e
image gate verifies whether the underlying parse is now clean (either
outcome is acceptable — a stale suppression at one line is harmless, a
recurrence stays blocked from failing the example).

## Provenance and tracking

The `.deb` is a Debian *unstable* build installed on Ubuntu 26.04. Its
`Depends` (libc6 >= 2.43, libtinyxml2-11, python3-pygments, libstdc++6,
libgcc-s1, python3:any) all resolve from resolute; sid itself is never
added to `sources.list`. Because sid builds sit outside the Ubuntu
security tracker, the pin is registered as a `docker-deb` target in
`scripts/check_dependency_updates.py` so a newer sid upload surfaces in
the weekly dependency report.
