#!/usr/bin/env bash

s6-setuidgid x env HOME=/home/x /opt/devspace/images/base/script/s6-init/entrypoint.sh > /var/log/oncetask.log
