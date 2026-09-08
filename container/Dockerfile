# syntax=docker/dockerfile:1
# SPDX-License-Identifier: Apache-2.0

# OpenSSH 10.4 build stage.  The image authenticates SSH with the
# post-quantum ssh-mldsa44-ed25519 signature only.  The build task mints
# the test key with ssh-keygen, and the CI device-validation job reaches
# the device with ssh/scp over that same mldsa44 host and user key, so
# the builder needs an OpenSSH 10.4-or-newer ssh-keygen, ssh, and scp.
# Jammy ships 8.9 and packages nothing newer, so build them from the
# release tarball (pinned by hash; the same tarball the image recipe
# builds); ssh-keygen, ssh, and scp are copied into the builder below.
FROM ubuntu:22.04 AS openssh

SHELL ["/bin/bash", "-o", "errexit", "-o", "nounset", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND noninteractive

ARG OPENSSH_VERSION=10.4p1
ARG OPENSSH_SHA256=ef6026dd2aea8d56059638d5d3262902c892ceba9f88395835e0d06d3fb63238

RUN apt-get update &&\
  apt-get install --no-install-recommends -y \
    ca-certificates curl gcc libc6-dev libssl-dev make zlib1g-dev &&\
  rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/openssh
RUN curl -fsSL -o openssh.tar.gz \
    "https://ftp.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-${OPENSSH_VERSION}.tar.gz" &&\
  echo "${OPENSSH_SHA256}  openssh.tar.gz" | sha256sum -c - &&\
  tar -xzf openssh.tar.gz --strip-components=1 &&\
  ./configure &&\
  make -j"$(nproc)" ssh scp ssh-keygen

FROM ubuntu:22.04

SHELL ["/bin/bash", "-o", "errexit", "-o", "nounset", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND noninteractive

# Required Packages for the Host Development System
# http://www.yoctoproject.org/docs/latest/mega-manual/mega-manual.html#required-packages-for-the-host-development-system
COPY packages.lock /root/packages.lock
RUN --mount=type=cache,target=/var/lib/apt \
  --mount=type=cache,target=/var/cache/apt \

  # Update APT lists
  apt-get update &&\
  apt-get -y upgrade &&\

  # Configure default locale.
  apt-get install --no-install-recommends -y locales &&\
  printf 'C.UTF-8 UTF-8\nen_US.UTF-8 UTF-8\n' > /etc/locale.gen && locale-gen &&\
  update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 LANGUAGE=en_US:en &&\
  export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 LANGUAGE=en_US:en &&\

  # Install base Yocto Poky requirements from lockfile
  grep -vE '^[[:blank:]]*(#|$)' /root/packages.lock | xargs apt-get install --no-install-recommends -y &&\

  # Use Bash as the default /bin/sh
  ln -sf /bin/bash /bin/sh &&\

  # Cleanup
  apt-get autoclean &&\
  rm -rf /tmp/* /var/tmp/*

# Create a non-root user that will perform the actual build.
# BUILDER_UID should match the host UID to avoid permission issues.
ARG BUILDER_UID=1000
RUN id builder 2>/dev/null || useradd --uid ${BUILDER_UID} --shell /bin/bash --create-home builder && \
  echo 'builder ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers.d/builder && \
  chmod 0660 /etc/sudoers.d/builder

# We need these for consistent sorting, formating, etc., but they cannnot
# be set until after the locales are generated.  Yocto also requires them.
ENV LANGUAGE en_US:en
ENV LANG     en_US.UTF-8
ENV LC_ALL   en_US.UTF-8

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install kas and other Python packages via uv
COPY requirements.txt /root/requirements.txt
RUN --mount=type=cache,target=/root/.cache \

  # Install locked requirements
  uv pip install --system -r /root/requirements.txt --link-mode=copy &&\

  # Cleanup
  rm -rf /tmp/* /var/tmp/*

# Post-quantum-capable OpenSSH 10.4 client from the openssh stage above:
# ssh-keygen mints the mldsa44 test key, and ssh/scp are what the
# validation suite uses to reach the device over the mldsa44 host and
# user keys (Jammy's 8.9 rejects those key types).  /usr/local/bin
# precedes /usr/bin on PATH, so these shadow Jammy's 8.9.
COPY --from=openssh /usr/src/openssh/ssh-keygen /usr/local/bin/ssh-keygen
COPY --from=openssh /usr/src/openssh/ssh /usr/local/bin/ssh
COPY --from=openssh /usr/src/openssh/scp /usr/local/bin/scp

USER builder
WORKDIR /home/builder
# -r 2:15: rewrite SIGINT to SIGTERM so a Ctrl-C on the host shuts
# kas and bitbake down cleanly instead of leaving them mid-interrupt.
ENTRYPOINT ["/bin/dumb-init", "-r", "2:15", "/usr/local/bin/kas"]
CMD ["--help"]

# NOTE: Uncomment these for debugging
#USER root
#WORKDIR /root
#ENTRYPOINT ["/bin/dumb-init", "/bin/bash"]
#CMD ['-l']
