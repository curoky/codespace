# Copyright (c) 2018-2025 curoky(cccuroky@gmail.com).
#
# This file is part of devspace.
# See https://github.com/curoky/devspace for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# function psgrepme() {
#   name=$(whoami)
#   psgrep ${1} | grep ${name:0:7} | grep -v "sshd: ${name:0:7}"
# }

# function killwith() {
#   ps aux | grep -v "grep" | grep "$@" | awk '{print $2}' | xargs kill
# }

# function killmewith() {
#   psme | grep -v "grep" | grep "$@" | awk '{print $2}' | xargs kill
# }

# function killwith9() {
#   ps aux | grep -v "grep" | grep "$@" | awk '{print $2}' | xargs kill -9
# }

function dudir() {
  num=${1:-10}
  # http://www.lostsaloon.com/technology/how-to-sort-du-command-output-by-size-in-linux/
  # For FreeBSD version du: du -h -d0 $(ls -A) . | sort -h
  du -ahd1 2>&1 | sort -h | grep -v "Permission denied" | tail -n $num
}

function d() {
  cd $(dirs | xargs -n 1 | fzf | sed 's@^~@'"$HOME"'@')
}

# function get_file_from_parent_dir() {
#   local now_path=$PWD
#   local filename=$1

#   while [[ ! -f "$now_path/$filename" && $now_path != "/" ]]; do
#     now_path=$(dirname "${now_path}")
#   done

#   echo ${now_path}
# }

# function download_with_retries() {
#   # Due to restrictions of bash functions, positional arguments are used here.
#   # In case if you using latest argument NAME, you should also set value to all previous parameters.
#   # Example: download_with_retries $ANDROID_SDK_URL "." "android_sdk.zip"
#   local URL="$1"
#   local DEST="${2:-.}"
#   local NAME="${3:-${URL##*/}}"

#   echo "Downloading $URL..."
#   mkdir -p $DEST
#   i=20
#   while [ $i -gt 0 ]; do
#     ((i--))
#     wget $URL --output-document="$DEST/$NAME" \
#       --no-verbose
#     if $?; then
#       sleep 30
#     else
#       return 0
#     fi
#   done

#   echo "Could not download $URL"
#   return 1
# }

# function github_latest_rel() {
#   local REPO="$1"
#   local SUFFIX="$2"
#   local DEST="${3:-.}"
#   local NAME="${4:-${URL##*/}}"

#   local URL
#   URL=$(
#     curl -sS https://api.github.com/repos/$REPO/releases/latest |
#       grep -Po "https[^\"]*$SUFFIX" |
#       head -n1
#   )
#   download_with_retries $URL $DEST $NAME
# }

function set-http-proxy() {
  local proxy="http://$1:$2"
  export http_proxy=$proxy
  export HTTP_PROXY=$proxy
  export https_proxy=$proxy
  export HTTPS_PROXY=$proxy
  export all_proxy=$proxy
  export ALL_PROXY=$proxy
}

function set-wifi-proxy() {
  networksetup -setwebproxy wi-fi $1 $2
  networksetup -setsecurewebproxy wi-fi $1 $2
}

function unset-wifi-proxy() {
  networksetup -setwebproxystate wi-fi off
  networksetup -setsecurewebproxystate wi-fi off
}

function unset-http-proxy() {
  echo "unset http_proxy"
  unset http_proxy
  unset HTTP_PROXY
  unset https_proxy
  unset HTTPS_PROXY
  unset all_proxy
  unset ALL_PROXY
}

# function tighten-permissions() {
#   if [[ -d $1 ]]; then
#     find $1 -type d -exec chmod 700 {} \;
#     find $1 -type f -exec chmod 600 {} \;
#   fi
# }

# function cleanup_history() {
#   # https://unix.stackexchange.com/questions/48713/how-can-i-remove-duplicates-in-my-bash-history-preserving-order

#   # tac $HISTFILE | awk '!a[$0]++' | tac > t; mv t $HISTFILE
#   # tac $HISTFILE | awk '!x[$0]++' | tac | sponge $HISTFILE
#   ruby -i -e 'puts readlines.reverse.uniq.reverse' $HISTFILE
# }

# function analyze-file-extension-name() {
#   # https://stackoverflow.com/questions/1842254/how-can-i-find-all-of-the-distinct-file-extensions-in-a-folder-hierarchy
#   # find . -type f -name "*.*" | rev | cut -d. -f1 | rev  | tr '[:upper:]' '[:lower:]' | sort | uniq --count | sort -rn
#   find . -type f | perl -ne 'print $1 if m/\.([^.\/]+)$/' | sort | uniq -c | sort -n
# }

# function mkcd takedir() {
#   mkdir -p $@ && cd ${@:$#}
# }
