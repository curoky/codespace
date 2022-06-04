FROM debian:bookworm-backports

ARG CUDA_VERSION=11.4.0
ARG DRIVER_VERSION=470.42.01

RUN apt-get update -y \
  && apt-get install -y libxml2 curl

COPY ./install.sh .
RUN ./install.sh $CUDA_VERSION $DRIVER_VERSION
