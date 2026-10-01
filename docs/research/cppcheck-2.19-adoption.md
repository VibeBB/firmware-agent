# Cppcheck 2.13.0 to 2.19.0 adoption review

Reviewed 2026-10-01 while moving the firmware-tools image to Ubuntu 26.04.
The official Cppcheck release notes for versions 2.14.0 through 2.19.0 were
reviewed. No new checker or configuration feature from that range applies to
the current firmware sources, so the existing warning, style, performance,
and portability checks remain enabled without additional options.

## Parser finding

The smart-kettle contract uses C11 and analyzes both `fw/src` and `fw/sim`
with `fw/include`. Cppcheck 2.19.0 reports `syntaxError` at
`fw/sim/sim_main.c:15`, on the GCC local-register binding
`register uintptr_t r0 __asm__("r0") = op;`. The same invocation under the
locked Cppcheck 2.13.0 image reports no finding.

The finding persists with `--std=c11`, `--std=c17`, and the unlisted
`--std=gnu11` argument, an ARM32 platform, GCC/ARM target defines, and the
configured include path.
`arm-none-eabi-gcc` 14.2.1 accepts the file with the simulator's C11,
Cortex-M3, Thumb, freestanding, and include flags. The full build and QEMU
simulation also validate this source. This identifies a Cppcheck 2.19 parser
misparse of a valid GCC extension, not invalid example C or a missing
standard, target define, or include.

The contract therefore suppresses only `syntaxError` at that exact path and
line. Other findings in the file and elsewhere remain blocking; compiler and
simulation checks remain required. A regression test verifies that the
suppression does not match the next line.
