#include "hal.h"
#include "kettle.h"

int main(void)
{
    kettle_t kettle;

    hal_init();
    kettle_init(&kettle, KETTLE_TARGET_CENTI_C);
    hal_feedback(FEEDBACK_BOOT);
    for (;;) {
        kettle_inputs_t in;
        kettle_outputs_t out;

        in.boil_pressed = hal_boil_pressed();
        in.lid_closed = hal_lid_closed();
        in.temp_valid = hal_read_temp(&in.temp_centi_c);
        in.water_level_raw = hal_water_level();
        out = kettle_step(&kettle, &in);
        hal_heater(out.heater_on);
        hal_feedback(out.feedback);
        if (!out.heater_on) {
            hal_sleep();
        }
    }
}
