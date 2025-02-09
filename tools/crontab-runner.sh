#!/usr/bin/env bash

mkdir -p ~/.cache/crontab
logfile=~/.cache/crontab/"${1:-default}".log
exec >>$logfile 2>&1

echo "==================== start at ($(date '+%Y-%m-%d %H:%M:%S')) ======================="

$2 "${@:3}"

echo "==================== end at ($(date '+%Y-%m-%d %H:%M:%S'))======================"
