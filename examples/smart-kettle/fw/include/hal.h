/* Board support for the smart-kettle on RP2040 (pins from fw_pins.h). */
#ifndef HAL_H
#define HAL_H

#include <stdbool.h>
#include <stdint.h>

#include "kettle.h"

void hal_init(void);
bool hal_boil_pressed(void);
bool hal_lid_closed(void);
bool hal_read_temp(int16_t *centi_c);
uint16_t hal_water_level(void);
void hal_heater(bool on);
void hal_feedback(kettle_feedback_t feedback);
void hal_sleep(void);

#endif /* HAL_H */
