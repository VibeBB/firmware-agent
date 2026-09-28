#include "kettle.h"

static kettle_outputs_t enter(kettle_t *kettle, kettle_state_t state, kettle_feedback_t feedback)
{
    kettle_outputs_t out;
    kettle->state = state;
    out.heater_on = (state == KETTLE_HEATING);
    out.feedback = feedback;
    return out;
}

static bool can_heat(const kettle_inputs_t *in)
{
    return in->lid_closed && in->water_level_raw >= KETTLE_MIN_WATER_RAW;
}

void kettle_init(kettle_t *kettle, int16_t target_centi_c)
{
    kettle->state = KETTLE_IDLE;
    kettle->target_centi_c = target_centi_c;
}

kettle_outputs_t kettle_step(kettle_t *kettle, const kettle_inputs_t *in)
{
    kettle_outputs_t out;

    if (kettle->state == KETTLE_FAULT) {
        return enter(kettle, KETTLE_FAULT, FEEDBACK_NONE);
    }
    if (!in->temp_valid || in->temp_centi_c > KETTLE_MAX_TEMP_CENTI_C) {
        return enter(kettle, KETTLE_FAULT, FEEDBACK_WARNING);
    }
    switch (kettle->state) {
    case KETTLE_IDLE:
    case KETTLE_DONE:
        if (!in->boil_pressed) {
            return enter(kettle, kettle->state, FEEDBACK_NONE);
        }
        if (!can_heat(in)) {
            return enter(kettle, kettle->state, FEEDBACK_WARNING);
        }
        return enter(kettle, KETTLE_HEATING, FEEDBACK_HEATING);
    case KETTLE_HEATING:
        if (!can_heat(in)) {
            return enter(kettle, KETTLE_IDLE, FEEDBACK_WARNING);
        }
        if (in->temp_centi_c >= kettle->target_centi_c) {
            return enter(kettle, KETTLE_DONE, FEEDBACK_DONE);
        }
        return enter(kettle, KETTLE_HEATING, FEEDBACK_NONE);
    default:
        break;
    }
    out = enter(kettle, KETTLE_FAULT, FEEDBACK_WARNING);
    return out;
}

const char *kettle_state_name(kettle_state_t state)
{
    switch (state) {
    case KETTLE_IDLE:
        return "IDLE";
    case KETTLE_HEATING:
        return "HEATING";
    case KETTLE_DONE:
        return "DONE";
    case KETTLE_FAULT:
        return "FAULT";
    default:
        return "UNKNOWN";
    }
}

const char *kettle_feedback_name(kettle_feedback_t feedback)
{
    switch (feedback) {
    case FEEDBACK_NONE:
        return "NONE";
    case FEEDBACK_BOOT:
        return "BOOT";
    case FEEDBACK_HEATING:
        return "HEATING";
    case FEEDBACK_DONE:
        return "DONE";
    case FEEDBACK_WARNING:
        return "WARNING";
    default:
        return "UNKNOWN";
    }
}
