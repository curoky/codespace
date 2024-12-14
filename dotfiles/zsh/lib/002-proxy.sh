
if [[ -f /var/run/s6/container_environment/HTTP_PROXY ]]; then
  export http_proxy=$(cat /var/run/s6/container_environment/HTTP_PROXY)
  export HTTP_PROXY=$http_proxy
  export https_proxy=$http_proxy
  export HTTPS_PROXY=$http_proxy
  export all_proxy=$http_proxy
  export ALL_PROXY=$http_proxy
  export no_proxy=localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8
  export NO_PROXY=localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8
fi
