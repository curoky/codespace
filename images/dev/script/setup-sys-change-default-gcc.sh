#!/usr/bin/env bash

target_gcc_version=${1:-13}
priority=${2:-30}

if [[ -f /usr/bin/gcc-$target_gcc_version ]]; then
  update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-$target_gcc_version \
    $priority \
    --slave /usr/bin/gcov gcov /usr/bin/gcov-$target_gcc_version \
    --slave /usr/bin/gcov-dump gcov-dump /usr/bin/gcov-dump-$target_gcc_version \
    --slave /usr/bin/gcov-tool gcov-tool /usr/bin/gcov-tool-$target_gcc_version \
    --slave /usr/bin/gcc-ar gcc-ar /usr/bin/gcc-ar-$target_gcc_version \
    --slave /usr/bin/gcc-nm gcc-nm /usr/bin/gcc-nm-$target_gcc_version \
    --slave /usr/bin/gcc-ranlib gcc-ranlib /usr/bin/gcc-ranlib-$target_gcc_version

  update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-$target_gcc_version $priority
  update-alternatives --install /usr/bin/cc cc /usr/bin/gcc-$target_gcc_version $priority
  update-alternatives --install /usr/bin/c++ c++ /usr/bin/g++-$target_gcc_version $priority
fi
