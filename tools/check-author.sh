#!/usr/bin/env bash
set -euo pipefail

# expected_author_name=${1:-unknown}
# expected_author_email=${2:-unknown}
expected_author_name='unset'
expected_author_email='unset'

# get args from cmdline with getopt, --name and --email
# if not provided, use default values
while getopts ":n:e:" opt; do
  case $opt in
    n)
      expected_author_name=$OPTARG
      ;;
    e)
      expected_author_email=$OPTARG
      ;;
    \?)
      echo "Invalid option: -$OPTARG" >&2
      exit 1
      ;;
  esac
done

if [[ $expected_author_name != "unset" ]] && [[ $expected_author_name != "$GIT_AUTHOR_NAME" ]]; then
  echo "Expected author name to be '$expected_author_name', but was '$GIT_AUTHOR_NAME'"
  exit 1
fi

if [[ $expected_author_email != "unset" ]] && [[ $expected_author_email != "$GIT_AUTHOR_EMAIL" ]]; then
  echo "Expected author email to be '$expected_author_email', but was '$GIT_AUTHOR_EMAIL'"
  exit 1
fi
