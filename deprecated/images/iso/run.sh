set -xeuo pipefail

docker run --privileged -it \
  --network=host \
  -v ./build:/build \
  -v ./script:/script \
  -v ./config:/config \
  docker.io/curoky/devspace:live-build \
  /bin/bash
