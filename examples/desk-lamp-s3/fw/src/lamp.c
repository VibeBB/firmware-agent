#include "lamp.h"

void lamp_init(lamp_t *lamp)
{
    lamp->mode = LAMP_OFF;
    lamp->pressed_samples = 0U;
    lamp->latched = false;
}

bool lamp_step(lamp_t *lamp, bool pressed)
{
    if (!pressed) {
        lamp->pressed_samples = 0U;
        lamp->latched = false;
        return false;
    }
    if (lamp->latched) {
        return false;
    }
    lamp->pressed_samples++;
    if (lamp->pressed_samples < LAMP_DEBOUNCE_SAMPLES) {
        return false;
    }
    lamp->latched = true;
    lamp->mode = (lamp->mode == LAMP_BRIGHT) ? LAMP_OFF : (lamp_mode_t)(lamp->mode + 1);
    return true;
}

uint8_t lamp_duty(lamp_mode_t mode)
{
    switch (mode) {
    case LAMP_DIM:
        return 51U;
    case LAMP_BRIGHT:
        return 255U;
    case LAMP_OFF:
    default:
        return 0U;
    }
}

const char *lamp_mode_name(lamp_mode_t mode)
{
    switch (mode) {
    case LAMP_DIM:
        return "DIM";
    case LAMP_BRIGHT:
        return "BRIGHT";
    case LAMP_OFF:
    default:
        return "OFF";
    }
}
