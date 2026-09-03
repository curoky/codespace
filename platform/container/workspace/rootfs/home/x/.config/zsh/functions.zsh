function psgrep() {
  ps aux | grep "${1:-.}" | grep -v grep
}

function killit() {
  ps aux | grep -v grep | grep "$@" | awk '{print $2}' | xargs sudo kill
}

function set-http-proxy() {
  if (( $# != 2 )); then
    print -u2 "usage: set-http-proxy HOST PORT"
    return 2
  fi

  local proxy="http://$1:$2"
  export http_proxy="$proxy"
  export HTTP_PROXY="$proxy"
  export https_proxy="$proxy"
  export HTTPS_PROXY="$proxy"
  export all_proxy="$proxy"
  export ALL_PROXY="$proxy"
}

function unset-http-proxy() {
  unset http_proxy HTTP_PROXY https_proxy HTTPS_PROXY all_proxy ALL_PROXY
}

function set-wifi-proxy() {
  if (( $# != 2 )); then
    print -u2 "usage: set-wifi-proxy HOST PORT"
    return 2
  fi

  networksetup -setwebproxy wi-fi "$1" "$2"
  networksetup -setsecurewebproxy wi-fi "$1" "$2"
}

function unset-wifi-proxy() {
  networksetup -setwebproxystate wi-fi off
  networksetup -setsecurewebproxystate wi-fi off
}
