/* Hand-written device driver handlers for the mruby-ux device API.
 *
 * The generated fw_api_* bindings (see api/mruby-ux.mruby-api.json) call
 * these symbols after argument decoding.  Every handler/init/constructor
 * name in the spec must appear here, or the fw.mrubyc gate fails.
 */
#ifndef FW_API_HANDLERS_H
#define FW_API_HANDLERS_H

#include <stddef.h>
#include <stdint.h>

#include "mrubyc.h"

/* Symbol constants the handlers receive for symbol-typed arguments. */
enum {
	kFwHwLed1 = 0,
	kFwHwLed2,
	kFwHwLed3,
	kFwHwLedCount
};

int fw_hw_led_init(void);
int fw_hw_led_set(int32_t part, int state);
int fw_hw_led_toggle(int32_t part);
int fw_hw_led_all(const mrbc_int_t *states, size_t states_n);
int fw_hw_led_dump(char *buf, size_t cap);
int fw_hw_led_raw(mrbc_int_t idx, mrbc_float_t level);
int fw_hw_led_on_change(const mrbc_value *rest, const mrbc_value *blk);

int fw_hw_sample_open(void *data);
void fw_hw_sample_close(void *data);
int fw_hw_sample_read(void *data, mrbc_int_t ch, mrbc_float_t *buf, size_t cap);

#endif /* FW_API_HANDLERS_H */
