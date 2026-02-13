set -xeuo pipefail

# --cap-add=all \
# --security-opt seccomp=unconfined \
# --security-opt label=disable \
docker build . --network=host --file Dockerfile \
  --tag docker.io/curoky/devspace:live-build # --pull=false # --log-level debug --progress plain
