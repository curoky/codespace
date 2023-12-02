# syntax=docker/dockerfile:1.9-labs
FROM curoky/devspace:base-debian11

COPY --chown=5230:5230 --exclude=**/*.a --from=curoky/devspace:deps-cuda-cu12.3.2-cudnn8.9.7 /usr/local/cuda-12.3 /usr/local/cuda-12.3
COPY --chown=5230:5230 --exclude=**/*.a --from=curoky/devspace:deps-cuda-cu12.3.2-cudnn8.9.7 /opt/nvidia/cudnn8.9-cu12 /opt/nvidia/cudnn8.9-cu12
COPY --chown=5230:5230 ./config/ /home/x/app/devspace/docker/dist/pytorch/config/

USER root
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    gcc-10 g++-10 \
  && /home/x/app/devspace/dist/image/gcc/script/setup-sys-change-default-gcc.sh 10 \
  && ln -s /opt/conda/envs/py3/bin/python3 /usr/bin/python \
  && ln -s /opt/conda/envs/py3/bin/python3 /usr/bin/python3

USER x
ENV PATH=$PATH:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin:/opt/conda/condabin:

RUN nix-env -p /nix/var/nix/profiles/nvidia -iA -f nixpkgs/default.nix nsight-systems \
  && nix-collect-garbage

RUN setup-conda-env.sh -e /home/x/app/devspace/docker/dist/pytorch/config/conda/torch2.4.yaml --add_tf_env --cuda_version 12.3 --cudnn_version 8.9

ENTRYPOINT ["/home/x/app/devspace/dist/image/base/script/entrypoint.sh"]
