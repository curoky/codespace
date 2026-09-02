# Qwen3.8-Flash-Next-FP8 serving image (vLLM engine).
#
# Base image and assembly are aligned with the support Service: debian:trixie-slim
# with binman-installed standalone s6/execline as PID 1.
#
# Unlike support, this image ships the full CUDA + inference stack itself
# (Debian has no CUDA runtime and no vLLM). The ~172 GiB FP8 weights are NOT baked
# in; they are resolved at run time from a bind-mounted Hugging Face cache.
#
# day-0 architecture: Qwen3.8-Flash-Next (architecture Qwen4ExpForConditionalGeneration)
# is NOT in any stable PyPI vLLM release, and the official recipe explicitly states
# "PyPI installation is not supported" -- it ships only the dedicated
# vllm/vllm-openai:qwen38-flash-next image (labelled "vLLM 0.28.0+ / nightly").
# Model support landed on main in PR #53896 (commit pinned by VLLM_COMMIT below);
# we therefore install a pinned nightly wheel from vLLM's per-commit index instead
# of a tagged release wheel. Bump VLLM_COMMIT once the architecture ships in a
# stable release, after which this can revert to a release wheel.
FROM docker.io/debian:trixie-slim

# CUDA userspace runtime is provided by the NVIDIA Container Toolkit at run time
# (mounted from the host driver). uv builds its own CPython venv (no system
# python3 needed) and the CUDA runtime libs come from the vLLM wheels; the image
# only needs bash (serve.sh), TLS certs, curl (binman installer), zstd (binman
# unpacks .tar.zst) and libgomp1 (OpenMP runtime for torch).
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    bash ca-certificates curl zstd libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY platform/container/services/vllm/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

# Inference stack installed into a dedicated venv via uv (installed by binman).
# Python 3.12 is the newest version the GPU inference stack supports: vLLM
# nominally allows 3.10-3.13, but the prebuilt CUDA/flashinfer/xformers wheels
# only cover up to 3.12; 3.13 fails to build.
#
# VLLM_COMMIT pins the vLLM main commit whose nightly wheel carries the
# Qwen3.8-Flash-Next architecture (PR #53896, merged 2026-08-31). Nightly wheels
# live at https://wheels.vllm.ai/<commit>; the wheel's on-disk version is a
# placeholder, so we resolve it by index, not by a release URL. Bump the commit
# to pick up later fixes, or revert to a release wheel once the architecture ships.
#
# CUDA_TAG selects the torch CUDA backend resolved from the PyTorch index. This
# vLLM commit pins torch==2.13.0, which PyTorch publishes for cu126/cu129/cu130
# but NOT cu128 -- so the previous cu128 default failed to resolve (torch==2.13.0
# is simply absent from the cu128 index). We default to cu129: the target 8x H100
# node runs an older CUDA 12.x driver (535 / CUDA 12.2), which runs cu129 (still
# CUDA 12.x) wheels fine -- this avoids the cu13 default that would fail at import
# with `libcudart.so.13: cannot open shared object file`. Override CUDA_TAG=cu130
# for a CUDA 13 host, or cu126 for an even older 12.x driver.
#
# --index-strategy unsafe-best-match: the deps span three indexes (vLLM per-commit,
# PyTorch cu129, PyPI). uv defaults to taking each package from the FIRST index
# that lists it, which pins e.g. `packaging` to the stale copy on the PyTorch
# index (<=24.1) and then fails flashinfer-python==0.6.18's `packaging>=24.2`.
# unsafe-best-match lets uv pick the best version across all indexes instead.
ARG VLLM_COMMIT=e126687a9a828d513c01a07cd69f025f27d63280
ARG CUDA_TAG=cu129
ENV SERVE_VENV=/opt/codespace/vllm/venv
RUN /opt/bm/bin/uv venv "${SERVE_VENV}" --python 3.12 \
  && /opt/bm/bin/uv pip install --python "${SERVE_VENV}/bin/python" \
    --prerelease=allow \
    --index-strategy unsafe-best-match \
    vllm \
    --extra-index-url "https://wheels.vllm.ai/${VLLM_COMMIT}" \
    --extra-index-url "https://download.pytorch.org/whl/${CUDA_TAG}"

ENV PATH="/opt/codespace/vllm/venv/bin:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:$PATH"

COPY platform/container/workspace/rootfs/etc/s6/skel/ /etc/s6/skel/
COPY platform/container/services/vllm/rootfs/ /
RUN chmod +x /opt/codespace/vllm/serve.sh
COPY platform/container/workspace/scripts/install-s6.sh /tmp/install-s6.sh
RUN /tmp/install-s6.sh

ENTRYPOINT ["/etc/s6/init/bin/init"]
