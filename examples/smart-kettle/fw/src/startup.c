/* Minimal Cortex-M startup shared by the RP2040 image and the QEMU build. */
#include <stdint.h>

extern uint32_t _sidata[];
extern uint32_t _sdata[];
extern uint32_t _edata[];
extern uint32_t _sbss[];
extern uint32_t _ebss[];
extern uint32_t _estack[];

int main(void);
void reset_handler(void);
void fault_handler(void);

typedef void (*vector_t)(void);

__attribute__((section(".vectors"), used)) static const vector_t vectors[16] = {
    (vector_t)(uintptr_t)_estack,
    reset_handler,
    fault_handler, /* NMI */
    fault_handler, /* HardFault */
};

void fault_handler(void)
{
    for (;;) {
    }
}

void reset_handler(void)
{
    const uintptr_t data_words = ((uintptr_t)_edata - (uintptr_t)_sdata) / sizeof(uint32_t);
    const uintptr_t bss_words = ((uintptr_t)_ebss - (uintptr_t)_sbss) / sizeof(uint32_t);
    uintptr_t i;

    for (i = 0U; i < data_words; i++) {
        _sdata[i] = _sidata[i];
    }
    for (i = 0U; i < bss_words; i++) {
        _sbss[i] = 0U;
    }
    (void)main();
    for (;;) {
    }
}
