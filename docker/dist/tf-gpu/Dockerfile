FROM curoky/dotbox:minimal-debian11

# COPY --link --from=curoky/infra-image:cuda11.4-cudnn8 /usr/local/cuda-11.4 /usr/local/cuda-11.4
# COPY --link --from=curoky/infra-image:cuda11.4-cudnn8 /usr/local/cudnn8-cu11.4 /usr/local/cudnn8-cu11.4
# COPY --link --from=curoky/infra-image:cuda12.3-cudnn8 /usr/local/cuda-12.3 /usr/local/cuda-12.3
# COPY --link --from=curoky/infra-image:cuda12.3-cudnn8 /usr/local/cudnn8-cu12.3 /usr/local/cudnn8-cu12.3
# COPY --link --from=curoky/infra-image:tensorflow2.5-cu11.4-cudnn8 /tmp/tensorflow_pkg/ /app/tensorflow_pkg

USER root
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    gcc-10 g++-10 \
  && /app/dotbox/docker/minimal/script/setup-sys-change-default-gcc.sh 10 \
  && ln -s /app/conda/envs/py3/bin/python3 /usr/bin/python \
  && ln -s /app/conda/envs/py3/bin/python3 /usr/bin/python3

USER x
ENV PATH="$PATH:/home/x/.nix-profile/bin"

COPY config config
RUN nix-env -p /nix/var/nix/profiles/tf-gpu -iA \
    nixpkgs.bazelisk \
  && nix-env -p /nix/var/nix/profiles/tf-gpu -iA -f /app/dotbox/third-party/nixpkgs/default.nix nsight-systems \
  && /app/dotbox/docker/minimal/script/setup-conda-env.sh config/conda_env/tf2.5.yaml 1 11.4 \
  && /app/dotbox/docker/minimal/script/setup-conda-env.sh config/conda_env/tf2.16.yaml 1 12.3
