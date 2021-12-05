FROM curoky/dotbox:nixpkg
LABEL org.opencontainers.image.authors="cccuroky@gmail.com"

COPY pip pip
COPY install-pkgs.sh .

RUN sudo mkdir -p /o/conda && sudo chown 1000:1000 -R /o \
  && curl -sSL -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
  && bash /tmp/miniconda.sh -b -u -p /o/conda \
  && ./install-pkgs.sh ./pip
