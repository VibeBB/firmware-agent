SDCC ?= sdcc
MCU ?= 16hv753
BUILD := build
TARGET := $(BUILD)/pic-blink.hex

all: $(TARGET)

$(BUILD):
	mkdir -p $(BUILD)

# sdcc -o takes an extensionless base name; it emits <base>.hex plus the
# intermediate .asm/.o/.lst/.cod next to it.
$(TARGET): src/main.c include/fw_pins.h | $(BUILD)
	$(SDCC) -mpic14 -p$(MCU) --use-non-free -o $(BUILD)/pic-blink src/main.c

clean:
	rm -rf $(BUILD)

.PHONY: all clean
