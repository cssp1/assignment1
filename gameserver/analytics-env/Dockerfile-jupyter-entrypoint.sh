#!/bin/sh -l

if [ -z $ENVKEY ]; then
    echo "ENVKEY is not set"
    exit 1
fi

eval $(envkey-source)

exec "$@"
