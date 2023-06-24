# syntax=docker/dockerfile:1.9.0
FROM debian:stable-slim AS stage-cudnn
ARG CUDA_VERSION=11.4.0
ARG CUDNN_VERSION=8.9.7.29

RUN apt-get update -y \
  && apt-get install -y curl xz-utils

COPY ./install-cudnn.sh .

RUN ./install-cudnn.sh $CUDA_VERSION $CUDNN_VERSION

FROM debian:stable-slim

ARG CUDA_VERSION=11.4.0
ARG CUDA_DRIVER_VERSION=470.42.01

RUN apt-get update -y \
  && apt-get install -y libxml2 curl ncdu xz-utils perl

COPY ./install-cuda.sh .
RUN ./install-cuda.sh $CUDA_VERSION $CUDA_DRIVER_VERSION

COPY --link --from=stage-cudnn /home/x/app/nvidia/ /home/x/app/nvidia/
