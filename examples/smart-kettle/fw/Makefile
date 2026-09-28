# Smart-kettle firmware: RP2040 image (all) and QEMU logic build (sim).
CC := arm-none-eabi-gcc
BUILD := build
CFLAGS := -std=c11 -Os -g -Wall -Wextra -Werror -ffreestanding \
	-fno-tree-loop-distribute-patterns -ffunction-sections -fdata-sections -Iinclude
LDFLAGS := -nostdlib -Wl,--gc-sections -lgcc
HEADERS := include/kettle.h include/hal.h include/fw_pins.h

TARGET_SRC := src/startup.c src/main.c src/kettle.c src/hal_rp2040.c
SIM_SRC := src/startup.c src/kettle.c sim/sim_main.c

.PHONY: all sim clean
all: $(BUILD)/smart-kettle.elf
sim: $(BUILD)/sim/kettle-sim.elf

$(BUILD)/smart-kettle.elf: $(TARGET_SRC) $(HEADERS) link/rp2040.ld
	@mkdir -p $(dir $@)
	$(CC) -mcpu=cortex-m0plus -mthumb $(CFLAGS) -T link/rp2040.ld $(TARGET_SRC) $(LDFLAGS) -o $@

$(BUILD)/sim/kettle-sim.elf: $(SIM_SRC) $(HEADERS) sim/mps2_an385.ld
	@mkdir -p $(dir $@)
	$(CC) -mcpu=cortex-m3 -mthumb $(CFLAGS) -T sim/mps2_an385.ld $(SIM_SRC) $(LDFLAGS) -o $@

clean:
	rm -rf $(BUILD)
