# syntax=docker/dockerfile:1.7
#
# The dev image: everything that builds and tests this repository, for
# linux/arm64 and linux/amd64 (docs/SETUP.md, "Docker").
#
#   ARM GNU Toolchain (arm-none-eabi-gcc, binutils)  patch C code, tools/patch_build.py
#   LLVM (llvm-objcopy, llvm-objdump)                scripts/disasm.sh, tools/patch.py --verify
#   Python + requirements-dev.txt                    emu/, tests/, tools/
#   Node + npm                                       web/ (npm ci from web/package-lock.json)
#
# Every input is pinned: the base images by digest, the Debian packages by a
# snapshot.debian.org date, the Arm toolchain by version and SHA-256, the
# Python packages by version. Novation's firmware is never part of the build
# context or of any layer: .dockerignore admits only the files this build
# reads, and scripts/dev mounts the firmware read-only at run time.
#
# Build for this machine (scripts/dev does this on its own when the tag is
# missing):
#   docker build -f docker/Dockerfile -t summit-mpe-dev .
# Both platforms, for a registry:
#   docker buildx build --platform linux/arm64,linux/amd64 -f docker/Dockerfile -t <registry>/summit-mpe-dev:<tag> --push .
#
# No Ghidra or JDK here: reverse engineering stays native (docs/SETUP.md).

ARG PYTHON_IMAGE=python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ARG NODE_IMAGE=node:26.13.0-trixie-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072

FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE} AS dev
ARG TARGETARCH

# Debian packages from a fixed snapshot, so a rebuild gets the same versions.
ARG DEBIAN_SNAPSHOT=20261101T000000Z
RUN set -eux; \
    src=/etc/apt/sources.list.d/debian.sources; \
    sed -i -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
           -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" "$src"; \
    printf 'Acquire::Check-Valid-Until "false";\nAcquire::Retries "5";\n' > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl git libatomic1 llvm-19 perl xz-utils; \
    rm -rf /var/lib/apt/lists/*

# Arm GNU Toolchain, from Arm's release page, checked against the SHA-256 Arm
# publishes (<file>.sha256asc). 15.3.rel2 is GCC 15.3 with binutils 2.45.
ARG ARM_TOOLCHAIN=15.3.rel2
ARG ARM_TOOLCHAIN_SHA256_arm64=a0dc18893171d39dec82fd8d57eeab3da836fd3df4b61978db3eccbf4a6bb948
ARG ARM_TOOLCHAIN_SHA256_amd64=463df9665c246fa13bab2102115bbf83440661b6eb70b44f3dfd4712ca30037a
RUN set -eux; \
    case "$TARGETARCH" in \
        arm64) host=aarch64; sum="$ARM_TOOLCHAIN_SHA256_arm64" ;; \
        amd64) host=x86_64;  sum="$ARM_TOOLCHAIN_SHA256_amd64" ;; \
        *) echo "unsupported TARGETARCH $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    file="arm-gnu-toolchain-${ARM_TOOLCHAIN}-${host}-arm-none-eabi.tar.xz"; \
    curl -fsSL --retry 5 -o "/tmp/$file" \
        "https://gitlab.arm.com/api/v4/projects/tooling%2Fgnu-toolchains-for-arm/packages/generic/gnu-toolchain/${ARM_TOOLCHAIN}/$file"; \
    echo "$sum  /tmp/$file" | sha256sum -c -; \
    mkdir -p /opt/arm-gnu-toolchain; \
    tar -xJf "/tmp/$file" -C /opt/arm-gnu-toolchain --strip-components=1; \
    rm -f "/tmp/$file"; \
    cd /opt/arm-gnu-toolchain; \
    rm -rf share/doc share/info share/man share/gdb bin/*gdb* lib/python* include/gdb; \
    bin/arm-none-eabi-gcc --version | head -1

# Node and npm from the official image.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version && npm --version

# Python packages for the harness and the tests (no hardware packages:
# those are requirements-hw.txt, installed natively on the Mac).
COPY requirements-dev.txt /tmp/requirements-dev.txt
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements-dev.txt \
 && rm /tmp/requirements-dev.txt

COPY docker/entrypoint.sh /usr/local/bin/summit-mpe-entrypoint
# /cache is a named volume at run time (scripts/dev): home, npm cache, pyc.
RUN mkdir -p /cache && chmod 1777 /cache

ENV PATH=/opt/venv/bin:/opt/arm-gnu-toolchain/bin:/usr/lib/llvm-19/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LLVM_BIN=/usr/lib/llvm-19/bin \
    SUMMIT_MPE_IN_IMAGE=1 \
    SUMMIT_PYTHON=/opt/venv/bin/python \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8
ENTRYPOINT ["/usr/local/bin/summit-mpe-entrypoint"]
CMD ["bash"]
