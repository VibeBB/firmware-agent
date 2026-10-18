/* pic-blink: PIC16HV753 firmware — status LED on RC5, wake button on RA2,
 * analog sense on AN0. Built with SDCC (-mpic14 -p16hv753 --use-non-free)
 * per pic-blink.fw.json. */
#include <stdint.h>
#include <pic14/pic16hv753.h>

#include "fw_pins.h"

/* CONFIG1: internal oscillator, WDT off, MCLR enabled, code protection
 * off, BOR on, CLKOUT disabled (DS41656 CONFIG1 bit map, 0x3FFF default). */
__code unsigned int __at(0x2007) config1 = 0x3fffu;

static volatile uint16_t spin;

static void pause(void)
{
    for (spin = 0; spin < 20000u; spin++) {
    }
}

static uint16_t sense_read(void)
{
    ADCON0 |= 0x02u; /* GO/DONE: start AN0 conversion */
    while (ADCON0 & 0x02u) {
    }
    return (uint16_t)(((uint16_t)ADRESH << 8) | ADRESL);
}

int main(void)
{
    TRISA = 0xffu;   /* port A inputs: wake button (RA2), AN0, MCLR */
    ANSELA = 0x01u;  /* RA0 analog */
    ADCON0 = 0x01u;  /* ADC on, channel AN0 */
    ADCON1 = 0x00u;  /* FVR/2Vref, left justify off */
    TRISC = 0x00u;   /* port C outputs */
    PORTC = FW_PIN_STATUS_LED_INITIAL;

    for (;;) {
        const uint16_t level = sense_read();
        PORTC = (level > 512u) ? 0x20u : 0x00u;
        pause();
        PORTC ^= 0x20u;
    }
}
