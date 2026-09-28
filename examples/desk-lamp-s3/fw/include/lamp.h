#ifndef LAMP_H
#define LAMP_H

#include <stdbool.h>
#include <stdint.h>

#define LAMP_DEBOUNCE_SAMPLES 3U

typedef enum {
    LAMP_OFF = 0,
    LAMP_DIM,
    LAMP_BRIGHT,
} lamp_mode_t;

typedef struct {
    lamp_mode_t mode;
    uint8_t pressed_samples;
    bool latched;
} lamp_t;

void lamp_init(lamp_t *lamp);
/* Feed one button sample; returns true when the mode changed. */
bool lamp_step(lamp_t *lamp, bool pressed);
uint8_t lamp_duty(lamp_mode_t mode);
const char *lamp_mode_name(lamp_mode_t mode);

#endif
