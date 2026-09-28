/* Smart-kettle control logic: portable C with no hardware access. */
#ifndef KETTLE_H
#define KETTLE_H

#include <stdbool.h>
#include <stdint.h>

#define KETTLE_TARGET_CENTI_C 9500
#define KETTLE_MAX_TEMP_CENTI_C 11000
#define KETTLE_MIN_WATER_RAW 800U

typedef enum {
    KETTLE_IDLE = 0,
    KETTLE_HEATING,
    KETTLE_DONE,
    KETTLE_FAULT
} kettle_state_t;

typedef enum {
    FEEDBACK_NONE = 0,
    FEEDBACK_BOOT,
    FEEDBACK_HEATING,
    FEEDBACK_DONE,
    FEEDBACK_WARNING
} kettle_feedback_t;

typedef struct {
    bool boil_pressed;
    bool lid_closed;
    bool temp_valid;
    int16_t temp_centi_c;
    uint16_t water_level_raw;
} kettle_inputs_t;

typedef struct {
    bool heater_on;
    kettle_feedback_t feedback;
} kettle_outputs_t;

typedef struct {
    kettle_state_t state;
    int16_t target_centi_c;
} kettle_t;

void kettle_init(kettle_t *kettle, int16_t target_centi_c);
kettle_outputs_t kettle_step(kettle_t *kettle, const kettle_inputs_t *in);
const char *kettle_state_name(kettle_state_t state);
const char *kettle_feedback_name(kettle_feedback_t feedback);

#endif /* KETTLE_H */
