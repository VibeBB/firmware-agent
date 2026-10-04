ARG UV_VERSION=0.12.23
ARG UV_DIGEST=sha256:f513a91fc62fe7c17567eee97230dd198e43edb8a9fbecca843714a4358fe1bc
FROM ghcr.io/astral-sh/uv:${UV_VERSION}@${UV_DIGEST} AS uv

# ubuntu:26.04 (resolute)
FROM ubuntu:26.04@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78

ARG DEBIAN_FRONTEND=noninteractive
ARG IMAGE_REVISION=unknown
ARG PLATFORMIO_VERSION=6.2.0
ARG ESPRESSIF32_PLATFORM=espressif32@7.1.3
ARG ESP_QEMU_RELEASE=esp-develop-9.2.2-20260417
ARG ESP_QEMU_ASSET=qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-linux-gnu.tar.xz
ARG ESP_QEMU_SHA256=0eecb2a34a5586c0e59110f77b9343b7b336e82fdb0e1a30e1dc1bab8a547e35

# Fail the build when the left side of a verification pipe (curl|sha256sum)
# breaks instead of silently passing the right side.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
ENV PLATFORMIO_CORE_DIR=/opt/platformio
ENV PLATFORMIO_SETTING_ENABLE_TELEMETRY=no
ENV PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL=0
ENV PLATFORMIO_SETTING_CHECK_PRUNE_SYSTEM_THRESHOLD=0
ENV PATH="/opt/firmware/.venv/bin:/opt/esp-qemu/bin:/opt/platformio/packages/tool-xtensa-esp-elf-gdb/bin:/opt/pio/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENV PYTHONPYCACHEPREFIX=/tmp/firmware-pycache

LABEL org.opencontainers.image.source="https://github.com/VibeBB/firmware-agent" \
      org.opencontainers.image.licenses="BSD-3-Clause" \
      org.opencontainers.image.revision="${IMAGE_REVISION}" \
      firmware.platformio.version="${PLATFORMIO_VERSION}" \
      firmware.espressif32.platform="${ESPRESSIF32_PLATFORM}" \
      firmware.esp-qemu.release="${ESP_QEMU_RELEASE}"

COPY --from=uv /uv /uvx /usr/local/bin/

# GPL-licensed tools (GCC, GDB, QEMU, Cppcheck) are installed as separate
# executables and only ever invoked as subprocesses.
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        ca-certificates \
        curl \
        git \
        make \
        cmake \
        ninja-build \
        xz-utils \
        gcc-arm-none-eabi \
        libnewlib-arm-none-eabi \
        binutils-arm-none-eabi \
        gdb-multiarch \
        qemu-system-arm \
        cppcheck \
        libpixman-1-0 \
        libgcrypt20 \
        libsdl2-2.0-0 \
        libslirp0 \
        libglib2.0-0t64 \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Espressif QEMU (esp32 / esp32s3 machines), GPL-2.0, checksum-pinned.
RUN curl --fail --location --silent --show-error \
        --retry 5 --retry-delay 10 --retry-all-errors \
        --output /tmp/esp-qemu.tar.xz \
        "https://github.com/espressif/qemu/releases/download/${ESP_QEMU_RELEASE}/${ESP_QEMU_ASSET}" \
    && echo "${ESP_QEMU_SHA256}  /tmp/esp-qemu.tar.xz" | sha256sum --check \
    && mkdir -p /opt/esp-qemu \
    && tar -xJf /tmp/esp-qemu.tar.xz -C /opt/esp-qemu --strip-components=1 \
    && rm -f /tmp/esp-qemu.tar.xz \
    && qemu-system-xtensa -M help | grep -q '^esp32s3 ' \
    && mkdir -p /usr/share/doc/esp-qemu \
    && printf '%s\n' \
        "source=https://github.com/espressif/qemu" \
        "release=${ESP_QEMU_RELEASE}" \
        "sha256=${ESP_QEMU_SHA256}" \
        "license=GPL-2.0-or-later" \
        > /usr/share/doc/esp-qemu/SOURCE

WORKDIR /opt/firmware
COPY pyproject.toml uv.lock .python-version README.md LICENSE ./
COPY src ./src
RUN uv python install 3.14 \
    && uv venv /opt/pio --python 3.12 \
    && uv pip install --python /opt/pio "platformio==${PLATFORMIO_VERSION}" \
    && uv sync --locked --no-dev --no-group sdk-check \
    && python -m firmware --help >/dev/null

# Warm the pinned Espressif platform, ESP-IDF, toolchain, and gdb so gates run
# with --network none; the warm-up build doubles as a smoke test.
COPY examples/desk-lamp-s3/fw /tmp/warm/fw
RUN pio pkg install -g --platform "${ESPRESSIF32_PLATFORM}" \
    && pio run -d /tmp/warm/fw -e esp32s3 \
    && test -s /tmp/warm/fw/.pio/build/esp32s3/flash.bin \
    && rm -rf /tmp/warm /opt/platformio/.cache \
    && chmod -R a+rwX /opt/platformio

RUN arm-none-eabi-gcc --version | head -1 \
    && cppcheck --version \
    && qemu-system-arm --version | head -1 \
    && qemu-system-xtensa --version | head -1 \
    && gdb-multiarch --version | head -1 \
    && xtensa-esp32s3-elf-gdb --version | head -1 \
    && pio --version \
    && python -m firmware doctor

# The uv-managed CPython and the ESP-IDF helper venvs bundle pip with
# vendored copies of urllib3, msgpack, and setuptools that nothing in the
# image invokes — dependencies install via uv and the shipped venv is
# pip-less — so strip the payload instead of shipping unused vulnerable
# vendored packages. This runs after the platform warm-up because
# idf_tools bootstraps its venvs through the interpreter's ensurepip at
# build time; runtime gates never install packages (--network none).
RUN rm -rf /opt/uv-python/bin/pip* \
           /opt/uv-python/cpython-*/bin/pip* \
           /opt/uv-python/cpython-*/lib/python3.14/site-packages/pip \
           /opt/uv-python/cpython-*/lib/python3.14/site-packages/pip-*.dist-info \
           /opt/uv-python/cpython-*/lib/python3.14/ensurepip \
           /opt/pio/bin/pip* \
           /opt/pio/lib/python3.14/site-packages/pip \
           /opt/pio/lib/python3.14/site-packages/pip-*.dist-info \
           /opt/platformio/penv/bin/pip* \
           /opt/platformio/penv/lib/python3.14/site-packages/pip \
           /opt/platformio/penv/lib/python3.14/site-packages/pip-*.dist-info \
           /opt/platformio/penv/.espidf-*/bin/pip* \
           /opt/platformio/penv/.espidf-*/lib/python3.14/site-packages/pip \
           /opt/platformio/penv/.espidf-*/lib/python3.14/site-packages/pip-*.dist-info \
           /opt/platformio/penv/.espidf-*/lib/python3.14/ensurepip

# Tighten the login.defs umask to 027 (Lynis AUTH-9328): the image has no
# interactive users, so files created at runtime stay group-readable only.
RUN printf 'UMASK 027\n' >> /etc/login.defs

WORKDIR /work
