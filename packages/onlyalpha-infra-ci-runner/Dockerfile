FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ARG UV_VERSION=0.10.5
ARG PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

ENV DEBIAN_FRONTEND=noninteractive \
    UV_CACHE_DIR=/opt/onlyalpha-ci/uv-cache \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL} \
    UV_HTTP_RETRIES=0 \
    UV_HTTP_TIMEOUT=120 \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --index-url "${PYPI_INDEX_URL}" "uv==${UV_VERSION}"

COPY toolchain.txt /opt/onlyalpha-ci/toolchain.txt
RUN uv venv --no-project --no-python-downloads --python /usr/local/bin/python /opt/onlyalpha-ci/toolchain \
    && uv pip install --python /opt/onlyalpha-ci/toolchain/bin/python --requirements /opt/onlyalpha-ci/toolchain.txt

COPY verify-toolchain.sh /usr/local/bin/onlyalpha-ci-verify
RUN chmod 0555 /usr/local/bin/onlyalpha-ci-verify \
    && onlyalpha-ci-verify

LABEL org.opencontainers.image.title="OnlyAlpha CI Runner Toolchain" \
      org.opencontainers.image.description="Pinned Python 3.12 and uv cache for OnlyAlpha CI" \
      org.opencontainers.image.version="2026.9.4.1"

CMD ["bash"]
