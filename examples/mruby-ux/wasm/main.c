/* SPDX-License-Identifier: BSD-3-Clause
 * Emscripten harness: identical UX logic to the product target, printed
 * through the mruby/c Emscripten HAL so node can assert the transcript.
 */
#include <stdio.h>
#include <stdint.h>

#include "fw_mruby.h"
#include "mrubyc.h"

extern const uint8_t ux_app[];

static uint8_t memory_pool[FW_MRUBY_MEMORY_SIZE];

int
main(void)
{
	mrbc_init_alloc(memory_pool, FW_MRUBY_MEMORY_SIZE);
	mrbc_init_global();
	mrbc_init_class();

	mrbc_tcb *tcb = mrbc_create_task(ux_app, 0);
	if (tcb == NULL) {
		puts("SIM FAIL: task create");
		return 1;
	}
	mrbc_run();
	return 0;
}
