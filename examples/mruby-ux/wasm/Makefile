# SPDX-License-Identifier: BSD-3-Clause
# Emscripten build of the mruby/c VM + generated UX bytecode for the
# node-runner simulation leg.
MRUBYC_DIR ?= /opt/mrubyc
BUILD_DIR := build
EMCC ?= emcc

MRUBYC_SRCS := $(wildcard $(MRUBYC_DIR)/src/*.c)
MRUBYC_SRCS := $(filter-out $(MRUBYC_DIR)/src/hal.c,$(MRUBYC_SRCS))

CFLAGS := -O2 -Wall -Wextra \
	-I../fw/include -I../fw/generated \
	-I$(MRUBYC_DIR)/src -I$(MRUBYC_DIR)/hal/emscripten \
	-include fw_mruby.h

all: $(BUILD_DIR)/ux.js

FW_API_SRCS := $(wildcard ../fw/generated/fw_api*.c) ../fw/src/fw_api_handlers.c

$(BUILD_DIR)/ux.js: main.c ../fw/generated/ux_app_bytecode.c $(FW_API_SRCS) $(MRUBYC_SRCS) $(MRUBYC_DIR)/hal/emscripten/hal.c
	@mkdir -p $(BUILD_DIR)
	$(EMCC) $(CFLAGS) -sASYNCIFY -sALLOW_MEMORY_GROWTH=1 \
		-o $@ $^

clean:
	rm -rf $(BUILD_DIR)

.PHONY: all clean
