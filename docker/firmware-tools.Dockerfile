ARG UV_VERSION=0.12.23
ARG UV_DIGEST=sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21
# Emscripten SDK stage: digest-pinned, shared with the dashboard tools image
# so the .mrb/WASM legs use one proven toolchain. ARGs used in FROM must be
# declared before the first FROM.
ARG EMSDK_VERSION=6.0.10
ARG EMSDK_DIGEST=sha256:e077d54e2b8970575ebc4f185ac1de0b95c05f2b266134d4ba27449af7aebf65
FROM ghcr.io/astral-sh/uv:${UV_VERSION}@${UV_DIGEST} AS uv
FROM emscripten/emsdk:${EMSDK_VERSION}@${EMSDK_DIGEST} AS emscripten

# ubuntu:26.04 (resolute)
FROM ubuntu:26.04@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78

ARG DEBIAN_FRONTEND=noninteractive
ARG IMAGE_REVISION=unknown
ARG PLATFORMIO_VERSION=6.2.0
ARG ESPRESSIF32_PLATFORM=espressif32@7.1.3
ARG ESP_QEMU_RELEASE=esp-develop-9.2.2-20260417
ARG ESP_QEMU_ASSET=qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-linux-gnu.tar.xz
ARG ESP_QEMU_SHA256=0eecb2a34a5586c0e59110f77b9343b7b336e82fdb0e1a30e1dc1bab8a547e35
# cppcheck tracks Debian unstable (sid) instead of the resolute apt pin so
# the image ships the newest release; the .deb is fetched from the permanent
# snapshot.debian.org archive and verified before install. Its Depends are
# satisfied from resolute (libc6 2.43, libtinyxml2-11, python3-pygments).
ARG CPPCHECK_VERSION=2.22.0-1
ARG CPPCHECK_DEB_URL=https://snapshot.debian.org/archive/debian/20261007T000000Z/pool/main/c/cppcheck/cppcheck_2.22.0-1_amd64.deb
ARG CPPCHECK_DEB_SHA256=936dbeba9e147b2e9255c44b3c59c37f33373f118a271aac05799c85a45795c5
# mruby/c capability pins: mruby 4.0.0 builds the mrbc bytecode compiler;
# mruby/c tracks a master commit because release4.0.0 predates the AVR,
# ESP32 and RP2040 HALs and the feature-off macros the gates need.
ARG MRUBY_VERSION=4.0.0
ARG MRUBYC_REF=2dec4802b09be1fc12f388d3c9267ffd9dc6c404
# Zephyr policy: non-Nordic Zephyr builds pin Canonical's Zephyr 26.04
# LTS distribution — the Canonical-maintained fork of upstream Zephyr 4.4
# hosted on Launchpad (zephyr-manifest@26.04.0, zephyr @ 2e4ba3e7). Its
# module revisions are identical to upstream v4.4.2, so module rows stay
# sha256-pinned GitHub tarballs. Nordic builds pin the nRF Connect SDK
# LTS line (v3.4.1).
ARG ZEPHYR_VERSION=canonical-26.04.0
ARG NCS_VERSION=3.4.1
ARG PICO_SDK_VERSION=2.2.0

# Fail the build when the left side of a verification pipe (curl|sha256sum)
# breaks instead of silently passing the right side.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
ENV PLATFORMIO_CORE_DIR=/opt/platformio
ENV PLATFORMIO_SETTING_ENABLE_TELEMETRY=no
ENV PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL=0
ENV PLATFORMIO_SETTING_CHECK_PRUNE_SYSTEM_THRESHOLD=0
ENV PATH="/opt/firmware/.venv/bin:/opt/esp-qemu/bin:/opt/platformio/packages/tool-xtensa-esp-elf-gdb/bin:/opt/pio/bin:/opt/mruby/bin:/opt/emsdk:/opt/emsdk/upstream/emscripten:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENV PYTHONPYCACHEPREFIX=/tmp/firmware-pycache
ENV FW_MRUBYC_DIR=/opt/mrubyc \
    PICO_SDK_PATH=/opt/pico-sdk \
    EMSDK=/opt/emsdk \
    EM_CONFIG=/opt/emsdk/.emscripten

LABEL org.opencontainers.image.source="https://github.com/VibeBB/firmware-agent" \
      org.opencontainers.image.licenses="BSD-3-Clause" \
      org.opencontainers.image.revision="${IMAGE_REVISION}" \
      firmware.platformio.version="${PLATFORMIO_VERSION}" \
      firmware.espressif32.platform="${ESPRESSIF32_PLATFORM}" \
      firmware.esp-qemu.release="${ESP_QEMU_RELEASE}" \
      firmware.cppcheck.version="${CPPCHECK_VERSION}"

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --chmod=0755 docker/apt-sources-fallback /usr/local/bin/

# GPL-licensed tools (GCC, GDB, QEMU, Cppcheck) are installed as separate
# executables and only ever invoked as subprocesses.
# archive.ubuntu.com's port-80 front end has repeated outages (2026-08/09/10);
# apt-sources-fallback swaps the deb822 sources to Canonical's EC2 mirror
# whenever the resolute indexes or package downloads fail to land.
RUN apt-sources-fallback \
        ca-certificates \
        curl \
        git \
        make \
        cmake \
        ninja-build \
        xz-utils \
        gcc \
        libc6-dev \
        gcc-arm-none-eabi \
        libnewlib-arm-none-eabi \
        binutils-arm-none-eabi \
        gdb-multiarch \
        qemu-system-arm \
        libpixman-1-0 \
        libgcrypt20 \
        libsdl2-2.0-0 \
        libslirp0 \
        libglib2.0-0t64 \
        zlib1g \
        gcc-avr \
        avr-libc \
        gcc-riscv64-unknown-elf \
        device-tree-compiler \
        nodejs \
        ruby \
        python3-pyelftools \
        python3-yaml \
        python3-kconfiglib \
        python3-jinja2 \
        python3-packaging \
        python3-jsonschema \
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

# mruby/c toolchain: fetch-pins.sh verifies every sha256 in
# third_party.manifest, then unpacks the source trees into the Zephyr,
# nRF Connect SDK, mruby/c, and Pico SDK roots. BSD/MIT licensed sources.
COPY docker/fetch-pins.sh docker/third_party.manifest /tmp/pins/
RUN bash /tmp/pins/fetch-pins.sh /tmp/pins/third_party.manifest \
    && mkdir -p /opt/mruby/bin
WORKDIR /opt/mruby-src
RUN ruby ./minirake -j"$(nproc)" \
    && cp build/host/bin/mrbc /opt/mruby/bin/mrbc \
    && PATH=/opt/mruby/bin:$PATH make -C /opt/mrubyc
WORKDIR /
RUN rm -rf /opt/mruby-src /tmp/pins \
    && printf '%s\n' "${MRUBYC_REF}" > /opt/mrubyc/REF \
    && printf '%s\n' "${ZEPHYR_VERSION}" > /opt/zephyr/ZEPHYR_VERSION \
    && printf '%s\n' "${NCS_VERSION}" > /opt/nrf/NCS_VERSION

# Emscripten SDK: reuse the digest-pinned stage so dashboard/firmware share
# the exact emcc + node pair.
COPY --from=emscripten /emsdk /opt/emsdk
RUN test -x /opt/emsdk/upstream/emscripten/emcc \
    && node --version \
    && emcc --version | head -1

# cppcheck (static analysis gate tool) from the checksum-pinned Debian sid
# .deb: the sid pin reaches upstream 2.22 while the resolute apt channel is
# stuck at 2.19. GPL-3.0; runs as a subprocess only.
RUN curl --fail --location --silent --show-error \
        --retry 5 --retry-delay 10 --retry-all-errors \
        --output /tmp/cppcheck.deb \
        "${CPPCHECK_DEB_URL}" \
    && echo "${CPPCHECK_DEB_SHA256}  /tmp/cppcheck.deb" | sha256sum --check \
    && apt-sources-fallback /tmp/cppcheck.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/cppcheck.deb \
    && mkdir -p /usr/share/doc/cppcheck \
    && printf '%s\n' \
        "source=Debian unstable pool via snapshot.debian.org" \
        "version=${CPPCHECK_VERSION}" \
        "sha256=${CPPCHECK_DEB_SHA256}" \
        > /usr/share/doc/cppcheck/SOURCE

RUN arm-none-eabi-gcc --version | head -1 \
    && gcc --version | head -1 \
    && gcov --version | head -1 \
    && cppcheck --version \
    && qemu-system-arm --version | head -1 \
    && qemu-system-xtensa --version | head -1 \
    && avr-gcc --version | head -1 \
    && riscv64-unknown-elf-gcc --version | head -1 \
    && (mrbc -v | head -1 || true) \
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
           /opt/uv-python/cpython-*/lib/python3.*/site-packages/pip \
           /opt/uv-python/cpython-*/lib/python3.*/site-packages/pip-*.dist-info \
           /opt/uv-python/cpython-*/lib/python3.*/ensurepip \
           /opt/pio/bin/pip* \
           /opt/pio/lib/python3.*/site-packages/pip \
           /opt/pio/lib/python3.*/site-packages/pip-*.dist-info \
           /opt/platformio/penv/bin/pip* \
           /opt/platformio/penv/lib/python3.*/site-packages/pip \
           /opt/platformio/penv/lib/python3.*/site-packages/pip-*.dist-info \
           /opt/platformio/penv/.espidf-*/bin/pip* \
           /opt/platformio/penv/.espidf-*/lib/python3.*/site-packages/pip \
           /opt/platformio/penv/.espidf-*/lib/python3.*/site-packages/pip-*.dist-info \
           /opt/platformio/penv/.espidf-*/lib/python3.*/ensurepip \
           /root/.cache/uv

# Tighten the login.defs umask to 027 (Lynis AUTH-9328): the image has no
# interactive users, so files created at runtime stay group-readable only.
RUN printf 'UMASK 027\n' >> /etc/login.defs

WORKDIR /work
