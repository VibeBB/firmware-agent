/* SPDX-License-Identifier: BSD-3-Clause
 * mruby-ux Zephyr/NCS entry point: boots the mruby/c VM on a static
 * memory pool sized by the generated fw_mruby.h, then runs the compiled
 * UX bytecode task until it exits.
 */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

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
		printk("SIM FAIL: task create\n");
		return 1;
	}
	mrbc_run();
	return 0;
}
