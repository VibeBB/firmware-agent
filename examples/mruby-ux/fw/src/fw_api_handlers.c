/* Hand-written device driver handlers for the mruby-ux device API.
 *
 * Reference implementation: a software LED state store so the bindings
 * behave identically on the nRF and Emscripten legs.  A product port
 * replaces these bodies with real register/GPIO access behind the same
 * signatures in fw_api_handlers.h.
 */
#include "fw_api_handlers.h"

#include <stdio.h>
#include <string.h>

static int led_state[kFwHwLedCount];

int fw_hw_led_init(void) {
	memset(led_state, 0, sizeof(led_state));
	return 0;
}

int fw_hw_led_set(const int32_t part, const int state) {
	if (part < 0 || part >= kFwHwLedCount) {
		return 0;
	}
	led_state[part] = state ? 1 : 0;
	return 1;
}

int fw_hw_led_toggle(const int32_t part) {
	if (part < 0 || part >= kFwHwLedCount) {
		return 0;
	}
	led_state[part] = !led_state[part];
	return led_state[part];
}

int fw_hw_led_all(const mrbc_int_t *states, const size_t states_n) {
	size_t applied = 0;
	for (size_t i = 0; i < states_n && i < (size_t)kFwHwLedCount; i++) {
		led_state[i] = states[i] ? 1 : 0;
		applied++;
	}
	return (int)applied;
}

int fw_hw_led_dump(char *buf, const size_t cap) {
	return snprintf(buf, cap, "LED[%d %d %d]", led_state[0], led_state[1],
			led_state[2]);
}

int fw_hw_led_raw(const mrbc_int_t idx, const mrbc_float_t level) {
	if (idx < 0 || idx >= kFwHwLedCount) {
		return -1;
	}
	led_state[idx] = level > 0.5 ? 1 : 0;
	return 0;
}

int fw_hw_led_on_change(const mrbc_value *rest, const mrbc_value *blk) {
	/* The demo keeps a single callback slot; products would queue it. */
	(void)rest;
	(void)blk;
	return 0;
}

struct fw_hw_sample {
	uint32_t seed;
	uint16_t open;
};

int fw_hw_sample_open(void *data) {
	struct fw_hw_sample *self = (struct fw_hw_sample *)data;
	self->seed = 0x1234u;
	self->open = 1u;
	return 0;
}

void fw_hw_sample_close(void *data) {
	struct fw_hw_sample *self = (struct fw_hw_sample *)data;
	self->open = 0u;
}

int fw_hw_sample_read(
	void *data, const mrbc_int_t ch, mrbc_float_t *buf, const size_t cap
) {
	const struct fw_hw_sample *self = (const struct fw_hw_sample *)data;
	if (!self->open || ch < 0 || buf == 0) {
		return -1;
	}
	const size_t n = cap < 8 ? cap : 8;
	for (size_t i = 0; i < n; i++) {
		buf[i] = (mrbc_float_t)((self->seed + (uint32_t)i * 37u) % 1024u) / 1023.0f;
	}
	return (int)n;
}
