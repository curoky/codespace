#!/usr/bin/env bash
set -xeuo pipefail

colima start --runtime docker --cpu 8 --memory 16 --disk 100
