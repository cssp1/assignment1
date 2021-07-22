#!/bin/bash

set -e

su jovyan

if [ -z $ENVKEY ]; then
    echo "ENVKEY is not set"
    exit 1
fi

eval "$(envkey-source --no-cache --force)"

exec "$@"
