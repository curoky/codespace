FROM docker.io/curoky/dotbox:stage-nixpkg as stage-nixpkg
RUN nix-env -p /nix/var/nix/profiles/nvidia -iA -f nixpkgs/default.nix nsight-systems \
  && nix-collect-garbage

FROM docker.io/curoky/dotbox:stage-conda as stage-conda
COPY config config
RUN ./setup-conda-env.sh config/conda_env/tf2.5.yaml 1 11.4 \
  && ./setup-conda-env.sh config/conda_env/tf2.16.yaml 1 12.3

FROM curoky/dotbox:base-debian11

COPY --chown=1000:1000 --link --from=stage-nixpkg /nix /nix
COPY --chown=1000:1000 --link --from=stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix
COPY --chown=1000:1000 --link --from=stage-nixpkg /home/x/.local/state/nix /root/.local/state/nix
COPY --chown=1000:1000 --link --from=stage-conda /app/conda /app/conda
COPY --chown=1000:1000 --link --from=stage-conda /app/pipx /app/pipx
COPY --chown=1000:1000 ./config /tmp/config

COPY --link --from=curoky/infra-image:cuda11.4-cudnn8 /usr/local/cuda-11.4 /usr/local/cuda-11.4
COPY --link --from=curoky/infra-image:cuda11.4-cudnn8 /usr/local/cudnn8-cu11.4 /usr/local/cudnn8-cu11.4
# COPY --link --from=curoky/infra-image:cuda12.3-cudnn8 /usr/local/cuda-12.3 /usr/local/cuda-12.3
# COPY --link --from=curoky/infra-image:cuda12.3-cudnn8 /usr/local/cudnn8-cu12.3 /usr/local/cudnn8-cu12.3
# COPY --link --from=curoky/infra-image:tensorflow2.5-cu11.4-cudnn8 /tmp/tensorflow_pkg/ /app/tensorflow_pkg

USER root
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    gcc-10 g++-10 \
  && /app/dotbox/docker/dist/default/script/setup-sys-change-default-gcc.sh 10 \
  && ln -s /app/conda/envs/py3/bin/python3 /usr/bin/python \
  && ln -s /app/conda/envs/py3/bin/python3 /usr/bin/python3

USER root
ENTRYPOINT ["/app/dotbox/docker/dist/default/script/entrypoint.sh"]
