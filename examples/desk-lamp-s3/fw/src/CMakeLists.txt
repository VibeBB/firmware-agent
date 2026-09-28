idf_component_register(
    SRCS "main.c" "lamp.c"
    INCLUDE_DIRS "../include"
    PRIV_REQUIRES driver esp_driver_gpio esp_driver_ledc
)
