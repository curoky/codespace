FROM debian:bookworm-backports

RUN apt-get update -y \
  && apt-get install -y curl xz-utils sudo \
  && groupadd -g 1000 -o x \
  && useradd -m -u 1000 -g 1000 x \
  && mkdir -m 0755 /nix \
  && chown x:x /nix

USER x

ENV PATH=$PATH:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin:/nix/var/nix/profiles/gcc13/bin \
  NIXPKGS_ALLOW_UNFREE=1 \
  NIXPKGS_ALLOW_BROKEN=1

RUN curl -L https://nixos.org/nix/install | sh -s -- --no-daemon \
  && nix-channel --update

COPY --from=third-party nixpkgs nixpkgs

RUN nix-env -p /nix/var/nix/profiles/default -iA \
    # system core package
    nixpkgs.tzdata.out nixpkgs.locale nixpkgs.glibcLocales nixpkgs.cacert \
    # compression
    nixpkgs.bzip2 nixpkgs.xz nixpkgs.zstd nixpkgs.zip nixpkgs.unzip nixpkgs.gnutar nixpkgs.zlib nixpkgs.zlib-ng nixpkgs.gzip nixpkgs.snappy \
    # download
    nixpkgs.gnupg nixpkgs.cacert nixpkgs.curl nixpkgs.wget nixpkgs.aria2 nixpkgs.rsync nixpkgs.croc \
    # edit
    nixpkgs.less nixpkgs.gnused nixpkgs.gnugrep nixpkgs.vim nixpkgs.bat nixpkgs.jq nixpkgs.flex \
    nixpkgs.bison nixpkgs.gettext nixpkgs.m4 \
    # compile
    nixpkgs.automake nixpkgs.autoconf nixpkgs.libtool nixpkgs.pkg-config nixpkgs.gnumake nixpkgs.cmake \
    nixpkgs.ninja nixpkgs.scons nixpkgs.meson nixpkgs.distcc nixpkgs.ccache \
    nixpkgs.bazelisk \
    # shell
    nixpkgs.zsh nixpkgs.bash nixpkgs.shfmt nixpkgs.starship nixpkgs.tmux nixpkgs.asciinema nixpkgs.atuin \
    # git
    nixpkgs.git nixpkgs.git-absorb nixpkgs.git-extras nixpkgs.git-lfs nixpkgs.git-filter-repo nixpkgs.gnupatch \
    # sre
    nixpkgs.iproute2 nixpkgs.iputils nixpkgs.netcat nixpkgs.lsof nixpkgs.connect nixpkgs.procps \
    nixpkgs.nettools nixpkgs.fd nixpkgs.ethtool nixpkgs.gdb nixpkgs.file nixpkgs.eza nixpkgs.fzf \
    nixpkgs.findutils nixpkgs.coreutils nixpkgs.lsb-release nixpkgs.tree nixpkgs.procs nixpkgs.gdu \
    nixpkgs.dstat nixpkgs.man nixpkgs.iptables nixpkgs.unixtools.xxd nixpkgs.util-linux nixpkgs.ncdu \
    nixpkgs.silver-searcher nixpkgs.diffutils nixpkgs.patchelf nixpkgs.strace nixpkgs.libcap \
    # linter
    nixpkgs.pre-commit nixpkgs.nodePackages.prettier nixpkgs.shfmt nixpkgs.ruff nixpkgs.clang-tools_16 \
    nixpkgs.buildifier nixpkgs.nixpkgs-fmt nixpkgs.nixfmt \
    # other
    nixpkgs.cloc nixpkgs.go-task nixpkgs.krb5 nixpkgs.openssh_gssapi nixpkgs.pandoc nixpkgs.graphviz \
    nixpkgs.openssl.bin nixpkgs.gh \
  && nix-env -iA -p /nix/var/nix/profiles/protobuf_3_8_0 -f nixpkgs/default.nix protobuf_3_8_0 \
  && nix-env -iA -p /nix/var/nix/profiles/protobuf_3_9_2 -f nixpkgs/default.nix protobuf_3_9_2 \
  && nix-env -iA -p /nix/var/nix/profiles/protobuf_3_20 nixpkgs.protobuf3_20 \
  && nix-env -iA -p /nix/var/nix/profiles/protobuf_24 nixpkgs.protobuf_24 \
  && nix-env -iA -p /nix/var/nix/profiles/vim-bundle -f nixpkgs/default.nix vim-bundle \
  && nix-env -iA -p /nix/var/nix/profiles/zsh-bundle -f nixpkgs/default.nix zsh-bundle \
  && chmod +w /nix/var/nix/profiles/default/* \
  && ln -s /nix/var/nix/profiles/default/bin/bazelisk /nix/var/nix/profiles/default/bin/bazel \
  && nix-env -iA -p /nix/var/nix/profiles/libs nixpkgs.python311Packages.libtorrent-rasterbar \
      nixpkgs.ncurses5 nixpkgs.libxml2.out nixpkgs.libxcrypt nixpkgs.libbacktrace \
  && nix-collect-garbage
