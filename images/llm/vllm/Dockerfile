# Qwen3.8-Flash-Next-FP8 serving image (vLLM engine).
#
# Base image and assembly aligned with images/sidecar/Dockerfile: debian:trixie-slim
# with binman-installed standalone s6/execline as PID 1 and services under
# rootfs/etc/s6/s6-rc.d.
#
# Unlike the sidecar, this image ships the full CUDA + inference stack itself
# (Debian has no CUDA runtime and no vLLM). The ~172 GiB FP8 weights are NOT baked
# in; they are resolved at run time from a bind-mounted Hugging Face cache.
#
# WARNING (day-0 architecture): the stable PyPI vLLM may not yet include the
# Qwen3.8-Flash-Next architecture. Pin VLLM_VERSION to a build that does (the
# official recipe uses a dedicated tag / nightly). If startup fails with an
# unknown-architecture error, bump VLLM_VERSION.
FROM docker.io/debian:trixie-slim

# CUDA userspace runtime is provided by the NVIDIA Container Toolkit at run time
# (mounted from the host driver); the image only needs Python, the CUDA runtime
# libraries pulled in by the vLLM wheel, and basic tooling.
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    bash ca-certificates curl tzdata zstd python3 python3-venv libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY images/llm/vllm/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# Inference stack installed into a dedicated venv via uv (installed by binman).
# Python 3.12 is the newest version the GPU inference stack supports: vLLM
# nominally allows 3.10-3.13, but the prebuilt CUDA/flashinfer/xformers wheels
# only cover up to 3.12; 3.13 fails to build. VLLM_VERSION must resolve to a
# build with Qwen3.8-Flash-Next support; the wheel pulls its own CUDA runtime.
ARG VLLM_VERSION=0.10.2
ENV LLM_VENV=/opt/llm/venv
RUN /opt/bm/bin/uv venv "${LLM_VENV}" --python 3.12 \
  && /opt/bm/bin/uv pip install --python "${LLM_VENV}/bin/python" "vllm==${VLLM_VERSION}"

ENV PATH="/opt/llm/venv/bin:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY images/dev/rootfs/etc/s6/skel /etc/s6/skel
COPY images/llm/vllm/rootfs/ /
RUN chmod +x /opt/llm/serve.sh
COPY images/dev/script/setup-s6.sh /tmp/setup-s6.sh
RUN /tmp/setup-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
