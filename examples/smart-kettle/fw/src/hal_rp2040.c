/* RP2040 register-level board support. Register offsets follow the RP2040
 * datasheet (SIO, IO_BANK0, PADS_BANK0, RESETS, ADC, PWM, I2C). */
#include "hal.h"

#include "fw_pins.h"

#define REG(addr) (*(volatile uint32_t *)(uintptr_t)(addr))

#define RESETS_BASE 0x4000c000U
#define IO_BANK0_BASE 0x40014000U
#define PADS_BANK0_BASE 0x4001c000U
#define I2C0_BASE 0x40044000U
#define ADC_BASE 0x4004c000U
#define PWM_BASE 0x40050000U
#define SIO_BASE 0xd0000000U

#define RESETS_RESET (RESETS_BASE + 0x0U)
#define RESETS_DONE (RESETS_BASE + 0x8U)
#define RESET_ADC (1U << 0)
#define RESET_I2C0 (1U << 3)
#define RESET_IO_BANK0 (1U << 5)
#define RESET_PADS_BANK0 (1U << 8)
#define RESET_PWM (1U << 14)

#define GPIO_CTRL(n) (IO_BANK0_BASE + 0x004U + 8U * (uint32_t)(n))
#define PAD_CTRL(n) (PADS_BANK0_BASE + 0x004U + 4U * (uint32_t)(n))
#define PAD_PUE (1U << 3)
#define PAD_IE (1U << 6)
#define FUNC_I2C 3U
#define FUNC_PWM 4U
#define FUNC_SIO 5U

#define SIO_GPIO_IN (SIO_BASE + 0x004U)
#define SIO_GPIO_OUT_SET (SIO_BASE + 0x014U)
#define SIO_GPIO_OUT_CLR (SIO_BASE + 0x018U)
#define SIO_GPIO_OE_SET (SIO_BASE + 0x024U)

#define PWM_CH_CSR(ch) (PWM_BASE + 0x14U * (uint32_t)(ch))
#define PWM_CH_CC(ch) (PWM_BASE + 0x14U * (uint32_t)(ch) + 0x0cU)
#define PWM_CH_TOP(ch) (PWM_BASE + 0x14U * (uint32_t)(ch) + 0x10U)

#define ADC_CS (ADC_BASE + 0x00U)
#define ADC_RESULT (ADC_BASE + 0x04U)
#define ADC_CS_EN (1U << 0)
#define ADC_CS_START_ONCE (1U << 2)
#define ADC_CS_READY (1U << 8)

#define I2C_CON (I2C0_BASE + 0x00U)
#define I2C_TAR (I2C0_BASE + 0x04U)
#define I2C_DATA_CMD (I2C0_BASE + 0x10U)
#define I2C_ENABLE (I2C0_BASE + 0x6cU)
#define I2C_RXFLR (I2C0_BASE + 0x78U)
#define I2C_CMD_READ (1U << 8)
#define I2C_CMD_STOP (1U << 9)
#define TEMP_SENSOR_ADDR 0x48U
#define I2C_TIMEOUT 10000U

#define WATER_ADC_CHANNEL (FW_PIN_WATER_LEVEL - 26)

static void unreset(uint32_t mask)
{
    REG(RESETS_RESET) &= ~mask;
    while ((REG(RESETS_DONE) & mask) != mask) {
    }
}

static void pin_function(uint32_t pin, uint32_t function, uint32_t pad)
{
    REG(PAD_CTRL(pin)) = pad;
    REG(GPIO_CTRL(pin)) = function;
}

static bool pin_level(uint32_t pin)
{
    return (REG(SIO_GPIO_IN) & (1U << pin)) != 0U;
}

void hal_init(void)
{
    unreset(RESET_IO_BANK0 | RESET_PADS_BANK0 | RESET_PWM | RESET_ADC | RESET_I2C0);

    pin_function(FW_PIN_BOIL_BUTTON, FUNC_SIO, PAD_IE | PAD_PUE);
    pin_function(FW_PIN_LID_SWITCH, FUNC_SIO, PAD_IE | PAD_PUE);
    pin_function(FW_PIN_HEATER_EN, FUNC_SIO, 0U);
    REG(SIO_GPIO_OUT_CLR) = 1U << FW_PIN_HEATER_EN;
    REG(SIO_GPIO_OE_SET) = 1U << FW_PIN_HEATER_EN;

    pin_function(FW_PIN_TEMP_SDA, FUNC_I2C, PAD_IE | PAD_PUE);
    pin_function(FW_PIN_TEMP_SCL, FUNC_I2C, PAD_IE | PAD_PUE);
    REG(I2C_ENABLE) = 0U;
    REG(I2C_CON) = 0x65U; /* master, fast mode, restart enabled, slave disabled */
    REG(I2C_TAR) = TEMP_SENSOR_ADDR;
    REG(I2C_ENABLE) = 1U;

    pin_function(FW_PIN_LED_RING, FUNC_PWM, 0U);
    pin_function(FW_PIN_BUZZER, FUNC_PWM, 0U);
    REG(PWM_CH_TOP(FW_PERIPH_LED_PWM_INSTANCE)) = 0xffffU;
    REG(PWM_CH_TOP(FW_PERIPH_BUZZER_PWM_INSTANCE)) = 0xffffU;
    REG(PWM_CH_CSR(FW_PERIPH_LED_PWM_INSTANCE)) = 1U;
    REG(PWM_CH_CSR(FW_PERIPH_BUZZER_PWM_INSTANCE)) = 1U;

    REG(ADC_CS) = ADC_CS_EN;
}

bool hal_boil_pressed(void)
{
    return pin_level(FW_PIN_BOIL_BUTTON) == (FW_PIN_BOIL_BUTTON_ACTIVE_LOW == 0);
}

bool hal_lid_closed(void)
{
    return pin_level(FW_PIN_LID_SWITCH) == (FW_PIN_LID_SWITCH_ACTIVE_LOW == 0);
}

bool hal_read_temp(int16_t *centi_c)
{
    uint32_t timeout = I2C_TIMEOUT;
    uint32_t raw;

    REG(I2C_DATA_CMD) = 0x00U; /* temperature result register */
    REG(I2C_DATA_CMD) = I2C_CMD_READ;
    REG(I2C_DATA_CMD) = I2C_CMD_READ | I2C_CMD_STOP;
    while (REG(I2C_RXFLR) < 2U) {
        if (--timeout == 0U) {
            return false;
        }
    }
    raw = (REG(I2C_DATA_CMD) & 0xffU) << 8;
    raw |= REG(I2C_DATA_CMD) & 0xffU;
    /* 7.8125 m°C per LSB -> centi-degrees */
    *centi_c = (int16_t)(((int32_t)(int16_t)raw * 25) / 32);
    return true;
}

uint16_t hal_water_level(void)
{
    REG(ADC_CS) = ADC_CS_EN | ((uint32_t)WATER_ADC_CHANNEL << 12) | ADC_CS_START_ONCE;
    while ((REG(ADC_CS) & ADC_CS_READY) == 0U) {
    }
    return (uint16_t)(REG(ADC_RESULT) & 0xfffU);
}

void hal_heater(bool on)
{
    if (on) {
        REG(SIO_GPIO_OUT_SET) = 1U << FW_PIN_HEATER_EN;
    } else {
        REG(SIO_GPIO_OUT_CLR) = 1U << FW_PIN_HEATER_EN;
    }
}

void hal_feedback(kettle_feedback_t feedback)
{
    uint32_t led = 0U;
    uint32_t tone = 0U;

    switch (feedback) {
    case FEEDBACK_BOOT:
    case FEEDBACK_DONE:
        led = 0xffffU;
        tone = 0x8000U;
        break;
    case FEEDBACK_HEATING:
        led = 0x4000U;
        break;
    case FEEDBACK_WARNING:
        led = 0xffffU;
        tone = 0xc000U;
        break;
    default:
        return;
    }
    REG(PWM_CH_CC(FW_PERIPH_LED_PWM_INSTANCE)) = led;
    REG(PWM_CH_CC(FW_PERIPH_BUZZER_PWM_INSTANCE)) = tone;
}

void hal_sleep(void)
{
    __asm__ volatile("wfi");
}
