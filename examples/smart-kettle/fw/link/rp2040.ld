/* RP2040: execute in place from QSPI flash, data and stack in SRAM. The
 * first 256 bytes are reserved for the pico-sdk boot2 stage, which this
 * example does not vendor. */
ENTRY(reset_handler)

MEMORY
{
    FLASH (rx) : ORIGIN = 0x10000000, LENGTH = 2048K
    RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
}

SECTIONS
{
    .boot2 : { LONG(0) . = 0x100; } > FLASH
    .text : { KEEP(*(.vectors)) *(.text*) *(.rodata*) . = ALIGN(4); } > FLASH
    .ARM.exidx : { *(.ARM.exidx*) } > FLASH
    .data : { _sdata = .; *(.data*) . = ALIGN(4); _edata = .; } > RAM AT > FLASH
    _sidata = LOADADDR(.data);
    .bss (NOLOAD) : { _sbss = .; *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
    .stack (NOLOAD) : { . = ALIGN(8); . = . + 4K; } > RAM
    _estack = ORIGIN(RAM) + LENGTH(RAM);
}
