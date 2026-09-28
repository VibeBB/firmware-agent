/* QEMU (mps2-an385, Cortex-M3) scenario for the kettle logic. Output goes
 * through ARM semihosting; the exit status reports the verdict. */
#include <stddef.h>
#include <stdint.h>

#include "kettle.h"

#define SYS_WRITE0 0x04
#define SYS_EXIT 0x18
#define ADP_STOPPED_APPLICATION_EXIT 0x20026U
#define ADP_STOPPED_INTERNAL_ERROR 0x20024U

static uintptr_t semihost(uintptr_t op, uintptr_t arg)
{
    register uintptr_t r0 __asm__("r0") = op;
    register uintptr_t r1 __asm__("r1") = arg;
    __asm__ volatile("bkpt 0xab" : "+r"(r0) : "r"(r1) : "memory");
    return r0;
}

static void say(const char *text)
{
    (void)semihost(SYS_WRITE0, (uintptr_t)text);
    (void)semihost(SYS_WRITE0, (uintptr_t)"\n");
}

static void report(const char *prefix, const char *name)
{
    (void)semihost(SYS_WRITE0, (uintptr_t)prefix);
    say(name);
}

typedef struct {
    kettle_inputs_t in;
    kettle_state_t state;
    kettle_feedback_t feedback;
} step_t;

static const step_t scenario[] = {
    {{false, true, true, 2000, 900U}, KETTLE_IDLE, FEEDBACK_NONE},
    {{true, true, true, 2000, 300U}, KETTLE_IDLE, FEEDBACK_WARNING},
    {{true, true, true, 2000, 900U}, KETTLE_HEATING, FEEDBACK_HEATING},
    {{false, true, true, 6000, 900U}, KETTLE_HEATING, FEEDBACK_NONE},
    {{false, true, true, 9500, 900U}, KETTLE_DONE, FEEDBACK_DONE},
    {{true, false, true, 9000, 900U}, KETTLE_DONE, FEEDBACK_WARNING},
    {{true, true, true, 9000, 900U}, KETTLE_HEATING, FEEDBACK_HEATING},
    {{false, false, true, 9100, 900U}, KETTLE_IDLE, FEEDBACK_WARNING},
    {{false, true, false, 0, 900U}, KETTLE_FAULT, FEEDBACK_WARNING},
    {{true, true, true, 2000, 900U}, KETTLE_FAULT, FEEDBACK_NONE},
};

int main(void)
{
    kettle_t kettle;
    size_t i;
    int failures = 0;

    kettle_init(&kettle, KETTLE_TARGET_CENTI_C);
    say("BOOT");
    for (i = 0U; i < sizeof(scenario) / sizeof(scenario[0]); i++) {
        kettle_state_t before = kettle.state;
        kettle_outputs_t out = kettle_step(&kettle, &scenario[i].in);

        if (kettle.state != before) {
            report("STATE ", kettle_state_name(kettle.state));
        }
        if (out.feedback != FEEDBACK_NONE) {
            report("FEEDBACK ", kettle_feedback_name(out.feedback));
        }
        if (kettle.state != scenario[i].state || out.feedback != scenario[i].feedback ||
            out.heater_on != (kettle.state == KETTLE_HEATING)) {
            report("MISMATCH at step ", kettle_state_name(kettle.state));
            failures++;
        }
    }
    say(failures == 0 ? "SIM PASS" : "SIM FAIL");
    (void)semihost(SYS_EXIT,
                   failures == 0 ? ADP_STOPPED_APPLICATION_EXIT : ADP_STOPPED_INTERNAL_ERROR);
    return failures;
}
