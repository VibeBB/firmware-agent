#include <stdbool.h>
#include <stdio.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "fw_pins.h"
#include "lamp.h"

#define POLL_MS 10

/* Power-on self-test: a bouncy press, a clean press, a held press, a press. */
static const bool SELFTEST_SAMPLES[] = {
    true, false, true, true, true, true, true, false, false,
    true, true, true, false, true, true, true, true, false,
};
static const lamp_mode_t SELFTEST_MODES[] = {LAMP_DIM, LAMP_BRIGHT, LAMP_OFF};

static bool selftest(void)
{
    lamp_t lamp;
    size_t seen = 0U;
    size_t i;

    lamp_init(&lamp);
    for (i = 0U; i < sizeof(SELFTEST_SAMPLES) / sizeof(SELFTEST_SAMPLES[0]); i++) {
        if (!lamp_step(&lamp, SELFTEST_SAMPLES[i])) {
            continue;
        }
        printf("MODE %s\n", lamp_mode_name(lamp.mode));
        if (seen >= sizeof(SELFTEST_MODES) / sizeof(SELFTEST_MODES[0]) ||
            lamp.mode != SELFTEST_MODES[seen]) {
            return false;
        }
        seen++;
    }
    return seen == sizeof(SELFTEST_MODES) / sizeof(SELFTEST_MODES[0]);
}

static void hw_init(void)
{
    const gpio_config_t button = {
        .pin_bit_mask = 1ULL << FW_PIN_MODE_BUTTON,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    const ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_8_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = FW_PERIPH_LAMP_PWM_FREQUENCY_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    const ledc_channel_config_t channel = {
        .gpio_num = FW_PIN_LAMP_LED,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
    };

    ESP_ERROR_CHECK(gpio_config(&button));
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
    ESP_ERROR_CHECK(ledc_channel_config(&channel));
}

static void set_duty(lamp_mode_t mode)
{
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, lamp_duty(mode)));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0));
}

void app_main(void)
{
    lamp_t lamp;

    printf("BOOT %s\n", FW_DESIGN);
    printf(selftest() ? "SELFTEST PASS\n" : "SELFTEST FAIL\n");
    hw_init();
    lamp_init(&lamp);
    set_duty(lamp.mode);
    for (;;) {
        const bool pressed = gpio_get_level(FW_PIN_MODE_BUTTON) == (FW_PIN_MODE_BUTTON_ACTIVE_LOW ? 0 : 1);
        if (lamp_step(&lamp, pressed)) {
            set_duty(lamp.mode);
        }
        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}
