# syntax=docker/dockerfile:1.9.0
FROM debian:bookworm-backports

ARG CUDA_VERSION=11.4.0
ARG CUDA_DRIVER_VERSION=470.42.01
ARG CUDNN_VERSION=8.9.7.29_cuda11
ARG BINARY_TYPY='mix'

RUN apt-get update -y \
  && apt-get install -y libxml2 curl ncdu xz-utils perl

COPY ./install-cuda.sh .
RUN ./install-cuda.sh $CUDA_VERSION $CUDA_DRIVER_VERSION $BINARY_TYPY

COPY ./install-cudnn.sh .
RUN ./install-cudnn.sh $CUDNN_VERSION /app/nvidia/cudnn $BINARY_TYPY
