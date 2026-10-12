# SPDX-License-Identifier: BSD-3-Clause
# Zephyr/NCS application that embeds the mruby/c VM plus the generated
# UX bytecode. The mruby/c tree is staged read-only at /opt/mrubyc in the
# firmware-tools image; FW_MRUBYC_DIR lets a developer point elsewhere.
cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(mruby_ux)

set(MRUBYC_DIR $ENV{FW_MRUBYC_DIR})
if(NOT MRUBYC_DIR)
  set(MRUBYC_DIR /opt/mrubyc)
endif()

file(GLOB MRUBYC_CORE CONFIGURE_DEPENDS ${MRUBYC_DIR}/src/*.c)
list(REMOVE_ITEM MRUBYC_CORE ${MRUBYC_DIR}/src/hal.c)

target_sources(app PRIVATE
  src/main.c
  generated/ux_app_bytecode.c
  ${MRUBYC_DIR}/hal/zephyr/hal.c
  ${MRUBYC_CORE}
)
target_include_directories(app PRIVATE
  include
  generated
  ${MRUBYC_DIR}/src
  ${MRUBYC_DIR}/hal/zephyr
)
